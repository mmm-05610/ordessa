"""Per-brand fill-in matrix (harness-adapters.md §逐品牌测试填表).

Every brand row records the twelve required fields; wherever this tree gives
no evidence the value is exactly `UNKNOWN` - never a guess from the brand
family ("不以品牌大类推测"). `evidence` names the file:line behind a known
value; an UNKNOWN cell carries no evidence and no capability cell may lean on
it (enforced by tests/test_cells_matrix.py).

Evidence-level note: D-level (official-doc) claims are not mixed into this
table as if they were in-tree proof; they live in
docs/design/safety-controls/harness-adapters.md and research-and-reuse.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping

__all__ = ["BRAND_MATRIX", "MATRIX_FIELDS", "UNKNOWN", "MatrixCell"]

#: the twelve fields each cell must state
MATRIX_FIELDS: Final[tuple[str, ...]] = (
    "harness_binary_pin", "native_adapter_version", "os", "entry_point",
    "tool_coverage", "administrator_ceiling", "scope", "application_path",
    "reset_default", "observed_receipt", "negative_probe", "cross_session_impact",
)

UNKNOWN: Final[str] = "UNKNOWN"

_TOML = "plugins/harness/src/*/harnesses.toml"
_POSTURE = "plugins/server-compat/.../profiles/posture_config.py"
_TRANSLATE = "plugins/server-compat/.../profiles/posture_translation.py"


@dataclass(frozen=True)
class MatrixCell:
    """One matrix cell: a value plus the in-tree evidence behind it."""

    value: str
    evidence: str | None = None

    def __post_init__(self) -> None:
        if self.evidence is None and self.value != UNKNOWN:
            raise ValueError("a cell without evidence must be UNKNOWN")
        if self.evidence is not None and self.value == UNKNOWN:
            raise ValueError("UNKNOWN cells carry no evidence claim")


def _known(value: str, evidence: str) -> MatrixCell:
    return MatrixCell(value, evidence)


def _unknown() -> MatrixCell:
    return MatrixCell(UNKNOWN, None)


BRAND_MATRIX: Final[Mapping[str, Mapping[str, MatrixCell]]] = {
    "codex": {
        "harness_binary_pin": _known(
            "codex / codex-app-server bundle (PATH_OR_BUNDLE); first-hand "
            "measurements recorded against 0.147.0",
            f"{_TOML}:19-35; {_POSTURE}:257"),
        "native_adapter_version": _known(
            "identity version of record 2.0", f"{_TOML}:14-18"),
        "os": _unknown(),  # no OS-level pin evidence in this tree
        "entry_point": _known(
            "launch mode app-server: `codex app-server` (stdio) via the Go "
            "ACP bridge", f"{_TOML}:61-64"),
        "tool_coverage": _known(
            "sandbox_mode expresses write denial (edit/external_directory); "
            "approval_policy gates commands (bash asks are untrusted); no "
            "per-tool deny knob for bash/webfetch/skill/task/read",
            f"{_POSTURE}:206-228; {_TRANSLATE}:95-128"),
        "administrator_ceiling": _known(
            "Ordessa-side ceiling model is the permissions API; native "
            "managed requirements promotion refusal is asserted at compile, "
            "not observed against a managed file in-tree",
            "plugins/permissions/api/src/.../ceilings.py:1-38 (see "
            f"{_POSTURE}:231-243 never-looser write)"),
        "scope": _known(
            "execution-local profile overlay under the guest home "
            "(/runtime/home), not the user's own config root",
            f"{_TOML}:24-31"),
        "application_path": _known(
            "render_posture_config/write_posture_config controlled path "
            "(compat); product wiring is T05/T07 work", f"{_POSTURE}:246-358"),
        "reset_default": _unknown(),  # no evidence of native reset semantics
        "observed_receipt": _known(
            "ACP request/response payload shape in the bridge "
            "(PermissionDecision/RespondPermission) and top-level config "
            "read-back oracle; no nativeReceipt plumbing (G2)",
            "plugins/harness/adapters/acp-adapter/pkg/codexacp/embedded.go:"
            f"39-66,201; {_POSTURE}:231-243"),
        "negative_probe": _unknown(),  # harness-side controlled probe pending L2
        "cross_session_impact": _unknown(),  # no A/B isolation evidence yet (L2)
    },
    "claude-code": {
        "harness_binary_pin": _known(
            "claude CLI bundle + official adapter "
            "@agentclientprotocol/claude-agent-acp; settings surface measured "
            "on the 2.1.270 artifact", f"{_TOML}:95-99; {_POSTURE}:52-63"),
        "native_adapter_version": _known(
            "identity version of record 0.81.2", f"{_TOML}:90-94"),
        "os": _unknown(),
        "entry_point": _known(
            "launch mode acp: `claude-agent-acp` (stdio)", f"{_TOML}:124-127"),
        "tool_coverage": _known(
            "permissions.ask / permissions.deny tool-name lists (Read/Glob/"
            "Grep, Edit/Write/NotebookEdit, Bash, Task, WebFetch/WebSearch, "
            "Skill); external_directory has no pinned rule name",
            f"{_POSTURE}:56-70"),
        "administrator_ceiling": _known(
            "managed-settings precedence is a D-level official-doc claim only; "
            "in-tree the Ordessa ceiling model applies at compile",
            "docs/design/safety-controls/harness-adapters.md:9 (D row); "
            f"{_POSTURE}:65-70"),
        "scope": _known(
            "execution-local overlay at /runtime/home; settings.json targets "
            "recorded for hooks/skills", f"{_TOML}:100-119"),
        "application_path": _known(
            "render_claude_settings controlled path (compat merge into base "
            "text)", f"{_POSTURE}:106-178"),
        "reset_default": _unknown(),
        "observed_receipt": _unknown(),  # no in-tree ACP permission handler
        #   for claude; the request_permission method note (~line 248) belongs
        #   to dsh's documented surface, and claude declares no permissions
        #   capability (harnesses.toml:89).
        "negative_probe": _unknown(),
        "cross_session_impact": _unknown(),
    },
    "pi": {
        "harness_binary_pin": _known(
            "pi via PATH resolver; the observed integration is "
            "@automatalabs/pi-acp@0.5.0 through the Go bridge",
            f"{_TOML}:376-397"),
        "native_adapter_version": _known(
            "identity version of record 2.0", f"{_TOML}:389-393"),
        "os": _unknown(),
        "entry_point": _known(
            "launch mode exec: `pi --agent-dir /runtime/home --print`; "
            "embedded ACP runtime in the bridge",
            f"{_TOML}:415-418; plugins/harness/adapters/acp-adapter/pkg/"
            "piacp/embedded.go:68"),
        "tool_coverage": _unknown(),
        #   which tools a loaded tool_call gate extension can intercept is a
        #   property of the extension, not of Pi; nothing is pinned in-tree,
        #   so the compile cell stays unsupported and only refusal is allowed.
        "administrator_ceiling": _unknown(),
        "scope": _known(
            "execution-local agent dir (/runtime/home) via launch argv",
            f"{_TOML}:398-405"),
        "application_path": _unknown(),  # no extension-loading path in-tree
        "reset_default": _unknown(),
        "observed_receipt": _known(
            "ACP request/response shape only (RespondPermission in the "
            "bridge); no server-side handler, no extension receipt",
            "plugins/harness/adapters/acp-adapter/pkg/piacp/embedded.go:39-66,199"),
        "negative_probe": _unknown(),
        "cross_session_impact": _unknown(),
    },
}
