"""Shared Agent Client Protocol (ACP v1) consumer seam.

Frozen mid-batch (N008) because three families (gemini-cli, goose, vibe)
consume the same upstream protocol; extraction rule from design §3: share
only what is actually reused. Family clients subclass :class:`AcpClient` and
keep their own capability differences.

Protocol facts (https://agentclientprotocol.com/protocol, read 2026-10-04):

- JSON-RPC 2.0. Client→Agent: ``initialize`` (version negotiation),
  ``authenticate``, ``session/new``, ``session/prompt``, ``session/load``
  (optional), ``session/cancel`` (notification), ``session/set_mode``,
  ``logout``. Agent→Client: ``session/request_permission``,
  ``fs/read_text_file``, ``fs/write_text_file``, ``terminal/create``,
  ``terminal/output``, ``terminal/release``, ``terminal/wait_for_exit``,
  ``terminal/kill``, ``elicitation/create``, ``elicitation/complete``,
  ``session/update`` (notification).
- Custom methods are prefixed ``_``; custom data lives in ``_meta`` — the
  unknown-extension contract (G4): both are preserved verbatim and must not
  be dropped or rewritten.
- ``session/cancel`` is a notification (no response expected). A
  ``session/prompt`` response is a receipt boundary for one prompt turn;
  completion facts arrive via ``session/update`` records (G6: never invent
  completion).
- ``session/request_permission`` is a server→client request correlated by
  JSON-RPC id. This seam never answers it by itself (no auto-approve).
"""

from __future__ import annotations

from typing import Any, Mapping

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

ACP_PROTOCOL_VERSION = "1"


class AcpRemoteError(RemoteFailure):
    """The agent answered a JSON-RPC error object."""

    def __init__(self, method: str, request_id: Any, raw_error: Mapping[str, Any]):
        super().__init__(
            f"{method}#{request_id}: {raw_error.get('message', raw_error)}",
            code=raw_error.get("code"),
            data=raw_error.get("data"),
        )
        self.method = method
        self.request_id = request_id
        self.raw_error = dict(raw_error)


class AcpClient:
    """Base consumer for one owned ACP agent process (stdio JSON-RPC)."""

    #: Family layer overrides these.
    FAMILY_ID = "acp"
    PROTOCOL = f"acp/v{ACP_PROTOCOL_VERSION}"

    def __init__(self, channel: ProcessChannel, *, name: str = "acp"):
        self._channel = channel
        self._events: list[Message] = []
        self._pending: dict[Any, str] = {}
        self._seq = 0
        self._session_id: str | None = None

    @classmethod
    def launch(cls, spec: Any, *, name: str = "acp") -> "AcpClient":
        return cls(ProcessChannel.launch(spec, name=name), name=name)

    # -- handshake ----------------------------------------------------------
    def initialize(self, *, timeout: float = 10.0, **capabilities: Any) -> Mapping[str, Any]:
        """``initialize`` — the documented version negotiation. The wire
        ``protocolVersion`` field name is taken from the v1 schema family;
        families that document a different field override in their layer.
        """
        params: dict[str, Any] = {"protocolVersion": ACP_PROTOCOL_VERSION}
        if capabilities:
            params["capabilities"] = dict(capabilities)
        return self._request("initialize", params, timeout=timeout)

    # -- session identity ----------------------------------------------------
    def new_session(self, *, timeout: float = 10.0, **params: Any) -> Mapping[str, Any]:
        result = self._request("session/new", dict(params), timeout=timeout)
        session_id = result.get("sessionId") or result.get("sessionID")
        if isinstance(session_id, str):
            self._session_id = session_id
        return result

    def load_session(self, *, timeout: float = 10.0, **params: Any) -> Mapping[str, Any]:
        """``session/load`` (optional capability). No resume semantics are
        invented beyond the documented call."""
        return self._request("session/load", dict(params), timeout=timeout)

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # -- prompt (receipt boundary, not completion) -----------------------------
    def prompt(self, *, timeout: float = 60.0, on_request: Any = None, **params: Any) -> Any:
        """``session/prompt``. The response closes this prompt's request;
        completion facts arrive through ``session/update`` events — never
        assumed here (G6)."""
        return self._request("session/prompt", dict(params), timeout=timeout, on_request=on_request)

    def cancel(self, *, timeout: float = 10.0, **params: Any) -> None:
        """``session/cancel`` is a notification (no response expected)."""
        self._channel.notify("session/cancel", dict(params))

    # -- events ----------------------------------------------------------------
    def next_event(self, *, timeout: float = 10.0) -> Message:
        message = self._channel.next_message(timeout=timeout)
        self._events.append(message)
        return message

    def pump(self, *, timeout: float = 0.0) -> int:
        import time as _time

        deadline = _time.monotonic() + timeout
        count = 0
        while True:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                return count
            message = self._channel.poll_message(timeout=remaining)
            if message is None:
                return count
            self._events.append(message)
            count += 1

    def events(self) -> tuple[Message, ...]:
        return tuple(self._events)

    # -- reverse requests (never auto-answered) --------------------------------
    def reply_permission(self, request_id: Any, decision: str, *, option_id: Any = None) -> None:
        """Answer ``session/request_permission`` with the SAME id.

        ``decision`` is caller-chosen; there is no default (no auto-approve).
        Families with richer decision enums override in their layer.
        """
        result: dict[str, Any] = {"outcome": {"outcome": decision}}
        if option_id is not None:
            result["outcome"]["optionId"] = option_id
        self._channel.reply(request_id, result)

    def reply_request(self, request_id: Any, result: Any) -> None:
        self._channel.reply(request_id, result)

    def reply_request_error(self, request_id: Any, *, code: int, message: str, data: Any = None) -> None:
        self._channel.reply_error(request_id, code=code, message=message, data=data)

    # -- lifecycle ----------------------------------------------------------------
    def command(self, method: str, *, timeout: float = 10.0, on_request: Any = None, **params: Any) -> Any:
        return self._request(method, dict(params), timeout=timeout, on_request=on_request)

    def close(self) -> int:
        """Release only this owned channel/process (G6/G8)."""
        return self._channel.close()

    # -- internals -------------------------------------------------------------------
    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float,
        on_request: Any = None,
    ) -> Any:
        """JSON-RPC 2.0 round trip; never re-sent (G11). A transport breach
        after send is LostReceipt (unknown), a deadline is RequestTimeout."""
        self._seq += 1
        request_id = self._seq
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params:
            payload["params"] = dict(params)
        self._channel.send_raw(payload)
        self._pending[request_id] = method
        import time as _time

        deadline = _time.monotonic() + timeout
        while True:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                raise RequestTimeout(method, request_id, timeout)
            try:
                message: Message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError) as exc:
                raise LostReceipt(method, request_id, f"transport failure after send: {exc}") from exc
            raw = message.raw
            if raw.get("id") == request_id and message.kind == "response":
                del self._pending[request_id]
                error = raw.get("error")
                if error is not None:
                    raise AcpRemoteError(method, request_id, error)
                return raw.get("result")
            if message.kind == "request" and on_request is not None:
                on_request(message)
                continue
            self._events.append(message)  # notifications & unknown preserved (G4)
