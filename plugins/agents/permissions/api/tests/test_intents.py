"""T01 red/green: an intent may only narrow (FR-01, FR-07, FR-10)."""
from __future__ import annotations

import pytest

from ordessa_permissions_api import (
    BrandMode,
    PermissionIntent,
    PolicyRefusal,
    RuleAction,
    Scope,
    TypedRule,
)


def record(**overrides: object) -> dict:
    base: dict = {
        "intentId": "profile-balanced",
        "revision": 2,
        "harnessId": "claude-code",
        "scope": "user",
        "desiredMode": "default",
        "rules": [
            {"key": "read", "pattern": None, "action": "allow"},
            {"key": "bash", "pattern": "git push*", "action": "ask"},
        ],
    }
    base.update(overrides)
    return base


def test_an_intent_keeps_its_own_revision_harness_and_typed_rules() -> None:
    intent = PermissionIntent.from_record(record())
    assert intent.revision == 2
    assert intent.harness_id == "claude-code"
    assert intent.scope is Scope.USER
    assert [r.action for r in intent.rules] == [RuleAction.ALLOW, RuleAction.ASK]
    assert intent.revision_digest == "profile-balanced@2"


def test_the_desired_native_mode_is_kept_per_brand_not_translated() -> None:
    intent = PermissionIntent.from_record(record())
    assert intent.desired_mode == BrandMode.declare("claude-code", "default")
    # the intent never turns a brand name into an interpretation result
    assert not isinstance(intent.desired_mode, RuleAction)


def test_unknown_record_key_is_refused() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PermissionIntent.from_record(record(defaultAction="allow"))
    assert exc.value.code == "PERMISSION_INTENT_INVALID"


def test_rules_may_be_given_as_typed_objects_or_mappings() -> None:
    by_object = PermissionIntent.of(intent_id="i", revision=1, harness_id="claude-code",
                                    scope="session",
                                    rules=[TypedRule.of(key="read", action="allow")])
    by_mapping = PermissionIntent.from_record(record(scope="session"))
    assert by_object.rules[0].action is RuleAction.ALLOW
    assert by_mapping.rules[1].action is RuleAction.ASK


def test_a_session_intent_cannot_carry_a_project_or_user_rule() -> None:
    # Cross-scope promotion: the low-trust input must not speak for a
    # higher-trust rule, whatever the caller intended.
    for scope in ("project", "user", "admin"):
        with pytest.raises(PolicyRefusal) as exc:
            PermissionIntent.from_record(record(
                scope="session",
                rules=[{"key": "bash", "pattern": None, "action": "allow", "scope": scope}],
            ))
        assert exc.value.code == "POLICY_SCOPE_UNVERIFIED"


def test_a_user_intent_may_narrow_within_a_project_rule_but_not_above_itself() -> None:
    ok = PermissionIntent.from_record(record(
        scope="user",
        rules=[{"key": "bash", "pattern": None, "action": "deny", "scope": "project"}],
    ))
    assert ok.rules[0].scope is Scope.PROJECT
    with pytest.raises(PolicyRefusal):
        PermissionIntent.from_record(record(
            scope="project",
            rules=[{"key": "bash", "pattern": None, "action": "deny", "scope": "user"}],
        ))


def test_the_harness_id_and_the_desired_mode_brand_must_be_the_same_family() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PermissionIntent.from_record(record(harnessId="codex", desiredMode="default"))
    assert exc.value.code == "PERMISSION_MODE_UNSUPPORTED"
    # a claude mode is never accepted as a codex mode just because it is short
    with pytest.raises(PolicyRefusal) as exc2:
        PermissionIntent.from_record(record(harnessId="codex", desiredMode="bypassPermissions"))
    assert exc2.value.code == "PERMISSION_MODE_UNSUPPORTED"


def test_revision_must_be_a_positive_integer_and_harness_id_non_empty() -> None:
    for bad in (0, -3, "2", None):
        with pytest.raises(PolicyRefusal) as exc:
            PermissionIntent.from_record(record(revision=bad))
        assert exc.value.code == "PERMISSION_INTENT_INVALID"
    with pytest.raises(PolicyRefusal) as exc:
        PermissionIntent.from_record(record(harnessId=""))
    assert exc.value.code == "PERMISSION_INTENT_INVALID"


def test_an_empty_rule_set_is_legal_but_is_not_an_open_field() -> None:
    intent = PermissionIntent.from_record(record(rules=[]))
    assert intent.rules == ()
    assert not intent.is_permissive_for("bash", "git push")


def test_is_permissive_for_reports_only_what_the_intent_explicitly_allows() -> None:
    intent = PermissionIntent.from_record(record())
    assert intent.is_permissive_for("read", "src/app.ts")
    assert not intent.is_permissive_for("bash", "ls")


def test_duplicate_identical_rules_are_refused_as_a_shape_error() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PermissionIntent.from_record(record(rules=[
            {"key": "bash", "pattern": None, "action": "deny"},
            {"key": "bash", "pattern": None, "action": "deny"},
        ]))
    assert exc.value.code == "PERMISSION_INTENT_INVALID"


def test_an_intent_can_never_carry_a_ceiling_shaped_field() -> None:
    for forbidden in ("maximumExposure", "deny", "requireApproval", "signed"):
        with pytest.raises(PolicyRefusal) as exc:
            PermissionIntent.from_record(record(**{forbidden: True}))
        assert exc.value.code == "PERMISSION_INTENT_INVALID"
