"""The capture side's session-event seam (AR-3, MB-5).

First-hand finding on this baseline (2026-09-28, recorded in the report):
the agent domain's public contract (``plugins/agent/contracts``) exposes a
UI-facing snapshot store — ``AgentClient.subscribe(listener)`` change
notifications over ``AgentSnapshot`` — and **no server-side
"conversation turn completed" / "session ended" event surface** a plugin can
consume. Per the dispatch, the gap is registered, not worked around by
touching the agent domain.

What this module therefore owns:

* the minimal event shape the capture pipeline needs (``TurnEvent``), so the
  eventual producer side has a concrete contract to answer AR-3 with;
* the documented port name (``agent.turn_events``) the host composition
  would bind; absence is a diagnosable state (``source_status``), never an
  error and never a silent fake subscription;
* the failure discipline: a source that raises loses exactly that event —
  the capture pipeline never propagates into the session path.

Pure module: no HOME, no network, no spawn, no file writes, no secret
content.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

#: The documented port name for the (not yet existing) agent-domain event
#: source. Registered in api-requests AR-3 as the minimal needed shape:
#: ``subscribe(listener: Callable[[TurnEvent], None]) -> Callable[[], None]``.
TURN_SOURCE_PORT = "agent.turn_events"

SOURCE_ABSENT = "absent"
SOURCE_BOUND = "bound"

Unsubscribe = Callable[[], None]


@dataclass(frozen=True)
class TurnEvent:
    """One completed conversation turn (the minimal capture input).
    ``session_ended`` marks the session's terminal event (a capture flush
    trigger, not a separate subscription)."""

    profile_id: str
    session_id: str
    turn_id: str
    user_text: str
    assistant_text: str
    session_ended: bool = False


def turn_event_from_mapping(payload: Mapping[str, Any]) -> TurnEvent:
    """The typed projection a real producer would emit; strict on the
    identity fields, tolerant on text (an empty side stays an empty side)."""
    for field in ("profileId", "sessionId", "turnId"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"turn event is missing {field}")
    return TurnEvent(
        profile_id=payload["profileId"], session_id=payload["sessionId"],
        turn_id=payload["turnId"],
        user_text=str(payload.get("userText") or ""),
        assistant_text=str(payload.get("assistantText") or ""),
        session_ended=bool(payload.get("sessionEnded", False)))


class TurnSourceBinding:
    """Binds the (optional) event-source port to the capture pipeline.
    Absence is a first-class state the diagnostics expose."""

    def __init__(self) -> None:
        self._unsubscribe: Unsubscribe | None = None
        self._source_name: str | None = None
        self._last_error: str | None = None

    def bind(self, source: Any) -> None:
        """Bind a live source (whatever the composition supplies for the
        documented port). A source without ``subscribe`` is an honest
        refusal, never a fake binding."""
        subscribe = getattr(source, "subscribe", None)
        if not callable(subscribe):
            raise ValueError("the turn-event source does not expose subscribe()")
        self._unsubscribe = subscribe(self._on_event)
        self._source_name = getattr(source, "source_name", "agent.turn_events")
        self._last_error = None

    def unbind(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
        self._unsubscribe = None
        self._source_name = None

    def _on_event(self, payload: Any) -> None:
        # A raising handler must not take the source down: the event is
        # lost, the error recorded, the session unaffected (AR-3 failure
        # counterexample).
        try:
            if self._handler is not None:
                event = payload if isinstance(payload, TurnEvent) else turn_event_from_mapping(payload)
                self._handler(event)
        except Exception as exc:  # noqa: BLE001 - the boundary holds the failure
            self._last_error = f"{type(exc).__name__}: {exc}"

    #: the pipeline callback (set by the capture pipeline)
    _handler: Callable[[TurnEvent], None] | None = None

    def set_handler(self, handler: Callable[[TurnEvent], None]) -> None:
        self._handler = handler

    def source_status(self) -> dict[str, Any]:
        return {"source": self._source_name, "state": SOURCE_BOUND if self._source_name else SOURCE_ABSENT,
                "lastError": self._last_error,
                "note": "agent 域尚无公开轮次/会话事件面（AR-3 已登记）；捕获源缺席时捕获停止、注入照常"}
