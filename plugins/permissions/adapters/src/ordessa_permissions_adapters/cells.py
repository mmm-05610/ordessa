"""Capability cells: what may be claimed green, on exactly which evidence.

The matrix in `docs/design/safety-controls/harness-adapters.md` grades
evidence D (official docs) / S (code visible in this pinned tree) / L2 / L3,
and says: without L2/L3 no production permission or isolation may be claimed
wired. These cells encode that ruling per `(harnessId, capability)` for the
compile-time adapters domain. A cell without in-tree evidence is
`unsupported`/`unknown` and its adapters must support only explicit refusal.

Note on blocked seams (registered, not hidden):
- `pre-effect-gate` is unknown for every brand: no tool-side-effect
  authorization hook exists in this tree (specs/011-q5-safety/api-requests.md
  G1, owner C0). None of these adapters claims one.
- native receipt plumbing (G2) does not exist either; `native-receipt-verify`
  cells below describe *config read-back* oracles only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

__all__ = ["CAPABILITY_CELLS", "CapabilityCell"]

_CELL_STATUSES: Final[frozenset[str]] = frozenset({"supported", "unsupported", "unknown"})


@dataclass(frozen=True)
class CapabilityCell:
    harness_id: str
    capability: str          # policy-compile | pre-effect-gate | native-receipt-verify
    status: str              # supported | unsupported | unknown (never merged)
    evidence: str | None     # file:line in this repo, or None when unproven
    note: str = ""
    #: matrix fields (matrix.MATRIX_FIELDS) that must be non-UNKNOWN before
    #: this cell may be `supported`
    required_matrix_fields: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.status not in _CELL_STATUSES:
            raise ValueError(f"unknown cell status {self.status!r}")
        if self.status == "supported" and not self.evidence:
            raise ValueError("a supported cell must name evidence")


_POSTURE = "plugins/server-compat/.../profiles/posture_config.py"

CAPABILITY_CELLS: Final[tuple[CapabilityCell, ...]] = (
    # ---------------------------------------------------------------- claude
    CapabilityCell(
        "claude-code", "policy-compile", "supported",
        evidence=f"{_POSTURE}/posture_config.py:56-70,149-178",
        note="permissions.ask/permissions.deny tool-name lists, measured on the "
             "pinned artifact; allow/defaultMode unwritable",
        required_matrix_fields=("harness_binary_pin", "tool_coverage")),
    CapabilityCell(
        "claude-code", "pre-effect-gate", "unknown", evidence=None,
        note="no server-side request_permission handler in this tree; "
             "harnesses.toml:89 declares no permissions capability for claude; "
             "G1 seam blocked (owner C0)"),
    CapabilityCell(
        "claude-code", "native-receipt-verify", "supported",
        evidence=f"{_POSTURE}/posture_config.py:106-178",
        note="config-content read-back only (base merge before/after); the "
             "ACP-side receipt for claude stays UNKNOWN (G2)",
        required_matrix_fields=("tool_coverage",)),
    # ------------------------------------------------------------------ codex
    CapabilityCell(
        "codex", "policy-compile", "supported",
        evidence=f"{_POSTURE}/posture_config.py:77-80,206-285",
        note="sandbox_mode/approval_policy strictness tables measured on "
             "0.147.0-era artifact via codex doctor / prompt-input oracles",
        required_matrix_fields=("harness_binary_pin", "tool_coverage")),
    CapabilityCell(
        "codex", "pre-effect-gate", "unknown", evidence=None,
        note="Go bridge channel shape exists (pkg/codexacp/embedded.go:39-66,"
             "201) but no Python-side authorizer consumes it; G1 blocked"),
    CapabilityCell(
        "codex", "native-receipt-verify", "supported",
        evidence=f"{_POSTURE}/posture_config.py:231-243",
        note="top-level scalar read-back and never-looser comparison; no "
             "nativeReceipt plumbing (G2) - config verify only",
        required_matrix_fields=("harness_binary_pin", "tool_coverage",
                                "observed_receipt")),
    # --------------------------------------------------------------------- pi
    CapabilityCell(
        "pi", "policy-compile", "unsupported", evidence=None,
        note="extension-backed only: the tool_call gate is a Pi example "
             "extension, no load is evidenced in-tree (harnesses.toml:388 "
             "declares no permissions capability); refuses unless the caller "
             "supplies a loaded-gate observation for this pin"),
    CapabilityCell(
        "pi", "pre-effect-gate", "unknown", evidence=None,
        note="pkg/piacp/embedded.go:39-66,199 has the ACP request/response "
             "shape (S), no server-side handler; G1 blocked"),
    CapabilityCell(
        "pi", "native-receipt-verify", "unknown", evidence=None,
        note="no oracle in-tree proves a gate extension honoured a compiled "
             "rule; verify never answers Confirmed"),
    # ----------------------------------------------- families with no adapter
    *(CapabilityCell(harness, "policy-compile", "unsupported", evidence=None,
                     note="pinned in harnesses.toml but no measured permission "
                          "projection exists in-tree; composition must answer "
                          "POLICY_ADAPTER_MISSING, never allow")
      for harness in ("opencode", "hermes", "dsh", "qwen", "kilo")),
)
