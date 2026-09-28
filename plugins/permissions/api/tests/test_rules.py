"""T01 red/green: strong typing of a single rule (FR-01, FR-09, FR-10).

Every case here is a *refusal* expectation: the rule layer must never coerce,
never widen a missing field into a wildcard, and never read a typo as "no
rule".
"""
from __future__ import annotations

import dataclasses

import pytest

from ordessa_permissions_api import (
    PolicyRefusal,
    RuleAction,
    Scope,
    TargetMatcher,
    ToolIdentity,
    TypedRule,
    known_tool_keys,
)


def _code(exc: PolicyRefusal) -> str:
    return exc.code


# --- closed vocabulary ------------------------------------------------------

def test_tool_key_vocabulary_is_closed_and_matches_the_legacy_reference_names() -> None:
    assert set(known_tool_keys()) == {
        "read", "edit", "bash", "task", "external_directory", "webfetch", "skill",
    }


def test_unknown_tool_key_is_refused_typed_never_read_as_no_rule() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.of(key="Bash", action="allow")
    assert _code(exc.value) == "PERMISSION_UNKNOWN_TOOL"


def test_tool_identity_accepts_a_declared_key_only() -> None:
    assert ToolIdentity.of("bash").key == "bash"
    with pytest.raises(PolicyRefusal) as exc:
        ToolIdentity.of("mcp__whatever")
    assert _code(exc.value) == "PERMISSION_UNKNOWN_TOOL"


@pytest.mark.parametrize("action", ["allow", "ask", "deny"])
def test_rule_action_accepts_the_three_interpretation_results(action: str) -> None:
    assert RuleAction.of(action) is RuleAction(action)


@pytest.mark.parametrize("value", ["yolo", "auto", "plan", "bypassPermissions",
                                   "untrusted", "on-failure", "ALLOW", ""])
def test_brand_mode_names_are_never_rule_actions(value: str) -> None:
    # FR-03: `allow/ask/deny` are Ordessa's interpretation layer only; a
    # brand-native mode name must never be coerced into one.
    with pytest.raises(PolicyRefusal) as exc:
        RuleAction.of(value)
    assert _code(exc.value) == "PERMISSION_ACTION_UNSUPPORTED"


def test_rule_strictness_order_is_deny_over_ask_over_allow() -> None:
    assert RuleAction.DENY.strictness > RuleAction.ASK.strictness
    assert RuleAction.ASK.strictness > RuleAction.ALLOW.strictness


# --- shape refusal ----------------------------------------------------------

def test_rule_of_builds_a_targetless_rule_with_the_lowest_trust_scope() -> None:
    rule = TypedRule.of(key="bash", action="deny")
    assert rule.target is None
    assert rule.scope is Scope.SESSION
    assert rule.priority == 0
    assert rule.action is RuleAction.DENY


def test_unknown_dict_key_is_refused_outright() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.from_mapping({"key": "bash", "action": "deny", "glob": "rm*"})
    assert _code(exc.value) == "PERMISSION_RULE_INVALID"
    assert "glob" in str(exc.value)


def test_missing_action_is_refused_not_defaulted() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.from_mapping({"key": "bash"})
    assert _code(exc.value) == "PERMISSION_RULE_INVALID"


@pytest.mark.parametrize("raw", [None, "bash", 7, ["key"], ("key",)])
def test_non_object_rule_is_refused(raw: object) -> None:
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.from_mapping(raw)
    assert _code(exc.value) == "PERMISSION_RULE_INVALID"


def test_pattern_must_be_text_never_a_coerced_number_or_regex_object() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.of(key="read", action="allow", pattern=17)
    assert _code(exc.value) == "PERMISSION_PATTERN_INVALID"
    with pytest.raises(PolicyRefusal) as exc2:
        TypedRule.of(key="read", action="allow", pattern=["*"])
    assert _code(exc2.value) == "PERMISSION_PATTERN_INVALID"


def test_action_must_be_one_of_three() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.of(key="bash", action="approve")
    assert _code(exc.value) == "PERMISSION_ACTION_UNSUPPORTED"


def test_priority_must_be_a_bounded_integer() -> None:
    assert TypedRule.of(key="bash", action="deny", priority=5).priority == 5
    for bad in (True, "5", 1.5, -1, 10_000, None):
        with pytest.raises(PolicyRefusal) as exc:
            TypedRule.of(key="bash", action="deny", priority=bad)  # type: ignore[arg-type]
        assert _code(exc.value) == "PERMISSION_RULE_INVALID"


def test_scope_must_be_a_declared_scope() -> None:
    assert TypedRule.of(key="bash", action="deny", scope="project").scope is Scope.PROJECT
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.of(key="bash", action="deny", scope="global")
    assert _code(exc.value) == "PERMISSION_RULE_INVALID"


def test_scope_trust_order_is_session_below_project_below_user_below_admin() -> None:
    assert Scope.SESSION.rank < Scope.PROJECT.rank < Scope.USER.rank < Scope.ADMIN.rank


def test_rule_set_is_bounded_in_size() -> None:
    rules = [TypedRule.of(key="read", action="allow", pattern=f"p/{i}") for i in range(64)]
    assert TypedRule.from_many(rules)
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.from_many(rules + [TypedRule.of(key="read", action="allow")])
    assert _code(exc.value) == "PERMISSION_RULE_INVALID"


def test_from_many_accepts_mappings_and_refuses_a_bare_string() -> None:
    parsed = TypedRule.from_many([{"key": "bash", "action": "ask"}])
    assert parsed[0].action is RuleAction.ASK
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.from_many("not-a-list")  # type: ignore[arg-type]
    assert _code(exc.value) == "PERMISSION_RULE_INVALID"


# --- target matcher ---------------------------------------------------------

def test_generic_wildcard_matcher_cannot_be_constructed() -> None:
    for pattern in ("*", "**", "?*", "*.*", "  "):
        with pytest.raises(PolicyRefusal) as exc:
            TargetMatcher.glob(pattern)
        assert _code(exc.value) == "PERMISSION_PATTERN_INVALID"


def test_matcher_is_bounded_printable_text() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        TargetMatcher.glob("bad\x00pattern")
    assert _code(exc.value) == "PERMISSION_PATTERN_INVALID"
    with pytest.raises(PolicyRefusal) as exc2:
        TargetMatcher.glob("x" * 200)
    assert _code(exc2.value) == "PERMISSION_PATTERN_INVALID"


def test_matcher_keeps_spaces_and_quotes_because_targets_are_commands() -> None:
    matcher = TargetMatcher.glob("rm -rf '/'")
    assert matcher.matches("rm -rf '/'")
    assert not matcher.matches("ls")


def test_specificity_flag_separates_a_named_target_from_a_prefix_glob() -> None:
    assert not TargetMatcher.glob("src/app.ts").is_generic
    assert TargetMatcher.glob("src/**").is_generic
    assert TargetMatcher.glob("/etc/*").is_generic


def test_a_targetless_rule_matches_anything_but_a_pattern_rule_never_invents_a_target() -> None:
    broad = TypedRule.of(key="bash", action="deny")
    narrow = TypedRule.of(key="bash", action="deny", pattern="git push*")
    assert broad.matches("anything at all")
    assert narrow.matches("git push origin main")
    assert not narrow.matches(None)
    assert not narrow.matches("git status")


def test_rules_are_immutable_values() -> None:
    rule = TypedRule.of(key="bash", action="deny")
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.action = RuleAction.ALLOW  # type: ignore[misc]
