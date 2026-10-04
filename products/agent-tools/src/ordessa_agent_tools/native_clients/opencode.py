"""OpenCode server consumer client (family ``opencode``, protocol ``opencode-http/1``).

Pinned facts (N004, official https://opencode.ai/docs/server/ read 2026-10-04):

- Channel: local HTTP server ``opencode serve [--port N] [--hostname H]``
  (default 127.0.0.1:4096 — loopback by default) plus SSE event streams.
- Session identity: ``POST /session`` (body ``{parentID?, title?}``) creates a
  real session; ``POST /session/:id/message`` records the user message — that
  response is a receipt, NOT the assistant's completed answer (completion
  facts arrive as bus events / follow-up messages).
- Cancellation is explicit: ``POST /session/:id/abort``. The upstream doc does
  not tie task lifetime to the SSE connection, and does not say a dropped SSE
  stream ends a task — so a disconnect is never treated as completion here.
- Events: ``GET /event`` (first ``server.connected``, then bus events) and
  ``GET /global/event``. Payload schemas are NOT specified upstream beyond
  that; unknown event types/fields surface verbatim (G4) and are never
  guessed at.
- Auth: transport-level HTTP basic auth via ``OPENCODE_SERVER_PASSWORD`` (and
  optional ``OPENCODE_SERVER_USERNAME``); provider credentials are a separate
  ``PUT /auth/:id`` route. This client never inherits user credentials (G12).
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping

from ._http import HttpChannelFailure, LoopbackHttpChannel, SseEvent
from ._transport import ChannelClosed

FAMILY_ID = "opencode"
PROTOCOL = "opencode-http/1"


class OpenCodeApiError(HttpChannelFailure):
    """The server answered with a non-2xx status on a JSON route."""

    def __init__(self, route: str, status: int, body: Any = None):
        super().__init__("OPENCODE_API_ERROR", f"{route} -> {status}: {body!r}")
        self.route = route
        self.status = status
        self.body = body


def describe() -> dict[str, Any]:
    return {
        "familyId": FAMILY_ID,
        "channel": "loopback-http+sse",
        "protocol": PROTOCOL,
        "routes": [
            "GET /global/health",
            "GET /session",
            "POST /session",
            "GET /session/status",
            "POST /session/:id/message",
            "POST /session/:id/prompt_async",
            "POST /session/:id/abort",
            "GET /event",
            "GET /global/event",
        ],
    }


class OpenCodeClient:
    """Consumer of one local OpenCode server. Loopback only (G9/G12); no
    auto-retry anywhere (G11); SSE disconnect is never completion (G6)."""

    def __init__(self, channel: LoopbackHttpChannel):
        self._channel = channel
        self._events: list[SseEvent] = []

    @classmethod
    def connect(cls, base_url: str, *, timeout: float = 10.0) -> "OpenCodeClient":
        """Connect to a loopback server URL. Non-loopback destinations raise
        NonLoopbackRefused at construction (G9)."""
        return cls(LoopbackHttpChannel(base_url, timeout=timeout))

    # -- handshake ----------------------------------------------------------
    def initialize(self, *, timeout: float | None = None) -> Mapping[str, Any]:
        """Real handshake: ``GET /global/health`` (``{healthy, version}``)."""
        status, body = self._channel.request_json("GET", "/global/health", timeout=timeout)
        self._expect_ok("/global/health", status, body)
        return body

    # -- session identity ----------------------------------------------------
    def create_session(
        self,
        *,
        title: str | None = None,
        parent_id: str | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if parent_id is not None:
            body["parentID"] = parent_id
        status, result = self._channel.request_json("POST", "/session", body=body, timeout=timeout)
        self._expect_ok("POST /session", status, result)
        return result

    def session_status(self, *, timeout: float | None = None) -> Mapping[str, Any]:
        status, result = self._channel.request_json("GET", "/session/status", timeout=timeout)
        self._expect_ok("GET /session/status", status, result)
        return result

    # -- sending (receipts are not completion) --------------------------------
    def send(self, session_id: str, parts: Any, *, timeout: float | None = None, **fields: Any) -> Any:
        """``POST /session/:id/message``. The response records the message —
        it is a receipt, NOT the assistant's completed answer (G6).
        """
        body: dict[str, Any] = {"parts": parts}
        body.update(fields)
        status, result = self._channel.request_json(
            "POST", f"/session/{session_id}/message", body=body, timeout=timeout
        )
        self._expect_ok(f"POST /session/{session_id}/message", status, result)
        return result

    def send_async(self, session_id: str, parts: Any, *, timeout: float | None = None, **fields: Any) -> int:
        """``POST /session/:id/prompt_async`` → 204 No Content accepted. The
        204 is acceptance only; completion is observed via events."""
        body: dict[str, Any] = {"parts": parts}
        body.update(fields)
        status, _ = self._channel.request_json(
            "POST", f"/session/{session_id}/prompt_async", body=body, timeout=timeout
        )
        if status != 204:
            raise OpenCodeApiError(f"POST /session/{session_id}/prompt_async", status)
        return status

    # -- events ----------------------------------------------------------------
    def events(self, *, max_events: int | None = None) -> Iterator[SseEvent]:
        """SSE bus events verbatim (unknown types preserved, G4).

        The stream ENDING is not task completion: upstream documents abort as
        the explicit stop and leaves SSE-disconnect semantics unspecified, so
        callers must confirm state via protocol routes (G6 counter-example).
        """
        for event in self._channel.stream_events("/event", max_events=max_events):
            self._events.append(event)
            yield event

    def global_events(self, *, max_events: int | None = None) -> Iterator[SseEvent]:
        for event in self._channel.stream_events("/global/event", max_events=max_events):
            self._events.append(event)
            yield event

    def seen_events(self) -> tuple[SseEvent, ...]:
        return tuple(self._events)

    # -- control ----------------------------------------------------------------
    def cancel(self, session_id: str, *, timeout: float | None = None) -> Any:
        """``POST /session/:id/abort`` — the documented explicit stop (G6)."""
        status, result = self._channel.request_json(
            "POST", f"/session/{session_id}/abort", timeout=timeout
        )
        self._expect_ok(f"POST /session/{session_id}/abort", status, result)
        return result

    def close(self) -> None:
        """Release only this client's connection (G8)."""
        self._channel.close()

    # -- internals ---------------------------------------------------------------
    @staticmethod
    def _expect_ok(route: str, status: int, body: Any) -> None:
        if status < 200 or status >= 300:
            raise OpenCodeApiError(route, status, body)
        if body is None and status != 204:
            raise OpenCodeApiError(route, status, "empty body")


# re-exported so family callers see one failure surface
__all__ = [
    "FAMILY_ID",
    "PROTOCOL",
    "ChannelClosed",
    "OpenCodeApiError",
    "OpenCodeClient",
    "describe",
]
