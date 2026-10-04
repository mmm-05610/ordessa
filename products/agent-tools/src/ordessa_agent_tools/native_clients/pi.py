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
- Receipts are NOT completion: ``prompt`` answers ``data.disposition`` as
  ``"started"`` or ``"handled"`` (``handled`` = no run started, no
  ``agent_settled`` will follow); ``agent_end`` is merely one run ending —
  retry/compaction/steer may follow. Only ``agent_settled`` means the agent
  will not automatically continue.
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
from collections import deque
from typing import Any, Callable, Mapping, Sequence

from ._transport import (
    ChannelClosed,  # noqa: F401 - re-typed here for callers
    ChannelFailure,
    FramingError,
    LaunchSpec,
    LostReceipt,
    Message,
    ProcessChannel,
    RequestTimeout,
)

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
    :class:`~ordessa_agent_tools.native_clients.LaunchSpec`). ``minimal``
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
    :class:`ProcessChannel`. Each instance owns exactly one channel/process
    (G8) and one request-id namespace (``req-N``); two clients never share
    ids, streams or cleanup."""

    def __init__(self, channel: ProcessChannel, *, name: str = "pi-rpc"):
        self._channel = channel
        self.name = name
        self._events: deque[Mapping[str, Any]] = deque()
        self._pending: dict[str, str] = {}  # request_id -> command (G11 ledger)
        self._request_seq = 0
        self._run_state: str | None = None

    @classmethod
    def launch(cls, spec: LaunchSpec, *, name: str = "pi-rpc") -> "PiRpcClient":
        """Launch the owned pi process described by ``spec`` and wrap it."""
        return cls(ProcessChannel.launch(spec, name=name), name=name)

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
        response ``data`` verbatim — per the pinned protocol a dict carrying
        ``data.disposition`` ``"started"`` or ``"handled"`` (``handled``
        means no run was started and no ``agent_settled`` will follow).
        Completion boundaries are observed via :meth:`wait_settled` /
        :meth:`events`, not from this receipt. ``on_event(raw_event)`` (if
        given) is fed every session event that arrives while this receipt is
        being waited for; it is never fed an auto-reply and never causes one
        (no auto-approve).
        """
        args = dict(fields)
        args["message"] = message
        record = self._request("prompt", args, timeout=timeout, on_event=on_event)
        data = record.get("data")
        if isinstance(data, dict):
            disposition = data.get("disposition")
            if disposition == "started":
                self._run_state = "started"
            elif disposition == "handled":
                self._run_state = "handled"
        return data

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
        if self._run_state in _SETTLE_QUIET_STATES:
            return {
                "outcome": "no-run",
                "reason": f"no tracked run in progress (state={self._run_state!r})",
            }
        deadline = time.monotonic() + timeout
        index = 0  # non-destructive scan: observed events stay in the stream
        while True:
            if index < len(self._events):
                raw = self._events[index]
                index += 1
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RequestTimeout(SETTLED_EVENT, None, timeout)
                try:
                    message = self._channel.next_message(timeout=remaining)
                except RequestTimeout:
                    continue
                self._handle_frame(message.raw, waiting_id=None)
                continue
            if raw.get("type") == SETTLED_EVENT:
                self._run_state = "settled"
                return raw

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
        keys go out verbatim as same-level fields. This client never replies
        on its own initiative (no auto-approve)."""
        record: dict[str, Any] = {"id": request_id, "type": "extension_ui_response"}
        if payload:
            record.update(payload)
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
            del self._pending[rid]
            return raw
        if record_type == "response" and "success" in raw and addressed and rid in self._pending:
            del self._pending[rid]
            # fall through: the stale receipt still surfaces verbatim below
        self._events.append(raw)
        return None

    def _request(
        self,
        command: str,
        fields: Mapping[str, Any],
        *,
        timeout: float,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> Mapping[str, Any]:
        """One pi command round trip: same-id ``success`` receipt or typed
        failure. Never retries (G11); a write failure before send is
        ChannelClosed, a transport breach after send is LostReceipt
        (outcome unknown), a deadline is RequestTimeout."""
        self._request_seq += 1
        request_id = f"req-{self._request_seq}"
        payload: dict[str, Any] = {"id": request_id, "type": command}
        payload.update(fields)
        self._channel.send_raw(payload)  # raises ChannelClosed when already closed
        self._pending[request_id] = command  # written: a lost receipt stays unknown
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
            matched = self._handle_frame(message.raw, waiting_id=request_id)
            if matched is not None:
                if matched.get("success") is False:
                    raise PiCommandError(
                        command, request_id, matched.get("error"), raw=matched
                    )
                return matched
            if on_event is not None:
                on_event(message.raw)
