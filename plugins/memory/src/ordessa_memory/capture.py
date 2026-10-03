"""The capture pipeline (MB-5): session turns → durable queue → mem0
extraction via REST.

The honest gates, in order:

1. the turn source must be bound (AR-3: absent on this baseline — captured
   turns can only arrive through the bound source or the diagnostic
   ``ingest`` entry point tests and the composition use);
2. the binding must be enabled and the brand mounted;
3. extraction must be explicitly authorized (spec red line 3: real-model
   calls default off) AND the LLM wiring must have resolved a bundled
   provider (MB-4: otherwise the feature stays off, honestly).

A turn that passes the gates is enqueued durably; ``flush`` walks the queue
against the mem0 REST client. Every failure mode — endpoint 500, server
unreachable — stays inside the pipeline: recorded on the queued item, never
raised into the session path (the failure counterexample MB-5 pins). The
extraction request's wire shape is exactly the client's ``add_messages``
payload (two messages, one profile namespace), asserted by the tests at a
fake REST endpoint.

Pure module: no HOME, no spawn, no file writes of its own (the store does
the durability), no secret content.
"""
from __future__ import annotations

from typing import Any, Callable

from . import common
from .events import TurnEvent
from .mem0_client import Mem0Client, Mem0ServerError, Mem0Unreachable


class CaptureBlocked(Exception):
    """A turn was NOT captured, with the typed reason (diagnosable state,
    not an error surface)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CapturePipeline:
    def __init__(self, store: Any, client_getter: Callable[[], Mem0Client | None],
                 server_scope_getter: Callable[[], str | None] = lambda: None) -> None:
        self._store = store
        self._client_getter = client_getter
        self._server_scope_getter = server_scope_getter
        self._source_bound = False

    # -- gates ----------------------------------------------------------------

    def on_turn(self, event: TurnEvent, *, binding: dict[str, Any],
                brand: str | None = None) -> int | None:
        """One captured turn; returns the queue id or None with a typed
        reason. NEVER raises (the session path must be untouchable)."""
        try:
            if not self._source_bound:
                raise CaptureBlocked("capture source not bound (AR-3: event surface absent)")
            if not binding.get("enabled"):
                raise CaptureBlocked("memory binding disabled for this profile")
            if brand is not None and brand not in binding.get("boundBrands", []):
                raise CaptureBlocked(f"brand {brand} not in boundBrands")
            if not self._store.extraction_authorized():
                raise CaptureBlocked("extraction not explicitly authorized")
            if self._client_getter() is None:
                raise CaptureBlocked("mem0 stack not provisioned/reachable (llm wiring off)")
            return self._store.enqueue_turn(
                event.profile_id, event.session_id, event.turn_id,
                event.user_text, event.assistant_text)
        except CaptureBlocked as exc:
            self._store.record_diagnostic("capture-blocked", exc.reason)
            return None
        except Exception as exc:  # noqa: BLE001 - the session path is untouchable
            self._store.record_diagnostic(
                "capture-error", f"{type(exc).__name__}: {exc}")
            return None

    # -- extraction flush ---------------------------------------------------------

    def flush(self, *, limit: int = 50) -> dict[str, int]:
        """Drain the queue against the mem0 REST API. Returns counters; a
        failing item stays queued with its recorded error."""
        client = self._client_getter()
        counts = {"flushed": 0, "failed": 0, "skipped": 0}
        if client is None:
            self._store.record_diagnostic("flush-skipped", "mem0 client unavailable")
            counts["skipped"] = len(self._store.pending_turns(limit))
            return counts
        for item in self._store.pending_turns(limit):
            namespace = common.profile_namespace(
                self._server_scope_getter(), item["profileId"])
            messages = [
                {"role": "user", "content": item["userText"]},
                {"role": "assistant", "content": item["assistantText"]},
            ]
            try:
                client.add_messages(messages, namespace)
            except (Mem0ServerError, Mem0Unreachable) as exc:
                self._store.record_attempt(item["id"], str(exc))
                counts["failed"] += 1
                continue
            except Exception as exc:  # noqa: BLE001 - a bad item must not stop the drain
                self._store.record_attempt(item["id"], f"{type(exc).__name__}: {exc}")
                counts["failed"] += 1
                continue
            self._store.record_attempt(item["id"], None)
            counts["flushed"] += 1
        return counts

    # -- source binding ---------------------------------------------------------

    def mark_source_bound(self, bound: bool) -> None:
        self._source_bound = bound
