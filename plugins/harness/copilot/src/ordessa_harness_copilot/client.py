"""GitHub Copilot CLI consumer client (family ``copilot``, protocol ``copilot-cli-jsonrpc/3``).

Pinned facts (N009, official docs and first-hand ``github/copilot-sdk`` source
read 2026-10-04; SDK v1.0.16, CLI release v1.0.91, SDK-bundled CLI snapshot
1.0.90; MIT SDK / custom GitHub Copilot CLI License — see
``docs/implementation/agent-tools/night-harness-expansion/evidence/
copilot-decision.md`` for every source URL):

- Transport: JSON-RPC over stdio to the CLI **server mode**
  (``copilot --headless --stdio``; the SDK child argv is ``--headless
  --no-auto-update --log-level <lvl> [--no-auto-login] --stdio``). TCP is
  documented as ``--headless --port N`` but is never used by this client.
- Handshake: ``connect`` (docs name ``server.connect``) carries
  ``supportedTaskKinds`` and optional ``clientInfo`` and returns
  ``protocolVersion``. A legacy server answering ``-32601`` falls back to
  ``ping``. The Python SDK pins protocol min == max == 3: an unreported or
  out-of-range version is a hard typed error — never downgraded, never
  retried.
- Sessions: ``session.create`` / ``session.resume`` return the native
  ``sessionId`` (never fabricated). ``session.send`` returns a
  ``{messageId}`` **receipt**; ``wait`` defaults to false, and even an
  explicit wait still only guarantees the same receipt — completion evidence
  is the ``session.idle`` event. ``session.abort`` (``{sessionId}``) is the
  documented cancellation.
- Permissions: the CLI asks the consumer; the client answers against the
  SAME JSON-RPC id with a documented ``PermissionDecisionKind`` value. This
  client NEVER auto-approves: without an explicit caller decision the frame
  stays verbatim in :meth:`unanswered_requests` and nothing is written.
- The SDK auto-downloads / spawns the CLI and can read account state (pinned
  risk in N009). This client is therefore explicit-binary only: it refuses a
  launch spec without the documented server flags and without/with auto
  approve flags, and never passes a token (G12). G8 cleanup targets only the
  owned ``ProcessChannel`` process.

The client is a pure consumer over the frozen N001 transport seam
(``_transport``): byte framing, unknown preservation, typed failures, no
retry (G5/G4/G11) and owned-process cleanup (G8) delegate there. No
runtimeReady is ever claimed (L2 NOT RUN — no copilot CLI on this machine).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from ordessa_execution_agents.harness.transport.channel import (
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

FAMILY_ID = "copilot"
PROTOCOL = "copilot-cli-jsonrpc/3"

#: Protocol version pinned from ``sdk-protocol-version.json`` {"version": 3}
#: and the Python SDK bound ``_MIN_PROTOCOL_VERSION = 3`` (main, 2026-10-04).
SDK_PROTOCOL_VERSION = 3
MIN_PROTOCOL_VERSION = 3

#: Documented client-visible JSON-RPC methods (generated rpc surface + docs).
KNOWN_METHODS: tuple[str, ...] = (
    "connect",
    "ping",
    "session.create",
    "session.resume",
    "session.send",
    "session.abort",
    "session.permissions.handlePendingPermissionRequest",
    "session.interruptMainTurn",
    "session.shutdown",
)

#: Documented event type strings (streaming-events guide).
EVENT_TYPES: tuple[str, ...] = (
    "assistant.turn_start",
    "assistant.intent",
    "assistant.reasoning",
    "assistant.reasoning_delta",
    "assistant.message",
    "assistant.message_delta",
    "assistant.turn_end",
    "assistant.usage",
    "assistant.streaming_delta",
    "tool.execution_start",
    "tool.execution_partial_result",
    "tool.execution_progress",
    "tool.execution_complete",
    "tool.user_requested",
    "session.idle",
    "session.error",
    "session.compaction_start",
    "session.compaction_complete",
    "session.title_changed",
    "session.context_changed",
    "session.usage_info",
    "session.session_limits_changed",
    "session.usage_checkpoint",
    "session.task_complete",
    "session.shutdown",
    "permission.requested",
    "permission.completed",
    "user_input.requested",
    "user_input.completed",
    "elicitation.requested",
    "elicitation.completed",
    "subagent.started",
    "subagent.completed",
    "subagent.failed",
    "subagent.selected",
    "subagent.deselected",
    "skill.invoked",
    "abort",
    "user.message",
    "system.message",
    "external_tool.requested",
    "external_tool.completed",
    "exit_plan_mode.requested",
    "exit_plan_mode.completed",
    "command.queued",
    "command.completed",
    "session_limits_exhausted.requested",
    "session_limits_exhausted.completed",
)

#: Documented ``PermissionDecisionKind`` values usable as a reply. The caller
#: always chooses one — there is no default and no auto-approve (SAFETY).
#: ``no-result`` is deliberately excluded: it is an SDK sentinel meaning
#: "leave the request unanswered", not a decision.
PERMISSION_DECISIONS = frozenset(
    {
        "approve-once",
        "approve-for-session",
        "approve-for-location",
        "approve-permanently",
        "approve-read-only-for-session",
        "reject",
        "cancelled",
        "user-not-available",
    }
)

#: Launch flags that would bypass the caller's approval decisions. The Copilot
#: README promises "nothing happens without your explicit approval"; a client
#: that launched with an allow-all flag would break that guarantee (SAFETY).
FORBIDDEN_AUTO_APPROVE_FLAGS: tuple[str, ...] = (
    "--allow-all",
    "--allow-all-tools",
    "--allow-all-paths",
    "--yolo",
    "--auto-approve",
    "--yes",
)

#: The documented server-mode entry markers (SDK argv / docs).
REQUIRED_SERVER_FLAGS: tuple[str, ...] = ("--headless",)


class CopilotRpcError(RemoteFailure):
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


class CopilotProtocolError(ChannelFailure):
    """The server's protocol version is unreported or out of the pinned range.

    The SDK documents min == max == 3; no downgrade or retry exists, so this
    is surfaced as a hard typed failure instead of an invented fallback.
    """

    def __init__(self, detail: str):
        super().__init__("PROTOCOL_MISMATCH", detail)


class CopilotNotConnected(ChannelFailure):
    """A session RPC was attempted before the ``connect`` handshake."""

    def __init__(self, method: str):
        super().__init__(
            "NOT_CONNECTED",
            f"{method} refused before send: run connect() first (no frame written)",
        )


class CopilotConfigurationError(ChannelFailure):
    """Required native configuration is missing; refused before any write."""

    def __init__(self, detail: str):
        super().__init__("CONFIGURATION_MISSING", detail)


def describe() -> dict[str, Any]:
    """Static channel facts for the copilot family. No runtimeReady claim."""
    return {
        "familyId": FAMILY_ID,
        "channel": "stdio-jsonrpc-server-mode",
        "protocol": PROTOCOL,
        "protocolVersion": SDK_PROTOCOL_VERSION,
        "minProtocolVersion": MIN_PROTOCOL_VERSION,
        "transport": (
            "CLI server mode over stdio (`copilot --headless --stdio`); TCP "
            "`--headless --port N` documented but unused here"
        ),
        "handshake": (
            "connect (docs name server.connect) with supportedTaskKinds/clientInfo "
            "-> protocolVersion; legacy -32601 falls back to ping; out-of-range is "
            "a hard error"
        ),
        "knownMethods": list(KNOWN_METHODS),
        "permissionDecisions": sorted(PERMISSION_DECISIONS),
        "eventTypes": list(EVENT_TYPES),
        "receiptSemantics": (
            "session.send returns {messageId}; wait defaults to false; the receipt "
            "is never completion — completion evidence is session.idle"
        ),
        "sessionState": "COPILOT_HOME/session-state/{sessionId}/ (documented)",
        "cliManagement": (
            "consumes an explicitly bound binary only; never the SDK "
            "auto-download/managed process; no token is ever injected"
        ),
    }


class CopilotClient:
    """Consumer of one owned ``copilot --headless --stdio`` channel.

    Each instance owns exactly one channel/process (G8) and one request-id
    namespace (``req-N``); two clients never share ids, streams or cleanup.
    It holds no instance/task ledger and claims no runtime readiness.
    """

    def __init__(self, channel: ProcessChannel, *, name: str = "copilot-cli"):
        self._channel = channel
        self.name = name
        self._events: list[Mapping[str, Any]] = []
        self._inbound_by_id: dict[Any, Mapping[str, Any]] = {}
        self._unanswered: list[Mapping[str, Any]] = []
        self._pending: dict[str, str] = {}  # request_id -> method (G11 ledger)
        self._responses: dict[str, Mapping[str, Any]] = {}  # out-of-order receipts
        self._request_seq = 0
        self._connected = False
        self._handshake = "none"  # "none" | "connected" | "legacy-ping"
        self._negotiated_protocol_version: int | None = None
        self._session_id: str | None = None

    @classmethod
    def launch(cls, spec: LaunchSpec, *, name: str = "copilot-cli") -> "CopilotClient":
        """Launch the owned copilot process described by ``spec`` and wrap it.

        The spec is validated *before any process is spawned*: the documented
        server-mode markers must be present and auto-approve launch flags are
        refused (the caller owns every approval decision, SAFETY).
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
        if "--headless" not in argv:
            raise ValueError(
                "refused before spawn: the copilot client requires the documented "
                "server mode (`--headless`); no other entry point is substituted"
            )
        if "--stdio" not in argv and "--port" not in argv:
            raise ValueError(
                "refused before spawn: the copilot client requires `--stdio` "
                "(documented stdio server transport) or `--port`"
            )

    # -- ledger / facts ---------------------------------------------------
    @property
    def pending(self) -> dict[str, str]:
        """Requests written but not yet receipt-resolved (G11 ledger)."""
        return dict(self._pending)

    @property
    def handshake(self) -> str:
        """``none`` (not attempted), ``connected`` or legacy ``ping`` fallback."""
        return self._handshake

    @property
    def negotiated_protocol_version(self) -> int | None:
        return self._negotiated_protocol_version

    @property
    def session_id(self) -> str | None:
        """Native session id observed from session.create/resume; never fabricated."""
        return self._session_id

    def describe(self) -> dict[str, Any]:
        return describe()

    def events(self) -> tuple[Mapping[str, Any], ...]:
        """Snapshot of preserved frames in arrival order (G4)."""
        return tuple(self._events)

    def inbound_requests(self) -> tuple[Mapping[str, Any], ...]:
        """Every CLI→client request frame seen, verbatim (G4)."""
        return tuple(self._inbound_by_id.values())

    def unanswered_requests(self) -> tuple[Mapping[str, Any], ...]:
        """Inbound requests this client has not been asked to answer.

        They stay here (never auto-approved) until the caller explicitly
        replies.
        """
        return tuple(self._unanswered)

    def stderr_tail(self) -> str:
        """Peer stderr diagnostics tail — never protocol (G5)."""
        return self._channel.stderr_tail()

    # -- handshake ---------------------------------------------------------
    def connect(
        self,
        *,
        timeout: float = 10.0,
        client_info: Mapping[str, Any] | None = None,
        supported_task_kinds: tuple[str, ...] = ("agent", "client", "shell"),
    ) -> Mapping[str, Any]:
        """Documented ``connect`` handshake with finite protocol gating.

        Never carries a token (this client has no token parameter, G12). On a
        legacy server answering ``-32601`` the documented ``ping`` fallback is
        used and the outcome is surfaced as ``legacy-ping``. An unreported or
        out-of-range protocol version raises :class:`CopilotProtocolError`
        (min == max == 3) — no downgrade, no retry.
        """
        params: dict[str, Any] = {"supportedTaskKinds": list(supported_task_kinds)}
        if client_info is not None:
            params["clientInfo"] = dict(client_info)
        handshake = "connected"
        try:
            result = self._request("connect", params, timeout=timeout)
        except CopilotRpcError as exc:
            if exc.remote_code != -32601:
                raise
            handshake = "legacy-ping"
            result = self._request(
                "ping", {"message": "ordessa-copilot-handshake"}, timeout=timeout
            )
        server_version: Any = None
        if isinstance(result, Mapping):
            server_version = result.get("protocolVersion")
        if server_version is None:
            raise CopilotProtocolError(
                "server did not report protocolVersion; SDK protocol "
                f"{MIN_PROTOCOL_VERSION}-{SDK_PROTOCOL_VERSION} gating cannot be "
                "verified (no downgrade is invented)"
            )
        if not (MIN_PROTOCOL_VERSION <= int(server_version) <= SDK_PROTOCOL_VERSION):
            raise CopilotProtocolError(
                f"server reports protocolVersion {server_version}; this client "
                f"supports {MIN_PROTOCOL_VERSION}-{SDK_PROTOCOL_VERSION} "
                "(no downgrade, no retry)"
            )
        self._handshake = handshake
        self._connected = True
        self._negotiated_protocol_version = int(server_version)
        return {
            "handshake": handshake,
            "negotiatedProtocolVersion": int(server_version),
            "supportedTaskKinds": list(supported_task_kinds),
            "clientInfo": dict(client_info) if client_info is not None else None,
            "result": result,
        }

    def initialize(
        self,
        *,
        timeout: float = 10.0,
        client_info: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Alias for :meth:`connect` (seams.md §4 names the step connect/initialize)."""
        return self.connect(timeout=timeout, client_info=client_info)

    # -- session lifecycle --------------------------------------------------
    def create_session(
        self,
        *,
        session_id: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        request_permission: bool = True,
        timeout: float = 10.0,
        **fields: Any,
    ) -> Mapping[str, Any]:
        """Documented ``session.create``; returns the native result verbatim.

        ``sessionId`` comes from the CLI response and is never fabricated; when
        the caller omits it the runtime may generate one that cannot be
        resumed (documented SDK semantics). ``request_permission`` asks the
        runtime to surface permission requests to this consumer, which never
        auto-approves.
        """
        self._require_connected("session.create")
        params: dict[str, Any] = dict(fields)
        if session_id is not None:
            params["sessionId"] = session_id
        if model is not None:
            params["model"] = model
        if reasoning_effort is not None:
            params["reasoningEffort"] = reasoning_effort
        params["requestPermission"] = bool(request_permission)
        result = self._request("session.create", params, timeout=timeout)
        if isinstance(result, Mapping) and result.get("sessionId"):
            self._session_id = str(result["sessionId"])
        return dict(result) if isinstance(result, Mapping) else {}

    def resume_session(
        self, session_id: str, *, timeout: float = 10.0, **overrides: Any
    ) -> Mapping[str, Any]:
        """Documented ``session.resume``; state lives under COPILOT_HOME."""
        self._require_connected("session.resume")
        params: dict[str, Any] = {"sessionId": session_id}
        params.update(overrides)
        result = self._request("session.resume", params, timeout=timeout)
        if isinstance(result, Mapping) and result.get("sessionId"):
            self._session_id = str(result["sessionId"])
        else:
            self._session_id = session_id
        return dict(result) if isinstance(result, Mapping) else {}

    def detach_session(self) -> None:
        """Forget the tracked native session id (client-side reference only).

        Upstream ``disconnect``/``delete`` semantics are documented SDK
        behaviour that was not measured (L2 NOT RUN); nothing is claimed here.
        """
        self._session_id = None

    # -- prompt / events ----------------------------------------------------
    def send(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        wait: bool = False,
        mode: str | None = None,
        timeout: float = 120.0,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
        on_request: Callable[[Mapping[str, Any]], None] | None = None,
        **fields: Any,
    ) -> Mapping[str, Any]:
        """Send the documented ``session.send`` request; the result is a RECEIPT.

        The documented result is ``{messageId}`` and ``wait`` defaults to
        false (fire-and-forget): **the receipt is never completion**. Turn-end
        evidence arrives as the ``session.idle`` event via :meth:`wait_idle`.
        While in flight, notifications are preserved in :meth:`events` and fed
        to ``on_event(raw)``; CLI→client requests are handed to ``on_request``
        if given, otherwise queued unanswered (no auto-approve). A deadline is
        a typed :class:`RequestTimeout` with the outcome unknown and no re-send
        (G11).
        """
        self._require_connected("session.send")
        sid = session_id or self._session_id
        if sid is None:
            raise CopilotConfigurationError(
                "session.send refused before write: no native session; run "
                "create_session() or pass session_id"
            )
        params: dict[str, Any] = {"sessionId": sid, "prompt": prompt, "wait": bool(wait)}
        if mode is not None:
            params["mode"] = mode
        params.update(fields)
        result = self._request(
            "session.send", params, timeout=timeout, on_event=on_event, on_request=on_request
        )
        return dict(result) if isinstance(result, Mapping) else {}

    def wait_idle(self, *, timeout: float = 60.0) -> Mapping[str, Any]:
        """Collect frames until the documented ``session.idle`` notification.

        The idle frame is returned verbatim — it is the completion evidence,
        never invented from a send receipt. A deadline raises
        :class:`RequestTimeout` with the run outcome unknown (never re-sent,
        G11); unknown events are preserved and never satisfy the wait.
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout("session.idle", None, timeout)
            try:
                message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            raw = message.raw
            if raw.get("method") == "session.idle":
                self._events.append(raw)
                return raw
            self._route_frame(raw)

    def next_event(self, *, timeout: float = 10.0) -> Mapping[str, Any]:
        """Next preserved frame in arrival order, verbatim (G4)."""
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
            self._route_frame(message.raw)

    def pump(self, *, timeout: float = 0.0) -> int:
        """Read frames already available into the preserved stream (G4)."""
        deadline = time.monotonic() + timeout
        count = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return count
            message = self._channel.poll_message(timeout=remaining)
            if message is None:
                return count
            self._route_frame(message.raw)
            count += 1

    # -- reverse requests (never auto-answered) -----------------------------
    def reply_permission(self, request_id: Any, decision: str) -> None:
        """Answer a permission request on the SAME JSON-RPC id.

        ``decision`` must be one of the documented ``PermissionDecisionKind``
        values and is always caller-chosen — there is no default and no
        auto-approve (SAFETY). The same-id reply carries ``{"kind": decision}``
        (the SDK documents a permission result as a mapping with a ``kind``
        key). Replying for a request this client never saw is refused rather
        than fabricating an identity.
        """
        if decision not in PERMISSION_DECISIONS:
            raise ValueError(
                f"decision must be one of {sorted(PERMISSION_DECISIONS)}"
            )
        if request_id not in self._inbound_by_id:
            raise ValueError(
                f"no inbound request seen with JSON-RPC id {request_id!r}; "
                "refusing to fabricate a permission response"
            )
        self._channel.reply(request_id, {"kind": decision})

    def reply_request(self, request_id: Any, result: Any) -> None:
        """Generic same-id reply for documented/future request frames (G4)."""
        self._channel.reply(request_id, result)

    def reply_request_error(
        self, request_id: Any, *, code: int, message: str, data: Any = None
    ) -> None:
        """JSON-RPC error reply for an inbound request frame."""
        self._channel.reply_error(request_id, code=code, message=message, data=data)

    # -- control / lifecycle ------------------------------------------------
    def cancel(
        self,
        *,
        session_id: str | None = None,
        reason: str | None = None,
        timeout: float = 10.0,
    ) -> Mapping[str, Any]:
        """Documented ``session.abort`` — real evidence, never 'completed'.

        The result is the native ``{success, error}`` abort outcome verbatim.
        """
        self._require_connected("session.abort")
        sid = session_id or self._session_id
        if sid is None:
            raise CopilotConfigurationError(
                "session.abort refused before write: no native session; run "
                "create_session() or pass session_id"
            )
        params: dict[str, Any] = {"sessionId": sid}
        if reason is not None:
            params["reason"] = reason
        result = self._request("session.abort", params, timeout=timeout)
        return dict(result) if isinstance(result, Mapping) else {}

    def command(
        self,
        method: str,
        *,
        timeout: float = 10.0,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
        on_request: Callable[[Mapping[str, Any]], None] | None = None,
        **params: Any,
    ) -> Any:
        """Generic documented/future method round trip; result verbatim (G4)."""
        return self._request(
            method, dict(params), timeout=timeout, on_event=on_event, on_request=on_request
        )

    def close(self) -> int:
        """Release this client's own channel/process only (G6/G8). Pending
        requests stay unknown and are never re-sent (G11)."""
        return self._channel.close()

    # -- internals -----------------------------------------------------------
    def _require_connected(self, method: str) -> None:
        if not self._connected:
            raise CopilotNotConnected(method)

    def _route_request(self, raw: Mapping[str, Any], *, deliver: bool) -> None:
        """Preserve an inbound request verbatim; answer nothing by itself."""
        rid = raw.get("id")
        self._inbound_by_id[rid] = raw
        if deliver:
            return  # the waiter's on_request callback receives it directly
        self._unanswered.append(raw)

    def _route_frame(self, raw: Mapping[str, Any]) -> None:
        """Pump-side router: preserve frames without answering anything."""
        method = raw.get("method")
        if method is not None and "id" in raw:
            self._events.append(raw)
            self._route_request(raw, deliver=False)
            return
        if method is not None:
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
        are stashed by id, so nested requests issued from an event callback
        while another request is pending never steal each other's receipts
        (G6).
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
                error = raw.get("error")
                if error is not None:
                    raise CopilotRpcError(method, request_id, error)
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
            if incoming_method is not None and "id" in incoming:
                # CLI→client request (e.g. permission): preserve and offer to
                # the caller; answer nothing by ourselves (SAFETY).
                self._events.append(incoming)
                if on_request is not None:
                    self._route_request(incoming, deliver=True)
                    on_request(incoming)
                else:
                    self._route_request(incoming, deliver=False)
                continue
            if incoming_method is not None:
                # Notification (known or unknown): preserved verbatim (G4).
                self._events.append(incoming)
                if on_event is not None:
                    on_event(incoming)
                continue
            rid = incoming.get("id")
            if rid == request_id:
                del self._pending[request_id]
                error = incoming.get("error")
                if error is not None:
                    raise CopilotRpcError(method, request_id, error)
                return incoming.get("result")
            if rid in self._pending:
                # Receipt for another in-flight (possibly nested) request.
                self._responses[rid] = incoming
                self._events.append(incoming)  # kept verbatim even if its waiter timed out (G4)
                continue
            # Stale/foreign response: preserved verbatim, never a receipt.
            self._events.append(incoming)
