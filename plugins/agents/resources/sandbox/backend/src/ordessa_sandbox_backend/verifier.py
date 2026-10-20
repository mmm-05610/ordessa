"""SandboxVerifier — the backend half of `sandbox.native-configuration@1` (§C2).

FR-06 refuse-before-side-effect: `verify` is a pure gate. It consumes the
intent, the current pin/platform facts and the available evidence, and
answers one of `verified | unsupported | unknown | refused(code)` — without
applying, writing or spawning anything (the read-only `probe`/`target` seam
lives in `probe.py` and is UNBOUND until the harness-api checkpoint). The
caller must not commit a message or start a tool side effect unless the
verdict is VERIFIED.

The stable refusal codes come from `ordessa_sandbox_api` (contracts.md §C4),
and `unsupported` and `unknown` are never merged: the first means a proven
negative (absent adapter, a field the closed brand schema cannot express),
the second means "no evidence in this tree proves it" — pending T05 probes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from ordessa_sandbox_api import (
    CellStatus,
    NativeSandboxIntent,
    SandboxApiError,
    SandboxCeiling,
    SandboxErrorCode,
    SandboxEvidence,
    SandboxVerificationOutcome,
    check_cross_session_impact,
    check_platform_gate,
    check_within_ceiling,
    coverage_proves,
    matrix_cell,
)

from .catalogue import SandboxOptionCatalogue
from .probe import ConfigurationTarget, EffectObservation, EffectProbe
from .repository import NativeSandboxRepository, VerificationFacts


class VerdictKind(str, Enum):
    VERIFIED = "verified"
    #: a proven negative — the native surface cannot carry this (never
    #: merged with UNKNOWN, contracts.md §C4)
    UNSUPPORTED = "unsupported"
    #: not provable in this tree right now — fail closed, keep retrying
    #: after the T05 probe lands
    UNKNOWN = "unknown"
    #: a policy/config refusal (ceiling conflict, coverage gap, platform
    #: refusal) — also pre-effect
    REFUSED = "refused"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


@dataclass(frozen=True)
class SandboxVerdict:
    kind: VerdictKind
    code: SandboxErrorCode | None
    reason: str
    #: this package has no apply path; it is structurally always False
    effect_started: bool = False

    @property
    def refused_before_side_effect(self) -> bool:
        return self.kind is not VerdictKind.VERIFIED and not self.effect_started


_UNSUPPORTED_CODES = frozenset({
    SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
})
_REFUSED_CODES = frozenset({
    SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
    SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN,
    SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED,
    SandboxErrorCode.PROVIDER_BUSY,
    SandboxErrorCode.SANDBOX_INTENT_INVALID,
})


def _verdict_from_refusal(error: SandboxApiError) -> SandboxVerdict:
    code = error.code
    if code in _UNSUPPORTED_CODES:
        kind = VerdictKind.UNSUPPORTED
    elif code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN:
        kind = VerdictKind.UNKNOWN
    elif code in _REFUSED_CODES:
        kind = VerdictKind.REFUSED
    else:  # pragma: no cover - the API enum is closed
        kind = VerdictKind.REFUSED
    return SandboxVerdict(kind=kind, code=code, reason=error.message)


class SandboxVerifier:
    """Judges one intent against current facts; applies nothing."""

    def __init__(self, *, catalogue: SandboxOptionCatalogue | None = None,
                 admin_ceilings: Sequence[SandboxCeiling] = ()) -> None:
        self._catalogue = catalogue
        self._ceilings = tuple(admin_ceilings)

    def verify(self, intent: NativeSandboxIntent, live: VerificationFacts, *,
               evidence: Optional[SandboxEvidence] = None,
               repository: NativeSandboxRepository | None = None,
               target: ConfigurationTarget | None = None,
               probe: EffectProbe | None = None,
               admin_ceilings: Sequence[SandboxCeiling] = ()) -> SandboxVerdict:
        """Returns the verdict; the caller may only proceed on VERIFIED.

        Order encodes FR-06: every cheaper fail-closed gate runs before any
        evidence is trusted, and nothing in here mutates the world.
        """
        # 1. adapter presence — a known absence is `unsupported`, not unknown
        available = live.adapter_available and (
            target.is_available() if target is not None else True)
        if not available:
            return SandboxVerdict(
                kind=VerdictKind.UNSUPPORTED,
                code=SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                reason="no native-configuration adapter is available for this "
                       "target, so nothing can be expressed or verified; the "
                       "operation is refused before any side effect")

        # 2. the pin must be one this catalogue measures — an unregistered
        #    pin is unknown (no menu, no effect claim, no green path)
        if self._catalogue is not None and not self._catalogue.known_pin(
                intent.harness_id, live.native_version):
            return SandboxVerdict(
                kind=VerdictKind.UNKNOWN,
                code=SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                reason=f"({intent.harness_id!r}, {live.native_version!r}) is "
                       "not a pinned native-sandbox version in this "
                       "repository; unverified pins fail closed")

        ceilings = tuple(admin_ceilings) or self._ceilings
        try:
            # 3. administrator maxima: a request the ceiling forbids is
            #    refused with its stable code — never approximated, never
            #    resolved by ordering (contracts.md §C2/C4)
            if ceilings:
                check_within_ceiling(intent, ceilings)
            # 4. platform gate — a documented negative refuses; an
            #    unmeasured platform stays unknown
            check_platform_gate(intent, os_name=live.platform_os,
                                os_version=live.platform_version)
            # 5. coverage the brand's closed schema cannot express: proven
            #    negative -> unsupported (never "close enough")
            self._require_expressible(intent)
            # 6. cross-session contamination: a process-level change sharing
            #    the process without a declared impact set fails closed
            check_cross_session_impact(intent,
                                       current_session_id=live.session_id,
                                       co_resident=live.co_resident_sessions)
        except SandboxApiError as error:
            return _verdict_from_refusal(error)

        # 7. evidence: only a receipt bound to *these exact facts* proves
        #    the native effect; otherwise unknown
        resolved = evidence
        source = "provided evidence"
        if resolved is None and repository is not None:
            resolved = repository.get_evidence(live.target_handle,
                                               live.runtime_generation)
            source = "repository evidence"
        if resolved is None and probe is not None:
            return self._from_observation(
                probe.observe_effect(live.target_handle, intent))
        if resolved is None:
            return SandboxVerdict(
                kind=VerdictKind.UNKNOWN,
                code=SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                reason="no sandbox evidence exists for this target under the "
                       "current facts; an unverified sandbox is never "
                       "treated as protected")

        try:
            resolved.require_bound_to(
                server_instance_id=live.server_instance_id,
                session_id=live.session_id,
                runtime_generation=live.runtime_generation,
                native_version=live.native_version,
                config_digest=live.config_digest,
                platform=live.platform())
            proof = coverage_proves(intent, resolved,
                                    expected_native_version=live.native_version)
        except SandboxApiError as error:
            return _verdict_from_refusal(error)

        # 8. an attached (UNBOUND-seam) probe has the final word: its
        #    read-only observation can only downgrade, never green-wash
        if probe is not None:
            downgraded = self._from_observation(
                probe.observe_effect(live.target_handle, intent))
            if downgraded.kind is not VerdictKind.VERIFIED:
                return downgraded

        return SandboxVerdict(
            kind=VerdictKind.VERIFIED, code=None,
            reason=f"evidence ({source}) bound to the current facts proves "
                   f"coverage of {sorted(str(c) for c in proof.observed)}; "
                   "still no configuration was applied by this package")

    # ------------------------------------------------------------------ odds

    @staticmethod
    def _require_expressible(intent: NativeSandboxIntent) -> None:
        for category in sorted(intent.required_coverage, key=str):
            cell = matrix_cell(intent.brand, str(category))
            if cell is not None and cell.status is CellStatus.UNSUPPORTED:
                raise SandboxApiError(
                    SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                    f"{intent.brand}'s native sandbox cannot cover "
                    f"{category}: {cell.basis}; refusing to approximate it",
                    suggestion="keep that category under Permissions control")

    @staticmethod
    def _from_observation(observation: EffectObservation) -> SandboxVerdict:
        if observation.outcome is SandboxVerificationOutcome.VERIFIED:
            return SandboxVerdict(
                kind=VerdictKind.VERIFIED, code=None,
                reason=observation.reason or "probe observed the effect")
        if observation.outcome is SandboxVerificationOutcome.UNSUPPORTED:
            return SandboxVerdict(
                kind=VerdictKind.UNSUPPORTED,
                code=SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                reason=observation.reason or "probe reports a proven negative")
        return SandboxVerdict(
            kind=VerdictKind.UNKNOWN,
            code=SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
            reason=observation.reason or "probe could not observe the effect")
