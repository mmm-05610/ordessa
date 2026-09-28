"""Facet shape (RA-5), whole-item override semantics and session isolation
counterexamples (RA-7).

RA-7's two-session discipline: different four-group preferences on two
sessions never interfere; an explicit profile switch clears all of that
session's overrides together; golden transcripts are byte-stable per
session.
"""
from __future__ import annotations

import json

import pytest

from ordessa_runtime_preferences import facet, keys, session


# -- RA-5: facet descriptor ------------------------------------------------------

def test_facet_has_exactly_the_four_atomic_items():
    descriptor = facet.facet_descriptor()
    assert descriptor.facet_id == "assets.runtime-preferences"
    assert descriptor.api_major == 1
    assert [item.item_id for item in descriptor.items] == list(keys.GROUPS)
    assert all(item.value_type == "atomic" for item in descriptor.items)
    for item in descriptor.items:
        assert item.value_keys == keys.CANONICAL_PARAMS[item.item_id]
        assert item.default == {}  # default = follow the harness's native defaults


def test_registration_manifest_carries_defaults_and_whole_item_semantics():
    manifest = facet.facet_registration_manifest()
    assert manifest["facetId"] == "assets.runtime-preferences"
    assert [item["id"] for item in manifest["items"]] == list(keys.GROUPS)
    for item in manifest["items"]:
        assert item["valueType"] == "atomic"
        assert item["default"] == {}
        assert item["sensitive"] is False


def test_editor_manifest_declares_the_addEditor_contribution():
    manifest = facet.editor_registration_manifest()
    assert manifest["kind"] == "profile-editor"
    assert manifest["facetId"] == "assets.runtime-preferences"
    assert manifest["componentKey"] == "ordessa.runtime-preferences/preferences-editor"
    assert manifest["category"] == "behavior"
    assert manifest["items"] == list(keys.GROUPS)
    # RA-4: admin-only entries arrive as disabled items with their reason
    shell_disabled = manifest["disabledItems"]["shell"]
    entries = {(entry["brand"], entry["nativeKey"]) for entry in shell_disabled}
    assert ("codex", "shell_environment_policy") in entries
    assert ("claude-code", "env") in entries
    assert ("qwen", "tools.executionSandbox") in entries
    for group_items in manifest["disabledItems"].values():
        for entry in group_items:
            assert entry["reason"].strip()


# -- RA-5: whole-item validation ---------------------------------------------------

def test_item_values_validate_against_the_closed_vocabulary():
    facet.validate_item_value("memory", {"enabled": True, "budgetTokens": 4096,
                                         "extractionModelRef": "acme/m1"})
    facet.validate_item_value("shell", {"envRefs": {"EDITOR": "ref://editor"}})
    facet.validate_item_value("compaction", {})  # empty = documented default


def test_provisioning_keys_are_structurally_invalid():
    """AR-5: the memory item is pure typed parameters — a service provisioning
    request has no key to travel in."""
    with pytest.raises(facet.FacetValueError):
        facet.validate_item_value("memory", {"enabled": True,
                                             "serverEndpoint": "http://localhost:8888"})
    with pytest.raises(facet.FacetValueError):
        facet.validate_item_value("memory", {"enabled": True, "apiKeyRef": "ref://x"})


def test_unknown_items_and_values_are_violations():
    violations = facet.validate_items({
        "compaction": {"enabled": True},
        "teleportation": {"enabled": True},
        "shell": {"envRefs": {"A": "plaintext"}},
        "memory": {"enabled": "yes"},
    })
    codes = {v.code for v in violations}
    assert codes == {"PROFILE_FACET_ITEM_UNKNOWN", "PROFILE_FACET_VALUE_INVALID"}
    assert len(violations) == 3


def test_bool_discipline_in_facet_values():
    with pytest.raises(facet.FacetValueError):
        facet.validate_item_value("memory", {"enabled": 1})
    with pytest.raises(facet.FacetValueError):
        facet.validate_item_value("compaction", {"thresholdPercent": True})


def test_memory_facet_contract_is_the_ar5_surface():
    contract = facet.memory_facet_contract()
    assert contract["facetId"] == "assets.runtime-preferences"
    assert contract["itemId"] == "memory"
    assert sorted(contract["keys"]) == ["budgetTokens", "enabled", "extractionModelRef"]
    assert "置备" in contract["provisioning"]


# -- RA-7: whole-item override + two-session isolation -----------------------------

A = {"serverId": "srv-1", "sessionId": "session-A"}
B = {"serverId": "srv-1", "sessionId": "session-B"}


def _resolver_with_overrides():
    resolver = session.EffectivePreferencesResolver()
    resolver.overrides.set(A, "compaction", {"enabled": True, "thresholdPercent": 80})
    resolver.overrides.set(A, "retry", {"maxRetries": 5, "baseDelayMs": 200})
    resolver.overrides.set(B, "compaction", {"enabled": False, "keepRecentTokens": 512})
    return resolver


def test_two_sessions_with_different_four_group_values_never_interfere():
    resolver = _resolver_with_overrides()
    a = resolver.effective(A, {})
    b = resolver.effective(B, {})
    # A's compaction and retry stay A's; B's compaction stays B's
    assert a["compaction"] == {"enabled": True, "thresholdPercent": 80}
    assert a["retry"] == {"maxRetries": 5, "baseDelayMs": 200}
    assert b["compaction"] == {"enabled": False, "keepRecentTokens": 512}
    assert "retry" not in b  # B never inherited A's retry override
    # mutations on one side never leak
    a["compaction"]["enabled"] = False
    assert resolver.effective(A, {})["compaction"]["enabled"] is True


def test_profile_items_are_the_baseline_and_overrides_win_per_item():
    resolver = _resolver_with_overrides()
    profile = {"memory": {"enabled": True, "budgetTokens": 100},
               "compaction": {"enabled": None}}
    a = resolver.effective(A, profile)
    assert a["memory"] == {"enabled": True, "budgetTokens": 100}  # profile value
    assert a["compaction"] == {"enabled": True, "thresholdPercent": 80}  # override wins


def test_override_replaces_the_whole_item_never_merges():
    resolver = session.EffectivePreferencesResolver()
    resolver.overrides.set(A, "compaction", {"enabled": True})
    resolver.overrides.set(A, "compaction", {"thresholdPercent": 50})
    assert resolver.effective(A, {})["compaction"] == {"thresholdPercent": 50}


def test_profile_switch_clears_all_overrides_together():
    resolver = _resolver_with_overrides()
    assert resolver.switch_profile(A) is True
    assert resolver.effective(A, {}) == {}
    # B's overrides survive A's switch (the switch is per session)
    assert resolver.effective(B, {})["compaction"] == {"enabled": False,
                                                       "keepRecentTokens": 512}
    assert resolver.switch_profile(A) is False  # nothing left to clear


def test_overrides_reject_invalid_items_at_the_gate():
    resolver = session.EffectivePreferencesResolver()
    from ordessa_runtime_preferences.facet import FacetValueError
    with pytest.raises(FacetValueError):
        resolver.overrides.set(A, "memory", {"enabled": True, "serverRef": "x"})
    with pytest.raises(FacetValueError):
        resolver.overrides.set(A, "unknown-item", {"enabled": True})
    assert resolver.effective(A, {}) == {}


def test_session_ref_incomplete_is_an_error_not_a_guess():
    resolver = session.EffectivePreferencesResolver()
    with pytest.raises(ValueError):
        resolver.overrides.set({"sessionId": "only"}, "memory", {"enabled": True})


# -- golden transcripts: byte-stable per session ----------------------------------

def test_golden_transcripts_are_byte_stable_per_session():
    resolver = _resolver_with_overrides()
    def transcript():
        return json.dumps({
            "A": resolver.effective(A, {"memory": {"enabled": True}}),
            "B": resolver.effective(B, {}),
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    first, second = transcript(), transcript()
    assert first == second
    assert first == (
        '{"A":{"compaction":{"enabled":true,"thresholdPercent":80},'
        '"memory":{"enabled":true},"retry":{"baseDelayMs":200,"maxRetries":5}},'
        '"B":{"compaction":{"enabled":false,"keepRecentTokens":512}}}'
    )
