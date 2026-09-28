"""T012: read-only import of legacy Profile permission rules as USER INTENT.

The legacy engine (`ordessa_server_compat.profiles.permissions`, mirrored here
as stored-data vocabulary only - this package never imports it) resolves rules
**last-match-wins**: a later `allow` reverses an earlier `deny`. The new engine
is strictly-ordered (deny > ask > allow at equal priority, order irrelevant),
so that pair is NOT provably equivalent and the migrator must say so: the
entry is marked `needsReview`, kept out of the intent, and therefore resolves
to ask/deny - never to an imported allow. Everything else the task freezes:

* fidelity: the stored values are returned untouched and the legacy rows are
  never mutated or deleted (reversible read-back);
* ceiling: the migration never fabricates a `PolicyCeiling` and never derives
  an admin bound from profile data (unverified is not "no limit");
* idempotency: importing twice yields the same intent revision and digest.
"""
from __future__ import annotations

import json

import pytest
from support import admin_ceiling, clock_at, seeded_database, seed_session, utc

from ordessa_permissions_api import Denied, PendingApproval, PermissionIntent
from ordessa_permissions_backend import Authorizer
from ordessa_permissions_backend.facts import ApprovalFacts
from ordessa_permissions_backend.migration import LegacyProfileRulesMigration
from ordessa_permissions_backend.policies import PolicyRepository


def profile_row(profile_id: str = "profile-1", *, preset="default", rules=None,
                harness="pi"):
    rules_json = (None if rules is None else
                  (rules if isinstance(rules, str) else json.dumps(rules)))
    return {"id": profile_id, "harness_type": harness, "permission_preset": preset,
            "permission_rules_json": rules_json}


def migration(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    facts = ApprovalFacts(database)
    facts.ensure_schema()
    policies = PolicyRepository(database)
    policies.ensure_schema()
    return database, facts, policies, LegacyProfileRulesMigration(policies)


def review_reasons(plan):
    return [(item.index, item.reason) for item in plan.needs_review]


def actions(intent):
    return tuple(rule.action.value for rule in intent.rules) if intent else ()


# -- vocabulary and shape ---------------------------------------------------------

def test_legacy_vocabulary_is_mirrored_exactly():
    from ordessa_permissions_backend import migration as migration_module

    assert migration_module.LEGACY_TOOL_KEYS == (
        "read", "edit", "bash", "task", "external_directory", "webfetch", "skill")
    assert migration_module.LEGACY_ACTIONS == ("allow", "ask", "deny")
    assert migration_module.LEGACY_PRESET_ACTIONS == {
        "full-access": "allow", "default": "ask", "plan": "ask"}
    assert migration_module.LEGACY_PRESET_RULES["plan"] == (
        ("edit", None, "deny"), ("bash", None, "deny"), ("external_directory", None, "deny"))
    assert migration_module.MAX_LEGACY_RULES == 64


def test_equivalent_rules_import_as_user_intent(tmp_path):
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(rules=[
        {"key": "read", "action": "allow"},
        {"key": "read", "pattern": "/etc/*", "action": "deny"},
    ]))
    assert plan.needs_review == ()
    assert plan.imported_indices == (0, 1)
    assert actions(plan.intent) == ("allow", "deny")
    assert plan.intent.scope.value == "user"
    assert plan.intent.harness_id == "pi"
    assert plan.intent.intent_id == "legacy-profile:profile-1"
    assert plan.intent.revision == 1


def test_denial_after_allow_imports_both_strictest_wins(tmp_path):
    # legacy: last match (deny) wins. new: strictest wins (deny). Equivalent.
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(rules=[
        {"key": "bash", "action": "allow"},
        {"key": "bash", "action": "deny"},
    ]))
    assert plan.needs_review == ()
    assert actions(plan.intent) == ("allow", "deny")


# -- the deny-reversal case: needsReview, never allow ------------------------------

def test_deny_reversal_is_needs_review_and_never_resolves_to_allow(tmp_path):
    database, facts, policies, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(rules=[
        {"key": "bash", "action": "deny"},
        {"key": "bash", "action": "allow"},   # legacy last-match-wins would flip this
    ]))
    assert [item.index for item in plan.needs_review] == [1]
    assert "revers" in plan.needs_review[0].reason.lower()
    assert plan.imported_indices == (0,)
    assert actions(plan.intent) == ("deny",)

    # and live proof at the authorizer: with the imported intent in force, the
    # old engine's "allow" answer comes out ask/deny, never AllowedOnce.
    policies.store_ceiling(admin_ceiling())
    result = mig.import_profile(profile_row(rules=[
        {"key": "bash", "action": "deny"},
        {"key": "bash", "action": "allow"},
    ]))
    assert result.intent is not None
    authorizer = Authorizer(
        facts=facts, policies=policies,
        ceiling_provider=policies.ceilings_current,
        intent_provider=lambda: policies.intent_current("legacy-profile:profile-1"),
        clock=clock_at(utc()))
    outcome = authorizer.evaluate(
        principal="user-1",
        session_ref={"serverInstanceId": "srv-1", "sessionId": "session-1",
                     "nativeSessionId": "native-1"},
        execution_ref="turn-1", native_generation="1", tool_identity="bash",
        target_facts={"target": None},
        argument_digest="a" * 64,
        ceiling_revision=policies.ceilings_current()[0].revision_digest,
        policy_revision=result.intent.revision_digest,
        native_request_id="native-x")
    assert not hasattr(outcome, "grant"), f"legacy reversal leaked an allow: {outcome}"
    assert isinstance(outcome, (Denied, PendingApproval))
    del database


def test_ask_reversed_by_later_allow_is_also_needs_review(tmp_path):
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(rules=[
        {"key": "edit", "action": "ask"},
        {"key": "edit", "action": "allow"},
    ]))
    assert [item.index for item in plan.needs_review] == [1]


def test_unmatched_pattern_rules_still_flag_the_loosening_match(tmp_path):
    # Globs can overlap in ways no order can prove disjoint; the conservative
    # reading flags the later looser rule for the same key regardless of the
    # pattern, because last-match-wins would let it reverse the earlier deny
    # on any target both patterns match.
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(rules=[
        {"key": "bash", "pattern": "rm *", "action": "deny"},
        {"key": "bash", "pattern": "git *", "action": "allow"},
    ]))
    assert [item.index for item in plan.needs_review] == [1]


# -- entries that are not provably equivalent --------------------------------------

def test_unknown_key_and_action_and_shape_are_needs_review(tmp_path):
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(rules=[
        {"key": "web-search", "action": "allow"},
        {"key": "bash", "action": "yolo"},
        {"key": "bash", "action": "allow", "extra": True},
        "not-a-rule",
    ]))
    assert {item.index for item in plan.needs_review} == {0, 1, 2, 3}
    assert plan.imported_indices == ()
    assert actions(plan.intent) == ()


def test_wildcard_only_pattern_is_needs_review(tmp_path):
    # The legacy engine accepted "*"; the typed model refuses a pattern with
    # no bounded literal, so the entry cannot be imported losslessly.
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(rules=[{"key": "bash", "pattern": "*", "action": "ask"}]))
    assert [item.index for item in plan.needs_review] == [0]
    assert "pattern" in plan.needs_review[0].reason.lower()


def test_malformed_rules_json_is_needs_review_not_a_crash(tmp_path):
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(rules="{not json"))
    assert plan.needs_review[0].index is None
    assert plan.imported_indices == ()
    plan2 = mig.analyze(profile_row(rules={"key": "bash", "action": "allow"}))
    assert plan2.needs_review[0].index is None


def test_rules_above_the_legacy_cap_are_refused(tmp_path):
    _, _, _, mig = migration(tmp_path)
    rules = [{"key": "read", "pattern": f"/etc/path{i}", "action": "deny"}
             for i in range(65)]
    plan = mig.analyze(profile_row(rules=rules))
    assert plan.intent is None or actions(plan.intent) == ()
    assert any(item.index is None for item in plan.needs_review)


# -- presets ------------------------------------------------------------------------

def test_default_and_plan_presets_are_equivalent_and_need_no_review(tmp_path):
    _, _, _, mig = migration(tmp_path)
    assert mig.analyze(profile_row(preset="default", rules=[])).needs_review == ()
    plan = mig.analyze(profile_row(preset="plan", rules=[]))
    assert plan.needs_review == ()
    # plan's expansion denies are carried into the intent (fallback ask alone
    # would be looser than the legacy deny posture)
    assert actions(plan.intent) == ("deny", "deny", "deny")
    assert {rule.tool.key for rule in plan.intent.rules} == {
        "edit", "bash", "external_directory"}


def test_full_access_preset_is_needs_review_and_never_fabricates_an_allow(tmp_path):
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(preset="full-access", rules=[
        {"key": "read", "action": "allow"}]))
    preset_items = [item for item in plan.needs_review if item.index is None]
    assert preset_items and "full-access" in preset_items[0].reason
    # the explicit user rule is still importable intent; the preset fallback
    # posture (allow-all) is NOT - no wildcard rule was invented for it.
    assert actions(plan.intent) == ("allow",)
    assert [rule.tool.key for rule in plan.intent.rules] == ["read"]


def test_plan_preset_deny_reversed_by_user_allow_is_needs_review(tmp_path):
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(preset="plan", rules=[
        {"key": "bash", "action": "allow"}]))
    # the flagged entry is the user's stored rule at index 0 (the preset's
    # expansion sits ahead of it in the legacy evaluation order)
    assert [item.index for item in plan.needs_review] == [0]
    assert actions(plan.intent).count("deny") == 3
    assert "allow" not in actions(plan.intent)


def test_unknown_preset_is_needs_review(tmp_path):
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(preset="turbo", rules=[]))
    assert any(item.index is None and "preset" in item.reason.lower()
               for item in plan.needs_review)


# -- ceilings are never derived from profile data ------------------------------------

def test_import_never_fabricates_a_ceiling(tmp_path):
    _, _, policies, mig = migration(tmp_path)
    mig.import_profile(profile_row(preset="full-access", rules=[
        {"key": "bash", "action": "allow"}]))
    assert policies.ceilings_current() == ()
    plan = mig.analyze(profile_row(rules=[{"key": "bash", "action": "deny"}]))
    assert plan.ceiling_created is False


# -- idempotency, reversibility, fidelity ---------------------------------------------

def test_import_is_idempotent_in_revision_and_digest(tmp_path):
    _, _, policies, mig = migration(tmp_path)
    row = profile_row(rules=[{"key": "read", "action": "allow"},
                             {"key": "edit", "action": "deny"}])
    first = mig.import_profile(row)
    second = mig.import_profile(row)
    assert first.intent_digest == second.intent_digest
    assert first.intent.revision == second.intent.revision == 1
    assert len(policies.intent_history("legacy-profile:profile-1")) == 1
    # the stored intent reads back as a valid typed intent
    stored = policies.intent_current("legacy-profile:profile-1")
    assert isinstance(stored, PermissionIntent)
    assert stored.rules == first.intent.rules


def test_changed_legacy_values_reimport_as_a_new_revision(tmp_path):
    _, _, policies, mig = migration(tmp_path)
    first = mig.import_profile(profile_row(rules=[{"key": "read", "action": "deny"}]))
    second = mig.import_profile(profile_row(rules=[{"key": "read", "action": "ask"}]))
    assert second.intent.revision == 2
    assert first.intent_digest != second.intent_digest
    assert len(policies.intent_history("legacy-profile:profile-1")) == 2


def test_import_is_read_only_and_reversible_against_the_stored_row(tmp_path):
    database, _, _, mig = migration(tmp_path)
    with database.transaction() as conn:
        conn.execute("UPDATE server_profiles SET permission_preset=?, "
                     "permission_rules_json=? WHERE id=?",
                     ("plan", json.dumps([{"key": "bash", "action": "allow"}],
                                         sort_keys=False), "profile-1"))
    before = _read_row(database, "profile-1")
    result = mig.import_from_store(lambda pid: _read_row(database, pid), "profile-1")
    after = _read_row(database, "profile-1")
    assert before == after  # legacy values untouched: no mutation, no deletion
    assert result.original == {"permission_preset": before["permission_preset"],
                               "permission_rules_json": before["permission_rules_json"]}
    read_back = mig.read_back(lambda pid: _read_row(database, pid), "profile-1")
    assert read_back == result.original


def _read_row(database, profile_id):
    with database.read() as conn:
        row = conn.execute("SELECT id, harness_type, permission_preset,"
                           " permission_rules_json FROM server_profiles WHERE id=?",
                           (profile_id,)).fetchone()
    return None if row is None else dict(row)


def test_import_from_store_refuses_a_missing_row_without_fabricating(tmp_path):
    _, _, policies, mig = migration(tmp_path)
    with pytest.raises(KeyError):
        mig.import_from_store(lambda pid: None, "profile-ghost")
    assert policies.intent_current("legacy-profile:profile-ghost") is None


def test_missing_harness_id_is_needs_review(tmp_path):
    _, _, _, mig = migration(tmp_path)
    plan = mig.analyze(profile_row(harness="", rules=[{"key": "read", "action": "allow"}]))
    assert plan.intent is None
    assert any(item.index is None and "harness" in item.reason.lower()
               for item in plan.needs_review)
