"""Coverage proof: evidence must name every required category (FR-05/06).

`coverage_proves` answers exactly one question: do the observed categories
on this bound instance cover everything the intent requires? A Bash-only
probe never proves read/edit/MCP/network, and there is no "basically
protected" verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .coverage import ToolCategory
from .errors import SandboxApiError, SandboxErrorCode
from .evidence import SandboxEvidence, SandboxVerificationOutcome, code_for_outcome
from .intent import NativeSandboxIntent


@dataclass(frozen=True)
class CoverageProof:
    proven: bool
    required: frozenset[ToolCategory]
    observed: frozenset[ToolCategory]
    note: str = ""

    @property
    def missing(self) -> frozenset[ToolCategory]:
        return self.required - self.observed


def coverage_proves(intent: NativeSandboxIntent, evidence: SandboxEvidence,
                    *, expected_native_version: Optional[str] = None) -> CoverageProof:
    """Refuse with the precise code, or return the proof."""
    outcome_code = code_for_outcome(evidence.outcome)
    if evidence.outcome is not SandboxVerificationOutcome.VERIFIED:
        assert outcome_code is not None
        raise SandboxApiError(
            outcome_code,
            f"sandbox evidence for {evidence.harness_id} reads "
            f"{str(evidence.outcome)}: {evidence.reason or 'no reason recorded'}",
            suggestion="run the probe or drop the native-sandbox claim")
    if evidence.harness_id != intent.harness_id:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
            "evidence belongs to a different harness instance",
            suggestion="re-probe against this harness")
    pin = expected_native_version or intent.native_version_pin
    if pin is not None and evidence.native_version != pin:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
            f"evidence was observed on native version "
            f"{evidence.native_version!r}, not the current pin {pin!r}; it "
            "proves nothing about this instance",
            suggestion="re-probe against the pinned version")
    missing = intent.required_coverage - evidence.observed_covered_categories
    if missing:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN,
            f"observed sandbox coverage {sorted(str(c) for c in evidence.observed_covered_categories)} "
            f"does not prove required categories "
            f"{sorted(str(c) for c in missing)}; other tools remain governed "
            "by Permissions, not by this sandbox",
            suggestion="narrow requiredCoverage or extend the probed coverage")
    return CoverageProof(proven=True, required=intent.required_coverage,
                         observed=evidence.observed_covered_categories)
