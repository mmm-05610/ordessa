"""Qwen Code serve consumer client (family ``qwen``, protocol ``qwen-serve-http/1``).

Pinned facts (N007, upstream main @9915c7ff…, docs read 2026-10-04):

- Channel: a local ``qwen serve`` daemon (default ``http://127.0.0.1:4170``)
  speaking HTTP JSON routes plus per-session SSE. The daemon owns the
  workspace registry, each workspace runtime and the ``qwen --acp`` child it
  spawns; this client talks only to the daemon and never spawns anything.
- Handshake: ``GET /capabilities`` returns ``{v, protocolVersions, features,
  workspaceCwd, ...}`` verbatim; feature tags gate behaviour, ``v`` increments
  only on a breaking frame change.
- Session: ``POST /session`` creates or attaches in the daemon-owned ledger
  and answers ``{sessionId, workspaceCwd, attached?}``. The default daemon
  scope ``single`` shares one conversation per workspace, so this client
  defaults to ``sessionScope: "thread"`` for an independent conversation. A
  native ``sessionId`` is surfaced verbatim and never fabricated (G6).
- Send: ``POST /session/:id/prompt`` answers ``202 {promptId, lastEventId,
  eventEpoch?}`` — an **admission receipt, NOT completion**. Completion facts
  are ``turn_complete`` / ``turn_error`` frames on the session SSE stream,
  correlated by ``promptId``; a stream ending is not completion either.
- Cancel: ``POST /session/:id/cancel`` (204) cancels only the active prompt;
  queued prompts keep running (documented multi-prompt contract).
- Permissions: the agent's ``permission_request`` arrives on SSE and is
  answered by an explicit caller vote via
  ``POST /session/:id/permission/:requestId``. This client never auto-votes.
- Auth: the loopback default is tokenless; a bearer is only ever carried when
  the caller's own channel supplies one. No user credential is inherited
  (G12) and nothing is retried (G11).

Unknown SSE envelope types/fields are preserved verbatim (G4). The client is
a pure consumer over the frozen N001 transport seam (``_http``): loopback
enforcement, SSE framing, typed failures and owned-connection cleanup
delegate there; this module adds only qwen's document-level route shapes.
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping

from ._http import HttpChannelFailure, LoopbackHttpChannel, SseEvent
from ._transport import ChannelClosed

FAMILY_ID = "qwen"
PROTOCOL = "qwen-serve-http/1"

#: Events that actually settle a prompt turn on the session SSE stream. The
#: stream ending, a client eviction or a disconnect are NOT completion.
TURN_TERMINAL_EVENTS: frozenset[str] = frozenset({"turn_complete", "turn_error"})


class QwenApiError(HttpChannelFailure):
    """The daemon answered a JSON route with an unexpected status/body."""

    def __init__(self, route: str, status: int, body: Any = None):
        super().__init__("QWEN_API_ERROR", f"{route} -> {status}: {body!r}")
        self.route = route
        self.status = status
        self.body = body


def describe() -> dict[str, Any]:
    """Static channel facts. No runtime readiness is claimed."""
    return {
        "familyId": FAMILY_ID,
        "channel": "loopback-http+sse-over-acp",
        "protocol": PROTOCOL,
        "routes": [
            "GET /capabilities",
            "GET /health",
            "POST /session",
            "POST /session/:id/prompt",
            "POST /session/:id/cancel",
            "DELETE /session/:id",
            "GET /session/:id/events",
            "POST /session/:id/permission/:requestId",
        ],
    }


class QwenClient:
    """Consumer of one local ``qwen serve`` daemon. Loopback only (G9/G12);
    no auto-retry anywhere (G11); SSE stream end is never completion (G6)."""

    def __init__(self, channel: LoopbackHttpChannel, *, client_id: str | None = None):
        self._channel = channel
        self._client_id = client_id
        self._events: list[SseEvent] = []

    @classmethod
    def connect(
        cls, base_url: str, *, timeout: float = 10.0, client_id: str | None = None
    ) -> "QwenClient":
        """Connect to a loopback daemon URL. Non-loopback destinations raise
        NonLoopbackRefused at construction (G9)."""
        return cls(LoopbackHttpChannel(base_url, timeout=timeout), client_id=client_id)

    # -- handshake ----------------------------------------------------------
    def initialize(self, *, timeout: float | None = None) -> Mapping[str, Any]:
        """Real handshake: ``GET /capabilities`` verbatim (v1 protocol
        versions, feature tags, primary workspaceCwd)."""
        status, body = self._channel.request_json(
            "GET", "/capabilities", headers=self._headers(), timeout=timeout
        )
        self._expect_ok("GET /capabilities", status, body)
        return body

    # -- session identity ----------------------------------------------------
    def create_session(
        self,
        *,
        cwd: str | None = None,
        session_scope: str = "thread",
        model_service_id: str | None = None,
        timeout: float | None = None,
        **fields: Any,
    ) -> Mapping[str, Any]:
        """``POST /session``; the daemon is the session-ledger owner.

        ``session_scope="thread"`` (this client's default) asks the daemon for
        a fresh distinct conversation; the daemon's own default ``single``
        would attach to an existing shared session. ``attached: true`` is
        surfaced verbatim — never rewritten into a new session. The native
        ``sessionId`` comes only from the daemon (no fabrication, G6).
        """
        body: dict[str, Any] = {"sessionScope": session_scope}
        if cwd is not None:
            body["cwd"] = cwd
        if model_service_id is not None:
            body["modelServiceId"] = model_service_id
        body.update(fields)
        status, result = self._channel.request_json(
            "POST", "/session", body=body, headers=self._headers(), timeout=timeout
        )
        self._expect_ok("POST /session", status, result)
        return result

    def session_status(self, session_id: str, *, timeout: float | None = None) -> Mapping[str, Any]:
        """``GET /session/:id/status`` for the live owning runtime."""
        route = f"GET /session/{session_id}/status"
        status, result = self._channel.request_json(
            "GET", f"/session/{session_id}/status", headers=self._headers(), timeout=timeout
        )
        self._expect_ok(route, status, result)
        return result

    # -- sending (the 202 is a receipt, not completion) -----------------------
    def send(
        self,
        session_id: str,
        prompt: Any,
        *,
        timeout: float | None = None,
        **fields: Any,
    ) -> Mapping[str, Any]:
        """``POST /session/:id/prompt`` → 202 admission receipt.

        **The returned ``{promptId, lastEventId, eventEpoch?}`` is NOT
        completion.** Settle the turn by correlating ``turn_complete`` /
        ``turn_error`` on :meth:`events` by ``promptId``. Any non-202 status
        is a typed :class:`QwenApiError`; nothing is retried (G11).
        """
        body: dict[str, Any] = {"prompt": prompt}
        body.update(fields)
        route = f"POST /session/{session_id}/prompt"
        status, result = self._channel.request_json(
            "POST", f"/session/{session_id}/prompt", body=body, headers=self._headers(), timeout=timeout
        )
        if status != 202:
            raise QwenApiError(route, status, result)
        return result

    # -- events ----------------------------------------------------------------
    def events(
        self,
        session_id: str,
        *,
        last_event_id: int | str | None = None,
        max_events: int | None = None,
    ) -> Iterator[SseEvent]:
        """Session SSE events verbatim (unknown types preserved, G4).

        ``last_event_id`` becomes the ``Last-Event-ID`` replay cursor. The
        iterator ending when the server closes the stream is NOT completion:
        only a ``turn_complete`` / ``turn_error`` frame settles the prompt.
        """
        headers = self._headers()
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        for event in self._channel.stream_events(
            f"/session/{session_id}/events", headers=headers, max_events=max_events
        ):
            self._events.append(event)
            yield event

    def seen_events(self) -> tuple[SseEvent, ...]:
        return tuple(self._events)

    # -- control ----------------------------------------------------------------
    def cancel(self, session_id: str, *, timeout: float | None = None) -> int:
        """``POST /session/:id/cancel`` → 204. Cancels only the active prompt;
        prompts already queued behind it keep running (documented)."""
        route = f"POST /session/{session_id}/cancel"
        status, body = self._channel.request_json(
            "POST", f"/session/{session_id}/cancel", headers=self._headers(), timeout=timeout
        )
        if status != 204:
            raise QwenApiError(route, status, body)
        return status

    def close_session(self, session_id: str, *, timeout: float | None = None) -> int:
        """``DELETE /session/:id`` → 204. Closes the live session (its on-disk
        transcript stays loadable by the daemon); idempotent upstream."""
        route = f"DELETE /session/{session_id}"
        status, body = self._channel.request_json(
            "DELETE", f"/session/{session_id}", headers=self._headers(), timeout=timeout
        )
        if status != 204:
            raise QwenApiError(route, status, body)
        return status

    def respond_permission(
        self,
        session_id: str,
        request_id: str,
        *,
        option_id: str | None = None,
        cancel: bool = False,
        timeout: float | None = None,
    ) -> Any:
        """Answer a pending ``permission_request`` with one explicit caller
        choice. There is no default and no auto-approve: exactly one of
        ``option_id`` / ``cancel=True`` must be given, otherwise nothing is
        sent and a ``ValueError`` is raised before any write."""
        if cancel == (option_id is not None):
            raise ValueError("exactly one of option_id or cancel=True is required")
        outcome = (
            {"outcome": "cancelled"}
            if cancel
            else {"outcome": "selected", "optionId": option_id}
        )
        route = f"POST /session/{session_id}/permission/{request_id}"
        status, result = self._channel.request_json(
            "POST",
            f"/session/{session_id}/permission/{request_id}",
            body={"outcome": outcome},
            headers=self._headers(),
            timeout=timeout,
        )
        self._expect_ok(route, status, result)
        return result

    def close(self) -> None:
        """Release only this client's own connection (G8)."""
        self._channel.close()

    # -- internals ---------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._client_id is not None:
            headers["X-Qwen-Client-Id"] = self._client_id
        return headers

    @staticmethod
    def _expect_ok(route: str, status: int, body: Any) -> None:
        if status < 200 or status >= 300:
            raise QwenApiError(route, status, body)
        if body is None and status != 204:
            raise QwenApiError(route, status, "empty body")


# re-exported so family callers see one failure surface
__all__ = [
    "FAMILY_ID",
    "PROTOCOL",
    "ChannelClosed",
    "QwenApiError",
    "QwenClient",
    "TURN_TERMINAL_EVENTS",
    "describe",
]
