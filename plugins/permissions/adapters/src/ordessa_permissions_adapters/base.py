"""Shared §C1 adapter behaviour: prechecks, ceiling intersection, verification.

Everything that is *not* brand-specific lives here, so each brand file only
states what its measured native surface can and cannot express. Two invariants
hold for every adapter:

* a compile refuses rather than approximating: when the intent asks for
  something the writable surface cannot express, or asks to widen the ceiling,
  the answer is a typed refusal, never a narrower field silently dropped
  (FR-03);
* verification confirms only a fully bound observation: same pin, same
  runtime generation, oracle-covered fields, matching values, confirmed
  receipt with a stated source. Anything weaker is `unknown`; a contradiction
  is `mismatch` - neither is ever `confirmed`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Protocol, runtime_checkable

from ordessa_permissions_api import (
    TOOL_KEYS,
    RuleAction,
    TOOL_EXPOSURE,
    select_intent_action,
)

from .codes import AdapterCode
from .dto import PolicyCompileSnapshot, PolicyObservation, SupportEvidence
from .ranges import NativeVersionRange
from .results import (
    CompileRefusal,
    CompileResult,
    CompiledIntentSet,
    SupportOutcome,
    SupportReport,
    VerifyResult,
)

__all__ = ["BaseBrandAdapter", "PermissionPolicyAdapter"]


@runtime_checkable
class PermissionPolicyAdapter(Protocol):
    """The §C1 contribution shape: keyed by (harnessId, nativeVersionRange)."""

    adapter_id: str
    harness_id: str
    version_range: NativeVersionRange

    def supports(self, evidence: Any) -> SupportReport: ...

    def compilePolicy(self, snapshot: Any) -> CompileResult: ...

    def verifyPolicy(self, observation: Any) -> VerifyResult: ...


class BaseBrandAdapter(ABC):
    """Brand-specific hooks; the flow and the refusals are shared."""

    adapter_id: str = ""
    harness_id: str = ""
    version_range: NativeVersionRange
    #: named evidence for the capability this adapter claims when it answers
    #: `supported` (a supported answer without evidence is rejected outright).
    capability_evidence: str = ""

    def __init__(self) -> None:
        assert self.adapter_id and self.harness_id, "adapter identity is required"
        assert isinstance(self.version_range, NativeVersionRange)

    # ------------------------------------------------------------ descriptor
    def descriptor(self) -> Any:
        from .registry import PolicyAdapterDescriptor
        return PolicyAdapterDescriptor(adapter_id=self.adapter_id,
                                       harness_id=self.harness_id,
                                       version_range=self.version_range)

    # ------------------------------------------------------------ supports
    def supports(self, evidence: Any) -> SupportReport:
        if not isinstance(evidence, SupportEvidence):
            return SupportReport.unknown(
                code=AdapterCode.POLICY_SCOPE_UNVERIFIED,
                reason="no well-formed support evidence was given")
        if evidence.harness_id != self.harness_id:
            return SupportReport.unsupported(
                code=AdapterCode.POLICY_ADAPTER_MISSING,
                reason=f"this adapter is keyed to {self.harness_id!r}, not "
                       f"{evidence.harness_id!r}")
        if not self.version_range.contains(evidence.native_version):
            # an unmeasured pin: we cannot say either way
            return SupportReport.unknown(
                code=AdapterCode.POLICY_SCOPE_UNVERIFIED,
                reason=f"native version {evidence.native_version!r} is outside "
                       f"the measured range of {self.adapter_id}")
        return self._supports_extra(evidence)

    def _supports_extra(self, evidence: SupportEvidence) -> SupportReport:
        return SupportReport.supported(evidence=self.capability_evidence)

    @abstractmethod
    def expressible_actions(self) -> Mapping[str, Any]:
        """Per tool key, the enforcement actions this brand expresses natively."""

    # ------------------------------------------------------------ compile
    def compilePolicy(self, snapshot: Any) -> CompileResult:
        refusal = self._precheck(snapshot)
        if refusal is not None:
            return refusal
        assert isinstance(snapshot, PolicyCompileSnapshot)
        mode = self._mode_gate(snapshot)
        if isinstance(mode, CompileRefusal):
            return mode
        actions, conflicts = self._effective_actions(snapshot)
        if conflicts:
            return conflicts
        assert actions is not None
        assembled = self._assemble(actions, snapshot, mode)
        if isinstance(assembled, CompileRefusal):
            return assembled
        assert isinstance(assembled, CompiledIntentSet)
        return CompiledIntentSet(
            harness_id=self.harness_id, fields=assembled.fields,
            notes=assembled.notes,
            intent_revision=None if snapshot.intent is None
            else snapshot.intent.revision_digest,
            ceiling_revision=None if snapshot.ceiling is None
            else snapshot.ceiling.revision_digest)

    def _precheck(self, snapshot: Any) -> CompileRefusal | None:
        if not isinstance(snapshot, PolicyCompileSnapshot):
            return self._refusal(AdapterCode.POLICY_SCOPE_UNVERIFIED,
                                 "snapshot must be a PolicyCompileSnapshot")
        if snapshot.harness_id != self.harness_id:
            return self._refusal(
                AdapterCode.POLICY_SCOPE_UNVERIFIED,
                f"snapshot names harness {snapshot.harness_id!r}, this adapter "
                f"is keyed to {self.harness_id!r}")
        if not self.version_range.contains(snapshot.native_version):
            return self._refusal(
                AdapterCode.POLICY_SCOPE_UNVERIFIED,
                f"native version {snapshot.native_version!r} is outside the "
                f"measured range of {self.adapter_id}; compiling blind is refused")
        if snapshot.ceiling is not None and not snapshot.ceiling.is_trusted:
            return self._refusal(
                AdapterCode.POLICY_SCOPE_UNVERIFIED,
                "the effective ceiling is not from a trusted source; no policy "
                "is compiled under an unverified upper bound")
        if snapshot.intent is not None and snapshot.intent.harness_id != self.harness_id:
            return self._refusal(
                AdapterCode.POLICY_SCOPE_UNVERIFIED,
                f"the intent is declared for harness {snapshot.intent.harness_id!r}")
        # target-scoped rules and ceiling entries: no brand has a pinned
        # per-target rule syntax in this tree, so these refuse rather than
        # compile a broader/narrower approximation of the pattern.
        if snapshot.intent is not None:
            for rule in snapshot.intent.rules:
                if rule.target is not None:
                    return CompileRefusal(
                        AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE,
                        source=f"{self.adapter_id}.compilePolicy",
                        target=f"target-scoped intent rule {rule.tool.key}"
                               f"({rule.target.pattern})")
        if snapshot.ceiling is not None:
            for entry in (snapshot.ceiling.entries_denied
                          + snapshot.ceiling.entries_require_approval):
                if entry.target is not None:
                    return CompileRefusal(
                        AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE,
                        source=f"{self.adapter_id}.compilePolicy",
                        target=f"target-scoped ceiling entry {entry.tool.key}"
                               f"({entry.target.pattern})")
        return None

    def _mode_gate(self, snapshot: PolicyCompileSnapshot) -> Any:
        """Brand hook: return a writable mode constraint or a CompileRefusal."""
        mode = snapshot.intent.desired_mode if snapshot.intent else None
        if mode is not None:
            return CompileRefusal(
                AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE,
                source=f"{self.adapter_id}.compilePolicy",
                target=f"{self.harness_id}:{mode.name} is not a writable native "
                       "setting for this adapter")
        return None

    def _effective_actions(self, snapshot: PolicyCompileSnapshot
                           ) -> tuple[Mapping[str, RuleAction] | None,
                                      CompileRefusal | None]:
        """Intent within the ceiling: the stricter wins; a widening refuses."""
        rules = () if snapshot.intent is None else snapshot.intent.rules
        ceiling = snapshot.ceiling
        actions: dict[str, RuleAction] = {}
        widened: list[str] = []
        exposure_violations: list[str] = []
        for key in TOOL_KEYS:
            intent_action, _ = select_intent_action(rules, tool=key, target=None)
            ceiling_action: RuleAction | None = None
            if ceiling is not None:
                if ceiling.blocks(key, None):
                    ceiling_action = RuleAction.DENY
                elif ceiling.requires_approval(key, None):
                    ceiling_action = RuleAction.ASK
            requested = intent_action if intent_action is not None else RuleAction.ASK
            effective = requested
            if ceiling_action is not None and \
                    ceiling_action.strictness > effective.strictness:
                effective = ceiling_action
            if intent_action is not None and effective is not intent_action:
                # the caller asked for something looser than the ceiling allows
                widened.append(f"{key}: asked {intent_action.value}, ceiling "
                               f"forces {effective.value}")
            if intent_action is RuleAction.ALLOW and ceiling is not None and \
                    TOOL_EXPOSURE[key].rank > ceiling.maximum_exposure.rank:
                exposure_violations.append(
                    f"{key} reaches {TOOL_EXPOSURE[key].value} exposure; the "
                    f"ceiling bounds this Harness to {ceiling.maximum_exposure.value}")
            actions[key] = effective
        if widened or exposure_violations:
            return None, CompileRefusal(
                AdapterCode.POLICY_CEILING_VIOLATION,
                source=f"{self.adapter_id}.compilePolicy",
                target="; ".join(widened + exposure_violations)[:512])
        return actions, None

    @abstractmethod
    def _assemble(self, actions: Mapping[str, RuleAction],
                  snapshot: PolicyCompileSnapshot, mode: Any
                  ) -> CompileResult:
        """Brand hook: turn effective actions into native fields or refuse."""

    def _refusal(self, code: AdapterCode, target: str) -> CompileRefusal:
        return CompileRefusal(code=code, source=f"{self.adapter_id}.compilePolicy",
                              target=target[:512])

    # ------------------------------------------------------------ verify
    def verifiable_fields(self) -> frozenset[str]:
        """Field names this brand has a *measured* read-back oracle for."""
        return frozenset()

    def verifyPolicy(self, observation: Any) -> VerifyResult:
        if not isinstance(observation, PolicyObservation):
            return VerifyResult.unknown("observation is not a PolicyObservation")
        if observation.harness_id != self.harness_id:
            return VerifyResult.mismatch(
                f"observation is about {observation.harness_id!r}, not "
                f"{self.harness_id!r}")
        compiled = observation.compile_binding
        observed = observation.observed_binding
        if compiled is None or observed is None:
            return VerifyResult.unknown(
                "observation lacks the compile/observed identity bindings")
        for binding in (compiled, observed):
            if binding.native_version is not None and \
                    not self.version_range.contains(binding.native_version):
                return VerifyResult.unknown(
                    f"version {binding.native_version!r} is outside every "
                    "measured range; nothing can be vouched for at this pin")
        if compiled.native_version != observed.native_version:
            return VerifyResult.mismatch(
                f"observed at {observed.native_version!r} but compiled under "
                f"{compiled.native_version!r}")
        if compiled.runtime_generation is None or observed.runtime_generation is None:
            return VerifyResult.unknown("a generation identity is missing")
        if compiled.runtime_generation != observed.runtime_generation:
            return VerifyResult.mismatch(
                f"observed in generation {observed.runtime_generation!r} but "
                f"compiled in {compiled.runtime_generation!r}")
        if not observation.expected_fields:
            return VerifyResult.unknown("the observation expects nothing to verify")
        oracle = self.verifiable_fields()
        for name in observation.expected_fields:
            if name not in oracle:
                return VerifyResult.unknown(
                    f"{name!r} has no measured read-back oracle for this brand")
        observed_values = dict(observation.observed_values)
        for name in observation.expected_fields:
            if name not in observed_values:
                return VerifyResult.unknown(f"{name!r} was not observed")
            if _normalize(observed_values[name]) != _normalize(
                    observation.expected_fields[name]):
                return VerifyResult.mismatch(f"{name!r} differs from the compiled value")
        if not observation.receipt_confirmed:
            return VerifyResult.unknown("the native receipt is not confirmed")
        if not observation.receipt_source:
            return VerifyResult.unknown("the receipt has no stated source")
        return VerifyResult.confirmed()


def _normalize(value: Any) -> tuple[str, ...] | str:
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(sorted(str(item) for item in value))
    return str(value)
