"""The §C1 result shapes: support reports, intent sets, refusals, verify kinds.

`unsupported` and `unknown` never merge (contracts §C4); a refusal is a value,
not an exception, so the caller can show it *before* anything has an effect;
and a compiled intent set carries its own digest so a later verification can
bind to the exact bytes it was compiled to.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Union

from .codes import ADAPTER_REMEDIES, AdapterCode

__all__ = [
    "CompiledIntentSet",
    "CompileRefusal",
    "CompileResult",
    "SupportOutcome",
    "SupportReport",
    "VerifyOutcome",
    "VerifyResult",
]

_TEXT_OK = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")


def _checked_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or _TEXT_OK.fullmatch(value) is None or not value.strip():
        raise ValueError(f"{field_name} must be bounded single-line printable text")
    return value


class SupportOutcome(str, Enum):
    """The three support answers. They are *not* interchangeable."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SupportReport:
    outcome: SupportOutcome
    reason: str = ""
    code: AdapterCode | None = None
    evidence: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, SupportOutcome):
            raise ValueError("SupportReport.outcome must be a SupportOutcome")
        object.__setattr__(self, "reason", _checked_text(self.reason or "-",
                                                         field_name="reason"))
        if self.outcome is SupportOutcome.SUPPORTED:
            # a green answer without named evidence is exactly the
            # "unknown marked green" the success criteria forbid
            if not self.evidence:
                raise ValueError("a supported answer must name its evidence")
        elif self.code is None:
            raise ValueError("unsupported/unknown answers must carry a stable code")

    @classmethod
    def supported(cls, *, evidence: str, reason: str = "capability measured in-tree"
                  ) -> "SupportReport":
        return cls(outcome=SupportOutcome.SUPPORTED, reason=reason, evidence=evidence)

    @classmethod
    def unsupported(cls, *, code: AdapterCode, reason: str) -> "SupportReport":
        return cls(outcome=SupportOutcome.UNSUPPORTED, code=code, reason=reason)

    @classmethod
    def unknown(cls, *, code: AdapterCode, reason: str) -> "SupportReport":
        return cls(outcome=SupportOutcome.UNKNOWN, code=code, reason=reason)


def _normalize_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        name = _checked_text(key, field_name="field name")
        if isinstance(value, (list, tuple, set, frozenset)):
            items = tuple(sorted(_checked_text(item, field_name=f"{name}[]")
                                 for item in value))
            if not items:
                raise ValueError(f"compiled field {name!r} must not be emitted empty")
            out[name] = items
        elif isinstance(value, str):
            out[name] = _checked_text(value, field_name=name)
        else:
            raise ValueError(f"compiled field {name!r} carries an unrenderable value")
    return out


@dataclass(frozen=True)
class CompiledIntentSet:
    """Native-expressible fields a brand can be asked to honour, frozen."""

    harness_id: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    intent_revision: str | None = None
    ceiling_revision: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "harness_id",
                           _checked_text(self.harness_id, field_name="harness_id"))
        object.__setattr__(self, "fields", _normalize_fields(self.fields))
        object.__setattr__(self, "notes", tuple(
            _checked_text(note, field_name="note") for note in self.notes))
        digest = hashlib.sha256(json.dumps(
            {"harness": self.harness_id,
             "fields": {k: (list(v) if isinstance(v, tuple) else v)
                        for k, v in sorted(self.fields.items())},
             "notes": list(self.notes)},
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        object.__setattr__(self, "_digest", digest)

    @property
    def outcome(self) -> str:
        return "intent-set"

    @property
    def digest(self) -> str:
        return self._digest

    def as_record(self) -> dict[str, Any]:
        return {key: (list(value) if isinstance(value, tuple) else value)
                for key, value in self.fields.items()}


@dataclass(frozen=True)
class CompileRefusal:
    """A typed refusal: stable code, source, target and remedy (§C4, FR-09)."""

    code: AdapterCode
    source: str
    target: str | None = None
    remedy: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, AdapterCode):
            raise ValueError("CompileRefusal.code must be an AdapterCode")
        object.__setattr__(self, "source", _checked_text(self.source, field_name="source"))
        if self.target is not None:
            object.__setattr__(self, "target", _checked_text(self.target,
                                                             field_name="target"))
        object.__setattr__(self, "remedy",
                           self.remedy if self.remedy is not None
                           else ADAPTER_REMEDIES[self.code])
        if self.remedy is not None:
            object.__setattr__(self, "remedy", _checked_text(self.remedy,
                                                             field_name="remedy"))

    @property
    def outcome(self) -> str:
        return "refusal"

    @property
    def human_readable(self) -> str:
        parts = [f"source={self.source}"]
        if self.target:
            parts.append(f"target={self.target}")
        parts.append(f"remedy={self.remedy}")
        return f"{self.code.value}: " + "; ".join(parts)


CompileResult = Union[CompiledIntentSet, CompileRefusal]


class VerifyOutcome(str, Enum):
    """`Confirmed` only for a bound, oracle-covered, receipted observation."""

    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class VerifyResult:
    outcome: VerifyOutcome
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, VerifyOutcome):
            raise ValueError("VerifyResult.outcome must be a VerifyOutcome")
        object.__setattr__(self, "reason", _checked_text(self.reason or "-",
                                                         field_name="reason"))

    @classmethod
    def confirmed(cls, reason: str = "observation matches the compiled fields"
                  ) -> "VerifyResult":
        return cls(outcome=VerifyOutcome.CONFIRMED, reason=reason)

    @classmethod
    def unknown(cls, reason: str) -> "VerifyResult":
        return cls(outcome=VerifyOutcome.UNKNOWN, reason=reason)

    @classmethod
    def mismatch(cls, reason: str) -> "VerifyResult":
        return cls(outcome=VerifyOutcome.MISMATCH, reason=reason)
