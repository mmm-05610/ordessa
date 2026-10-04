"""Kimi Wire consumer client (family ``kimi``, protocol ``kimi-wire/1.10``).

Pinned facts (N006, official Wire mode docs read 2026-10-04; legacy Python
Kimi CLI, final release 1.52.0, Apache-2.0). All source URLs are recorded in
``docs/implementation/agent-tools/night-harness-expansion/evidence/kimi-decision.md``.

- Launch: ``kimi --wire`` over stdin/stdout, JSON-RPC 2.0, one JSON object per
  line. ``initialize`` (added Wire 1.1) is optional: legacy clients may send
  ``prompt`` directly. A server that does not support ``initialize`` answers
  ``-32601`` and the documented behaviour is to fall back to no-handshake
  mode. ``params.protocol_version`` is the only negotiation field; mismatch
  handling is **not documented** and is surfaced as ``unknown`` here, never
  invented into a downgrade/retry policy.
- ``prompt``: the agent sends ``event`` notifications and ``request`` frames
  while the turn runs and returns the prompt response when the turn completes,
  with ``status`` ``finished`` | ``cancelled`` | ``max_steps_reached``.
  **The write is not completion**: only this response carries terminal status,
  and a missing response is a typed timeout with the outcome unknown (G11) —
  never fabricated into "completed". Nothing is ever re-sent.
- ``event`` notifications carry ``{"type": ..., "payload": {...}}`` Wire
  messages; ``request`` frames are agent→client (``ApprovalRequest``,
  ``QuestionRequest``, ``ToolCallRequest``, ``HookRequest``) and are answered
  on the SAME JSON-RPC id. **This client never auto-approves**: without an
  explicit caller decision the frame stays unanswered and verbatim in
  :meth:`inbound_requests`.
- ``replay`` (Wire 1.3+) re-sends recorded history read-only; the docs state
  clients must not respond to replayed request messages. This client enforces
  that explicitly: every request frame observed during a replay is fenced and
  any later reply targeting it raises :class:`ReplayResponseRefused`.
- ``steer`` injects into the running turn (``{"status": "steered"}`);
  ``cancel`` cancels the running turn/replay (the prompt then answers
  ``status: cancelled``).
- The Rust variant (``kimi-agent``) is a different, experimental capability
  set; :meth:`KimiWireClient.launch` requires the documented ``--wire`` entry
  point and refuses auto-approve launch flags, so it is never silently
  substituted.

The client is a pure consumer over the frozen N001 transport seam
(``_transport``): byte framing, unknown preservation, typed failures, no
retry (G5/G4/G11) and owned-process cleanup (G8) delegate there; this module
adds only kimi's document-level record shapes. No runtimeReady is ever
claimed (L2 NOT RUN — no kimi CLI on this machine).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Sequence

from ._transport import (
    ChannelClosed,  # noqa: F401 - re-typed here for callers
    ChannelFailure,
    FramingError,
    LaunchSpec,
    LostReceipt,
    Message,
    ProcessChannel,
    RemoteFailure,
    RequestTimeout,
)

FAMILY_ID = "kimi"
PROTOCOL = "kimi-wire/1.10"

#: Wire protocol version pinned from the official docs (2026-10-04).
WIRE_PROTOCOL_VERSION = "1.10"

#: Documented client→agent Wire methods (Wire 1.10 doc state).
KNOWN_METHODS: tuple[str, ...] = (
    "initialize",
    "prompt",
    "replay",
    "steer",
    "set_plan_mode",
    "cancel",
)

#: Documented prompt terminal statuses — carried verbatim, never remapped.
PROMPT_TERMINAL_STATUSES = frozenset({"finished", "cancelled", "max_steps_reached"})

#: Documented agent→client request payload types.
INBOUND_REQUEST_TYPES: tuple[str, ...] = (
    "ApprovalRequest",
    "ToolCallRequest",
    "QuestionRequest",
    "HookRequest",
)

#: Documented approval decisions; the caller always picks one (SAFETY).
APPROVAL_RESPONSES = frozenset({"approve", "approve_for_session", "reject"})

#: Launch flags that would auto-approve tool calls. This client refuses to
#: launch a channel built to bypass the caller's approval decisions (SAFETY).
FORBIDDEN_AUTO_APPROVE_FLAGS: tuple[str, ...] = (
    "--yolo",
    "--yes",
    "--auto-approve",
    "--afk",
)


class KimiRpcError(RemoteFailure):
    """The peer answered with a JSON-RPC error object (raw error kept)."""

    def __init__(self, method: str, request_id: Any, raw_error: Mapping[str, Any]):
        super().__init__(
            f"{method}#{request_id}: {raw_error.get('message', raw_error)}",
            code=raw_error.get("code"),
            data=raw_error.get("data"),
        )
        self.method = method
        self.request_id = request_id
        self.raw_error = dict(raw_error)


class ReplayResponseRefused(ChannelFailure):
    """N006 explicit fence: a replayed request is never answered.

    Wire ``replay`` re-sends recorded history read-only; answering a replayed
    ``ApprovalRequest``/``QuestionRequest`` would approve history a second
    time. The client refuses both automatic and explicit replies for any
    request id observed during replay.
    """

    def __init__(self, request_id: Any):
        super().__init__(
            "REPLAY_RESPONSE_REFUSED",
            (
                f"request id {request_id!r} was replayed from history; replay is "
                "read-only and must never answer historical approval/question "
                "requests"
            ),
        )
        self.request_id = request_id


def describe() -> dict[str, Any]:
    """Static channel facts for the kimi Wire family. No runtimeReady claim."""
    return {
        "familyId": FAMILY_ID,
        "channel": "wire-jsonrpc-stdio",
        "protocol": PROTOCOL,
        "wireVersion": WIRE_PROTOCOL_VERSION,
        "handshake": (
            "initialize (optional; protocol_version negotiated) with documented "
            "-32601 no-handshake fallback; mismatch policy unknown"
        ),
        "knownMethods": list(KNOWN_METHODS),
        "inboundRequestTypes": list(INBOUND_REQUEST_TYPES),
        "promptSemantics": (
            "documented: the response is returned when the turn completes and "
            "carries finished|cancelled|max_steps_reached; the write is not "
            "completion and a missing response is unknown (never re-sent)"
        ),
        "replaySemantics": (
            "read-only history re-send; clients must not answer replayed "
            "requests (enforced by ReplayResponseRefused)"
        ),
        "variants": (
            "python kimi --wire pinned; Rust kimi-agent is a different "
            "capability set and is not substituted"
        ),
    }


class KimiWireClient:
    """Consumer of one owned ``kimi --wire`` stdio channel.

    Each instance owns exactly one channel/process (G8) and one request-id
    namespace (``req-N``); two clients never share ids, streams or cleanup.
    It holds no instance/task ledger and claims no runtime readiness.
    """

    def __init__(self, channel: ProcessChannel, *, name: str = "kimi-wire"):
        self._channel = channel
        self.name = name
        self._events: list[Mapping[str, Any]] = []
        self._inbound_by_id: dict[Any, Mapping[str, Any]] = {}
        self._unanswered: list[Mapping[str, Any]] = []
        self._pending: dict[str, str] = {}  # request_id -> method (G11 ledger)
        self._responses: dict[str, Mapping[str, Any]] = {}  # out-of-order receipts
        self._request_seq = 0
        self._replayed_request_ids: set[Any] = set()
        self._replay_in_progress = False
        self._handshake = "none"  # "none" | "initialized" | "no-handshake"
        self._server_protocol_version: Any = None

    @classmethod
    def launch(cls, spec: LaunchSpec, *, name: str = "kimi-wire") -> "KimiWireClient":
        """Launch the owned kimi process described by ``spec`` and wrap it.

        The spec is validated *before any process is spawned*: the documented
        ``--wire`` entry point must be present (a Rust ``kimi-agent`` argv is a
        different capability set, never substituted) and auto-approve flags
        are refused (this client exists to keep the caller's decision in the
        loop).
        """
        cls._validate_launch_spec(spec)
        return cls(ProcessChannel.launch(spec, name=name), name=name)

    @staticmethod
    def _validate_launch_spec(spec: LaunchSpec) -> None:
        argv = tuple(spec.argv) if spec is not None and spec.argv else ()
        if not argv:
            raise ValueError("refused before spawn: launch spec has an empty argv")
        for flag in FORBIDDEN_AUTO_APPROVE_FLAGS:
            if flag in argv:
                raise ValueError(
                    f"refused before spawn: auto-approve launch flag {flag!r} is "
                    "forbidden (the caller owns every approval decision)"
                )
        if "--wire" not in argv:
            raise ValueError(
                "refused before spawn: the kimi wire client requires the "
                "documented `kimi --wire` entry point; the Rust `kimi-agent` "
                "variant is a different capability set and is never substituted"
            )

    # -- ledger / facts ---------------------------------------------------
    @property
    def pending(self) -> dict[str, str]:
        """Requests written but not yet receipt-resolved (G11 ledger)."""
        return dict(self._pending)

    @property
    def handshake(self) -> str:
        """``none`` (not attempted), ``initialized`` or documented ``no-handshake``."""
        return self._handshake

    def describe(self) -> dict[str, Any]:
        return describe()

    def events(self) -> tuple[Mapping[str, Any], ...]:
        """Snapshot of preserved frames in arrival order.

        Event notifications, inbound ``request`` frames (including replayed
        ones), unknown methods and stale/foreign responses are all kept
        verbatim (G4); nothing is normalised or dropped.
        """
        return tuple(self._events)

    def inbound_requests(self) -> tuple[Mapping[str, Any], ...]:
        """Every agent→client ``request`` frame seen, verbatim (G4)."""
        return tuple(self._inbound_by_id.values())

    def unanswered_requests(self) -> tuple[Mapping[str, Any], ...]:
        """Inbound requests this client has not been asked to answer.

        They stay here (never auto-approved) until the caller explicitly
        replies or they are fenced as replayed.
        """
        return tuple(self._unanswered)

    def stderr_tail(self) -> str:
        """Peer stderr diagnostics tail — never protocol (G5)."""
        return self._channel.stderr_tail()

    # -- handshake / session ----------------------------------------------
    def initialize(
        self,
        *,
        timeout: float = 10.0,
        client_name: str = "ordessa-agent-tools",
        client_version: str = "0.1.0a2",
        supports_question: bool = True,
        supports_plan_mode: bool = False,
        external_tools: Sequence[Mapping[str, Any]] | None = None,
        hooks: Sequence[Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        """Optional handshake with documented protocol-version negotiation.

        Sends ``initialize`` with ``params.protocol_version`` (this client
        implements Wire 1.10) and returns the negotiation fields verbatim:
        the server's reported ``protocol_version``, server info,
        ``slash_commands`` and capabilities. A version mismatch is surfaced
        (``version_match: False``) because no mismatch policy is documented —
        nothing is downgraded or retried. A ``-32601`` answer triggers the
        documented fallback to no-handshake mode instead of an exception.
        """
        params: dict[str, Any] = {
            "protocol_version": WIRE_PROTOCOL_VERSION,
            "client": {"name": client_name, "version": client_version},
            "capabilities": {"supports_question": bool(supports_question)},
        }
        if supports_plan_mode:
            params["capabilities"]["supports_plan_mode"] = True
        if external_tools is not None:
            params["external_tools"] = [dict(tool) for tool in external_tools]
        if hooks is not None:
            params["hooks"] = [dict(hook) for hook in hooks]
        try:
            result = self._request("initialize", params, timeout=timeout)
        except KimiRpcError as exc:
            if exc.remote_code == -32601:
                self._handshake = "no-handshake"
                return {
                    "handshake": "no-handshake",
                    "client_declared_version": WIRE_PROTOCOL_VERSION,
                    "server_reported_version": None,
                    "version_match": "unknown",
                    "reason": (
                        "server answered -32601; documented fallback to "
                        "no-handshake mode (legacy prompt-only clients)"
                    ),
                }
            raise
        self._handshake = "initialized"
        server_version: Any = None
        if isinstance(result, Mapping):
            server_version = result.get("protocol_version")
        self._server_protocol_version = server_version
        version_match: bool | str
        if server_version is None:
            version_match = "unknown"
        else:
            version_match = server_version == WIRE_PROTOCOL_VERSION
        return {
            "handshake": "initialized",
            "client_declared_version": WIRE_PROTOCOL_VERSION,
            "server_reported_version": server_version,
            "version_match": version_match,
            "server": result.get("server") if isinstance(result, Mapping) else None,
            "slash_commands": (
                result.get("slash_commands") if isinstance(result, Mapping) else None
            ),
            "capabilities": (
                result.get("capabilities") if isinstance(result, Mapping) else None
            ),
            "external_tools": (
                result.get("external_tools") if isinstance(result, Mapping) else None
            ),
            "result": result,
        }

    def create_session(self, *, timeout: float = 10.0, **fields: Any) -> Mapping[str, Any]:
        """Session creation is CLI-owned; no wire method exists (G6).

        Wire 1.10 documents NO session-create request — sessions are created
        by the CLI at launch (``--session <id>`` creates a new one when the id
        is unknown; ``--continue`` resumes the last). This method therefore
        sends **nothing** and stays at the ``prepared`` state; a sessionId is
        never fabricated. ``timeout``/``fields`` are recorded as caller intent.
        """
        return {
            "status": "prepared",
            "method": None,
            "requested": dict(fields),
            "session": None,
            "note": (
                "Wire 1.10 has no session-create method; native session "
                "identity is owned by the CLI launch (--session/--continue)"
            ),
        }

    # -- prompt / control --------------------------------------------------
    def send_prompt(
        self,
        message: str,
        *,
        timeout: float = 120.0,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
        on_request: Callable[[Mapping[str, Any]], None] | None = None,
        **fields: Any,
    ) -> Mapping[str, Any]:
        """Send the documented ``prompt`` request and await the turn end.

        Per the pinned docs the response is returned only when the turn
        completes, carrying ``status`` ``finished`` | ``cancelled`` |
        ``max_steps_reached``. The returned mapping is that native result
        verbatim: **the write is never completion**, the status is never
        remapped, and a deadline is a typed :class:`RequestTimeout` with the
        outcome unknown (never re-sent, G11). While the turn runs, ``event``
        notifications are preserved in :meth:`events` and fed to
        ``on_event(raw)``; agent→client requests are handed to ``on_request``
        if given, otherwise queued unanswered (no auto-approve).
        """
        params: dict[str, Any] = dict(fields)
        params["user_input"] = message
        result = self._request(
            "prompt", params, timeout=timeout, on_event=on_event, on_request=on_request
        )
        return dict(result) if isinstance(result, Mapping) else {}

    def steer(
        self,
        message: str,
        *,
        timeout: float = 10.0,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
        **fields: Any,
    ) -> Mapping[str, Any]:
        """Inject input into the running turn (documented ``steer``)."""
        params: dict[str, Any] = dict(fields)
        params["user_input"] = message
        result = self._request("steer", params, timeout=timeout, on_event=on_event)
        return dict(result) if isinstance(result, Mapping) else {}

    def cancel(self, *, timeout: float = 10.0) -> Mapping[str, Any]:
        """Documented ``cancel`` (no params) — real evidence, never 'completed'.

        The in-flight prompt then returns ``status: cancelled``; cancel does
        not fabricate a turn result by itself.
        """
        result = self._request("cancel", {}, timeout=timeout)
        return dict(result) if isinstance(result, Mapping) else {}

    def set_plan_mode(self, enabled: bool, *, timeout: float = 10.0) -> Mapping[str, Any]:
        """Documented ``set_plan_mode``; requires supports_plan_mode at init."""
        result = self._request("set_plan_mode", {"enabled": bool(enabled)}, timeout=timeout)
        return dict(result) if isinstance(result, Mapping) else {}

    def replay(
        self,
        *,
        timeout: float = 30.0,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> Mapping[str, Any]:
        """Documented read-only ``replay`` history re-send (Wire 1.3+).

        While the replay response is awaited, every inbound ``request`` frame
        is recorded as **replayed** and is never delivered to a handler nor
        answered (N006 fence); its id stays fenced for the rest of the client's
        life, so a later explicit reply raises :class:`ReplayResponseRefused`.
        Returns the native result (``status`` plus ``events``/``requests``
        counts) verbatim.
        """
        self._replay_in_progress = True
        try:
            result = self._request("replay", {}, timeout=timeout, on_event=on_event)
        finally:
            self._replay_in_progress = False
        return result if isinstance(result, Mapping) else {"status": result}

    # -- event stream -------------------------------------------------------
    def next_event(self, *, timeout: float = 10.0) -> Mapping[str, Any]:
        """Next preserved frame in arrival order, verbatim (G4).

        Raises :class:`RequestTimeout` (``method="<wait_event>"``) on deadline;
        unknown frames are never dropped to satisfy the read.
        """
        deadline = time.monotonic() + timeout
        while True:
            if self._events:
                return self._events.pop(0)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout("<wait_event>", None, timeout)
            try:
                message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            # ChannelClosed/FramingError propagate as their own typed failures.
            self._route_frame(message.raw)

    def pump(self, *, timeout: float = 0.0) -> int:
        """Read frames already available into the preserved stream (G4).

        Returns how many records were routed; nothing is answered and no
        caller hook fires (election off)."""
        deadline = time.monotonic() + timeout
        count = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return count
            message = self._channel.poll_message(timeout=remaining)
            if message is None:
                return count  # drained, closed or timed out — all "no more now"
            self._route_frame(message.raw)
            count += 1

    # -- reverse requests (never auto-answered) -----------------------------
    def reply_approval(
        self,
        request_id: Any,
        response: str,
        *,
        feedback: str | None = None,
    ) -> None:
        """Answer an ``ApprovalRequest`` on the SAME JSON-RPC id.

        ``response`` must be one of the documented decisions and is always
        caller-chosen — there is no default and no auto-approve (SAFETY).
        Replayed requests are refused (:class:`ReplayResponseRefused`).
        """
        if response not in APPROVAL_RESPONSES:
            raise ValueError(f"response must be one of {sorted(APPROVAL_RESPONSES)}")
        self._assert_reply_allowed(request_id)
        result: dict[str, Any] = {
            "request_id": self._payload_id(request_id),
            "response": response,
        }
        if feedback is not None:
            result["feedback"] = feedback
        self._channel.reply(request_id, result)

    def reply_question(self, request_id: Any, answers: Mapping[str, str]) -> None:
        """Answer a ``QuestionRequest`` on the SAME JSON-RPC id.

        ``answers`` is the caller's mapping (empty mapping = dismissed);
        nothing is guessed for the caller. Replayed requests are refused.
        """
        self._assert_reply_allowed(request_id)
        result = {"request_id": self._payload_id(request_id), "answers": dict(answers)}
        self._channel.reply(request_id, result)

    def reply_tool_call(
        self,
        request_id: Any,
        *,
        tool_call_id: str | None = None,
        return_value: Mapping[str, Any],
    ) -> None:
        """Answer a ``ToolCallRequest`` on the SAME JSON-RPC id.

        The caller performs the external tool; the documented result shape is
        ``{tool_call_id, return_value}``. Replayed requests are refused.
        """
        self._assert_reply_allowed(request_id)
        result = {
            "tool_call_id": tool_call_id
            if tool_call_id is not None
            else self._payload_id(request_id),
            "return_value": dict(return_value),
        }
        self._channel.reply(request_id, result)

    def reply_request(self, request_id: Any, result: Any) -> None:
        """Generic same-id reply for documented/future request frames.

        The fence still applies: replayed request ids are refused.
        """
        self._assert_reply_allowed(request_id)
        self._channel.reply(request_id, result)

    def reply_request_error(
        self, request_id: Any, *, code: int, message: str, data: Any = None
    ) -> None:
        """JSON-RPC error reply; replayed request ids are refused as well."""
        self._assert_reply_allowed(request_id)
        self._channel.reply_error(request_id, code=code, message=message, data=data)

    # -- generic / lifecycle ------------------------------------------------
    def command(
        self,
        method: str,
        *,
        timeout: float = 10.0,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
        on_request: Callable[[Mapping[str, Any]], None] | None = None,
        **params: Any,
    ) -> Any:
        """Generic documented/future method round trip; result verbatim (G4).

        Unknown semantics are never invented; JSON-RPC errors become typed
        :class:`KimiRpcError` with the raw error object kept.
        """
        return self._request(
            method, dict(params), timeout=timeout, on_event=on_event, on_request=on_request
        )

    def close(self) -> int:
        """Release this client's own channel/process only (G6/G8). Other
        clients' connections are untouched; pending requests stay unknown and
        are never re-sent (G11)."""
        return self._channel.close()

    # -- internals -----------------------------------------------------------
    def _assert_reply_allowed(self, request_id: Any) -> None:
        if request_id in self._replayed_request_ids:
            raise ReplayResponseRefused(request_id)

    def _payload_id(self, request_id: Any) -> Any:
        frame = self._inbound_by_id.get(request_id)
        if frame is None:
            raise ValueError(
                f"no inbound request seen with JSON-RPC id {request_id!r}; "
                "refusing to fabricate a payload identity"
            )
        params = frame.get("params")
        payload = params.get("payload") if isinstance(params, Mapping) else None
        if isinstance(payload, Mapping) and "id" in payload:
            return payload["id"]
        if isinstance(payload, Mapping) and "tool_call_id" in payload:
            return payload["tool_call_id"]
        raise ValueError(
            f"inbound request {request_id!r} has no documented payload id; "
            "refusing to fabricate one"
        )

    def _route_request(self, raw: Mapping[str, Any], *, deliver: bool) -> None:
        """Preserve an inbound request verbatim; answer nothing by itself."""
        rid = raw.get("id")
        self._inbound_by_id[rid] = raw
        if self._replay_in_progress:
            # N006 fence: during a replay window nothing inbound is answered
            # and no caller handler may even be offered the chance.
            self._replayed_request_ids.add(rid)
            return
        if deliver:
            return  # the waiter's on_request callback receives it directly
        self._unanswered.append(raw)

    def _route_frame(self, raw: Mapping[str, Any]) -> None:
        """Pump-side router: preserve frames without answering anything."""
        method = raw.get("method")
        if method == "request":
            if raw.get("id") not in self._inbound_by_id:
                self._events.append(raw)
            self._route_request(raw, deliver=False)
            return
        if method == "event" or method is not None:
            self._events.append(raw)
            return
        rid = raw.get("id")
        if rid in self._pending:
            self._responses[rid] = raw
            return
        self._events.append(raw)

    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
        on_request: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> Any:
        """One JSON-RPC round trip: same-id result/error or typed failure.

        Never retries (G11): a write failure before send is ChannelClosed, a
        transport breach after send is LostReceipt (outcome unknown), a
        deadline is RequestTimeout. Responses for *other* in-flight requests
        are stashed by id, so nested requests (e.g. ``steer``/``cancel``
        issued from an event callback while ``prompt`` is pending) never steal
        each other's receipts (G6).
        """
        self._request_seq += 1
        request_id = f"req-{self._request_seq}"
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params:
            payload["params"] = dict(params)
        self._channel.send_raw(payload)  # raises ChannelClosed when already closed
        self._pending[request_id] = method  # written: a lost receipt stays unknown
        deadline = time.monotonic() + timeout
        while True:
            raw = self._responses.pop(request_id, None)
            if raw is not None:
                del self._pending[request_id]
                # A response that resolves a nested request can carry an error.
                error = raw.get("error")
                if error is not None:
                    raise KimiRpcError(method, request_id, error)
                return raw.get("result")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout(method, request_id, timeout)
            try:
                message: Message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError) as exc:
                raise LostReceipt(
                    method, request_id, f"transport failure after send: {exc}"
                ) from exc
            incoming = message.raw
            incoming_method = incoming.get("method")
            if incoming_method == "event":
                self._events.append(incoming)
                if on_event is not None:
                    on_event(incoming)
                continue
            if incoming_method == "request":
                self._events.append(incoming)
                if not self._replay_in_progress and on_request is not None:
                    self._route_request(incoming, deliver=True)
                    on_request(incoming)
                else:
                    self._route_request(incoming, deliver=False)
                continue
            if incoming_method is not None:
                # Future/unknown notification: preserved verbatim (G4).
                self._events.append(incoming)
                if on_event is not None:
                    on_event(incoming)
                continue
            rid = incoming.get("id")
            if rid == request_id:
                del self._pending[request_id]
                error = incoming.get("error")
                if error is not None:
                    raise KimiRpcError(method, request_id, error)
                return incoming.get("result")
            if rid in self._pending:
                # Receipt for another in-flight (possibly nested) request.
                self._responses[rid] = incoming
                continue
            # Stale/foreign response: preserved verbatim, never a receipt.
            self._events.append(incoming)
