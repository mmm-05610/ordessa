"""Ordessa native-sandbox asset API (`ordessa-sandbox-api`, task T04).

Pure domain layer for `sandbox.native-configuration@1` / `sandbox.describe@1`:
the `NativeSandboxIntent` schema with closed per-brand vocabularies,
instance-bound `SandboxEvidence`, platform-limit and admin-ceiling checks,
and the coverage proof that refuses to call a Bash-only sandbox a general
protection. Stdlib only; no storage, service, subprocess or host imports.

This concept is deliberately distinct from Pacthold's neutral execution
resource (of the same letters in `runtime_composition`): nothing here is,
imports, or names that port type, and native-isolation evidence can never be
satisfied by it.
"""
from __future__ import annotations

from .ceiling import SandboxCeiling, check_within_ceiling, intersect_ceilings
from .claims import FieldClaimRegistry
from .coverage import ToolCategory, parse_coverage
from .describe import SandboxDescription, SandboxOption, describe_sandbox
from .errors import SandboxApiError, SandboxErrorCode
from .evidence import (
    PlatformFacts,
    SandboxEvidence,
    SandboxVerificationOutcome,
    code_for_outcome,
)
from .intent import (
    ClaudeSandboxConfig,
    CodexSandboxConfig,
    NativeSandboxIntent,
    NetworkMode,
    PiSandboxConfig,
    PlatformGate,
    SandboxApplyScope,
    brand_coverable_categories,
)
from .matrix import (
    BRAND_MATRIX,
    BRAND_OPTIONS,
    MATRIX_CELL_FIELDS,
    UNKNOWN_FIELD,
    CellStatus,
    DescribeOption,
    MatrixCell,
    MatrixCellFields,
    matrix_cell,
)
from .platform import (
    PlatformAssessment,
    PlatformResult,
    assess_platform,
    check_platform_gate,
)
from .proof import CoverageProof, coverage_proves
from .sessions import SessionSlot, check_cross_session_impact
from .wire_family import SANDBOX_WIRE_FAMILIES, wire_family_for

__all__ = [
    "BRAND_MATRIX",
    "BRAND_OPTIONS",
    "MATRIX_CELL_FIELDS",
    "SANDBOX_WIRE_FAMILIES",
    "UNKNOWN_FIELD",
    "CellStatus",
    "ClaudeSandboxConfig",
    "CodexSandboxConfig",
    "CoverageProof",
    "DescribeOption",
    "FieldClaimRegistry",
    "MatrixCell",
    "MatrixCellFields",
    "NativeSandboxIntent",
    "NetworkMode",
    "PiSandboxConfig",
    "PlatformAssessment",
    "PlatformFacts",
    "PlatformGate",
    "PlatformResult",
    "SandboxApiError",
    "SandboxApplyScope",
    "SandboxCeiling",
    "SandboxDescription",
    "SandboxErrorCode",
    "SandboxEvidence",
    "SandboxOption",
    "SandboxVerificationOutcome",
    "SessionSlot",
    "ToolCategory",
    "assess_platform",
    "brand_coverable_categories",
    "check_cross_session_impact",
    "check_platform_gate",
    "check_within_ceiling",
    "code_for_outcome",
    "coverage_proves",
    "describe_sandbox",
    "intersect_ceilings",
    "matrix_cell",
    "parse_coverage",
    "wire_family_for",
]
