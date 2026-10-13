"""Pi native RPC consumer client (family ``pi``, protocol ``pi-rpc/1``).

Pinned facts (N003, official pi 0.86.1 MIT rpc docs, frozen 2026-10-04):

- Launch: ``pi --mode rpc --no-session`` (or ``--session-dir <dir>``);
  ``--offline`` / ``PI_OFFLINE=1`` disables startup network access; a minimal
  isolated start keeps ``--no-extensions --no-skills --no-context-files
  --no-prompt-templates --no-approve``.
- Transport: strict JSONL — *not* JSON-RPC 2.0. stdin command records are
  ``{"id":"req-1","type":"<command>",...args}`` with args as same-level
  fields; stdout answers ``{"id":...,"type":"response","command":...,
  "success":true,"data":{...}}`` or ``"success":false,"error":"..."``.
  Lines pi itself cannot parse produce
  ``{"type":"response","command":"parse","success":false,"error":...}`` with
  no ``id`` — such records carry no receipt semantics and stay in the event
  stream verbatim (G4); they are never mistaken for a command response (G6).
- stdout also carries session events (``message_update``, ``agent_end``,
  ``agent_settled``, ``bash_execution_update``, ``compaction_*``) and
  bidirectional extension-UI records (``extension_ui_request`` is answered
  with a same-``id`` ``extension_ui_response`` and produces no regular
  response). Unknown types/fields surface verbatim, never dropped (G4).
- Receipts are NOT completion: the pinned 0.86.1 source returns a successful
  ``prompt`` response without data. Acceptance includes queued or immediately
  handled input. ``agent_end`` is merely one run ending; only
  ``agent_settled`` proves no automatic continuation remains.
- There is NO ``initialize``/version negotiation in the documented protocol;
  the handshake here is a ``get_state`` command round trip that invents
  nothing. Resume/replay semantics are undocumented upstream — they remain
  unknown and nothing is fabricated. No runtime readiness is ever claimed.

The client is a pure consumer over the frozen N001 transport seam
(``_transport``): byte framing, unknown preservation, typed failures, no
retry (G5/G11) and owned-process cleanup (G6/G8) delegate there; this module
adds only pi's document-level record shapes. It never auto-approves, never
re-sends, and never touches anything beyond its own channel.
"""

from __future__ import annotations

import time
import threading
import json
from collections import deque
from typing import Any, Callable, Mapping, Sequence

from ordessa_execution_agents.harness.transport import (
    ChannelClosed,  # noqa: F401 - re-typed here for callers
    ChannelFailure,
    FramingError,
    LostReceipt,
    Message,
    ProcessChannel,
    PreparedFrame,
    PreparedFramePool,
    PreparedFrameRefused,
    RequestTimeout,
)

UPSTREAM_SOURCE_COMMIT = "13cbf77df2396303013a41646bcfa77b4271ae56"

FAMILY_ID = "pi"
PI_PROTOCOL_ID = "pi-rpc/1"

#: Documented pi-rpc/1 commands frozen by N003 (official rpc doc state at
#: 2026-10-04). There is NO ``initialize``/negotiation command in this list.
KNOWN_COMMANDS: tuple[str, ...] = (
    "prompt",
    "steer",
    "follow_up",
    "abort",
    "clear_queue",
    "new_session",
    "get_state",
    "get_messages",
    "set_model",
    "cycle_model",
    "get_available_models",
    "set_thinking_level",
    "cycle_thinking_level",
    "get_available_thinking_levels",
    "set_steering_mode",
    "set_follow_up_mode",
    "compact",
    "set_auto_compaction",
    "set_auto_retry",
    "abort_retry",
    "bash",
    "abort_bash",
    "get_session_stats",
    "export_html",
    "switch_session",
    "fork",
    "clone",
    "get_fork_messages",
    "get_entries",
    "get_tree",
    "get_last_assistant_text",
    "set_session_name",
    "get_commands",
)

#: The only event that certifies "no automatic continuation".
SETTLED_EVENT = "agent_settled"

# _run_state values: None (never prompted), "started", "handled",
# "settled", "unknown" (send outcome unknown after RequestTimeout/LostReceipt).
# wait_settled refuses to block for the first two quiet states (G6: no run
# means no settle boundary, never fake completion).
_SETTLE_QUIET_STATES = ("handled", "settled", None)


class PiCommandError(ChannelFailure):
    """A pi command record was answered with ``success:false``.

    The peer's error text is preserved verbatim (G4); nothing is retried or
    rewritten, and the raw response record is kept for evidence.
    """

    def __init__(
        self,
        command: str,
        request_id: Any,
        error: Any,
        *,
        raw: Mapping[str, Any] | None = None,
    ):
        super().__init__("PI_COMMAND_ERROR", f"{command}#{request_id}: {error}")
        self.command = command
        self.request_id = request_id
        self.error = error
        self.raw = raw


def rpc_launch_argv(
    *,
    session_dir: str | None = None,
    offline: bool = False,
    minimal: bool = False,
    extra: Sequence[str] = (),
) -> tuple[str, ...]:
    """Build the pi rpc launch argv *plan* (pure; never executed here).

    ``session_dir=None`` maps to ``--no-session``; otherwise
    ``--session-dir <dir>``. ``offline`` adds ``--offline`` (``PI_OFFLINE=1``
    can equivalently be set via ``extra_env`` on a
    :class:`~ordessa_execution_agents.harness.transport.LaunchSpec`). ``minimal``
    appends the documented no-* flags for a minimal isolated start.
    """
    argv = ["pi", "--mode", "rpc"]
    if session_dir is None:
        argv.append("--no-session")
    else:
        argv += ["--session-dir", str(session_dir)]
    if offline:
        argv.append("--offline")
    if minimal:
        argv += [
            "--no-extensions",
            "--no-skills",
            "--no-context-files",
            "--no-prompt-templates",
            "--no-approve",
        ]
    argv += list(extra)
    return tuple(argv)


def describe() -> dict[str, Any]:
    """Static channel facts for the pi family. No runtime readiness claim."""
    return {
        "familyId": FAMILY_ID,
        "channel": "rpc-jsonl",
        "protocol": PI_PROTOCOL_ID,
        "knownCommands": list(KNOWN_COMMANDS),
    }


class PiRpcClient:
    """Consumer of the pi native RPC JSONL channel over one owned
    :class:`ProcessChannel`. Each instance consumes exactly one caller-supplied channel
    (G8) and one request-id namespace (``req-N``); two clients never share
    ids, streams or cleanup."""

    def __init__(self, channel: ProcessChannel, *, name: str = "pi-rpc"):
        self._channel = channel
        self.name = name
        self._events: deque[Mapping[str, Any]] = deque()
        self._pending: dict[str, str] = {}  # request_id -> command (G11 ledger)
        self._prepared_waiting = set()
        self._request_seq = 0
        self._prepared = PreparedFramePool(PI_PROTOCOL_ID)
        self._rpc_lock = threading.RLock()
        self._run_state: str | None = None
        self._run_settled_event: Mapping[str, Any] | None = None
        self._ui_pending: dict[str, str] = {}
        self._ui_seen: set[str] = set()
        self._ui_lock = threading.RLock()

    # -- ledger / facts --------------------------------------------------
    @property
    def pending(self) -> dict[str, str]:
        """Requests written but not yet receipt-resolved (G11 ledger)."""
        return dict(self._pending)

    def describe(self) -> dict[str, Any]:
        return describe()

    def stderr_tail(self) -> str:
        """Peer stderr diagnostics tail — never protocol (G5)."""
        return self._channel.stderr_tail()

    # -- handshake / session ----------------------------------------------
    def initialize(self, *, timeout: float = 10.0) -> Any:
        """First handshake: one ``get_state`` command round trip.

        pi documents no initialize/version negotiation; none is invented
        here. Returns the response ``data`` verbatim (G4).
        """
        record = self._request("get_state", {}, timeout=timeout)
        return record.get("data")

    def create_session(self, *, timeout: float = 10.0, **fields: Any) -> Mapping[str, Any]:
        """Best-effort native session creation via the ``new_session`` command.

        Pi's session/resume/replay semantics are undocumented upstream, so
        the result is always the ``status:"prepared"`` structure with the
        native response ``data`` embedded verbatim — a real sessionId may
        appear inside ``data`` only if the peer sent one; this client never
        fabricates one (G6: sessionId identity stays native).
        """
        record = self._request("new_session", dict(fields), timeout=timeout)
        return {"status": "prepared", "command": "new_session", "data": record.get("data")}

    # -- prompt / settle ---------------------------------------------------
    def send_prompt(
        self,
        message: str,
        *,
        timeout: float = 10.0,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
        **fields: Any,
    ) -> Mapping[str, Any]:
        """Send the documented ``prompt`` command record.

        **The returned receipt is NOT a completion notice.** It is the
        response verbatim when it has no ``data``; additional ``data`` is
        returned unchanged for existing consumers. The pinned 0.86.1
        response has no disposition and proves only acceptance.
        Completion boundaries are observed via :meth:`wait_settled` /
        :meth:`events`, not from this receipt. ``on_event(raw_event)`` (if
        given) is fed every session event that arrives while this receipt is
        being waited for; it is never fed an auto-reply and never causes one
        (no auto-approve).
        """
        with self._rpc_lock:
            return self._send_prompt_locked(message, timeout=timeout, on_event=on_event, **fields)

    def _send_prompt_locked(self, message, *, timeout, on_event, **fields):
        if self._run_state == "unknown":
            raise LostReceipt("prompt", None, "prior prompt outcome remains unknown; next prompt refused")
        args = dict(fields)
        args["message"] = message
        # A historical settle event cannot conclude a subsequent prompt.
        self._run_settled_event = None
        try:
            record = self._request("prompt", args, timeout=timeout, on_event=on_event)
        except (RequestTimeout, LostReceipt):
            # Sent without a receipt: the run MAY be in flight — the outcome is
            # unknown, never "no run" (G11).
            self._run_state = "unknown"
            raise
        data = record.get("data")
        if self._run_settled_event is not None:
            self._run_state = "settled"
            return record.get("data", record)
        if isinstance(data, dict):
            disposition = data.get("disposition")
            if disposition == "started":
                self._run_state = "started"
            elif disposition == "handled":
                self._run_state = "handled"
            else:
                self._run_state = "accepted"
        else:
            self._run_state = "accepted"
        # Preserve data extensions used by existing consumers; the actual
        # pinned no-data response is returned verbatim, without a made-up
        # disposition or completion state.
        return record.get("data", record)

    def wait_settled(self, *, timeout: float) -> Mapping[str, Any]:
        """Collect session events until ``agent_settled`` or timeout.

        Returns the ``agent_settled`` event record verbatim (G4) — the only
        event certifying no automatic continuation. On deadline a typed
        :class:`RequestTimeout(method="agent_settled")` is raised; events
        already observed stay available verbatim via :meth:`events` (G11:
        the wait is never re-issued on its own). When no run is active
        (last prompt receipt was ``handled``, a settle was already observed,
        or no prompt was sent) this returns the ``{"outcome": "no-run", ...}``
        marker immediately instead of waiting — no run, no settle boundary,
        and no fabricated completion.
        """
        with self._rpc_lock:
            return self._wait_settled_locked(timeout=timeout)

    def _wait_settled_locked(self, *, timeout):
        if self._run_state == "unknown":
            # The prompt outcome was never observed (lost receipt / unknown
            # disposition): a run MAY exist. Answering "no-run" would be a
            # fabricated conclusion — the answer stays unknown (G11).
            return {
                "outcome": "unknown",
                "reason": "prompt receipt was lost or undocumented; run state unknown",
            }
        if self._run_settled_event is not None:
            return self._run_settled_event
        if self._run_state in _SETTLE_QUIET_STATES:
            return {
                "outcome": "no-run",
                "reason": f"no tracked run in progress (state={self._run_state!r})",
            }
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout(SETTLED_EVENT, None, timeout)
            try:
                message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError) as exc:
                self._run_state = "unknown"
                raise LostReceipt(SETTLED_EVENT, None, f"settle evidence unavailable: {exc}") from exc
            self._handle_frame(message.raw, waiting_id=None)
            if self._run_settled_event is not None:
                self._run_state = "settled"
                return self._run_settled_event

    # -- event stream -------------------------------------------------------
    def events(self) -> tuple[Mapping[str, Any], ...]:
        """Snapshot of the event stream so far, in arrival order.

        Every record — session events, unknown types (G4), no-id parse-error
        records, extension-UI records — is preserved verbatim as received on
        the wire; nothing is normalised or dropped.
        """
        return tuple(self._events)

    def next_event(self, *, timeout: float = 10.0) -> Mapping[str, Any]:
        """Next event record in arrival order, verbatim (G4).

        Raises :class:`RequestTimeout` (``method="<wait_event>"``) when the
        deadline elapses without an event; unknown frames are never dropped
        to satisfy the read.
        """
        deadline = time.monotonic() + timeout
        while True:
            if self._events:
                return self._events.popleft()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout("<wait_event>", None, timeout)
            try:
                message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            self._handle_frame(message.raw, waiting_id=None)

    def pump(self, *, timeout: float = 0.0) -> int:
        """Read frames already available (or arriving within ``timeout``) from
        the channel into the event stream (G4), without consuming them from
        :meth:`events`/:meth:`next_event`. Returns how many records were
        routed. Election off (never answers anything itself)."""
        deadline = time.monotonic() + timeout
        count = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return count
            message = self._channel.poll_message(timeout=remaining)
            if message is None:
                return count  # drained, closed or timed out — all "no more now"
            self._handle_frame(message.raw, waiting_id=None)
            count += 1

    # -- control --------------------------------------------------------------
    def cancel(self, *, timeout: float = 10.0, clear_queue: bool = False) -> Mapping[str, Any]:
        """Cancel via the documented ``abort`` command (optionally a
        ``clear_queue`` command first). Returns the raw ``abort`` response
        record verbatim — cancel is real evidence, never "completed" (G6)."""
        if clear_queue:
            self._request("clear_queue", {}, timeout=timeout)
        return self._request("abort", {}, timeout=timeout)

    def reply_extension_ui(
        self, request_id: Any, payload: Mapping[str, Any] | None = None
    ) -> None:
        """Answer an ``extension_ui_request`` with the SAME id, as the
        documented bidirectional record ``extension_ui_response``. ``payload``
        must be the native ``value``/``confirmed`` or ``cancelled:true`` shape
        for the observed dialog method. Notifications and unknown methods do
        not grant reply authority. Every dialog can be answered once, even
        if that write loses its outcome. No response is sent automatically."""
        fields = dict(payload or {})
        if {"id", "type"}.intersection(fields):
            raise ValueError("extension UI payload cannot replace record identity")
        with self._ui_lock:
            if not isinstance(request_id, str) or request_id not in self._ui_pending:
                raise ValueError("extension UI response requires an observed pending request")
            method = self._ui_pending[request_id]
            cancelled = set(fields) == {"cancelled"} and fields["cancelled"] is True
            expected = "confirmed" if method == "confirm" else "value"
            valid = (set(fields) == {expected} and (
                type(fields[expected]) is bool if expected == "confirmed"
                else isinstance(fields[expected], str)
            ))
            if not (cancelled or valid):
                raise ValueError("extension UI response does not match the native method")
            record = {"id": request_id, "type": "extension_ui_response", **fields}
            # Consume before writing: partial write/disconnect must never enable
            # the same reply to be re-sent. There is no native reply receipt.
            del self._ui_pending[request_id]
            self._channel.send_raw(record)

    def command(
        self, command_type: str, *, timeout: float = 10.0, **fields: Any
    ) -> Mapping[str, Any]:
        """Generic pi command round trip for any documented (or future)
        command name. Returns the full raw response record verbatim (G4);
        ``success:false`` raises :class:`PiCommandError`. Nothing here
        hard-codes a command as successful."""
        return self._request(command_type, dict(fields), timeout=timeout)

    # -- lifecycle --------------------------------------------------------------
    def close(self) -> int:
        """Release this client's own channel/process only (G6/G8). Other
        clients' connections are untouched; pending requests stay unknown and
        are never re-sent (G11)."""
        self._prepared.close()
        return self._channel.close()

    # -- internals -------------------------------------------------------------
    def _handle_frame(
        self, raw: Mapping[str, Any], *, waiting_id: str | None
    ) -> Mapping[str, Any] | None:
        """Route one channel frame.

        Returns the matched response record when it resolves ``waiting_id``;
        otherwise the frame is appended to the event stream verbatim (G4) and
        ``None`` is returned. Stale receipts for earlier (timed-out) requests
        are surfaced verbatim too; only their pending-ledger entry is cleared
        (the attempt itself is never re-issued, G11).
        """
        record_type = raw.get("type")
        rid = raw.get("id")
        addressed = isinstance(rid, (str, int))
        if (
            waiting_id is not None
            and record_type == "response"
            and addressed
            and rid == waiting_id
            and rid in self._pending
        ):
            if raw.get("command") != self._pending[rid] or type(raw.get("success")) is not bool:
                raise LostReceipt(self._pending[rid], rid, "response identity or success field invalid")
            self._ack_prepared_request(rid)
            del self._pending[rid]
            return raw
        if (record_type == "response" and type(raw.get("success")) is bool
                and addressed and rid in self._pending
                and raw.get("command") == self._pending[rid]):
            self._ack_prepared_request(rid)
            del self._pending[rid]
            # fall through: the stale receipt still surfaces verbatim below
        self._events.append(raw)
        if record_type == "extension_ui_request":
            self._observe_extension_ui(raw)
        if raw.get("type") == SETTLED_EVENT:
            self._run_settled_event = raw
        return None

    def _observe_extension_ui(self, raw: Mapping[str, Any]) -> None:
        """Qualify only pinned Pi dialog methods, preserving every raw event.

        rpc-types.ts:223-267 and rpc-mode.ts:126-250 at
        UPSTREAM_SOURCE_COMMIT distinguish dialogs from fire-and-forget UI.
        Unknown future methods stay visible without receiving reply authority.
        """
        method = raw.get("method")
        if not isinstance(method, str) or method not in {"select", "confirm", "input", "editor"}:
            return
        rid = raw.get("id")
        valid = isinstance(rid, str) and bool(rid) and isinstance(raw.get("title"), str)
        if method == "select":
            options = raw.get("options")
            valid = valid and isinstance(options, list) and all(isinstance(v, str) for v in options)
        if method == "confirm":
            valid = valid and isinstance(raw.get("message"), str)
        optional = "placeholder" if method == "input" else "prefill" if method == "editor" else None
        if optional is not None and optional in raw:
            valid = valid and isinstance(raw[optional], str)
        if "timeout" in raw:
            value = raw["timeout"]
            valid = valid and type(value) in (int, float) and 0 <= value < float("inf")
        if not valid:
            raise FramingError("malformed Pi extension UI dialog")
        with self._ui_lock:
            if rid in self._ui_seen:
                # Re-observation cannot resurrect a consumed callback or replace
                # the method attached to a pending native id.
                raise FramingError("duplicate Pi extension UI dialog id")
            self._ui_seen.add(rid)
            self._ui_pending[rid] = method

    def _input_gate(self, command):
        if command in {"prompt", "steer", "follow_up"} and self._run_state == "unknown":
            raise LostReceipt(command, None, "prior input outcome remains unknown; next input refused")

    def _unknown_request(self, command):
        # Only run-bearing inputs latch the run state: a refused read or config
        # command never implies a sentinel run or unknown input (G6/G11 apply to
        # input receipting, not to every record type). No re-send happens either
        # way; the original refusal still surfaces from its caller.
        if command in {"prompt", "steer", "follow_up"}:
            self._run_state = "unknown"
        cut = getattr(self._channel, "mark_input_unknown", None)
        if callable(cut):
            try:
                cut()
            except Exception:
                pass  # Preserve original receipt error; never restore a writer.

    def _ack_prepared_request(self, request_id):
        if request_id in self._prepared_waiting:
            self._channel.acknowledge_frame(request_id)
            self._prepared_waiting.remove(request_id)

    def prepare_request(self, command: str, fields: Mapping[str, Any]) -> PreparedFrame:
        """Freeze an original Pi record for capture; no send or authority."""
        with self._rpc_lock:
            return self._prepare_request_locked(command, fields)

    def _prepare_request_locked(self, command, fields):
        if (not isinstance(command, str) or not command or len(command) > 256
                or any(ord(c) < 32 for c in command) or not isinstance(fields, Mapping)):
            raise ValueError("native command and same-level fields required")
        if {"id", "type"}.intersection(fields):
            raise ValueError("command fields cannot replace record identity")
        self._input_gate(command)
        self._request_seq += 1
        rid = f"req-{self._request_seq}"
        return self._prepared.prepare({"id": rid, "type": command, **dict(fields)}, rid)

    def dispatch_prepared(self, frame: PreparedFrame, *, before_write,
                          timeout: float = 10.0, on_event=None) -> Mapping[str, Any]:
        """Spend once, guarded at actual write; no durable receipt or grant."""
        with self._rpc_lock:
            return self._dispatch_prepared_locked(frame, before_write=before_write, timeout=timeout, on_event=on_event)

    def _dispatch_prepared_locked(self, frame, *, before_write, timeout, on_event):
        if not callable(before_write) or on_event is not None and not callable(on_event):
            raise ValueError("explicit native write guard and callable event callback required")
        if type(timeout) not in (int, float) or not 0 < timeout < float('inf'):
            raise ValueError("finite positive receipt timeout required")
        if any(not callable(getattr(self._channel, name, None)) for name in
               ('send_frame', 'mark_input_unknown', 'acknowledge_frame')):
            raise PreparedFrameRefused("actual write barrier and unknown transport fence unavailable")
        rid, wire = self._prepared.consume(frame)
        command = json.loads(wire)["type"]
        self._input_gate(command)
        self._pending[rid] = command
        self._prepared_waiting.add(rid)
        if command in {"prompt", "steer", "follow_up"}:
            self._run_settled_event = None
        guard_failed = False
        def guard():
            nonlocal guard_failed
            try:
                before_write(wire)
            except BaseException:
                guard_failed = True
                raise
        try:
            self._channel.send_frame(wire, before_write=guard)
        except BaseException as exc:
            if guard_failed:
                self._pending.pop(rid, None)
                self._prepared_waiting.discard(rid)
                self._unknown_request(command)
                raise
            self._unknown_request(command)
            if isinstance(exc, ChannelClosed):
                raise LostReceipt(command, rid, f"write outcome unknown: {exc}") from exc
            raise
        try:
            record = self._wait_receipt(command, rid, timeout=timeout, on_event=on_event)
        except PiCommandError as error:
            if rid not in self._pending and error.request_id == rid and error.command == command:
                raise  # Only this original accepted native response is known.
            self._unknown_request(command)
            raise
        except BaseException:
            self._unknown_request(command)
            raise
        if command in {"prompt", "steer", "follow_up"}:
            self._run_state = "settled" if self._run_settled_event is not None else "accepted"
        return record

    def _request(self, command, fields, *, timeout, on_event=None):
        """Immediate consumer path; unknown input never enables another send."""
        with self._rpc_lock:
            return self._request_locked(command, fields, timeout=timeout, on_event=on_event)

    def _request_locked(self, command, fields, *, timeout, on_event=None):
        if {"id", "type"}.intersection(fields):
            raise ValueError("command fields cannot replace record identity")
        self._input_gate(command)
        self._request_seq += 1
        request_id = f"req-{self._request_seq}"
        self._pending[request_id] = command
        if command in {"prompt", "steer", "follow_up"}:
            self._run_settled_event = None
        try:
            self._channel.send_raw({"id": request_id, "type": command, **dict(fields)})
            record = self._wait_receipt(command, request_id, timeout=timeout, on_event=on_event)
        except ChannelClosed as exc:
            self._unknown_request(command)
            raise LostReceipt(command, request_id, f"write outcome unknown: {exc}") from exc
        except PiCommandError as error:
            if request_id not in self._pending and error.request_id == request_id and error.command == command:
                raise
            self._unknown_request(command)
            raise
        except BaseException:
            self._unknown_request(command)
            raise
        if command in {"prompt", "steer", "follow_up"}:
            self._run_state = "settled" if self._run_settled_event is not None else "accepted"
        return record

    def _wait_receipt(self, command, request_id, *, timeout, on_event=None):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout(command, request_id, timeout)
            try:
                message: Message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError) as exc:
                raise LostReceipt(
                    command, request_id, f"transport failure after send: {exc}"
                ) from exc
            try:
                matched = self._handle_frame(message.raw, waiting_id=request_id)
            except FramingError as exc:
                raise LostReceipt(command, request_id, f"invalid event after send: {exc}") from exc
            if matched is not None:
                if matched.get("success") is False:
                    raise PiCommandError(
                        command, request_id, matched.get("error"), raw=matched
                    )
                return matched
            if on_event is not None:
                on_event(message.raw)
