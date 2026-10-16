"""DeepSeek dsh ACP consumer client (family ``dsh``, protocol ``dsh-acp/1``).

Pinned facts (dsh-package-freeze-v1; DeepSeek real-interface check 2026-10-07):
official ``dsh`` is a developer preview exposing an ACP stdio face. The npm
pin ``@deepseek-ai/dsh`` ``0.1.5-rc.1`` is the locked repository value
(``tooling/npm/package-lock.json``: resolved
``https://registry.npmmirror.com/@deepseek-ai/dsh/-/dsh-0.1.5-rc.1.tgz``,
integrity ``sha512-rmNmzQCg3oIc1z8xH7izRSOuy1TNzq+/NILyfM+7e8DKOyV+yBtg47WEsqR2SiIe1ATec3L/rUa1YhIcfQ2XEg==``).
The npm latest ``0.2.0-rc.2`` is deliberately NOT chased: its ACP face has
zero in-repo evidence (freeze §1). Launch: ``dsh --profile acp`` over stdio.

Wire facts (repo-grounded: ``plugins/harness/pi/vendor/acp-adapter/internal/acp/types.go`` and
``plugins/harness/pi/vendor/acp-adapter/docs/SPEC.md`` / ``DECISIONS.md``):

- One JSON object per LF line. Every frame THIS client emits carries
  ``jsonrpc: "2.0"`` (ACP JSON-RPC 2.0). Inbound frames are preserved
  verbatim and accepted either way (unknown preservation, G4).
- Handshake: ``initialize`` request (``params.clientInfo``/``params.capabilities``)
  then the ``initialized`` notification. There is NO version negotiation;
  upgrades therefore re-pin the release.
- Session identity: ``session/new`` -> ``result.sessionId`` (string).
  ``session/prompt`` -> ``result.stopReason``; the repository pins the
  terminal vocabulary ``end_turn`` / ``error`` / ``cancelled`` (bridge
  DECISIONS.md). **A prompt receipt is not completion**: a response without a
  valid terminal stopReason is UNKNOWN, never a success.
- **dsh rejects ``session/load``** (freeze §1). Recovery is permanently
  absent: this client has no load method, no load constant and no load
  fallback; ``session/resume`` exists as a frame but belongs to the bridge
  continuation contract (``agent-box.dsh-continuation@1``) and never enters
  provider supported methods.
- Reverse requests: ``session/request_permission`` (agent -> client). This
  client NEVER answers on its own initiative; the caller owns the decision
  (SAFETY).
- Unknown methods/events surface verbatim and are never dropped (G4). There
  is NO automatic retry anywhere (G11): a lost receipt keeps its original id
  and the outcome stays unknown.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Mapping

from ordessa_execution_agents.harness.transport import (
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
    native_frame_bytes,
)

FAMILY_ID = "dsh"
PROTOCOL = "dsh-acp/1"
JSONRPC_VERSION = "2.0"

#: Terminal prompt stop reasons pinned by this repository (bridge DECISIONS).
PROMPT_TERMINAL_STATUSES = frozenset({"end_turn", "error", "cancelled"})

#: Terminal stop reasons that report a run failure, never "not sent" (G6).
PROMPT_FAILED_STOP_REASONS = frozenset({"error", "cancelled"})

#: ACP permission outcomes the caller may choose; this client never picks one.
PERMISSION_OUTCOMES = frozenset({"selected", "cancelled"})

#: Frames that carry a native ``sessionId`` target and cannot be retargeted.
SESSION_TARGETED_METHODS = frozenset({
    "session/prompt", "session/cancel", "session/resume",
    "session/close", "session/set_config_option",
})


class DshRpcError(RemoteFailure):
    """dsh answered with a JSON-RPC error object (kept verbatim)."""

    def __init__(self, method: str, request_id: Any, raw_error: Mapping[str, Any]):
        super().__init__(
            f"{method}#{request_id}: {raw_error.get('message', raw_error)}",
            code=raw_error.get("code"),
            data=raw_error.get("data"),
        )
        self.method = method
        self.request_id = request_id
        self.raw_error = dict(raw_error)


class PromptTurnFailed(ChannelFailure):
    """A prompt turn ended with terminal ``error``/``cancelled``. The raw
    native response is preserved (G6). This is a run outcome, not a transport
    condition — never treat it as "not sent"."""

    def __init__(self, stop_reason: str, raw: Mapping[str, Any]):
        ChannelFailure.__init__(
            self, "PROMPT_TURN_FAILED", f"prompt turn ended with stopReason {stop_reason!r}")
        self.stop_reason = stop_reason
        self.raw = dict(raw)


def identity_text(value: Any) -> bool:
    if (not isinstance(value, str) or not value or value.strip() != value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def describe() -> dict[str, Any]:
    return {
        "familyId": FAMILY_ID,
        "channel": "stdio-jsonrpc",
        "protocol": PROTOCOL,
        "wire": 'JSONL frames; every client frame carries jsonrpc:"2.0" (ACP JSON-RPC 2.0)',
        "handshake": "initialize -> initialized notification; no version negotiation",
        "knownMethods": [
            "initialize",
            "session/new",
            "session/prompt",
            "session/cancel",
            "session/close",
            "session/set_config_option",
            "session/resume",
        ],
        # Deliberately absent, never a fallback: dsh rejects session/load;
        # this client has no load frame, no load constant and no load path.
        "absentMethods": ["session/load"],
    }


class DshAcpClient:
    """Consumer of one owned ``dsh --profile acp`` stdio channel.

    It is a client: it holds no session ledger and claims no runtime
    readiness. Everything unknown stays verbatim in :meth:`events`.
    """

    def __init__(self, channel: ProcessChannel, *, name: str = "dsh-acp"):
        self._channel = channel
        self._rpc_lock = threading.RLock()
        self._events: list[Mapping[str, Any]] = []
        self._pending: dict[Any, str] = {}
        self._prepared_waiting = set()
        self._prompt_requests: dict[Any, str] = {}
        self._request_seq = 0
        self._initialized = False
        self._reverse_requests: dict[Any, Message] = {}
        self._prepared = PreparedFramePool(PROTOCOL)
        self._prepared_requests = {}  # local unspent handles, never recovery truth
        self._prepared_unknown = False

    @classmethod
    def launch(cls, spec: Any, *, name: str = "dsh-acp") -> "DshAcpClient":
        return cls(ProcessChannel.launch(spec, name=name), name=name)

    # -- handshake --------------------------------------------------------
    def initialize(self, *, timeout: float = 10.0) -> Mapping[str, Any]:
        """Handshake: ``initialize`` then the ``initialized`` notification.

        Returns the server info result verbatim (protocol version, agent
        capabilities, agent info). There is no version negotiation to invent.
        """
        result = self._request(
            "initialize",
            {
                "clientInfo": {"name": "ordessa-harness-dsh",
                                "title": "Ordessa dsh Provider", "version": "0.1.0a1"},
                "capabilities": {},
            },
            timeout=timeout,
        )
        self._channel.notify("initialized", {})
        self._initialized = True
        return result

    # -- session identity ---------------------------------------------------
    def new_session(self, *, cwd: str, timeout: float = 10.0, **extra: Any) -> Mapping[str, Any]:
        """``session/new`` — real session creation. Returns the raw result
        (``sessionId``, ``configOptions``) verbatim; no model call is made."""
        if not isinstance(cwd, str) or not cwd:
            raise ValueError("session creation requires an explicit cwd")
        if "cwd" in extra:
            raise ValueError("cwd cannot override the selected working directory")
        params: dict[str, Any] = {"cwd": cwd}
        params.update(extra)
        return self._request("session/new", params, timeout=timeout)

    def resume_session(self, session_id: str, *, timeout: float = 10.0, **overrides: Any) -> Mapping[str, Any]:
        """``session/resume``. The frame exists on the ACP face, but resume
        semantics beyond the call are registered as unverified (unknown).
        Continuation belongs to the bridge contract
        (``agent-box.dsh-continuation@1``); this method never enters the
        provider's supported methods and is not a recovery fallback."""
        if "sessionId" in overrides:
            raise ValueError("sessionId cannot override session_id")
        params: dict[str, Any] = {"sessionId": session_id}
        params.update(overrides)
        return self._request("session/resume", params, timeout=timeout)

    def prompt(self, session_id: str, *, text: str, timeout: float = 10.0,
               **extra: Any) -> Mapping[str, Any]:
        """``session/prompt`` — sends work to the agent.

        The round-trip response carries the native ``stopReason``. **A prompt
        receipt is not completion**: only a structurally terminal response
        (``end_turn``/``error``/``cancelled``) is accepted as the turn's
        outcome; ``error``/``cancelled`` raise :class:`PromptTurnFailed`,
        anything malformed, non-terminal or unknown stays
        :class:`LostReceipt` (outcome unknown). Calling this may invoke a
        model — callers must hold explicit authorisation (L4 boundary).
        """
        if not isinstance(text, str):
            raise ValueError("prompt input must be explicit text")
        if any(name in extra for name in ("sessionId", "content", "prompt")):
            raise ValueError("sessionId/content/prompt cannot override the selected target/input")
        params: dict[str, Any] = {
            "sessionId": session_id,
            "content": [{"type": "text", "text": text}],
        }
        params.update(extra)
        return self._request("session/prompt", params, timeout=timeout)

    def cancel(self, session_id: str, *, timeout: float = 10.0) -> Mapping[str, Any]:
        """``session/cancel`` — cancellation is real evidence, never
        "completed" (G6). The native result (``cancelled``) is verbatim."""
        return self._request("session/cancel", {"sessionId": session_id}, timeout=timeout)

    def close_session(self, session_id: str, *, timeout: float = 10.0) -> Mapping[str, Any]:
        """``session/close`` — closes the native session. This is an effect on
        the native session; it never claims the owning PROCESS was stopped."""
        return self._request("session/close", {"sessionId": session_id}, timeout=timeout)

    def set_config_option(self, session_id: str, config_id: str, value: str, *,
                          timeout: float = 10.0) -> Mapping[str, Any]:
        """``session/set_config_option`` — a native session-config write. The
        receipt is verbatim; a configuration evidence port (absent in this
        package version) would be required to conclude applied effects."""
        return self._request(
            "session/set_config_option",
            {"sessionId": session_id, "configId": config_id, "value": value},
            timeout=timeout)

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
    def reply_permission(self, request_id: Any, outcome: str, *,
                         option_id: str | None = None) -> None:
        """Answer a pending ``session/request_permission`` with the SAME id.

        ``outcome`` must be one of the ACP outcomes; the caller owns the
        decision — no default, no auto-approve (SAFETY). ``selected`` requires
        an explicit option id; ``cancelled`` carries none — a cancelled
        decision can never silently become an approval.
        """
        request = self._reverse_requests.get(request_id)
        if request is None or request.method != "session/request_permission":
            raise ValueError("decision replies require a pending session/request_permission request")
        if outcome not in PERMISSION_OUTCOMES:
            raise ValueError("invalid permission outcome")
        if outcome == "selected":
            if not identity_text(option_id):
                raise ValueError("a selected permission outcome requires an explicit option id")
            value: Any = {"outcome": {"outcome": "selected", "optionId": option_id}}
        else:
            if option_id is not None:
                raise ValueError("a cancelled permission outcome carries no option id")
            value = {"outcome": {"outcome": "cancelled"}}
        # Consume before writing: partial-write failure must not permit replay.
        del self._reverse_requests[request_id]
        self._channel.reply(request_id, value)

    def reply_request(self, request_id: Any, result: Any) -> None:
        """Generic reverse-request answer; shapes stay the caller's choice."""
        if request_id not in self._reverse_requests:
            raise ValueError("no pending native reverse request with this id")
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
        self._events.append(raw)

    # -- control -----------------------------------------------------------
    def command(self, method: str, *, timeout: float = 10.0, **params: Any) -> Any:
        """Generic method round trip (future/unknown methods included); the
        result is returned verbatim and unknown semantics are never invented."""
        return self._request(method, dict(params), timeout=timeout)

    def command_once(self, method: str, params: Mapping[str, Any], *,
                     before_send: Callable[[Mapping[str, Any]], None],
                     timeout: float = 10.0) -> Any:
        """Fix the actual RPC identity, persist it, then dispatch exactly once.

        The hook sees a detached copy of the exact frozen native request at
        the actual write-lock/lease barrier. Its failure performs no write.
        A receipt timeout leaves this original ID pending;
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
        if method in SESSION_TARGETED_METHODS:
            session = params.get("sessionId")
            if not isinstance(session, str) or not session:
                raise ValueError(method + " requires the original native sessionId")
            return session
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
            payload = {"jsonrpc": JSONRPC_VERSION, "id": native_id, "method": method}
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
            session = self._prepared_method(method, payload.get("params", {}))
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
            if method == "session/prompt":
                self._prompt_requests[native_id] = session
            try:
                self._channel.send_frame(wire, before_write=lambda: before_write(wire))
                return self.recover_request(native_id, timeout=timeout, on_request=on_request)
            except DshRpcError as error:
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
    def _request_frame(self, request_id, method, params):
        payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": request_id, "method": method}
        if params:
            payload["params"] = dict(params)
        return payload

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
        object raises :class:`DshRpcError` with its raw error kept.
        """
        self._check_pending_method(method)
        if before_send is not None:
            return self._request_once_locked(method, params, timeout=timeout,
                                             on_request=on_request, before_send=before_send)
        self._request_seq += 1
        request_id = f"req-{self._request_seq}"
        self._pending[request_id] = method
        if method == "session/prompt":
            self._prompt_requests[request_id] = params["sessionId"]
        self._channel.send_raw(self._request_frame(request_id, method, params))
        return self.recover_request(request_id, timeout=timeout, on_request=on_request)

    def _request_once_locked(self, method, params, *, timeout, on_request, before_send):
        self._prepared_method(method, params)
        if self._prepared_unknown:
            raise LostReceipt(method, None, "original guarded write unresolved; query without another write")
        if type(timeout) not in (int, float) or not 0 < timeout < float("inf"):
            raise ValueError("finite positive receipt timeout required")
        if any(not callable(getattr(self._channel, name, None)) for name in
               ("send_frame", "mark_input_unknown", "acknowledge_frame")):
            raise PreparedFrameRefused("actual write barrier and unknown transport fence unavailable")
        self._request_seq += 1
        request_id = f"req-{self._request_seq}"
        wire = native_frame_bytes(self._request_frame(request_id, method, params))
        session = self._prepared_method(method, json.loads(wire).get("params", {}))
        admitted = False
        def guard():
            nonlocal admitted
            # Original journal binding/revalidation cannot mutate the bytes
            # written. It runs inside the transport's actual IO barrier.
            before_send(json.loads(wire))
            self._pending[request_id] = method
            self._prepared_waiting.add(request_id)
            if method == "session/prompt":
                self._prompt_requests[request_id] = session
            admitted = True
        try:
            self._channel.send_frame(wire, before_write=guard)
            return self.recover_request(request_id, timeout=timeout, on_request=on_request)
        except DshRpcError as error:
            # A guard may throw the native class before pending exists. Known
            # requires successful admission and actual original receipt ACK.
            if (admitted and request_id not in self._pending and request_id not in self._prepared_waiting
                    and error.request_id == request_id and error.method == method):
                raise
            self._cut_prepared_unknown()
            raise
        except BaseException:
            self._cut_prepared_unknown()
            raise

    def _check_pending_method(self, method):
        if method == "session/prompt" and "session/prompt" in self._pending.values():
            raise LostReceipt(method, None,
                              "earlier session/prompt receipt is unknown; recover without resending input")
        if method == "session/set_config_option" and "session/set_config_option" in self._pending.values():
            raise LostReceipt(method, None,
                              "original session configuration receipt unknown; query without another write")

    def recover_request(self, request_id: Any, *, timeout: float = 10.0,
                        on_request: Callable[[Message], None] | None = None) -> Any:
        """Wait for an unresolved RPC receipt on this connection without sending.

        This is not persisted recovery across processes. After channel loss,
        native session state can only be observed with independently known
        identities. A lost receipt cannot prove that input was not dispatched.
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
            self._prompt_requests.pop(request_id, None)
            raise DshRpcError(method, request_id, error)
        result = raw["result"]
        failure = None
        if method == "session/prompt":
            # A malformed/non-terminal prompt response KEEPS the original
            # pending id (outcome unknown); only a structurally terminal
            # response acknowledges the receipt — and may still fail the turn.
            failure = self._prompt_terminal_failure(request_id, result)
        self._ack_prepared_request(request_id)
        del self._pending[request_id]
        self._prompt_requests.pop(request_id, None)
        if failure is not None:
            raise failure
        return result

    @staticmethod
    def _prompt_terminal_failure(request_id, result):
        """Validate terminal prompt semantics; returns a typed failure or None."""
        if not isinstance(result, Mapping):
            raise LostReceipt("session/prompt", request_id,
                              "malformed prompt response; outcome unknown")
        stop = result.get("stopReason")
        if not identity_text(stop) or stop not in PROMPT_TERMINAL_STATUSES:
            raise LostReceipt("session/prompt", request_id,
                              "nonterminal or unknown completion status; outcome unknown")
        if stop in PROMPT_FAILED_STOP_REASONS:
            return PromptTurnFailed(stop, result)
        return None
