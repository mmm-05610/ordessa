"""The administrator ceiling: an upper bound that cannot be widened.

A ceiling is only constructible from a trusted-source record. Absence of one is
modelled, not implied: `CeilingSource.UNVERIFIED` means "no limit is known",
which is the opposite of "no limit applies", and the synthesis layer refuses any
decision that needs enforcement on it.

Several ceilings **intersect**: denials and approval requirements accumulate and
the exposure bound takes the strictest member, so no ordering can relax one
(FR-01).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping, Sequence

from .codes import PolicyRefusal, RefusalCode, probe
from .rules import Scope, TargetMatcher, ToolIdentity, _text

__all__ = [
    "CeilingEntry",
    "CeilingSource",
    "EffectiveCeiling",
    "ExposureLevel",
    "PolicyCeiling",
    "TOOL_EXPOSURE",
    "intersect_ceilings",
]

_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {"policyId", "scope", "revision", "source", "signed", "deny", "requireApproval",
     "maximumExposure", "effectiveFrom"})
_ENTRY_FIELDS: Final[frozenset[str]] = frozenset({"key", "pattern", "action"})
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
#: A ceiling speaks for user-level policy or above; a session record never can.
_CEILING_MIN_SCOPE_RANK: Final[int] = Scope.USER.rank
_ACTION_ALIASES: Final[Mapping[str, str]] = {
    "ask": "require-approval", "requireApproval": "require-approval",
    "require-approval": "require-approval",
}


class ExposureLevel(str, Enum):
    """How far an allowed operation may reach; a higher rank is a broader reach."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    EXEC = "exec"
    FULL = "full"

    @property
    def rank(self) -> int:
        return {"none": 0, "read": 1, "write": 2, "network": 3, "exec": 4, "full": 5}[self.value]

    @classmethod
    def of(cls, value: Any) -> "ExposureLevel":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_CEILING_INVALID", source="ceilings.ExposureLevel.of",
                                target=probe(value)) from None


#: Which exposure an `allow` on a key implies, used to test it against a ceiling.
TOOL_EXPOSURE: Final[Mapping[str, ExposureLevel]] = {
    "read": ExposureLevel.READ,
    "edit": ExposureLevel.WRITE,
    "external_directory": ExposureLevel.WRITE,
    "webfetch": ExposureLevel.NETWORK,
    "bash": ExposureLevel.EXEC,
    "task": ExposureLevel.EXEC,
    "skill": ExposureLevel.EXEC,
}


class CeilingSource(str, Enum):
    """Where a ceiling record came from; anything unverified is not a ceiling."""

    SIGNED_ADMIN = "signed-admin"
    HOST_TRUSTED = "host-trusted"
    UNVERIFIED = "unverified"


_TRUSTED_SOURCES: Final[frozenset[str]] = frozenset(
    {CeilingSource.SIGNED_ADMIN.value, CeilingSource.HOST_TRUSTED.value})


@dataclass(frozen=True)
class CeilingEntry:
    """One restriction of a ceiling: a hard denial or an approval requirement."""

    tool: ToolIdentity
    action: str
    target: TargetMatcher | None = None

    @classmethod
    def of(cls, key: Any, *, pattern: Any = None, action: Any = "deny") -> "CeilingEntry":
        normalized = _ACTION_ALIASES.get(action, action) if isinstance(action, str) else action
        if normalized not in ("deny", "require-approval"):
            # An `allow` has no place in a ceiling: that would be a widening.
            raise PolicyRefusal("PERMISSION_CEILING_INVALID", source="ceilings.CeilingEntry.of",
                                target=probe(action))
        matcher = None if pattern is None else TargetMatcher.glob(pattern)
        return cls(tool=ToolIdentity(_text(key, code=RefusalCode.PERMISSION_UNKNOWN_TOOL.value,
                                           source="ceilings.CeilingEntry.of")),
                   action=normalized, target=matcher)

    @classmethod
    def from_mapping(cls, raw: Any, *, list_kind: str, source: str) -> "CeilingEntry":
        """Read one entry; it may only carry the restriction its list declares."""
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_CEILING_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        extra = set(raw) - _ENTRY_FIELDS
        if extra:
            raise PolicyRefusal("PERMISSION_CEILING_INVALID", source=source,
                               target=",".join(sorted(extra)))
        declared = raw.get("action") or list_kind
        entry = cls.of(raw.get("key"), pattern=raw.get("pattern"), action=declared)
        if entry.action != list_kind:
            raise PolicyRefusal("PERMISSION_CEILING_INVALID", source=source,
                                target=f"a {list_kind} list cannot hold {entry.action}")
        return entry

    @property
    def is_denial(self) -> bool:
        return self.action == "deny"

    def matches(self, tool: str, target: str | None) -> bool:
        if self.tool.key != tool:
            return False
        if self.target is None:
            return True
        return self.target.matches(target)


def _timestamp(value: Any, *, source: str) -> dt.datetime:
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_CEILING_INVALID", source=source,
                                target="unparseable effectiveFrom") from None
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PolicyRefusal("PERMISSION_CEILING_INVALID", source=source,
                            target=None if value is None else type(value).__name__)
    return value


@dataclass(frozen=True)
class PolicyCeiling:
    """One versioned upper bound from a trusted source."""

    policy_id: str
    scope: Scope
    revision: int
    source: CeilingSource
    signed: bool
    hard_denies: tuple[CeilingEntry, ...]
    require_approval: tuple[CeilingEntry, ...]
    maximum_exposure: ExposureLevel
    effective_from: dt.datetime
    verified: bool = True

    @classmethod
    def from_record(cls, raw: Any) -> "PolicyCeiling":
        source = "ceilings.PolicyCeiling.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_CEILING_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        extra = set(raw) - _RECORD_FIELDS
        if extra:
            raise PolicyRefusal("PERMISSION_CEILING_INVALID", source=source,
                               target="unknown ceiling fields: " + ",".join(sorted(extra)))
        policy_id = _text(raw.get("policyId"), code="PERMISSION_CEILING_INVALID",
                          source=f"{source}.policyId")
        revision = raw.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise PolicyRefusal("PERMISSION_CEILING_INVALID", source=f"{source}.revision",
                                target=repr(revision))
        denies = tuple(
            CeilingEntry.from_mapping(item, list_kind="deny", source=f"{source}.deny")
            for item in _entry_sequence(raw.get("deny"), field="deny"))
        approvals = tuple(
            CeilingEntry.from_mapping(item, list_kind="require-approval",
                                      source=f"{source}.requireApproval")
            for item in _entry_sequence(raw.get("requireApproval"), field="requireApproval"))
        ceiling = cls(
            policy_id=policy_id, scope=_scope(raw.get("scope")), revision=revision,
            source=_source(raw.get("source")), signed=raw.get("signed") is True,
            hard_denies=denies, require_approval=approvals,
            maximum_exposure=ExposureLevel.of(raw.get("maximumExposure")),
            effective_from=_timestamp(raw.get("effectiveFrom"), source=f"{source}.effectiveFrom"),
        )
        # Provenance is checked after the shape so a malformed record is reported
        # as malformed; an unusable one is still never read as "no limit".
        if not ceiling.is_trusted:
            raise PolicyRefusal(RefusalCode.POLICY_SCOPE_UNVERIFIED,
                                source=f"{source} (provenance)", target=policy_id)
        return ceiling

    @classmethod
    def unverified(cls, policy_id: str) -> "PolicyCeiling":
        """The explicit 'no trusted record' ceiling; never a permissive default."""
        return cls(
            policy_id=_text(policy_id, code="PERMISSION_CEILING_INVALID",
                            source="ceilings.PolicyCeiling.unverified"),
            scope=Scope.ADMIN, revision=0, source=CeilingSource.UNVERIFIED, signed=False,
            hard_denies=(), require_approval=(), maximum_exposure=ExposureLevel.FULL,
            effective_from=_EPOCH, verified=False,
        )

    @property
    def scope_rank(self) -> int:
        return self.scope.rank

    @property
    def is_trusted(self) -> bool:
        return (self.verified and self.signed
                and self.source.value in _TRUSTED_SOURCES
                and self.scope_rank >= _CEILING_MIN_SCOPE_RANK)

    @property
    def revision_digest(self) -> str:
        return f"{self.policy_id}@{self.revision}"

    def blocks(self, tool: str, target: str | None) -> bool:
        return any(entry.matches(tool, target) for entry in self.hard_denies)

    def requires_approval(self, tool: str, target: str | None) -> bool:
        return any(entry.matches(tool, target) for entry in self.require_approval)

    @property
    def all_entries(self) -> tuple[CeilingEntry, ...]:
        return self.hard_denies + self.require_approval


def _scope(value: Any) -> Scope:
    # An unparseable scope keeps the lowest trust, which the provenance check
    # then refuses; it never defaults to ADMIN.
    try:
        return Scope.of(value)
    except PolicyRefusal:
        return Scope.SESSION


def _source(value: Any) -> CeilingSource:
    if isinstance(value, CeilingSource):
        return value
    if not isinstance(value, str) or value not in {item.value for item in CeilingSource}:
        # An absent or invented provenance is unverified, not "host default".
        raise PolicyRefusal(RefusalCode.POLICY_SCOPE_UNVERIFIED, source="ceilings.source",
                            target=probe(value))
    return CeilingSource(value)


def _entry_sequence(value: Any, *, field: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise PolicyRefusal("PERMISSION_CEILING_INVALID", source=f"ceilings.{field}",
                            target=type(value).__name__)
    return tuple(value)


@dataclass(frozen=True)
class EffectiveCeiling:
    """The intersection of every ceiling in force, as one non-widenable bound."""

    is_trusted: bool
    revision_digest: str
    entries_denied: tuple[CeilingEntry, ...]
    entries_require_approval: tuple[CeilingEntry, ...]
    maximum_exposure: ExposureLevel

    def blocks(self, tool: str, target: str | None) -> bool:
        return any(entry.matches(tool, target) for entry in self.entries_denied)

    def requires_approval(self, tool: str, target: str | None) -> bool:
        return any(entry.matches(tool, target) for entry in self.entries_require_approval)


def _entry_key(entry: CeilingEntry) -> tuple[str, str, str]:
    return (entry.tool.key, entry.action, entry.target.pattern if entry.target else "")


def intersect_ceilings(ceilings: Sequence[PolicyCeiling]) -> EffectiveCeiling:
    """Intersect every ceiling in force. Empty input is a missing provider."""
    items = list(ceilings)
    if not items:
        raise PolicyRefusal(RefusalCode.POLICY_ADAPTER_MISSING,
                            source="ceilings.intersect_ceilings")
    for ceiling in items:
        if not isinstance(ceiling, PolicyCeiling):
            raise PolicyRefusal("PERMISSION_CEILING_INVALID",
                                source="ceilings.intersect_ceilings",
                                target=type(ceiling).__name__)
    denied = tuple(sorted((entry for item in items for entry in item.hard_denies),
                          key=_entry_key))
    approval = tuple(sorted((entry for item in items for entry in item.require_approval),
                            key=_entry_key))
    exposure = min((item.maximum_exposure for item in items), key=lambda item: item.rank)
    members = "+".join(sorted({item.revision_digest for item in items}))
    return EffectiveCeiling(
        is_trusted=all(item.is_trusted for item in items),
        revision_digest=members,
        entries_denied=denied,
        entries_require_approval=approval,
        maximum_exposure=exposure,
    )
