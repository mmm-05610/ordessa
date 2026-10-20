"""Typed rules, target matchers and the administrator exception authority.

A rule is a value object: it is either well shaped or it is refused, and
refusal is never coercion. Three properties carry the whole security argument:

* the tool-key vocabulary is closed, so a typo cannot read as "no rule";
* a pattern must name a bounded target - an absent or wildcard-shaped pattern is
  never widened into "everything";
* ordering cannot widen either: an `allow` that sits above a stricter rule is an
  exception and needs a verifiable `AdminAuthorization` bound to that exact
  operation, ceiling revision and expiry.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatchcase
from typing import Any, Final, Mapping, Sequence

from .codes import PolicyRefusal, RefusalCode, probe

__all__ = [
    "AdminAuthorization",
    "MAX_PRIORITY",
    "MAX_RULES",
    "RuleAction",
    "Scope",
    "TOOL_KEYS",
    "TargetMatcher",
    "ToolIdentity",
    "TypedRule",
    "known_tool_keys",
]

#: The tool keys the product's reference names. The set is closed: a key that is
#: not here is refused, because "no rule for it" and "a typo for another key"
#: must not look the same. This is the same vocabulary the legacy store used, so
#: migration inputs stay readable (FR-10).
TOOL_KEYS: Final[tuple[str, ...]] = (
    "read", "edit", "bash", "task", "external_directory", "webfetch", "skill",
)
MAX_RULES: Final[int] = 64
MAX_PRIORITY: Final[int] = 32
_RULE_FIELDS: Final[frozenset[str]] = frozenset(
    {"key", "pattern", "action", "priority", "scope", "authorization"})
_AUTHORITY_FIELDS: Final[frozenset[str]] = frozenset(
    {"issuer", "subject", "target", "ceilingRevision", "verified", "expiresAt"})
#: A glob is bounded printable text: command patterns carry spaces and quotes, so
#: only control characters and unbounded length are refused.
_PATTERN_OK = re.compile(r"[^\x00-\x1f\x7f]{1,128}\Z")
_TEXT_OK = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")
_METACHARS = "*?[]\\"
_METACHAR_EDGES: Final[tuple[str, ...]] = ("*", "?", "[", "]", "\\")


def known_tool_keys() -> tuple[str, ...]:
    """The closed rule vocabulary, in declaration order."""
    return TOOL_KEYS


def _text(value: Any, *, code: str, source: str) -> str:
    if not isinstance(value, str) or _TEXT_OK.fullmatch(value) is None or not value.strip():
        raise PolicyRefusal(code, source=source, target=probe(value))
    return value


class RuleAction(str, Enum):
    """Ordessa's interpretation layer only - never a brand's mode name (FR-03)."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"

    @property
    def strictness(self) -> int:
        return {"allow": 1, "ask": 2, "deny": 3}[self.value]

    @classmethod
    def of(cls, value: Any) -> "RuleAction":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_ACTION_UNSUPPORTED",
                                source="rules.RuleAction.of", target=probe(value)) from None


class Scope(str, Enum):
    """Where a rule claims to come from; rank is trust, not breadth."""

    SESSION = "session"
    PROJECT = "project"
    USER = "user"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return {"session": 1, "project": 2, "user": 3, "admin": 4}[self.value]

    @classmethod
    def of(cls, value: Any, *, source: str = "rules.Scope.of") -> "Scope":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_RULE_INVALID", source=source,
                                target=probe(value)) from None


@dataclass(frozen=True)
class TargetMatcher:
    """A bounded target pattern. `is_generic` marks the prefix globs that can only
    restrict, never except."""

    pattern: str = field()

    def __post_init__(self) -> None:
        if not isinstance(self.pattern, str) or _PATTERN_OK.fullmatch(self.pattern) is None:
            raise PolicyRefusal("PERMISSION_PATTERN_INVALID", source="rules.TargetMatcher",
                                target=probe(self.pattern))
        if not _has_bounded_literal(self.pattern):
            raise PolicyRefusal("PERMISSION_PATTERN_INVALID",
                                source="rules.TargetMatcher (no literal target)",
                                target=probe(self.pattern))

    @classmethod
    def glob(cls, pattern: Any) -> "TargetMatcher":
        return cls(pattern)

    @property
    def is_generic(self) -> bool:
        """A pattern that only bounds a prefix/suffix, e.g. `/etc/*`."""
        if "**" in self.pattern:
            return True
        return self.pattern.startswith(_METACHAR_EDGES) or self.pattern.endswith(
            _METACHAR_EDGES)

    def matches(self, target: str | None) -> bool:
        if target is None:
            # A pattern rule cannot speak about a target it was not given.
            return False
        return fnmatchcase(target, self.pattern)

    def __str__(self) -> str:
        return self.pattern


def _has_bounded_literal(pattern: str) -> bool:
    if not pattern.strip():
        return False
    longest = 0
    run = 0
    for char in pattern:
        if char in _METACHARS or char.isspace():
            longest = max(longest, run)
            run = 0
        else:
            run += 1
    return max(longest, run) >= 2


@dataclass(frozen=True)
class ToolIdentity:
    """One declared tool key."""

    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or self.key not in TOOL_KEYS:
            raise PolicyRefusal(RefusalCode.PERMISSION_UNKNOWN_TOOL,
                                source="rules.ToolIdentity", target=probe(self.key))

    @classmethod
    def of(cls, key: Any) -> "ToolIdentity":
        return cls(key)


@dataclass(frozen=True)
class AdminAuthorization:
    """A verifiable administrator authorization for one narrow exception.

    It unlocks an *intent-internal* exception only; it can never widen a
    ceiling, and an unverifiable or foreign object is refused here rather than
    trusted at decision time.
    """

    issuer: str
    subject: str
    target: str
    ceiling_revision: str
    expires_at: dt.datetime

    @classmethod
    def of(cls, *, issuer: Any, subject: Any, target: Any, ceiling_revision: Any,
           verified: Any, expires_at: Any) -> "AdminAuthorization":
        return cls.from_record({"issuer": issuer, "subject": subject, "target": target,
                                "ceilingRevision": ceiling_revision, "verified": verified,
                                "expiresAt": expires_at})

    @classmethod
    def from_record(cls, raw: Any) -> "AdminAuthorization":
        source = "authority.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        extra = set(raw) - _AUTHORITY_FIELDS
        if extra:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target=",".join(sorted(extra)))
        if raw.get("verified") is not True:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID",
                                source=f"{source} (signature not verified)",
                                target=str(raw.get("issuer")))
        ToolIdentity(_text(raw.get("subject"), code=RefusalCode.PERMISSION_UNKNOWN_TOOL.value,
                           source=f"{source}.subject"))
        return cls(
            issuer=_text(raw.get("issuer"), code="PERMISSION_AUTHORIZATION_INVALID",
                         source=f"{source}.issuer"),
            subject=raw.get("subject"),
            target=_text(raw.get("target"), code="PERMISSION_AUTHORIZATION_INVALID",
                         source=f"{source}.target"),
            ceiling_revision=_text(raw.get("ceilingRevision"),
                                   code="PERMISSION_AUTHORIZATION_INVALID",
                                   source=f"{source}.ceilingRevision"),
            expires_at=_aware_timestamp(raw.get("expiresAt"), source=f"{source}.expiresAt"),
        )

    def covers(self, *, tool: str, target: str | None, ceiling_revision: str,
               now: dt.datetime) -> bool:
        """Verbatim scope match only: no prefix reading, no wildcard widening."""
        if self.expires_at <= now:
            return False
        if self.subject != tool or self.ceiling_revision != ceiling_revision:
            return False
        return target is not None and self.target == target


def _aware_timestamp(value: Any, *, source: str) -> dt.datetime:
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target="unparseable timestamp") from None
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                            target=None if value is None else type(value).__name__)
    return value


@dataclass(frozen=True)
class TypedRule:
    """One rule: a tool identity, an optional bounded matcher, one action."""

    tool: ToolIdentity
    action: RuleAction
    target: TargetMatcher | None = None
    priority: int = 0
    scope: Scope = Scope.SESSION
    authorization: AdminAuthorization | None = None

    @classmethod
    def of(cls, *, key: Any, action: Any, pattern: Any = None, priority: Any = 0,
           scope: Any = Scope.SESSION,
           authorization: Any = None) -> "TypedRule":
        tool = ToolIdentity(_text(key, code=RefusalCode.PERMISSION_UNKNOWN_TOOL.value,
                                  source="rules.TypedRule.of"))
        parsed_action = RuleAction.of(action)
        matcher = None if pattern is None else TargetMatcher.glob(pattern)
        return cls(tool=tool, action=parsed_action, target=matcher,
                   priority=_priority(priority), scope=Scope.of(scope),
                   authorization=_authorization(authorization, action=parsed_action,
                                                matcher=matcher, priority=priority))

    @classmethod
    def from_mapping(cls, raw: Any, *, index: int | None = None) -> "TypedRule":
        source = f"rules.TypedRule.from_mapping(index={index})" if index is not None \
            else "rules.TypedRule.from_mapping"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_RULE_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        extra = set(raw) - _RULE_FIELDS
        if extra:
            raise PolicyRefusal("PERMISSION_RULE_INVALID", source=source,
                                target="unknown rule fields: " + ",".join(sorted(extra)))
        for required in ("key", "action"):
            if raw.get(required) is None:
                raise PolicyRefusal("PERMISSION_RULE_INVALID", source=source,
                                    target=f"missing {required}")
        authorization = raw.get("authorization")
        if isinstance(authorization, Mapping):
            authorization = AdminAuthorization.from_record(authorization)
        return cls.of(key=raw.get("key"), action=raw.get("action"), pattern=raw.get("pattern"),
                      priority=raw.get("priority", 0), scope=raw.get("scope", Scope.SESSION),
                      authorization=authorization)

    @classmethod
    def from_many(cls, rules: Any) -> tuple["TypedRule", ...]:
        if isinstance(rules, (str, bytes)) or not isinstance(rules, Sequence):
            raise PolicyRefusal("PERMISSION_RULE_INVALID", source="rules.TypedRule.from_many",
                                target=None if rules is None else type(rules).__name__)
        if len(rules) > MAX_RULES:
            raise PolicyRefusal("PERMISSION_RULE_INVALID", source="rules.TypedRule.from_many",
                                target=f"at most {MAX_RULES} rules")
        built: list[TypedRule] = []
        for index, raw in enumerate(rules):
            if isinstance(raw, TypedRule):
                built.append(raw)
            else:
                built.append(cls.from_mapping(raw, index=index))
        return tuple(built)

    @property
    def exception(self) -> bool:
        return self.authorization is not None

    def matches(self, target: str | None) -> bool:
        if self.target is None:
            return True
        return self.target.matches(target)

    def matches_tool(self, tool_key: str) -> bool:
        return self.tool.key == tool_key


def _priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_PRIORITY:
        raise PolicyRefusal("PERMISSION_RULE_INVALID", source="rules.TypedRule.priority",
                            target=None if value is None else repr(value))
    return value


def _authorization(value: Any, *, action: RuleAction, matcher: TargetMatcher | None,
                   priority: Any) -> AdminAuthorization | None:
    if value is None:
        if action is RuleAction.ALLOW and isinstance(priority, int) and priority > 0:
            # A higher-priority allow is an exception over a stricter rule; the
            # order alone never authorises it.
            raise PolicyRefusal("PERMISSION_RULE_INVALID",
                                source="rules.TypedRule (priority widening needs authority)",
                                target=f"priority={priority}")
        return None
    if not isinstance(value, AdminAuthorization):
        raise PolicyRefusal("PERMISSION_RULE_INVALID", source="rules.TypedRule.authorization",
                            target=type(value).__name__)
    if matcher is None or matcher.is_generic:
        raise PolicyRefusal("PERMISSION_RULE_INVALID",
                            source="rules.TypedRule (a generic pattern cannot except)",
                            target=None if matcher is None else matcher.pattern)
    return value
