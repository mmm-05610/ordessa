"""The §C2 result shapes: compiled intents, refusals, and the platform verdicts.

A refusal that this package *authors* is a value, never an exception, so the
caller can surface it before anything has an effect (contracts.md §C4, FR-09).
The assess and verify verdicts are NOT re-declared here any more: after the
``harness-api`` checkpoint this facet speaks the platform's own closed
vocabularies — ``ordessa_harness_api.contracts.Assessment``
(``supported``/``unsupported``/``unknown``) and ``Verification``
(``Match``/``Mismatch``/``VerificationUnknown``). The former local mirrors
(``AssessOutcome``/``AssessReport``/``VerifyOutcome``/``VerifyResult``) are
deleted: one vocabulary, no second spelling of the same tri-state.

§C4 still demands the sandbox *stable codes* (and forbids merging
``unsupported`` with ``unknown``). The platform result records carry a free
``reason`` and an ``evidence_ref`` instead of a code field, so the stable code
travels as the reason's prefix — the exact convention
``ordessa_sandbox_api.errors.SandboxApiError`` already uses
(``"SANDBOX_EFFECT_UNKNOWN: ..."``). :func:`sandbox_reason` writes it and
:func:`sandbox_code_of` reads it back, so the two verdicts stay two distinct,
machine-readable answers that also resolve to different wire families
(``ordessa_sandbox_api.wire_family``).

A compiled intent set must carry at least one field: an "intent-set" with
nothing in it would certify a vacuous apply, which the success criteria forbid.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Union

from ordessa_harness_api.contracts import Assessment, Match, Mismatch, \
    Verification, VerificationUnknown
from ordessa_harness_api.intents import IntentSet
from ordessa_sandbox_api import SandboxErrorCode

from .seam import CompiledFieldIntent

__all__ = [
    "ADAPTER_REMEDIES",
    "CompiledIntent",
    "CompileRefusal",
    "CompileResult",
    "assessment_supported",
    "assessment_unknown",
    "assessment_unsupported",
    "sandbox_code_of",
    "sandbox_reason",
    "unknown_verification",
    "unsupported_verification",
    "verification_match",
    "verification_mismatch",
]

_TEXT_OK = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")


def _checked_text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _TEXT_OK.fullmatch(value) is None or not value.strip():
        raise ValueError(f"{name} must be bounded single-line printable text")
    return value


#: human-readable remedies per stable code (§C4: source, target, fix suggestion)
ADAPTER_REMEDIES: Mapping[SandboxErrorCode, str] = {
    SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED:
        "the native surface cannot express this; keep the requirement under "
        "Permissions or choose a harness that covers it — never approximate",
    SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN:
        "narrow requiredCoverage to what this brand's sandbox actually covers",
    SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED:
        "this documented platform is out of the native sandbox's scope",
    SandboxErrorCode.SANDBOX_CONFIG_CONFLICT:
        "an administrator ceiling or a field-claim collision forbids this; a "
        "profile/user intent cannot widen it and no priority ordering resolves it",
    SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN:
        "re-probe / declare the affected sessions; an unverified sandbox is "
        "never treated as protected",
    SandboxErrorCode.SANDBOX_INTENT_INVALID:
        "correct the intent shape; unknown keys and wildcards are refused",
}


def sandbox_reason(code: SandboxErrorCode, reason: str) -> str:
    """A platform-result reason carrying the §C4 stable code as its prefix."""
    text = _checked_text(reason, name="reason")
    return _checked_text(f"{code.value}: {text}", name="reason")


def sandbox_code_of(text: str | None) -> SandboxErrorCode | None:
    """The stable code carried in a platform result's reason, or ``None``.

    Reading the code back is what keeps ``unsupported`` and ``unknown`` from
    merging now that the verdict type is the platform's: the two land in
    different wire families (`CAPABILITY_UNSUPPORTED` vs `OUTCOME_UNKNOWN`).
    """
    if not isinstance(text, str):
        return None
    head = text.split(":", 1)[0].strip()
    try:
        return SandboxErrorCode(head)
    except ValueError:
        return None


def unsupported_verification(code: SandboxErrorCode, reason: str) -> Verification:
    """A proven negative at the verification edge.

    ``Verification`` is the platform's closed trio and has no ``unsupported``
    member, so a documented limit is reported as ``VerificationUnknown`` whose
    reason carries the stable unsupported code (``Assessment`` — where the
    platform *does* have an ``unsupported`` status — stays the authoritative
    place for the capability verdict). The code prefix keeps it separable from
    a merely unobserved effect; neither is ever a ``Match``.
    """
    return VerificationUnknown(sandbox_reason(code, reason))


def unknown_verification(reason: str) -> Verification:
    return VerificationUnknown(sandbox_reason(
        SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN, reason))


@dataclass(frozen=True)
class CompiledIntent:
    """The native fields a brand can be asked to honour, as bound C3 seeds."""

    harness_id: str
    intents: tuple[CompiledFieldIntent, ...]
    sandbox_id: str = ""
    revision: int = 0
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "harness_id", _checked_text(self.harness_id, name="harness_id"))
        intents = tuple(self.intents)
        if not intents:
            raise ValueError("an intent-set must carry at least one compiled field")
        for item in intents:
            if not isinstance(item, CompiledFieldIntent):
                raise ValueError("CompiledIntent.intents must be CompiledFieldIntent values")
        object.__setattr__(self, "intents", intents)
        object.__setattr__(self, "notes", tuple(_checked_text(n, name="note") for n in self.notes))

    @property
    def outcome(self) -> str:
        return "intent-set"

    @property
    def field_paths(self) -> tuple[str, ...]:
        return tuple(f.field_path for f in self.intents)

    def to_harness_c3(self) -> IntentSet:
        """The real Harness C3 ``IntentSet`` for this compiled facet item.

        The platform DTOs validate their own shape, so an un-boundable field
        raises ``ordessa_harness_api.errors.ContractError`` here rather than
        producing a partial set.
        """
        return IntentSet(tuple(f.to_harness_c3() for f in self.intents))


@dataclass(frozen=True)
class CompileRefusal:
    """A typed compile refusal: stable code, source, target, remedy."""

    code: SandboxErrorCode
    source: str
    target: str | None = None
    remedy: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, SandboxErrorCode):
            raise ValueError("CompileRefusal.code must be a SandboxErrorCode")
        object.__setattr__(self, "source", _checked_text(self.source, name="source"))
        if self.target is not None:
            object.__setattr__(self, "target", _checked_text(self.target, name="target"))
        object.__setattr__(self, "remedy",
                           self.remedy if self.remedy is not None else ADAPTER_REMEDIES[self.code])

    @property
    def outcome(self) -> str:
        return "refusal"

    # a refusal is a refusal: it NEVER carries a compiled field, so a caller
    # cannot mistake a "success-shaped" object with nothing in it for progress.
    @property
    def emitted_intents(self) -> tuple[CompiledFieldIntent, ...]:
        return ()

    @property
    def intents(self) -> tuple[CompiledFieldIntent, ...]:
        return ()

    @property
    def reason(self) -> str:
        """The refusal in the platform reason convention (stable code prefix)."""
        return sandbox_reason(self.code, self.target or self.source)

    @property
    def human_readable(self) -> str:
        parts = [f"source={self.source}"]
        if self.target:
            parts.append(f"target={self.target}")
        parts.append(f"remedy={self.remedy}")
        return f"{self.code.value}: " + "; ".join(parts)


CompileResult = Union[CompiledIntent, CompileRefusal]


def assessment_supported(evidence: str, reason: str = "capability measured in-tree"
                         ) -> Assessment:
    return Assessment("supported", evidence_ref=evidence, reason=reason)


def assessment_unsupported(code: SandboxErrorCode, reason: str) -> Assessment:
    """A documented limit: the platform's ``unsupported`` status + stable code."""
    return Assessment("unsupported", reason=sandbox_reason(code, reason))


def assessment_unknown(code: SandboxErrorCode, reason: str) -> Assessment:
    """An unmeasured fact: the platform's ``unknown`` status + stable code.

    Never merged with ``unsupported`` — a missing probe is not a limit.
    """
    return Assessment("unknown", reason=sandbox_reason(code, reason))


def verification_match(evidence_ref: str) -> Match:
    return Match(evidence_ref=_checked_text(evidence_ref, name="evidence_ref"))


def verification_mismatch(code: SandboxErrorCode, reason: str) -> Mismatch:
    return Mismatch(sandbox_reason(code, reason))
