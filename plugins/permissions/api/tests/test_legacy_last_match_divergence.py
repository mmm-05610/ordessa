"""T01 red/green: the legacy last-match-wins engine diverges (FR-10).

Two things must both be true, and the pair is the migration record:

1. the legacy resolver really does let a *later* `allow` reverse an *earlier*
   `deny` - asserted so a future change cannot be mistaken for the semantics
   our migrator has to cope with;
2. the new `synthesize` refuses that same widening.

`ordessa_server_compat` is imported only here (see
``test_permissions_api_dependency_direction``), and the new engine is imported inside the test
bodies on purpose: pre-implementation this file must still prove the legacy
behaviour while the new assertions go red, instead of the whole module erroring
out at collection.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
LEGACY_SRC = REPO_ROOT / "plugins" / "server-compat" / "src"
NOW = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
HEX = "c" * 64


@pytest.fixture(scope="module")
def legacy_permissions():
    """The legacy resolver, reached through the repo tree it lives in."""
    if str(LEGACY_SRC) not in sys.path:
        sys.path.insert(0, str(LEGACY_SRC))
    from ordessa_server_compat.profiles import permissions  # noqa: PLC0415
    assert str(pathlib.Path(permissions.__file__).resolve()).startswith(str(LEGACY_SRC))
    return permissions


def widening_rule_list() -> list[dict]:
    return [
        {"key": "bash", "pattern": None, "action": "deny"},
        {"key": "bash", "pattern": None, "action": "allow"},
    ]


def ceiling_record(**overrides: object) -> dict:
    base: dict = {
        "policyId": "admin-migrated", "scope": "admin", "revision": 1,
        "source": "signed-admin", "signed": True, "deny": [], "requireApproval": [],
        "maximumExposure": "full", "effectiveFrom": "2026-09-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def migrated_intent(rules: list[dict], **overrides: object):
    from ordessa_permissions_api import PermissionIntent

    base: dict = {
        "intentId": "migrated-profile", "revision": 1, "harnessId": "claude-code",
        "scope": "user", "desiredMode": "default", "rules": rules,
    }
    base.update(overrides)
    return PermissionIntent.from_record(base)


def op_request(ceiling, intent, tool_key: str, target: str | None):
    """A request whose revision pins are derived from the objects in force."""
    from ordessa_permissions_api import build_operation_request

    return build_operation_request(
        principal="user-1", server_instance_id="srv-1", session_id="sess-1",
        native_session_id="chan-9", execution_id="exec-1", native_generation="gen-3",
        tool_key=tool_key, target=target, argument_digest=HEX,
        native_request_id="nat-legacy-1", ceilings=[ceiling], intent=intent)


def test_legacy_tool_key_vocabulary_is_the_one_we_must_migrate_not_reinvent(
        legacy_permissions) -> None:
    assert set(legacy_permissions.TOOL_KEYS) == {
        "read", "edit", "bash", "task", "external_directory", "webfetch", "skill"}
    assert set(legacy_permissions.ACTIONS) == {"allow", "ask", "deny"}


def test_legacy_last_match_wins_does_let_a_later_allow_reverse_an_earlier_deny(
        legacy_permissions) -> None:
    # This is the behaviour the ceiling model exists to refuse (FR-10).
    assert legacy_permissions.resolve(widening_rule_list(), key="bash", target="rm -rf /") \
        == "allow"


def test_legacy_ordering_alone_flips_the_answer_for_the_same_rule_set(
        legacy_permissions) -> None:
    reversed_rules = list(reversed(widening_rule_list()))
    assert legacy_permissions.resolve(reversed_rules, key="bash", target="rm -rf /") == "deny"


def test_the_new_engine_refuses_the_same_widening_that_legacy_allowed(legacy_permissions) -> None:
    from ordessa_permissions_api import (
        PolicyCeiling,
        PolicySynthesized,
        RuleAction,
        synthesize,
    )

    ceiling = PolicyCeiling.from_record(ceiling_record())
    intent = migrated_intent(widening_rule_list())
    assert legacy_permissions.resolve(widening_rule_list(), key="bash", target="rm -rf /") \
        == "allow"
    result = synthesize(ceilings=[ceiling], intent=intent,
                        request=op_request(ceiling, intent, "bash", "rm -rf /"), now=NOW)
    assert isinstance(result, PolicySynthesized)
    assert result.action is RuleAction.DENY


def test_the_new_engine_refuses_a_ceiling_widening_the_legacy_engine_cannot_see(
        legacy_permissions) -> None:
    from ordessa_permissions_api import PolicyCeiling, PolicySynthesized, synthesize

    rules = [{"key": "edit", "pattern": "/etc/passwd", "action": "deny"},
             {"key": "edit", "pattern": "/etc/passwd", "action": "allow"}]
    assert legacy_permissions.resolve(rules, key="edit", target="/etc/passwd") == "allow"
    ceiling = PolicyCeiling.from_record(
        ceiling_record(policyId="admin-hard", deny=[{"key": "edit", "pattern": "/etc/*"}]))
    intent = migrated_intent(rules)
    result = synthesize(ceilings=[ceiling], intent=intent,
                        request=op_request(ceiling, intent, "edit", "/etc/passwd"), now=NOW)
    assert isinstance(result, PolicySynthesized)
    assert result.action.value == "deny"
    assert result.decision.reason.code.value == "POLICY_CEILING_VIOLATION"


def test_a_migrated_rule_list_never_widens_a_require_approval_ceiling(
        legacy_permissions) -> None:
    from ordessa_permissions_api import (
        PolicyCeiling,
        PolicySynthesized,
        RuleAction,
        synthesize,
    )

    rules = [{"key": "bash", "pattern": None, "action": "allow"}]
    assert legacy_permissions.resolve(rules, key="bash", target="git push") == "allow"
    ceiling = PolicyCeiling.from_record(
        ceiling_record(policyId="admin-approval", revision=4,
                       requireApproval=[{"key": "bash"}]))
    intent = migrated_intent(rules)
    result = synthesize(ceilings=[ceiling], intent=intent,
                        request=op_request(ceiling, intent, "bash", "git push"), now=NOW)
    assert isinstance(result, PolicySynthesized)
    assert result.action is not RuleAction.ALLOW
    assert result.action is RuleAction.ASK


def test_a_migrated_preset_is_posture_never_authority(legacy_permissions) -> None:
    # `full-access` in the legacy store is a starting posture, not a widening
    # an importer may carry across as policy.
    assert legacy_permissions.PRESET_ACTIONS["full-access"] == "allow"
    from ordessa_permissions_api import PermissionIntent, PolicyRefusal, SCHEMA_CODES

    assert "PERMISSION_INTENT_INVALID" in SCHEMA_CODES
    with pytest.raises(PolicyRefusal) as exc:
        PermissionIntent.from_record({
            "intentId": "migrated-preset", "revision": 1, "harnessId": "claude-code",
            "scope": "user", "desiredMode": "default", "preset": "full-access", "rules": [],
        })
    assert exc.value.code == "PERMISSION_INTENT_INVALID"
