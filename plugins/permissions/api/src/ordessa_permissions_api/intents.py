"""The configurable layer: a Profile's or session's *intent* (FR-01, FR-07).

An intent states what the user wants within the ceiling; it can only narrow. Two
refusals define that boundary:

* a rule may not claim a higher scope than the intent itself carries, so a
  session input cannot promote a project/user rule;
* the record has no field for ceiling vocabulary (`deny` lists,
  `maximumExposure`, `signed`), because an intent that could hold them could
  become one.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Final, Mapping

from .brand import BrandMode
from .codes import PolicyRefusal, RefusalCode
from .rules import RuleAction, Scope, TypedRule, _text

__all__ = ["NO_INTENT_REVISION", "PermissionIntent"]

_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {"intentId", "revision", "harnessId", "scope", "rules", "desiredMode"})
#: The revision pin an operation carries when no intent is in force. It is a
#: value, not an absence: `None` would read as "not checked".
NO_INTENT_REVISION: Final[str] = "no-intent"
_INTENT_SCOPES: Final[tuple[Scope, ...]] = (Scope.SESSION, Scope.PROJECT, Scope.USER)


@dataclass(frozen=True)
class PermissionIntent:
    """One versioned, harness-scoped set of typed rules."""

    intent_id: str
    revision: int
    harness_id: str
    scope: Scope
    rules: tuple[TypedRule, ...]
    desired_mode: BrandMode | None = None

    @classmethod
    def of(cls, *, intent_id: Any, revision: Any, harness_id: Any, scope: Any = Scope.SESSION,
           rules: Any = (), desired_mode: Any = None) -> "PermissionIntent":
        parsed_scope = Scope.of(scope, source="intents.PermissionIntent.of")
        if parsed_scope not in _INTENT_SCOPES:
            # Administrator authority belongs to a ceiling record, never here.
            raise PolicyRefusal("PERMISSION_INTENT_INVALID", source="intents.scope",
                                target=parsed_scope.value)
        parsed_rules = TypedRule.from_many(rules)
        for rule in parsed_rules:
            if rule.scope.rank > parsed_scope.rank:
                raise PolicyRefusal(
                    RefusalCode.POLICY_SCOPE_UNVERIFIED,
                    source=f"intents.PermissionIntent (scope {parsed_scope.value} cannot"
                           f" carry {rule.scope.value}-scope rules)",
                    target=f"{rule.tool.key}")
        return cls(
            intent_id=_text(intent_id, code="PERMISSION_INTENT_INVALID",
                             source="intents.intentId"),
            revision=_revision(revision),
            harness_id=_text(harness_id, code="PERMISSION_INTENT_INVALID",
                             source="intents.harnessId"),
            scope=parsed_scope, rules=parsed_rules, desired_mode=desired_mode,
        )

    @classmethod
    def from_record(cls, raw: Any) -> "PermissionIntent":
        source = "intents.PermissionIntent.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_INTENT_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        extra = set(raw) - _RECORD_FIELDS
        if extra:
            raise PolicyRefusal("PERMISSION_INTENT_INVALID", source=source,
                               target="unknown intent fields: " + ",".join(sorted(extra)))
        intent = cls.of(intent_id=raw.get("intentId"), revision=raw.get("revision"),
                        harness_id=raw.get("harnessId"), scope=raw.get("scope"),
                        rules=raw.get("rules") or ())
        seen: set[tuple[str, str, str, int, str]] = set()
        for rule in intent.rules:
            shape = (rule.tool.key,
                     rule.target.pattern if rule.target else "",
                     rule.action.value, rule.priority, rule.scope.value)
            if shape in seen:
                raise PolicyRefusal("PERMISSION_INTENT_INVALID", source=f"{source}.rules",
                                    target=f"duplicate rule {rule.tool.key}")
            seen.add(shape)
        # The shape is settled first, so a malformed intent reports as one; only
        # then is the brand name checked, against this intent's own harness.
        declared_mode = raw.get("desiredMode")
        mode = None if declared_mode in (None, "") else BrandMode.declare(
            intent.harness_id, declared_mode)
        return replace(intent, desired_mode=mode)

    @property
    def revision_digest(self) -> str:
        return f"{self.intent_id}@{self.revision}"

    def matching_rules(self, tool: str, target: str | None) -> tuple[TypedRule, ...]:
        return tuple(rule for rule in self.rules
                     if rule.matches_tool(tool) and rule.matches(target))

    def is_permissive_for(self, tool: str, target: str | None) -> bool:
        """Whether the intent, as written, allows this (tool, target) pair.

        This is a description of the intent only - it says nothing about a
        ceiling, and no caller may treat it as a decision.
        """
        from .synthesis import select_intent_action

        matched, _ = select_intent_action(self.rules, tool=tool, target=target)
        return matched is not None and matched is RuleAction.ALLOW


def _revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PolicyRefusal("PERMISSION_INTENT_INVALID", source="intents.revision",
                            target=repr(value))
    return value
