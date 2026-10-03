"""Shared §C2 adapter behaviour: assess/compile/verify flow and refusals.

Everything that is *not* brand-specific lives here, so each brand file only
states what its measured native surface can and cannot express. Two invariants
hold for every adapter:

* a compile refuses rather than approximating: a coverage requirement the brand
  cannot carry, a ceiling the intent would loosen, or a process-scoped change
  that would silently touch a co-resident session all yield a typed refusal with
  **zero** compiled fields — never a narrower field quietly dropped (FR-03);
* verification reflects an observation only. Its result type is the platform's
  closed ``Verification`` (``Match``/``Mismatch``/``VerificationUnknown``), so a
  drift or an unobserved effect yields ``Mismatch``/``VerificationUnknown`` and
  can never read as a confirmation.

The verdict vocabularies are imported, not mirrored (``harness-api`` checkpoint;
``results.py`` keeps no local assess/verify enum). The stable §C4 codes travel
in the reason prefix. ``compile`` takes the platform ``TargetHandle`` the host
issued through the ``AdapterContext`` — this package never turns a string into a
target or invents a generation.

The stable codes come from ``ordessa_sandbox_api`` (§C4); `unsupported` and
`unknown` stay distinct throughout.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ordessa_harness_api.contracts import Assessment, Verification
from ordessa_harness_api.intents import TargetHandle
from ordessa_sandbox_api import (
    NativeSandboxIntent,
    PlatformFacts,
    SandboxApiError,
    SandboxCeiling,
    SandboxErrorCode,
    ToolCategory,
    check_cross_session_impact,
    check_within_ceiling,
)
from ordessa_sandbox_backend import EffectObservation
from ordessa_sandbox_api import SandboxVerificationOutcome

from .dto import AdapterPin, AuthorizedFacts
from .ranges import NativeVersionRange
from .results import (
    CompiledIntent,
    CompileRefusal,
    CompileResult,
    assessment_supported,
    assessment_unsupported,
    assessment_unknown,
    unknown_verification,
    unsupported_verification,
    verification_match,
)

__all__ = ["BaseSandboxAdapter"]


class BaseSandboxAdapter(ABC):
    adapter_id: str = ""
    harness_id: str = ""
    brand: str = ""
    version_range: NativeVersionRange
    #: categories this brand's native schema can ever claim to cover
    coverable: frozenset[ToolCategory] = frozenset()
    capability_evidence: str = ""

    def __init__(self) -> None:
        assert self.adapter_id and self.harness_id and self.brand, \
            "adapter identity is required"
        assert isinstance(self.version_range, NativeVersionRange)

    # ------------------------------------------------------------- descriptor
    def configuration_descriptor(self, *, pins=None):
        """This adapter's payload for the REAL configuration point.

        The descriptor vocabulary and the conflict authority are the
        platform's (`points.py` / `HarnessContributionRegistry`); this is a
        pure builder, not a second registry.
        """
        from .points import build_configuration_descriptor
        return build_configuration_descriptor(self, pins=pins)

    @abstractmethod
    def native_field_claims(self) -> tuple[str, ...]:
        """The native config field paths this adapter owns (§C2 conflict gate)."""

    def config_from_payload(self, payload):
        """Brand hook: the closed point payload -> the domain brand config.

        The payload is already validated by the platform ``ValueSchema`` of the
        descriptor; this only re-expresses it as the domain config the brand
        rules are written against. Returning ``None`` means "this brand's
        payload carries no config" (Pi: the sandbox is an external extension),
        and the caller's template config stands.
        """
        return None

    # ------------------------------------------------------------- assess
    def assess(self, pin: AdapterPin, platform_facts: PlatformFacts,
               authorized_facts: AuthorizedFacts) -> Assessment:
        if not isinstance(pin, AdapterPin):
            return assessment_unknown(
                SandboxErrorCode.SANDBOX_INTENT_INVALID,
                "assess needs an AdapterPin")
        if pin.harness_id != self.harness_id:
            return assessment_unsupported(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                f"this adapter is keyed to {self.harness_id!r}, not "
                f"{pin.harness_id!r}")
        if not authorized_facts.adapter_available:
            return assessment_unsupported(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                "no native-configuration adapter is available for this "
                "target, so nothing can be expressed or verified")
        if not self.version_range.contains(pin.native_version):
            # an unmeasured pin: refuse to invent a menu
            return assessment_unknown(
                SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                f"native version {pin.native_version!r} is outside the measured "
                "range of " + self.adapter_id + "; no menu is invented")
        return self._assess_brand(pin, platform_facts, authorized_facts)

    def _assess_brand(self, pin: AdapterPin, platform_facts: PlatformFacts,
                      authorized_facts: AuthorizedFacts) -> Assessment:
        return assessment_supported(evidence=self.capability_evidence)

    # ------------------------------------------------------------- compile
    def compile(self, intent: NativeSandboxIntent, target: TargetHandle,
                ceiling: Sequence[SandboxCeiling], *,
                authorized: AuthorizedFacts | None = None) -> CompileResult:
        source = f"{self.adapter_id}.compile"
        if not isinstance(target, TargetHandle):
            return CompileRefusal(
                SandboxErrorCode.SANDBOX_INTENT_INVALID, source=source,
                target="compile needs the server-issued TargetHandle (§C2 "
                       "input); a bare string is not a handle and no generation "
                       "is ever invented here")
        if not isinstance(intent, NativeSandboxIntent):
            return CompileRefusal(SandboxErrorCode.SANDBOX_INTENT_INVALID, source=source,
                                  target="compile needs a NativeSandboxIntent")
        if intent.brand != self.brand:
            return CompileRefusal(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED, source=source,
                target=f"intent is for brand {intent.brand!r}; this adapter "
                       f"compiles {self.brand!r}")
        if intent.native_version_pin is not None and \
                not self.version_range.contains(intent.native_version_pin):
            return CompileRefusal(
                SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN, source=source,
                target=f"native pin {intent.native_version_pin!r} is outside "
                       "the measured range; compiling blind is refused")
        coverage_refusal = self._check_coverage(intent)
        if coverage_refusal is not None:
            return coverage_refusal
        ceilings = tuple(ceiling or ())
        try:
            if ceilings:
                check_within_ceiling(intent, ceilings)
            if authorized is not None and authorized.current_session_id is not None:
                check_cross_session_impact(
                    intent, current_session_id=authorized.current_session_id,
                    co_resident=authorized.co_resident_sessions)
        except SandboxApiError as error:
            return CompileRefusal(error.code, source=source, target=error.message)
        return self._compile_brand(intent, target, authorized)

    def _check_coverage(self, intent: NativeSandboxIntent) -> CompileRefusal | None:
        """Brand hook: refuse coverage the native sandbox cannot honestly carry."""
        return None

    @abstractmethod
    def _compile_brand(self, intent: NativeSandboxIntent, target: TargetHandle,
                       authorized: AuthorizedFacts | None) -> CompileResult:
        """Brand hook: emit compiled C3 fields, or refuse without approximating."""

    def _result(self, intent: NativeSandboxIntent, fields,
                notes=()) -> CompileResult:
        return CompiledIntent(harness_id=self.harness_id, intents=tuple(fields),
                              sandbox_id=intent.sandbox_id, revision=intent.revision,
                              notes=tuple(notes))

    # -------------------------------------------------------------- verify
    def verify(self, observation) -> Verification:
        """Fold one read-only observation into a platform ``Verification``.

        There is no local verdict enum any more: the platform's trio is the
        answer, and only ``Match`` can ever let the C4 service confirm. A
        proven native limit is reported as ``VerificationUnknown`` whose reason
        carries the unsupported code (see ``results.unsupported_verification``)
        — it is never folded into "we could not look".
        """
        if not isinstance(observation, EffectObservation):
            return unknown_verification(
                "observation is not an EffectObservation, so nothing is known")
        if observation.outcome is SandboxVerificationOutcome.VERIFIED:
            coverage = ",".join(sorted(str(category) for category
                                       in observation.covered_categories)) or "none"
            return verification_match(
                f"sandbox.effect-observation:{self.harness_id}:verified:"
                f"coverage={coverage}")
        if observation.outcome is SandboxVerificationOutcome.UNSUPPORTED:
            return unsupported_verification(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                observation.reason or "probe observed a proven negative")
        return unknown_verification(
            observation.reason or "probe could not observe the effect")
