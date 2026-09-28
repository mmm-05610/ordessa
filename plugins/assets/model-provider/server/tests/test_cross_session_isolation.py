# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_cross_session_isolation.py, verbatim)
"""G7 / FR-SESSION-4: cross-session isolation.

Two concurrent sessions share the harness. A's queued choice, A's application
and any late-arriving result must stay inside A's exact session reference
``(serverInstanceId, harnessId, acpSessionId)``; nothing here writes a
harness-global configuration, which this suite also asserts directly by
watching every global-facing surface the fakes expose.
"""
from __future__ import annotations

from test_next_turn_pipeline import CONFIG, FakeCatalog, FakeHarness, _choice

from ordessa_model_provider.next_turn import (
    OUTCOME_APPLIED, OUTCOME_PENDING, OUTCOME_UNKNOWN, NextTurnSelector,
)

SESSION_A = {"serverInstanceId": "srv-1", "harnessId": "codex", "acpSessionId": "sess-A"}
SESSION_B = {"serverInstanceId": "srv-1", "harnessId": "codex", "acpSessionId": "sess-B"}
OTHER_SERVER = {"serverInstanceId": "srv-2", "harnessId": "codex", "acpSessionId": "sess-A"}


def test_a_queue_leaves_b_and_the_global_harness_untouched():
    harness = FakeHarness()
    selector = NextTurnSelector(harness, FakeCatalog())
    selector.queue(SESSION_A, _choice(modelId="m2"), source="session-override")

    assert selector.pending(SESSION_B) is None          # B sees no queue entry
    b_resolution = selector.resolve_next_turn(SESSION_B)
    assert b_resolution.outcome == OUTCOME_PENDING      # B is not dragged along
    assert b_resolution.prompt_allowed is True

    a_resolution = selector.resolve_next_turn(SESSION_A)
    assert a_resolution.outcome == OUTCOME_APPLIED
    # the application named A's session only
    applied_session, applied_choice = harness.applied[0]
    assert applied_session == SESSION_A
    assert applied_choice["modelId"] == "m2"
    assert len(harness.applied) == 1


def test_same_ids_on_a_different_server_do_not_share_queue_state():
    selector = NextTurnSelector(FakeHarness(), FakeCatalog())
    selector.queue(SESSION_A, _choice(modelId="m2"), source="session-override")
    # srv-2's sess-A is a different session, whatever its ids spell
    assert selector.pending(OTHER_SERVER) is None
    assert selector.resolve_next_turn(OTHER_SERVER).outcome == OUTCOME_PENDING
    assert selector.pending(SESSION_A) is not None


def test_late_result_with_mismatched_identity_is_dropped():
    selector = NextTurnSelector(FakeHarness(), FakeCatalog())
    sequence = selector.queue(SESSION_A, _choice(), source="session-override")
    assert selector.late_result(SESSION_B, sequence) is False
    assert selector.late_result(OTHER_SERVER, sequence) is False
    assert selector.late_result(SESSION_A, sequence + 1) is False
    assert selector.late_result(SESSION_A, sequence) is True


def test_consumed_queue_is_gone_for_everyone():
    selector = NextTurnSelector(FakeHarness(), FakeCatalog())
    selector.queue(SESSION_A, _choice(), source="session-override")
    selector.resolve_next_turn(SESSION_A)
    assert selector.pending(SESSION_A) is None
    assert selector.resolve_next_turn(SESSION_A).outcome == OUTCOME_PENDING


def test_no_api_reaches_a_global_configuration_writer():
    """The global-config regression: switching A rewrites the harness's user
    global configuration. The selector's whole surface is exercised while the
    fakes record every call - none of them is a global write."""
    global_writes: list = []

    class WatchedHarness(FakeHarness):
        def apply(self, session_ref, choice):
            global_writes.append(("apply", dict(session_ref)))
            return super().apply(session_ref, choice)

    harness = WatchedHarness()
    selector = NextTurnSelector(harness, FakeCatalog())
    selector.queue(SESSION_A, _choice(modelId="m2"), source="session-override")
    selector.resolve_next_turn(SESSION_A)
    selector.queue(SESSION_B, _choice(modelId="m1"), source="session-override")
    selector.resolve_next_turn(SESSION_B)

    for kind, ref in global_writes:
        assert kind == "apply"                 # only session-scoped application
        assert ref.get("acpSessionId") in {"sess-A", "sess-B"}
        assert set(ref) == {"serverInstanceId", "harnessId", "acpSessionId"}
