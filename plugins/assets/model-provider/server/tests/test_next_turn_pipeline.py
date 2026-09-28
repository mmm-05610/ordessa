# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_next_turn_pipeline.py, verbatim)
"""G5 / FR-SESSION: the next-turn pipeline, driven by a fake harness port.

The fake harness speaks the frozen port protocol (ports.HarnessConfigPort);
it is a controlled stand-in, not bridge or model evidence (E1). The
counterexample every failure test shares: after a refused or unknown
resolution, ``prompt_allowed`` is False - the zero-prompt gate - and the
caller's draft is untouched because the selector never sees or edits it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ordessa_model_provider.ports import (
    ELIGIBILITY_READY, ELIGIBILITY_UNKNOWN, ELIGIBILITY_UNSUPPORTED,
    SESSION_CONFIG_OUTCOME_UNKNOWN, SESSION_CONFIG_REJECTED, SessionConfigError,
)
from ordessa_model_provider.next_turn import (
    OUTCOME_APPLIED, OUTCOME_PENDING, OUTCOME_REFUSED, OUTCOME_UNKNOWN,
    NextTurnSelector,
)

SESSION = {"serverInstanceId": "srv-1", "harnessId": "codex", "acpSessionId": "sess-A"}
CONFIG = "provider-1"


class FakeCatalog:
    def __init__(self, version=3, models=("m1", "m2"), archived=False, missing=False):
        self.version = version
        self.models = list(models)
        self.archived = archived
        self.missing = missing

    def config_version(self, provider_config_id):
        if self.missing:
            raise LookupError("provider-nope")
        return self.version

    def model_ids(self, provider_config_id):
        if self.missing:
            raise LookupError("provider-nope")
        return list(self.models)

    def is_archived(self, provider_config_id):
        if self.missing:
            raise LookupError("provider-nope")
        return self.archived


@dataclass
class FakeHarness:
    """Port-faithful fake: apply receipts always carry the post-apply
    read-back, because a receipt without one is an unknown outcome. The
    read-back echoes the applied model (a faithful backend); set
    ``read_back_model`` explicitly to simulate a mismatching backend."""

    eligibility_value: str = ELIGIBILITY_READY
    apply_error: tuple[str, str] | None = None
    read_back_model: str | None = None
    drop_read_back: bool = False
    config_options: dict = field(default_factory=dict)
    applied: list = field(default_factory=list)

    def describe(self, harness_id):
        return {"fields": ["authStyle"]}

    def eligibility(self, harness_id, config_ref, session_ref):
        return self.eligibility_value

    def apply(self, session_ref, choice):
        if self.apply_error is not None:
            raise SessionConfigError(*self.apply_error)
        self.applied.append((dict(session_ref), dict(choice)))
        model = self.read_back_model if self.read_back_model is not None else choice["modelId"]
        read_back = {} if self.drop_read_back else {"model": model}
        return {"readBack": read_back, "configOptions": dict(self.config_options)}

    def read_back(self, session_ref):
        return {"model": self.read_back_model}


def _choice(**over):
    choice = {"harnessId": "codex", "providerConfigId": CONFIG, "modelId": "m1"}
    choice.update(over)
    return choice


def test_happy_path_applies_and_freezes_turn_facts():
    selector = NextTurnSelector(FakeHarness(config_options={"reasoning": "high"}), FakeCatalog())
    sequence = selector.queue(SESSION, _choice(associated={"reasoning": "high"}),
                              source="session-override")
    assert selector.pending(SESSION) == _choice(associated={"reasoning": "high"})
    resolution = selector.resolve_next_turn(SESSION, profile_revision="rev-7")
    assert resolution.outcome == OUTCOME_APPLIED
    assert resolution.prompt_allowed is True
    fact = resolution.turn_fact
    assert (fact.provider_config_id, fact.model_id) == (CONFIG, "m1")
    assert fact.provider_config_version == 3
    assert fact.profile_revision == "rev-7"
    assert fact.evidence["applied"] == "read-back-verified"
    assert resolution.associated_options == {"reasoning": "high"}
    assert selector.late_result(SESSION, sequence) is False  # consumed


def test_queueing_never_touches_the_running_turn():
    selector = NextTurnSelector(FakeHarness(), FakeCatalog())
    selector.queue(SESSION, _choice(), source="session-override")
    # between queue and resolve the session keeps running; the queue entry is
    # the only state that changed, and resolving is the only way to consume it
    assert selector.pending(SESSION) is not None
    selector.cancel(SESSION)
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_PENDING
    assert resolution.prompt_allowed is True  # default path sends untouched


def test_eligibility_unknown_refuses_zero_prompt():
    selector = NextTurnSelector(FakeHarness(eligibility_value=ELIGIBILITY_UNKNOWN), FakeCatalog())
    selector.queue(SESSION, _choice(), source="session-override")
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_REFUSED
    assert "unknown" in resolution.reason
    assert resolution.prompt_allowed is False
    assert resolution.turn_fact is None


def test_eligibility_unsupported_refuses_zero_prompt():
    selector = NextTurnSelector(FakeHarness(eligibility_value=ELIGIBILITY_UNSUPPORTED), FakeCatalog())
    selector.queue(SESSION, _choice(), source="session-override")
    assert selector.resolve_next_turn(SESSION).prompt_allowed is False


def test_backend_rejection_is_refused():
    harness = FakeHarness(apply_error=(SESSION_CONFIG_REJECTED, "nope"))
    selector = NextTurnSelector(harness, FakeCatalog())
    selector.queue(SESSION, _choice(), source="session-override")
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_REFUSED
    assert resolution.reason == SESSION_CONFIG_REJECTED
    assert resolution.prompt_allowed is False
    assert harness.applied == []  # apply refused before touching the session


def test_outcome_unknown_blocks_further_sends():
    harness = FakeHarness(apply_error=(SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    selector = NextTurnSelector(harness, FakeCatalog())
    selector.queue(SESSION, _choice(), source="session-override")
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_UNKNOWN
    assert resolution.prompt_allowed is False  # blocked until someone verifies


def test_missing_or_mismatched_read_back_is_unknown():
    selector = NextTurnSelector(FakeHarness(drop_read_back=True), FakeCatalog())
    selector.queue(SESSION, _choice(), source="session-override")
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_UNKNOWN
    assert resolution.prompt_allowed is False

    selector.queue(SESSION, _choice(), source="session-override")
    selector._harness = FakeHarness(read_back_model="m-other")
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_UNKNOWN  # read-back must equal the choice


def test_archived_or_missing_config_or_foreign_model_refuses():
    harness = FakeHarness()
    selector = NextTurnSelector(harness, FakeCatalog(archived=True))
    selector.queue(SESSION, _choice(), source="session-override")
    assert selector.resolve_next_turn(SESSION).outcome == OUTCOME_REFUSED

    selector = NextTurnSelector(harness, FakeCatalog(missing=True))
    selector.queue(SESSION, _choice(), source="session-override")
    refused = selector.resolve_next_turn(SESSION)
    assert refused.outcome == OUTCOME_REFUSED and refused.prompt_allowed is False

    selector = NextTurnSelector(harness, FakeCatalog(models=("other",)))
    selector.queue(SESSION, _choice(), source="session-override")
    assert selector.resolve_next_turn(SESSION).outcome == OUTCOME_REFUSED


def test_r1_latest_revision_is_resolved_and_incompatible_blocks():
    """R1: the next turn resolves the newest revision. A config that changed
    since queuing (new version, adapter no longer supports it) blocks the
    turn - it never falls back to the old endpoint or a default model."""
    harness = FakeHarness(eligibility_value=ELIGIBILITY_UNSUPPORTED)
    catalog = FakeCatalog(version=9)
    selector = NextTurnSelector(harness, catalog)
    selector.queue(SESSION, _choice(), source="profile")
    resolution = selector.resolve_next_turn(SESSION, profile_revision="rev-9")
    assert resolution.outcome == OUTCOME_REFUSED
    assert resolution.prompt_allowed is False
    # and the refusal, not a fallback, is what the caller sees
    assert harness.applied == []


def test_associated_settings_never_silently_kept_or_defaulted():
    selector = NextTurnSelector(FakeHarness(config_options={"reasoning": "medium"}), FakeCatalog())
    selector.queue(SESSION, _choice(associated={"reasoning": "high"}), source="session-override")
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_REFUSED          # old value not silently used
    assert "not applied" in resolution.reason

    selector = NextTurnSelector(FakeHarness(config_options={}), FakeCatalog())
    selector.queue(SESSION, _choice(associated={"reasoning": "high"}), source="session-override")
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_REFUSED          # option disappeared
    assert "disappeared" in resolution.reason


def test_incomplete_choice_is_a_refusal():
    selector = NextTurnSelector(FakeHarness(), FakeCatalog())
    selector.queue(SESSION, {"harnessId": "codex"}, source="session-override")
    resolution = selector.resolve_next_turn(SESSION)
    assert resolution.outcome == OUTCOME_REFUSED
    assert resolution.prompt_allowed is False


def test_incomplete_session_reference_refuses():
    selector = NextTurnSelector(FakeHarness(), FakeCatalog())
    with pytest.raises(KeyError):
        selector.queue({"serverInstanceId": "srv-1"}, _choice(), source="session-override")
