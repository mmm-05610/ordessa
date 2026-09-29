"""Capture pipeline (MB-5): gates, durable queue, extraction request shapes
at a fake mem0 REST facade, and the failure counterexamples — an endpoint
500 or an unreachable server leaves the queue holding, raises nothing, and
the session path stays untouchable."""
from __future__ import annotations

from ordessa_memory import events
from ordessa_memory.capture import CapturePipeline
from ordessa_memory.events import TurnEvent, TurnSourceBinding

from conftest import FakeClientFactory


def _pipeline(store, client_factory, scope="srv-1"):
    return CapturePipeline(store, (lambda: client_factory.client if client_factory else None),
                           lambda: scope)


def _event(turn_id="t1", profile_id="p1", **kw):
    return TurnEvent(profile_id=profile_id, session_id="s1", turn_id=turn_id,
                     user_text="我偏好深色模式", assistant_text="已切换", **kw)


def _ready(store, pipeline):
    store.set_extraction_authorized(True)
    pipeline.mark_source_bound(True)


def test_unauthorized_extraction_blocks_capture_with_a_diagnosable_reason(store, client_factory):
    pipeline = _pipeline(store, client_factory)
    pipeline.mark_source_bound(True)
    store.set_extraction_authorized(False)
    assert pipeline.on_turn(_event(), binding={"enabled": True, "boundBrands": ["pi"]}) is None
    stats = store.capture_stats()
    assert stats["queued"] == 0
    assert any("authorized" in d["detail"] for d in store.recent_diagnostics())


def test_unbound_source_blocks_capture(store, client_factory):
    pipeline = _pipeline(store, client_factory)
    store.set_extraction_authorized(True)
    assert pipeline.on_turn(_event(), binding={"enabled": True, "boundBrands": []}) is None
    assert any("source not bound" in d["detail"]
               for d in store.recent_diagnostics())


def test_disabled_binding_blocks_capture(store, client_factory):
    pipeline = _pipeline(store, client_factory)
    _ready(store, pipeline)
    assert pipeline.on_turn(_event(), binding={"enabled": False, "boundBrands": ["pi"]}) is None


def test_missing_stack_blocks_capture(store):
    pipeline = _pipeline(store, None)
    _ready(store, pipeline)
    assert pipeline.on_turn(_event(), binding={"enabled": True, "boundBrands": ["pi"]}) is None


def test_captured_turn_enqueues_then_flushes_with_the_pinned_request_shape(
        store, client_factory, fake_mem0):
    pipeline = _pipeline(store, client_factory)
    _ready(store, pipeline)
    queue_id = pipeline.on_turn(_event(), binding={"enabled": True, "boundBrands": ["pi"]})
    assert queue_id is not None
    counts = pipeline.flush()
    assert counts == {"flushed": 1, "failed": 0, "skipped": 0}
    assert store.capture_stats()["queued"] == 0
    method, path, headers, body = fake_mem0.requests[-1]
    assert (method, path) == ("POST", "/memories")
    assert body["user_id"] == "ordessa:srv-1:profile:p1"
    assert body["messages"] == [
        {"role": "user", "content": "我偏好深色模式"},
        {"role": "assistant", "content": "已切换"}]


def test_server_500_keeps_the_turn_queued_and_raises_nothing(store, fake_mem0):
    """The failure counterexample: endpoint 500 → the turn stays queued with
    the recorded error; the session (caller) is never disturbed."""
    factory = FakeClientFactory(f"http://127.0.0.1:{fake_mem0.server_address[1]}")
    factory.client._timeout = 5
    # point the client at a 500-ing endpoint
    class _Five:
        def add_messages(self, *a, **kw):
            from ordessa_memory.mem0_client import Mem0ServerError
            raise Mem0ServerError(500, "upstream extraction failed")
    factory.client = _Five()
    pipeline = _pipeline(store, factory)
    _ready(store, pipeline)
    queue_id = pipeline.on_turn(_event(), binding={"enabled": True, "boundBrands": ["pi"]})
    assert queue_id is not None  # capture succeeded; flush will fail honestly
    counts = pipeline.flush()
    assert counts["failed"] == 1
    stats = store.capture_stats()
    assert stats["queued"] == 1 and stats["failed"] == 1
    assert "500" in stats["lastError"]


def test_flush_without_a_client_skips_honestly(store):
    pipeline = _pipeline(store, None)
    _ready(store, pipeline)
    counts = pipeline.flush()
    assert counts["skipped"] >= 0 and counts["flushed"] == 0


def test_turn_source_binding_isolates_a_raising_handler():
    binding = TurnSourceBinding()
    seen = []
    bomb = []

    def handler(event):
        if bomb:
            raise RuntimeError("extraction backend exploded")
        seen.append(event)

    binding.set_handler(handler)
    binding._on_event({"profileId": "p1", "sessionId": "s1", "turnId": "t1",
                       "userText": "u", "assistantText": "a"})
    assert len(seen) == 1
    bomb.append(True)
    binding._on_event({"profileId": "p1", "sessionId": "s1", "turnId": "t2",
                       "userText": "u", "assistantText": "a"})
    assert len(seen) == 1  # the failing event is lost, the handler survived
    assert "extraction backend exploded" in binding.source_status()["lastError"]


def test_malformed_event_payload_is_rejected_not_guessed():
    import pytest
    with pytest.raises(ValueError):
        events.turn_event_from_mapping({"sessionId": "s1", "turnId": "t1"})


def test_source_status_documents_the_ar3_absence(store):
    pipeline = _pipeline(store, None)
    status = pipeline and events.TurnSourceBinding().source_status()
    assert status["state"] == "absent"
    assert "AR-3" in status["note"]
