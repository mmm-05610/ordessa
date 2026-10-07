"""Queue fencing (spec 021 appendix §5): consumption, refusal, blocking and
out-of-order results around the next-turn pipeline.

The pre-existing selector popped the queue entry *before* the pipeline ran, so
a refused or undecided resolution silently turned the next send into the "no
queued choice" path - and that path allows the prompt. FR-06 and gate M08
forbid exactly that. Each test below pins one half of the new contract:

- the frozen ``(session, sequence)`` is what gets consumed, and only by a real
  ``applied`` (read-back verified) resolution;
- a ``refused`` keeps the intent for an explicit retry;
- an ``unknown`` keeps the intent *and* blocks every further resolve with zero
  prompt until an observation settles it - never an implicit second apply;
- a late or out-of-order sequence never consumes or clears anything (M12);
- the routing identity (channel/owner/canonical UID/generation) is part of the
  session identity, so the same native session id reached another way is a
  different session (M09).
"""
from __future__ import annotations

from test_next_turn_pipeline import (
    CONFIG, SESSION, FakeCatalog, FakeHarness, _choice,
)

from ordessa_model_provider.next_turn import (
    OBSERVED_CONFIRMED, OBSERVED_MISMATCH, OUTCOME_APPLIED, OUTCOME_PENDING,
    OUTCOME_REFUSED, OUTCOME_UNKNOWN, NextTurnSelector,
)
from ordessa_model_provider.ports import (
    ELIGIBILITY_UNSUPPORTED, SESSION_CONFIG_OUTCOME_UNKNOWN, SESSION_CONFIG_REJECTED,
)

SESSION_B = {"serverInstanceId": "srv-1", "harnessId": "codex", "acpSessionId": "sess-B"}


class CountingHarness(FakeHarness):
    """Counts every apply *attempt*, including the ones that refuse.

    ``FakeHarness.applied`` only records successes, which is exactly what a
    "no silent retry" counter must not rely on.
    """

    def __init__(self, **over):
        super().__init__(**over)
        self.attempts = 0

    def apply(self, session_ref, choice):
        self.attempts += 1
        return super().apply(session_ref, choice)


def _selector(harness=None):
    return NextTurnSelector(harness or FakeHarness(), FakeCatalog())


def test_a_refusal_keeps_the_intent_for_an_explicit_retry():
    harness = FakeHarness(eligibility_value=ELIGIBILITY_UNSUPPORTED)
    selector = _selector(harness)
    sequence = selector.queue(SESSION, _choice(), source="session-override")
    refused = selector.resolve_next_turn(SESSION)
    assert refused.outcome == OUTCOME_REFUSED
    assert refused.sequence == sequence        # it names the intent it froze
    assert refused.prompt_allowed is False
    # the intent survived the refusal: it is still the session's next-turn model
    assert selector.pending(SESSION) == _choice()
    assert selector.intent(SESSION)["sequence"] == sequence
    # and an explicit retry really re-runs it (nothing was consumed)
    harness.eligibility_value = "ready"
    retried = selector.resolve_next_turn(SESSION)
    assert retried.outcome == OUTCOME_APPLIED
    assert selector.pending(SESSION) is None


def test_an_undecided_application_blocks_every_further_resolve():
    harness = CountingHarness(apply_error=(SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    selector = _selector(harness)
    sequence = selector.queue(SESSION, _choice(), source="session-override")
    first = selector.resolve_next_turn(SESSION)
    assert first.outcome == OUTCOME_UNKNOWN
    assert first.prompt_allowed is False
    assert first.sequence == sequence
    assert selector.blocked(SESSION) == {"sequence": sequence,
                                         "reason": SESSION_CONFIG_OUTCOME_UNKNOWN}

    # Every later send of the same session answers unknown with zero prompt,
    # and never silently re-applies (nothing here retries on its own).
    for _ in range(3):
        again = selector.resolve_next_turn(SESSION)
        assert again.outcome == OUTCOME_UNKNOWN
        assert again.prompt_allowed is False
        assert again.sequence == sequence
    assert harness.attempts == 1             # exactly the first attempt, never a retry


def test_a_blocked_session_never_degrades_into_the_no_intent_path():
    harness = FakeHarness(apply_error=(SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    selector = _selector(harness)
    selector.queue(SESSION, _choice(), source="session-override")
    assert selector.resolve_next_turn(SESSION).prompt_allowed is False
    # the "nothing queued" answer is the one that would allow the prompt
    fresh = selector.resolve_next_turn(SESSION)
    assert fresh.outcome != OUTCOME_PENDING
    assert fresh.prompt_allowed is False
    # the intent is still visible for the operator and for a later retry
    assert selector.pending(SESSION) == _choice()


def test_an_observation_settles_the_block_without_applying_anything():
    harness = CountingHarness(apply_error=(SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    selector = _selector(harness)
    sequence = selector.queue(SESSION, _choice(), source="session-override")
    selector.resolve_next_turn(SESSION)
    applied_before = harness.attempts
    assert applied_before == 1

    # a mismatch observation: it proves the application did not happen, so the
    # unsafe state clears and the intent stays for an explicit retry
    assert selector.observe(SESSION, sequence, outcome=OBSERVED_MISMATCH) is True
    assert selector.blocked(SESSION) is None
    assert selector.pending(SESSION) == _choice()
    assert harness.attempts == applied_before  # observation applies nothing

    harness.apply_error = None
    assert selector.resolve_next_turn(SESSION).outcome == OUTCOME_APPLIED


def test_a_confirmed_observation_consumes_only_its_own_sequence():
    harness = FakeHarness(apply_error=(SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    selector = _selector(harness)
    sequence = selector.queue(SESSION, _choice(modelId="m1"), source="session-override")
    selector.resolve_next_turn(SESSION)
    newer = selector.queue(SESSION, _choice(modelId="m2"), source="session-override")

    # observing the OLD operation settles the old unsafe state but must not
    # consume the newer pick (FR-04/FR-06, M12)
    assert selector.observe(SESSION, sequence, outcome=OBSERVED_CONFIRMED) is True
    assert selector.blocked(SESSION) is None
    assert selector.intent(SESSION)["sequence"] == newer
    assert selector.pending(SESSION)["modelId"] == "m2"


def test_an_out_of_order_observation_lands_on_nothing():
    harness = FakeHarness(apply_error=(SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    selector = _selector(harness)
    sequence = selector.queue(SESSION, _choice(), source="session-override")
    selector.resolve_next_turn(SESSION)

    assert selector.observe(SESSION_B, sequence, outcome=OBSERVED_CONFIRMED) is False
    assert selector.observe(SESSION, sequence + 7, outcome=OBSERVED_CONFIRMED) is False
    assert selector.observe(SESSION, sequence, outcome="looks-fine") is False
    assert selector.blocked(SESSION)["sequence"] == sequence  # nothing cleared


def test_a_pick_made_during_the_application_survives_it():
    """FR-04: a new pick during the application applies on the *next* send; the
    running result never consumes it."""
    selector = _selector()
    first = selector.queue(SESSION, _choice(modelId="m1"), source="session-override")

    def pick_again(session_ref, choice):
        # the user picks while the application is in flight
        selector.queue(SESSION, _choice(modelId="m2"), source="session-override")
        return FakeHarness.apply(selector._harness, session_ref, choice)

    selector._harness.apply = pick_again
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_APPLIED
    assert resolution.sequence == first                 # what really applied
    assert resolution.turn_fact.model_id == "m1"
    assert selector.pending(SESSION)["modelId"] == "m2"  # the newer pick survived
    assert selector.intent(SESSION)["sequence"] != first


def test_a_late_result_cannot_settle_a_blocked_session():
    harness = FakeHarness(apply_error=(SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    selector = _selector(harness)
    sequence = selector.queue(SESSION, _choice(), source="session-override")
    selector.resolve_next_turn(SESSION)
    assert selector.late_result(SESSION, sequence) is False
    assert selector.late_result(SESSION, sequence + 1) is False
    assert selector.blocked(SESSION) is not None        # still blocked


def test_a_late_result_never_reaches_another_routing_identity():
    selector = _selector()
    sequence = selector.queue(SESSION, _choice(), source="session-override")
    assert selector.late_result(SESSION_B, sequence) is False
    channel_a = {**SESSION, "channel": "chat"}
    channel_b = {**SESSION, "channel": "print"}
    assert selector.late_result(channel_a, sequence) is False  # unknown channel
    selector.queue(channel_b, _choice(), source="session-override")
    assert selector.late_result(channel_b, 2) is True


def test_routing_identity_factors_separate_queues_and_results():
    """M09: the same native session id reached through another channel, under
    another owner or in another generation is a different session."""
    base = dict(SESSION)
    chat = {**base, "channel": "chat", "owner": "native-a", "canonicalUid": "uid-1",
            "generation": 7}
    print_channel = {**base, "channel": "print"}
    next_generation = {**base, "channel": "chat", "owner": "native-a",
                       "canonicalUid": "uid-1", "generation": 8}
    other_owner = {**base, "channel": "chat", "owner": "native-b", "canonicalUid": "uid-1",
                   "generation": 7}

    selector = _selector()
    chat_sequence = selector.queue(chat, _choice(modelId="m1"), source="session-override")
    # none of the sibling identities sees that queue entry
    for sibling in (print_channel, next_generation, other_owner):
        assert selector.pending(sibling) is None
        assert selector.late_result(sibling, chat_sequence) is False
        assert selector.intent(sibling) is None
        resolution = selector.resolve_next_turn(sibling)
        assert resolution.outcome == OUTCOME_PENDING  # not dragged along
        assert resolution.prompt_allowed is True
    # the bare triple is a session of its own, never the channel-qualified one
    assert selector.pending(base) is None
    assert selector.late_result(chat, chat_sequence) is True


def test_the_block_survives_a_newer_pick():
    harness = FakeHarness(apply_error=(SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    selector = _selector(harness)
    blocked_sequence = selector.queue(SESSION, _choice(modelId="m1"),
                                      source="session-override")
    selector.resolve_next_turn(SESSION)
    selector.queue(SESSION, _choice(modelId="m2"), source="session-override")

    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_UNKNOWN
    assert resolution.prompt_allowed is False
    # both identities are preserved: the blocked attempt and the newer pick
    assert resolution.sequence == blocked_sequence
    assert selector.pending(SESSION)["modelId"] == "m2"


def test_harness_binding_operation_key_is_version_and_generation_bound(monkeypatch):
    """M10 at the legacy double's key: two versions, two generations, two
    keys - an unversioned plan can never be replayed onto a reconfigured one."""
    from ordessa_model_provider.harness_binding import _operation_key

    session = {"serverInstanceId": "srv-1", "harnessId": "codex", "acpSessionId": "sess-A"}
    base = {"providerConfigId": "p-1", "modelId": "m1"}
    first = _operation_key(session, {**base, "version": 1})
    second = _operation_key(session, {**base, "version": 2})
    assert first != second
    assert _operation_key(session, {**base, "version": 1}) == first  # stable
    generated = _operation_key(session, {**base, "version": 1, "generation": 8})
    assert generated not in (first, second)


def test_the_submit_gate_operation_key_is_version_bearing():
    from ordessa_model_provider.turn_application import submission_operation_key

    target = {"serverInstanceId": "srv-1", "harnessId": "codex", "acpSessionId": "sess-A"}
    one = submission_operation_key("client-key-1", target, sequence=4, config_version=1)
    two = submission_operation_key("client-key-1", target, sequence=4, config_version=2)
    other_sequence = submission_operation_key("client-key-1", target, sequence=5,
                                              config_version=1)
    assert one != two and one != other_sequence
    assert "s4" in one and "v1" in one and "v2" in two
    routed = submission_operation_key(
        "client-key-1", target, sequence=4, config_version=1,
        routing_identity={"owner": "native-a", "canonicalUid": "uid-1", "generation": 7})
    assert routed != one
    assert routed.startswith("mp-turn-s4-v1-")
