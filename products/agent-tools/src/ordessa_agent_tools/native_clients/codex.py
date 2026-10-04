"""Codex app-server consumer client (family ``codex``, protocol ``codex-app-server/1``).

Pinned facts (N002, official app-server docs read 2026-10-04, npm
``@openai/codex`` 0.157.1, Apache-2.0):

- Launch: ``codex app-server`` over stdio (default) — JSON-RPC 2.0 style
  JSONL, one object per LF frame. Codex omits the ``jsonrpc`` header on the
  wire; this client matches that wire shape and accepts it either way.
- Handshake per connection: ``initialize`` request with
  ``params.clientInfo``/``params.capabilities``, then the ``initialized``
  notification. There is NO version negotiation — only capability gating
  (``experimentalApi`` etc.); upgrades therefore re-pin the release (G1).
- Session identity: ``thread/start`` → ``result.thread.id`` + ``sessionId``;
  task identity: ``turn/start`` → ``result.turn.id`` with ``status
  "inProgress"``. **A turn receipt is not completion** — the terminal state
  arrives as the ``turn/completed`` notification (completed | interrupted |
  failed). ``turn/steer``/``turn/interrupt`` target an existing turn
  (``expectedTurnId`` guards against cross-turn races).
- Reverse (server→client) requests correlate by JSON-RPC ``id``:
  ``item/permissions/requestApproval`` (answers ``accept`` |
  ``acceptForSession`` | ``decline`` | ``cancel`` |
  ``acceptWithExecpolicyAmendment``), ``mcpServer/elicitation/request``,
  ``tool/requestUserInput``, ``attestation/generate``. This client NEVER
  answers on its own initiative (no auto-approve); the caller decides.
- Unknown methods/events surface verbatim and are never dropped (G4). The
  overload error (-32001 "Server overloaded; retry later") is surfaced as a
  typed failure — never auto-retried from here (G11).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from ._transport import (
    ChannelClosed,
    ChannelFailure,
    FramingError,
    LostReceipt,
    Message,
    ProcessChannel,
    RemoteFailure,
    RequestTimeout,
)

FAMILY_ID = "codex"
PROTOCOL = "codex-app-server/1"

#: Terminal turn states named by the ``turn/completed`` notification (G6).
TURN_TERMINAL_STATUSES = frozenset({"completed", "interrupted", "failed"})

#: Decisions for ``item/permissions/requestApproval`` — enumerated for
#: callers; this client never picks one by itself (SAFETY).
APPROVAL_DECISIONS = frozenset(
    {"accept", "acceptForSession", "decline", "cancel"}
)


class CodexRpcError(RemoteFailure):
    """Codex answered with a JSON-RPC error object (``codexErrorInfo`` kept)."""

    def __init__(self, method: str, request_id: Any, raw_error: Mapping[str, Any]):
        super().__init__(
            f"{method}#{request_id}: {raw_error.get('message', raw_error)}",
            code=raw_error.get("code"),
            data=raw_error.get("codexErrorInfo"),
        )
        self.method = method
        self.request_id = request_id
        self.raw_error = dict(raw_error)


class TurnFailed(ChannelFailure):
    """A turn ended in terminal state ``failed``/``interrupted`` where a
    completion was awaited. The raw notification is preserved (G6). This is a
    run outcome, not a transport condition — never treat it as "not sent"."""

    def __init__(self, status: str, raw: Mapping[str, Any]):
        ChannelFailure.__init__(self, "TURN_FAILED", f"turn ended with status {status!r}")
        self.status = status
        self.raw = dict(raw)


def describe() -> dict[str, Any]:
    return {
        "familyId": FAMILY_ID,
        "channel": "stdio-jsonrpc",
        "protocol": PROTOCOL,
        "wire": "JSONL frames; jsonrpc header omitted on the wire (per upstream docs)",
        "handshake": "initialize -> initialized notification; no version negotiation",
        "knownMethods": [
            "initialize",
            "thread/start",
            "thread/resume",
            "thread/fork",
            "thread/read",
            "thread/list",
            "thread/unsubscribe",
            "turn/start",
            "turn/steer",
            "turn/interrupt",
        ],
    }


class CodexAppServerClient:
    """Consumer of one owned ``codex app-server`` stdio channel.

    It is a client: it holds no instance/task ledger and claims no runtime
    readiness. Everything unknown stays verbatim in :meth:`events`.
    """

    def __init__(self, channel: ProcessChannel, *, name: str = "codex-app-server"):
        self._channel = channel
        self._events: list[Mapping[str, Any]] = []
        self._pending: dict[Any, str] = {}
        self._request_seq = 0
        self._initialized = False

    @classmethod
    def launch(cls, spec: Any, *, name: str = "codex-app-server") -> "CodexAppServerClient":
        return cls(ProcessChannel.launch(spec, name=name), name=name)

    # -- handshake --------------------------------------------------------
    def initialize(self, *, timeout: float = 10.0) -> Mapping[str, Any]:
        """Handshake: ``initialize`` then the ``initialized`` notification.

        Returns the server info result verbatim (platform family/OS, user
        agent). There is no version negotiation to invent (G1).
        """
        result = self._request(
            "initialize",
            {
                "clientInfo": {"name": "ordessa-agent-tools", "title": "Ordessa Agent Tools", "version": "0.1.0a2"},
                "capabilities": {"experimentalApi": False},
            },
            timeout=timeout,
        )
        self._channel.notify("initialized", {})
        self._initialized = True
        return result

    # -- session/task identity --------------------------------------------
    def create_thread(
        self,
        *,
        cwd: str,
        model: str | None = None,
        approval_policy: str | None = None,
        sandbox: str | None = None,
        timeout: float = 10.0,
        **extra: Any,
    ) -> Mapping[str, Any]:
        """``thread/start`` — real session creation. Returns the raw result
        (``thread.id``, ``sessionId``, …) verbatim; no model call is made."""
        params: dict[str, Any] = {"cwd": cwd}
        if model is not None:
            params["model"] = model
        if approval_policy is not None:
            params["approvalPolicy"] = approval_policy
        if sandbox is not None:
            params["sandbox"] = sandbox
        params.update(extra)
        return self._request("thread/start", params, timeout=timeout)

    def resume_thread(self, thread_id: str, *, timeout: float = 10.0, **overrides: Any) -> Mapping[str, Any]:
        """``thread/resume``. Upstream documents the method; resume semantics
        beyond the call are registered as unverified (unknown)."""
        params: dict[str, Any] = {"threadId": thread_id}
        params.update(overrides)
        return self._request("thread/resume", params, timeout=timeout)

    def start_turn(
        self,
        *,
        thread_id: str,
        text: str,
        timeout: float = 10.0,
        **overrides: Any,
    ) -> Mapping[str, Any]:
        """``turn/start`` — sends work to the agent.

        The result is a receipt (``turn.id`` with ``status "inProgress"``),
        NOT completion; observe :meth:`wait_turn_completed` for the terminal
        ``turn/completed`` notification. Calling this may invoke a model —
        callers must hold explicit authorisation (L4 boundary, G12).
        """
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text}],
        }
        params.update(overrides)
        return self._request("turn/start", params, timeout=timeout)

    def wait_turn_completed(self, *, timeout: float = 30.0) -> Mapping[str, Any]:
        """Collect events until a ``turn/completed`` notification arrives.

        Returns it verbatim; timeout raises :class:`RequestTimeout` with the
        run outcome unknown (never auto-retried, G11). A terminal ``failed``
        raises :class:`TurnFailed` carrying the raw notification (G6).
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout("turn/completed", None, timeout)
            try:
                message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError) as exc:
                raise LostReceipt("turn/completed", None, f"transport failure: {exc}") from exc
            raw = message.raw
            if raw.get("method") == "turn/completed":
                status = str(raw.get("params", {}).get("status", ""))
                if status in {"failed", "interrupted"}:
                    raise TurnFailed(status, raw)
                return raw
            self._events.append(raw)

    # -- events ------------------------------------------------------------
    def next_event(self, *, timeout: float = 10.0) -> Mapping[str, Any]:
        raw = self._channel.next_message(timeout=timeout).raw
        self._events.append(raw)
        return raw

    def events(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._events)

    def pump(self, *, timeout: float = 0.0) -> int:
        deadline = time.monotonic() + timeout
        count = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return count
            message = self._channel.poll_message(timeout=remaining)
            if message is None:
                return count
            self._events.append(message.raw)
            count += 1

    # -- reverse requests (never auto-answered) ----------------------------
    def reply_approval(
        self,
        request_id: Any,
        decision: str,
        *,
        amendment: Mapping[str, Any] | None = None,
    ) -> None:
        """Answer ``item/permissions/requestApproval`` with the SAME id.

        ``decision`` must be one of the documented values; the caller owns
        the decision — no default, no auto-approve (SAFETY). An ``amendment``
        payload is only valid together with the explicit
        ``acceptWithExecpolicyAmendment`` decision — a declined decision can
        never silently become an approval.
        """
        if amendment is not None:
            if decision != "acceptWithExecpolicyAmendment":
                raise ValueError(
                    "an amendment payload requires decision='acceptWithExecpolicyAmendment'; "
                    "a declined decision is never upgraded to an approval"
                )
            self._channel.reply(request_id, {"acceptWithExecpolicyAmendment": dict(amendment)})
            return
        if decision not in APPROVAL_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(APPROVAL_DECISIONS)}")
        self._channel.reply(request_id, decision)

    def reply_request(self, request_id: Any, result: Any) -> None:
        self._channel.reply(request_id, result)

    def reply_request_error(self, request_id: Any, *, code: int, message: str, data: Any = None) -> None:
        self._channel.reply_error(request_id, code=code, message=message, data=data)

    # -- control -----------------------------------------------------------
    def cancel(self, *, thread_id: str, turn_id: str, timeout: float = 10.0) -> Mapping[str, Any]:
        """``turn/interrupt`` — cancellation is real evidence, never
        "completed" (G6)."""
        return self._request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=timeout)

    def command(self, method: str, *, timeout: float = 10.0, **params: Any) -> Any:
        """Generic method round trip (future/unknown methods included); the
        result is returned verbatim and unknown semantics are never invented."""
        return self._request(method, dict(params), timeout=timeout)

    def close(self) -> int:
        """Release this client's own channel/process only (G6/G8)."""
        return self._channel.close()

    # -- internals -----------------------------------------------------------
    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float,
        on_request: Callable[[Message], None] | None = None,
    ) -> Any:
        """One request round trip: correlated by id, never re-sent (G11).

        A transport breach after send raises :class:`LostReceipt` (outcome
        unknown); a deadline raises :class:`RequestTimeout`; a JSON-RPC error
        object raises :class:`CodexRpcError` with its ``codexErrorInfo`` kept.
        """
        self._request_seq += 1
        request_id = f"req-{self._request_seq}"
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params:
            payload["params"] = dict(params)
        self._channel.send_raw(payload)
        self._pending[request_id] = method
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout(method, request_id, timeout)
            try:
                message: Message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError) as exc:
                raise LostReceipt(method, request_id, f"transport failure after send: {exc}") from exc
            raw = message.raw
            if raw.get("id") == request_id and "method" not in raw:
                del self._pending[request_id]
                error = raw.get("error")
                if error is not None:
                    raise CodexRpcError(method, request_id, error)
                return raw.get("result")
            if message.kind == "request" and on_request is not None:
                on_request(message)
                continue
            self._events.append(raw)  # unknown/notification preserved verbatim (G4)
