# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_override_semantics.py, verbatim)
"""US-6: facet revision propagation vs session overrides vs profile switch.

The product scenario, as data-in/facts-out semantics: profile P (model +
another control) is shared by sessions A and B; A temporarily overrides the
model; P's global revision then changes model AND the other control. A keeps
its own model but takes P's new value for the other control; B takes both new
values; an explicit switch of A to another profile clears A's temporary
overrides entirely.
"""
from __future__ import annotations

from ordessa_model_provider_profile import (
    EffectiveChoiceResolver, SessionOverrides,
)

SESSION_A = {"serverInstanceId": "srv-1", "harnessId": "codex", "acpSessionId": "sess-A"}
SESSION_B = {"serverInstanceId": "srv-1", "harnessId": "codex", "acpSessionId": "sess-B"}

PROFILE_P_REVISION_1 = {"model": "cfg-1/m1", "permissions": "default"}
PROFILE_P_REVISION_2 = {"model": "cfg-2/m2", "permissions": "restricted"}


def _resolver():
    return EffectiveChoiceResolver(SessionOverrides())


def test_a_keeps_own_model_and_takes_p_new_other_control_b_takes_both():
    resolver = _resolver()
    resolver.overrides.set(SESSION_A, "model", "cfg-1/m1")
    # P's global revision moves to revision 2 (new model + new permission)
    assert resolver.effective(SESSION_A, PROFILE_P_REVISION_2) == {
        "model": "cfg-1/m1",             # A's temporary override survives
        "permissions": "restricted",     # the other control follows P's latest
    }
    assert resolver.effective(SESSION_B, PROFILE_P_REVISION_2) == {
        "model": "cfg-2/m2", "permissions": "restricted",  # B follows both
    }


def test_explicit_profile_switch_clears_all_session_overrides():
    resolver = _resolver()
    resolver.overrides.set(SESSION_A, "model", "cfg-1/m1")
    resolver.overrides.set(SESSION_A, "permissions", "custom")
    assert resolver.switch_profile(SESSION_A) is True
    assert resolver.effective(SESSION_A, PROFILE_P_REVISION_1) == PROFILE_P_REVISION_1
    assert resolver.switch_profile(SESSION_A) is False  # nothing left to clear


def test_overrides_do_not_leak_between_sessions_or_servers():
    resolver = _resolver()
    resolver.overrides.set(SESSION_A, "model", "cfg-1/m1")
    other_server = {"serverInstanceId": "srv-2", "harnessId": "codex", "acpSessionId": "sess-A"}
    assert resolver.overrides.get(SESSION_B) == {}
    assert resolver.overrides.get(other_server) == {}
    assert resolver.effective(SESSION_B, PROFILE_P_REVISION_1)["model"] == "cfg-1/m1"
