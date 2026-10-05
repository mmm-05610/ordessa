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
- Session identity: ``thread/start`` → ``result.thread.id``;
  task identity: ``turn/start`` → ``result.turn.id`` with ``status
  "inProgress"``. **A turn receipt is not completion** — the terminal state
  arrives as the ``turn/completed`` notification (completed | interrupted |
  failed). ``turn/steer``/``turn/interrupt`` target an existing turn
  (``expectedTurnId`` on steer guards against cross-turn races).
- Reverse (server→client) requests correlate by JSON-RPC ``id``:
  ``item/commandExecution/requestApproval`` (answers ``accept`` |
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
import threading
import json
from typing import Any, Callable, Mapping

from ordessa_harness_transport import (
    ChannelClosed,
    ChannelFailure,
    FramingError,
    LostReceipt,
    Message,
    ProcessChannel,
    RemoteFailure,
    RequestTimeout,
    PreparedFrame,
    PreparedFramePool,
    PreparedFrameRefused,
)

FAMILY_ID = "codex"
PROTOCOL = "codex-app-server/1"

#: Terminal turn states named by the ``turn/completed`` notification (G6).
TURN_TERMINAL_STATUSES = frozenset({"completed", "interrupted", "failed"})

#: Decisions for command/file approval requests — enumerated for
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
            data=raw_error.get("data", raw_error.get("codexErrorInfo")),
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
        self._rpc_lock = threading.RLock()
        self._events: list[Mapping[str, Any]] = []
        self._pending: dict[Any, str] = {}
        self._prepared_waiting = set()
        self._turn_requests: dict[Any, str] = {}
        self._request_seq = 0
        self._initialized = False
        self._last_turn: tuple[str, str] | None = None
        self._reverse_requests: dict[Any, Message] = {}
        self._prepared = PreparedFramePool(PROTOCOL)
        self._prepared_requests = {}  # local unspent handles, never recovery truth
        self._prepared_unknown = False

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
                "clientInfo": {"name": "ordessa-harness-codex", "title": "Ordessa Codex Provider", "version": "0.1.0a1"},
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
        (``thread.id``, …) verbatim; no model call is made."""
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
        if "threadId" in overrides:
            raise ValueError("threadId cannot override thread_id")
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
        if "turn/start" in self._pending.values():
            raise LostReceipt("turn/start", None, "earlier turn/start receipt is unknown; recover without resending input")
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text}],
        }
        if "threadId" in overrides or "input" in overrides:
            raise ValueError("threadId/input cannot override the selected target/input")
        params.update(overrides)
        result = self._request("turn/start", params, timeout=timeout)
        turn = result.get("turn") if isinstance(result, Mapping) else None
        if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str) or not turn["id"]:
            raise LostReceipt("turn/start", None, "malformed turn receipt; outcome unknown")
        self._last_turn = (thread_id, turn["id"])
        return result

    def wait_turn_completed(self, *, timeout: float = 30.0,
                            thread_id: str | None = None, turn_id: str | None = None) -> Mapping[str, Any]:
        """Wait for the selected native turn, including already buffered events.

        A timeout/disconnect remains unknown. The last validated start receipt
        supplies the default identity; callers can explicitly select a known
        turn after a read-only native recovery query. Nothing is re-sent.
        """
        if (thread_id is None) != (turn_id is None):
            raise ValueError("thread_id and turn_id must be supplied together")
        target = (thread_id, turn_id) if thread_id is not None else self._last_turn
        if target is None:
            raise ValueError("a native thread/turn identity is required")
        deadline = time.monotonic() + timeout
        scanned = 0
        while True:
            while scanned < len(self._events):
                raw = self._events[scanned]
                scanned += 1
                if raw.get("method") != "turn/completed":
                    continue
                params = raw.get("params")
                if not isinstance(params, Mapping):
                    raise LostReceipt("turn/completed", None, "malformed completion; outcome unknown")
                turn = params.get("turn")
                if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str) or not turn["id"] or not isinstance(params.get("threadId"), str) or not params["threadId"]:
                    raise LostReceipt("turn/completed", None, "missing native turn identity; outcome unknown")
                if (params.get("threadId"), turn["id"]) != target:
                    continue
                status = turn.get("status")
                if status not in TURN_TERMINAL_STATUSES:
                    raise LostReceipt("turn/completed", None, "nonterminal or unknown completion status")
                if status in {"failed", "interrupted"}:
                    raise TurnFailed(status, raw)
                return raw
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout("turn/completed", None, timeout)
            try:
                message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError) as exc:
                raise LostReceipt("turn/completed", None, f"transport failure: {exc}") from exc
            self._observe(message)

    # -- events ------------------------------------------------------------
    def next_event(self, *, timeout: float = 10.0) -> Mapping[str, Any]:
        raw = self._channel.next_message(timeout=timeout).raw
        self._observe(Message(raw))
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
            self._observe(message)
            count += 1

    # -- reverse requests (never auto-answered) ----------------------------
    def reply_approval(
        self,
        request_id: Any,
        decision: str,
        *,
        amendment: Mapping[str, Any] | None = None,
    ) -> None:
        """Answer a pending command/file approval with the SAME native id.

        ``decision`` must be one of the documented values; the caller owns
        the decision — no default, no auto-approve (SAFETY). An ``amendment``
        payload is only valid together with the explicit
        ``acceptWithExecpolicyAmendment`` decision — a declined decision can
        never silently become an approval.
        """
        if amendment is not None and decision != "acceptWithExecpolicyAmendment":
            raise ValueError("amendment requires an explicit execpolicy approval")
        if decision not in APPROVAL_DECISIONS and decision != "acceptWithExecpolicyAmendment":
            raise ValueError("invalid approval decision")
        request = self._reverse_requests.get(request_id)
        method = request.method if request is not None else None
        if method not in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            raise ValueError("decision replies require a pending command/file approval request")
        if decision == "acceptWithExecpolicyAmendment":
            if method != "item/commandExecution/requestApproval" or not isinstance(amendment, Mapping):
                raise ValueError("execpolicy amendment requires a command approval")
            rules = amendment.get("execpolicy_amendment")
            if set(amendment) != {"execpolicy_amendment"} or not isinstance(rules, list) or not all(isinstance(x, str) for x in rules):
                raise ValueError("invalid native execpolicy amendment")
            value: Any = {"acceptWithExecpolicyAmendment": dict(amendment)}
        else:
            value = decision
        self.reply_request(request_id, {"decision": value})

    def reply_request(self, request_id: Any, result: Any) -> None:
        if request_id not in self._reverse_requests:
            raise ValueError("no pending native reverse request with this id")
        request = self._reverse_requests[request_id]
        if request.method == "item/permissions/requestApproval":
            if not isinstance(result, Mapping) or not isinstance(result.get("permissions"), Mapping) or result.get("scope", "turn") not in {"turn", "session"} or "decision" in result:
                raise ValueError("permissions approval requires a native permissions object and scope")
        # Consume before writing: partial-write failure must not permit replay.
        del self._reverse_requests[request_id]
        self._channel.reply(request_id, result)

    def reply_request_error(self, request_id: Any, *, code: int, message: str, data: Any = None) -> None:
        if request_id not in self._reverse_requests:
            raise ValueError("no pending native reverse request with this id")
        del self._reverse_requests[request_id]
        self._channel.reply_error(request_id, code=code, message=message, data=data)

    def _observe(self, message: Message) -> None:
        raw = message.raw
        if message.kind == "request":
            if isinstance(message.id, bool) or not isinstance(message.id, (int, str)):
                raise FramingError("invalid native reverse request id")
            if message.id in self._reverse_requests:
                raise FramingError("duplicate unresolved native reverse request id")
            self._reverse_requests[message.id] = message
        if message.method == "serverRequest/resolved":
            params = raw.get("params", {})
            if isinstance(params, Mapping):
                if isinstance(params.get("requestId"), bool) or not isinstance(params.get("requestId"), (int, str)):
                    raise FramingError("invalid resolved native request id")
                request = self._reverse_requests.get(params.get("requestId"))
                request_params = request.raw.get("params", {}) if request else {}
                if isinstance(request_params, Mapping) and request_params.get("threadId") == params.get("threadId"):
                    self._reverse_requests.pop(params.get("requestId"), None)
        self._events.append(raw)

    # -- control -----------------------------------------------------------
    def cancel(self, *, thread_id: str, turn_id: str, timeout: float = 10.0) -> Mapping[str, Any]:
        """``turn/interrupt`` — cancellation is real evidence, never
        "completed" (G6)."""
        return self._request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=timeout)

    def command(self, method: str, *, timeout: float = 10.0, **params: Any) -> Any:
        """Generic method round trip (future/unknown methods included); the
        result is returned verbatim and unknown semantics are never invented."""
        return self._request(method, dict(params), timeout=timeout)

    def command_once(self, method: str, params: Mapping[str, Any], *,
                     before_send: Callable[[Mapping[str, Any]], None],
                     timeout: float = 10.0) -> Any:
        """Fix the actual RPC identity, persist it, then dispatch exactly once.

        The hook sees a detached copy of the exact native request. Its failure
        performs no write. A receipt timeout leaves this original ID pending;
        recover_request observes that ID without another dispatch.
        """
        if not callable(before_send):
            raise ValueError("explicit pre-send persistence hook required")
        return self._request(method, params, timeout=timeout, before_send=before_send)

    @staticmethod
    def _prepared_method(method, params):
        if (not isinstance(method, str) or not method or any(ord(c) < 32 for c in method)
                or not isinstance(params, Mapping)):
            raise ValueError("native method and parameter object required")
        if method == "turn/start":
            thread = params.get("threadId")
            if not isinstance(thread, str) or not thread:
                raise ValueError("turn/start requires the original native threadId")
            return thread
        return None

    def prepare_request(self, method: str, params: Mapping[str, Any]) -> PreparedFrame:
        """Allocate/freeze the actual native request before capture/admission.

        No pending request, transport write or effect permission is created.
        The returned bytes include LF and are the exact later dispatch bytes.
        """
        with self._rpc_lock:
            self._prepared_method(method, params)
            self._request_seq += 1
            native_id = f"req-{self._request_seq}"
            payload = {"id": native_id, "method": method}
            if params:
                payload["params"] = dict(params)
            frame = self._prepared.prepare(payload, native_id)
            self._prepared_requests[id(frame)] = frame
            return frame

    def dispatch_prepared(self, frame: PreparedFrame, *, before_write: Callable[[bytes], None],
                          timeout: float = 10.0,
                          on_request: Callable[[Message], None] | None = None) -> Any:
        """Spend this client's original frame once, guarded at actual stdin.

        Guard failure spends the frame too. Missing confirmation fences the
        original transport; later receipt observation cannot grant a resend.
        This primitive supplies neither admission nor durable input evidence.
        """
        with self._rpc_lock:
            if type(frame) is not PreparedFrame or self._prepared_requests.get(id(frame)) is not frame:
                raise PreparedFrameRefused("prepared request belongs to another client or is spent")
            if not callable(before_write) or (on_request is not None and not callable(on_request)):
                raise ValueError("explicit write guard and callable native request callback required")
            if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout < float("inf"):
                raise ValueError("finite positive receipt timeout required")
            try:
                payload = frame.payload
            except (ValueError, TypeError, UnicodeError):
                raise PreparedFrameRefused("prepared native payload is damaged") from None
            if not isinstance(payload, Mapping):
                raise PreparedFrameRefused("prepared native payload is damaged")
            method = payload.get("method")
            thread = self._prepared_method(method, payload.get("params", {}))
            if self._prepared_unknown:
                raise LostReceipt(method, frame.request_id, "original prepared input unresolved; query without another write")
            self._check_pending_method(method)
            if any(not callable(getattr(self._channel, name, None)) for name in
                   ("send_frame", "mark_input_unknown", "acknowledge_frame")):
                raise PreparedFrameRefused("actual write barrier and unknown transport fence unavailable")
            native_id, wire = self._prepared.consume(frame)
            del self._prepared_requests[id(frame)]
            self._pending[native_id] = method
            self._prepared_waiting.add(native_id)
            if method == "turn/start":
                self._turn_requests[native_id] = thread
            try:
                self._channel.send_frame(wire, before_write=lambda: before_write(wire))
                return self.recover_request(native_id, timeout=timeout, on_request=on_request)
            except CodexRpcError as error:
                if native_id not in self._pending and error.request_id == native_id and error.method == method:
                    raise  # Only the original accepted response is a known receipt.
                self._cut_prepared_unknown()
                raise
            except BaseException:
                self._cut_prepared_unknown()
                raise

    def _cut_prepared_unknown(self):
        self._prepared_unknown = True
        try:
            self._channel.mark_input_unknown()
        except BaseException:
            pass  # Preserve original error; actual transport already retains its cut.

    def _ack_prepared_request(self, request_id):
        if request_id in self._prepared_waiting:
            self._channel.acknowledge_frame(request_id)
            self._prepared_waiting.remove(request_id)

    def close(self) -> int:
        """Release this client's own channel/process only (G6/G8)."""
        with self._rpc_lock:
            self._prepared.close()
            self._prepared_requests.clear()
        return self._channel.close()

    # -- internals -----------------------------------------------------------
    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float,
        on_request: Callable[[Message], None] | None = None,
        before_send: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> Any:
        with self._rpc_lock:
            return self._request_locked(method, params, timeout=timeout, on_request=on_request, before_send=before_send)

    def _request_locked(self, method, params, *, timeout, on_request=None, before_send=None):
        """One request round trip: correlated by id, never re-sent (G11).

        A transport breach after send raises :class:`LostReceipt` (outcome
        unknown); a deadline raises :class:`RequestTimeout`; a JSON-RPC error
        object raises :class:`CodexRpcError` with its ``codexErrorInfo`` kept.
        """
        self._check_pending_method(method)
        self._request_seq += 1
        request_id = f"req-{self._request_seq}"
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params:
            payload["params"] = dict(params)
        if before_send is not None:
            before_send(json.loads(json.dumps(payload)))
        self._pending[request_id] = method
        if method == "turn/start":
            self._turn_requests[request_id] = params["threadId"]
        self._channel.send_raw(payload)
        return self.recover_request(request_id, timeout=timeout, on_request=on_request)

    def _check_pending_method(self, method):
        if method == "turn/start" and "turn/start" in self._pending.values():
            raise LostReceipt(method, None, "earlier turn/start receipt is unknown; recover without resending input")
        if method in {"config/batchWrite", "config/value/write"} and any(
                pending in {"config/batchWrite", "config/value/write"} for pending in self._pending.values()):
            raise LostReceipt(method, None, "original configuration receipt unknown; query without another write")

    def recover_request(self, request_id: Any, *, timeout: float = 10.0,
                        on_request: Callable[[Message], None] | None = None) -> Any:
        """Wait for an unresolved RPC receipt on this connection without sending.

        This is not persisted recovery across processes. After channel loss,
        query native thread state with independently known identities. A lost
        receipt cannot prove that input was not dispatched.
        """
        if request_id not in self._pending:
            raise ValueError("no unresolved request with this id")
        method = self._pending[request_id]
        for raw in self._events:
            if raw.get("id") == request_id and "method" not in raw:
                return self._accept_response(method, request_id, raw)
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
                return self._accept_response(method, request_id, raw)
            self._observe(message)
            if message.kind == "request" and on_request is not None:
                on_request(message)

    def _accept_response(self, method: str, request_id: Any, raw: Mapping[str, Any]) -> Any:
        if ("result" in raw) == ("error" in raw):
            raise LostReceipt(method, request_id, "malformed response; outcome unknown")
        error = raw.get("error")
        if "error" in raw and error is None:
            raise LostReceipt(method, request_id, "null error response; outcome unknown")
        if error is not None:
            if not isinstance(error, Mapping):
                raise LostReceipt(method, request_id, "malformed error; outcome unknown")
            self._ack_prepared_request(request_id)
            del self._pending[request_id]
            self._turn_requests.pop(request_id, None)
            raise CodexRpcError(method, request_id, error)
        result = raw["result"]
        if method == "turn/start":
            turn = result.get("turn") if isinstance(result, Mapping) else None
            if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str) or not turn["id"] or turn.get("status") not in TURN_TERMINAL_STATUSES | {"inProgress"} or not isinstance(turn.get("items"), list):
                raise LostReceipt(method, request_id, "malformed turn receipt; outcome unknown")
            self._last_turn = (self._turn_requests[request_id], turn["id"])
        self._ack_prepared_request(request_id)
        del self._pending[request_id]
        self._turn_requests.pop(request_id, None)
        return result
