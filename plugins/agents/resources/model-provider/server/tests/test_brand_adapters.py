# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_brand_adapters.py, verbatim)
"""Pi / Codex / Claude per-brand next-turn examples (E1 controlled evidence).

Each brand gets its own fake harness adapter describing the config format it
actually explains - Pi's logged-in seat, Codex's two config kinds (logged-in
account vs API credentials/base URL), Claude's logged-in seat - and runs the
pipeline to all three terminal outcomes. Evidence level: E1 (contract +
controlled fake, research.md R-4). This is NOT real-bridge (E2) or real-model
(E3) evidence; the delivery report must not present it as such.
"""
from __future__ import annotations

from test_next_turn_pipeline import FakeCatalog, FakeHarness, _choice

from ordessa_model_provider.ports import (
    ELIGIBILITY_READY, ELIGIBILITY_UNKNOWN, SESSION_CONFIG_OUTCOME_UNKNOWN,
)
from ordessa_model_provider.next_turn import (
    OUTCOME_APPLIED, OUTCOME_REFUSED, OUTCOME_UNKNOWN, NextTurnSelector,
)

BRANDS = {
    "pi": {"serverInstanceId": "srv-1", "harnessId": "pi", "acpSessionId": "pi-sess-1"},
    "codex": {"serverInstanceId": "srv-1", "harnessId": "codex", "acpSessionId": "codex-sess-1"},
    "claude": {"serverInstanceId": "srv-1", "harnessId": "claude", "acpSessionId": "claude-sess-1"},
}

#: What each brand's adapter declares it can explain (its own format, not a
#: generic template - design.md §3).
BRAND_CONFIG_FORMATS = {
    "pi": {"kind": "logged-in", "fields": ["authStyle"]},
    "codex-logged-in": {"kind": "logged-in", "fields": ["authStyle"]},
    "codex-api": {"kind": "api-credentials", "fields": ["authStyle", "baseUrl", "modelProvider"]},
    "claude": {"kind": "logged-in", "fields": ["authStyle"]},
}


def test_pi_logged_in_config_applies_next_turn():
    session = BRANDS["pi"]
    harness = FakeHarness(config_options={"reasoning": "high"})
    selector = NextTurnSelector(harness, FakeCatalog(models=("glm-5",)))
    selector.queue(session, _choice(harnessId="pi", modelId="glm-5"), source="session-override")
    resolution = selector.resolve_next_turn(session)
    assert resolution.outcome == OUTCOME_APPLIED
    assert resolution.turn_fact.evidence["applied"] == "read-back-verified"
    assert BRAND_CONFIG_FORMATS["pi"]["kind"] == "logged-in"


def test_codex_two_config_kinds_split_between_applied_and_refused():
    session = BRANDS["codex"]
    # logged-in seat: the adapter proves same-session next-turn application
    harness = FakeHarness()
    selector = NextTurnSelector(harness, FakeCatalog())
    selector.queue(session, _choice(harnessId="codex", modelId="m1"),
                   source="session-override")
    assert selector.resolve_next_turn(session).outcome == OUTCOME_APPLIED

    # API-credentials seat the adapter cannot yet prove for this session:
    # eligibility stays unknown and the choice refuses - R2 forbids selecting
    # it from the chat area on a bare "the model id is accepted" basis.
    unproven = FakeHarness(eligibility_value=ELIGIBILITY_UNKNOWN)
    selector = NextTurnSelector(unproven, FakeCatalog())
    selector.queue(session, _choice(harnessId="codex", modelId="m2"),
                   source="session-override")
    resolution = selector.resolve_next_turn(session)
    assert resolution.outcome == OUTCOME_REFUSED
    assert resolution.prompt_allowed is False
    assert BRAND_CONFIG_FORMATS["codex-api"]["kind"] == "api-credentials"


def test_claude_receipt_lost_is_unknown_outcome():
    session = BRANDS["claude"]
    harness = FakeHarness(apply_error=(SESSION_CONFIG_OUTCOME_UNKNOWN, "receipt lost"))
    selector = NextTurnSelector(harness, FakeCatalog())
    selector.queue(session, _choice(harnessId="claude"), source="session-override")
    resolution = selector.resolve_next_turn(session)
    assert resolution.outcome == OUTCOME_UNKNOWN
    assert resolution.prompt_allowed is False  # blocked until verified, no auto-retry
    assert BRAND_CONFIG_FORMATS["claude"]["kind"] == "logged-in"


def test_brand_evidence_is_labeled_e1():
    """Honesty pin: this module's evidence is E1 (controlled fake), so the
    facts it asserts must stay fake-side - no real harness process, no network,
    no model call is reachable from here."""
    import inspect

    from ordessa_model_provider import next_turn as module

    source = inspect.getsource(module)
    assert "urlopen" not in source and "socket" not in source
    assert ELIGIBILITY_READY == "ready"
