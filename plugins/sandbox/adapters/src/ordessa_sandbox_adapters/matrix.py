"""Per-cell adapter matrix (harness-adapters.md §逐品牌测试填表).

Each capability cell records the twelve required fields; wherever this tree has
no proof the value is exactly ``UNKNOWN`` and the cell may NOT be marked
``supported``/green — construction refuses it. An UNKNOWN field is never coerced
into a "protected" claim (the success criteria forbid marking unknown green).
The field names and the ``UNKNOWN`` sentinel are the ones the consumed Sandbox
domain publishes, so this table speaks the same dialect as the API matrix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from ordessa_sandbox_api import (
    MATRIX_CELL_FIELDS,
    UNKNOWN_FIELD,
    CellStatus,
    MatrixCellFields,
)

__all__ = ["ADAPTER_CAPABILITY_CELLS", "MATRIX_FIELDS", "UNKNOWN_FIELD",
           "AdapterCapabilityCell"]

#: the twelve fields each cell must state (same tuple the domain API defines)
MATRIX_FIELDS: Final[tuple[str, ...]] = tuple(MATRIX_CELL_FIELDS)

_TOML = "plugins/harness/src/ordessa_harness/harnesses.toml"
_POSTURE = "plugins/server-compat/.../profiles/posture_config.py"
_SCHEMA = "plugins/harness/adapters/acp-adapter/internal/codex/schema"


def _fields(**overrides) -> MatrixCellFields:
    return MatrixCellFields(**overrides)


@dataclass(frozen=True)
class AdapterCapabilityCell:
    harness_id: str
    capability: str  # config-compile | non-bash-coverage | native-effect-verify
    status: CellStatus
    evidence: str | None
    fields: MatrixCellFields
    note: str = ""
    #: matrix fields that must be non-UNKNOWN before this cell may be supported
    required_matrix_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is CellStatus.SUPPORTED:
            if not self.evidence:
                raise ValueError("a supported cell must name evidence")
            for name in self.required_matrix_fields:
                if getattr(self.fields, name) == UNKNOWN_FIELD:
                    raise ValueError(
                        f"{self.harness_id}/{self.capability} cannot be "
                        f"supported while required field {name!r} is UNKNOWN")
        elif self.evidence:
            raise ValueError("only supported cells may carry an evidence claim")


_CODEX_FIELDS = _fields(
    harness_binary_pin="codex harness 2.0 (harnesses.toml:18); codex binary "
                       "0.147.0-era posture_config measurement",
    native_adapter_version="codexacp bridge ProfileConfig.Sandbox "
                           "(pkg/codexacp/runtime.go:26-27,116-117)",
    tool_coverage="sandbox_mode governs bash/read/edit/network "
                  "(committed schema SandboxMode + posture_config.py:77-79)",
)
_CLAUDE_FIELDS = _fields(
    harness_binary_pin="claude-code harness 0.81.2 (harnesses.toml:94)",
    tool_coverage="Bash/PowerShell/Monitor subprocess toggles only "
                  "(API ClaudeSandboxConfig.COVERABLE=={BASH})",
    os="linux/wsl2/macos supported (documented mechanism); native Windows "
       "unsupported; unmeasured OS unknown",
)
_PI_FIELDS = _fields(
    harness_binary_pin="pi harness 2.0 (harnesses.toml:393)",
)

#: what the controlled C4 fixture can honestly state per brand (L2, not
#: production): the platform's own ConfigurationApplicationService planned
#: AND applied this facet's fragment over the REAL configuration point host
#: against an observed (0,1,0) installation, materialize_generation wrote
#: the compiled SetField into a real private generation directory, the
#: bytes were read back through the lease fd, and the adapter's verify
#: Match is what let the platform return Confirmed —
#: tests/test_controlled_c4_l2.py (T022; the pre-T022 tree only had
#: "intents compiled" and cited this file before it existed, which the
#: id-level citation guards in tests/test_matrix.py now forbid).
_L2 = "tests/test_controlled_c4_l2.py"
_L2_CODEX = f"{_L2}::test_codex_sandbox_mode_fragment_planned_and_applied_to_confirmed"
_L2_CLAUDE = f"{_L2}::test_claude_bash_sandbox_fragment_planned_and_applied_to_confirmed"
_L2_PURE = f"{_L2}::test_my_package_performs_no_io_during_the_plan_and_apply_chain"
_L2_PLAN_ONLY = f"{_L2}::test_plan_alone_registers_intents_without_writing_anything"


def _c4_write(brand_test_id: str) -> str:
    return ("platform C4 ConfigurationApplicationService.plan -> apply over "
            "the real harness.configuration-adapters point host "
            "(build_runtime carrier, host-issued publication token); "
            "materialize_generation publishes one private gen-* directory "
            f"under the INJECTED controlled temp target; proven by "
            f"{brand_test_id}; the adapter package itself performs no I/O "
            f"in the whole chain ({_L2_PURE}; plan alone writes nothing: "
            f"{_L2_PLAN_ONLY})")


def _c4_receipt(brand_test_id: str) -> str:
    return ("lease.read_bytes(resource) with the sha256 manifest asserted "
            "against the platform-published bytes, then Confirmed (with the "
            "readback evidence ref) -> query OperationRecord -> reconcile "
            "equality asserted in the platform's own result types in "
            f"{brand_test_id}")


_C4_NEGATIVE = (
    f"{_L2}: readback value drift "
    f"({_L2}::test_native_receipt_drift_never_confirms_and_reconciles_unknown) "
    "and a tampered digest manifest "
    f"({_L2}::test_tampered_readback_manifest_is_refused_confirmation) each "
    "yield Unknown, never Confirmed, and a restarted service reconciles the "
    "same durable Unknown while refusing to replay the plan; the (1,0,0) "
    "adapter version the only in-tree production-shaped observer records "
    "(harness external-adapter fixture __init__.py:69) is refused against "
    "this facet's exact (0,1,0) pin with capability-unsupported "
    "(test_observed_adapter_version_mismatch_is_refused_by_the_platform); "
    "an unobserved native version yields version-unverified, an unknown "
    "harness identity capability-unsupported, an unselectable point view "
    "adapter-missing and a stale expected revision stale-plan "
    "(test_unobserved_native_version_refuses_with_version_unverified, "
    "test_unknown_harness_identity_is_refused_by_the_platform, "
    "test_absent_facet_on_the_real_point_refuses_with_adapter_missing, "
    "test_stale_expected_revision_refuses_before_any_effect); a SetField "
    "beyond the registered claims is refused invalid-fragment by the "
    "platform claim ceiling (test_fragment_whose_claim_was_not_admitted_is_"
    "refused); a required coverage the observation cannot show (bash only) "
    "yields Refused carrying the stable SANDBOX_COVERAGE_UNPROVEN code and "
    "never reaches Confirmed "
    "(test_required_coverage_the_observation_cannot_show_never_confirms)")

ADAPTER_CAPABILITY_CELLS: Final[tuple[AdapterCapabilityCell, ...]] = (
    AdapterCapabilityCell(
        "codex", "config-compile", CellStatus.SUPPORTED,
        evidence=f"{_POSTURE}:77-79 writable table; {_SCHEMA} SandboxMode enum; "
                 "codexacp/runtime.go:26-27; bound C3 SetField built by "
                 "src/ordessa_sandbox_adapters/seam.py "
                 "(tests/test_c3_seam.py::test_codex_fields_bind_real_platform_setfield_objects)",
        fields=_CODEX_FIELDS,
        required_matrix_fields=("harness_binary_pin", "tool_coverage"),
        note="writable postures compiled from the pinned vocabulary; "
             "danger-full-access never writable"),
    AdapterCapabilityCell(
        "codex", "config-write-controlled-fixture-l2", CellStatus.SUPPORTED,
        evidence=f"{_c4_write(_L2_CODEX)}; readback "
                 f"{_c4_receipt(_L2_CODEX)}; negative {_C4_NEGATIVE}",
        fields=_fields(harness_binary_pin=_CODEX_FIELDS.harness_binary_pin,
                       native_adapter_version=_CODEX_FIELDS.native_adapter_version,
                       tool_coverage=_CODEX_FIELDS.tool_coverage,
                       entry_point="sandbox.native-config.codex over the codex "
                                   "config.toml target (toml codec)",
                       application_path=_c4_write(_L2_CODEX),
                       observed_receipt=_c4_receipt(_L2_CODEX),
                       negative_probe=_C4_NEGATIVE,
                       scope="instance-scoped controlled fixture; no hot apply"),
        required_matrix_fields=("harness_binary_pin", "tool_coverage",
                                "application_path", "observed_receipt",
                                "negative_probe"),
        note="L2 CONTROLLED FIXTURE ONLY — the installation is observed by an "
             "in-test describe_installation provider at (0,1,0); the native "
             "target is a temp dir, not Codex and not production "
             "(harness-api record: no Q5 production verifier installed)"),
    AdapterCapabilityCell(
        "codex", "native-effect-verify", CellStatus.UNKNOWN, evidence=None,
        fields=_fields(harness_binary_pin=_CODEX_FIELDS.harness_binary_pin,
                       application_path=_c4_write(_L2_CODEX),
                       negative_probe=_C4_NEGATIVE),
        note="still UNKNOWN for production: the harness-api record states "
             "instance generation and an operation-bound native receipt remain "
             "absent and restart reconcile must remain Unknown; the real "
             "Codex process never observed its generated config here (no L3)"),
    AdapterCapabilityCell(
        "claude-code", "config-compile", CellStatus.SUPPORTED,
        evidence="harness-adapters.md Claude row; API ClaudeSandboxConfig "
                 "COVERABLE=={BASH}; bound C3 SetField "
                 "(tests/test_c3_seam.py::test_claude_toggle_binds_a_real_setfield_and_claims_nothing_broader)",
        fields=_CLAUDE_FIELDS,
        required_matrix_fields=("harness_binary_pin", "tool_coverage"),
        note="only the three subprocess toggles compile; broader coverage "
             "refuses unproven"),
    AdapterCapabilityCell(
        "claude-code", "config-write-controlled-fixture-l2", CellStatus.SUPPORTED,
        evidence=f"{_c4_write(_L2_CLAUDE)}; readback "
                 f"{_c4_receipt(_L2_CLAUDE)}; negative {_C4_NEGATIVE}",
        fields=_fields(harness_binary_pin=_CLAUDE_FIELDS.harness_binary_pin,
                       tool_coverage=_CLAUDE_FIELDS.tool_coverage,
                       os=_CLAUDE_FIELDS.os,
                       entry_point="sandbox.native-config.claude-code over the "
                                   "settings.json target (json codec)",
                       application_path=_c4_write(_L2_CLAUDE),
                       observed_receipt=_c4_receipt(_L2_CLAUDE),
                       negative_probe=_C4_NEGATIVE,
                       scope="instance-scoped controlled fixture; no hot apply"),
        required_matrix_fields=("harness_binary_pin", "tool_coverage",
                                "application_path", "observed_receipt",
                                "negative_probe"),
        note="L2 CONTROLLED FIXTURE ONLY — bashSandbox landed in real bytes on "
             "disk and read back against an in-test observed (0,1,0) "
             "installation; the documented Seatbelt/bwrap mechanism was "
             "never exercised"),
    AdapterCapabilityCell(
        "claude-code", "non-bash-coverage", CellStatus.UNSUPPORTED, evidence=None,
        fields=_fields(harness_binary_pin=_CLAUDE_FIELDS.harness_binary_pin),
        note="read/edit/MCP are outside the Bash/PowerShell/Monitor sandbox "
             "scope — a proven negative, never approximated"),
    AdapterCapabilityCell(
        "claude-code", "native-effect-verify", CellStatus.UNKNOWN, evidence=None,
        fields=_fields(harness_binary_pin=_CLAUDE_FIELDS.harness_binary_pin,
                       application_path=_c4_write(_L2_CLAUDE),
                       negative_probe=_C4_NEGATIVE),
        note="documented mechanism only; no Claude process read the generated "
             "settings.json, and the operation-bound receipt stays absent"),
    AdapterCapabilityCell(
        "pi", "config-compile", CellStatus.UNSUPPORTED, evidence=None,
        fields=_PI_FIELDS,
        note="extension-backed only; with no loaded sandbox extension nothing "
             "compiles and bare Pi is never treated as isolated. Even the "
             "extension-present case compiles to a C3 InvokeAction the "
             "controlled materializer refuses (no separate action executor), "
             "so no Pi path reaches a write in this tree"),
    AdapterCapabilityCell(
        "pi", "native-effect-verify", CellStatus.UNKNOWN, evidence=None,
        fields=_fields(harness_binary_pin=_PI_FIELDS.harness_binary_pin),
        note="no oracle in-tree proves a loaded extension honoured the effect"),
)

