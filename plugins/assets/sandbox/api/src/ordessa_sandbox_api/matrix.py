"""Per-brand x per-category evidence matrix (harness-adapters.md fill-in).

Cell semantics are deliberately narrow: a cell is SUPPORTED only when a
first-hand fact in this repository pins the claim (level S) or a controlled
probe proves it (L2/L3). Official documentation alone is level D and yields
UNKNOWN at most — "no L2/L3, no production isolation claim". UNSUPPORTED is
a proven negative (a documented limit stated as such, or a closed schema
that carries no field for the category); it is never merged with UNKNOWN.

Fields that no source in this tree can answer carry the literal "UNKNOWN".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

#: Every per-cell field the harness-adapters.md fill-in demands.
MATRIX_CELL_FIELDS = (
    "harness_binary_pin", "native_adapter_version", "os", "entry_point",
    "tool_coverage", "administrator_ceiling", "scope", "application_path",
    "reset_default", "observed_receipt", "negative_probe",
    "cross_session_impact",
)

#: Honest placeholder for anything this tree cannot answer.
UNKNOWN_FIELD = "UNKNOWN"


class CellStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


@dataclass(frozen=True)
class MatrixCellFields:
    harness_binary_pin: str = UNKNOWN_FIELD
    native_adapter_version: str = UNKNOWN_FIELD
    os: str = UNKNOWN_FIELD
    entry_point: str = UNKNOWN_FIELD
    tool_coverage: str = UNKNOWN_FIELD
    administrator_ceiling: str = UNKNOWN_FIELD
    scope: str = UNKNOWN_FIELD
    application_path: str = UNKNOWN_FIELD
    reset_default: str = UNKNOWN_FIELD
    observed_receipt: str = UNKNOWN_FIELD
    negative_probe: str = UNKNOWN_FIELD
    cross_session_impact: str = UNKNOWN_FIELD


@dataclass(frozen=True)
class MatrixCell:
    brand: str
    category: str
    status: CellStatus
    evidence_level: str  # D | S | L2 | L3 per harness-adapters.md
    basis: str
    platform_note: str = ""
    fields: MatrixCellFields = field(default_factory=MatrixCellFields)


@dataclass(frozen=True)
class DescribeOption:
    option_id: str
    status: CellStatus
    source: str
    platforms: tuple[str, ...]
    coverage: tuple[str, ...]
    note: str = ""


_CODEX_RECEIPT = (
    "repo measurement: plugins/server-compat/src/ordessa_server_compat/profiles/"
    "posture_config.py:_SANDBOX_STRICTNESS/_WRITABLE_SANDBOX pins the accepted "
    "mode vocabulary; plugins/harness/adapters/acp-adapter/pkg/codexacp/"
    "runtime.go:ProfileConfig.Sandbox carries it to the bridge")
_CODEX_PROBE = (
    "repo measurement: render_codex_config/_codex_implied refuses values "
    "outside the pinned vocabulary (POSTURE_CONFIG_UNEXPRESSIBLE path) "
    "instead of writing a guess")
_CLAUDE_PIN = "harnesses.toml: Claude Code adapter 0.81.2; claude native 2.1.270 per posture_config measurement note"
_PI_PIN = "harnesses.toml: Pi harness entry version 2.0"

_CODEX_FIELDS = MatrixCellFields(
    harness_binary_pin="harnesses.toml: Codex harness entry version 2.0; "
                       "codex binary 0.147.0 per posture_config measurement note",
    native_adapter_version="codexacp bridge ProfileConfig{ApprovalPolicy,Sandbox} "
                           "(pkg/codexacp/runtime.go)",
    entry_point="Go ACP bridge profile -> codex app-server config",
    observed_receipt=_CODEX_RECEIPT,
    negative_probe=_CODEX_PROBE,
)


def _cell(brand: str, category: str, status: CellStatus, level: str, basis: str,
          fields: MatrixCellFields, platform_note: str = "") -> MatrixCell:
    return MatrixCell(brand=brand, category=category, status=status,
                      evidence_level=level, basis=basis, fields=fields,
                      platform_note=platform_note)


def _codex(category: str, status: CellStatus, level: str, basis: str) -> MatrixCell:
    return _cell("codex", category, status, level, basis, _CODEX_FIELDS)


BRAND_MATRIX: tuple[MatrixCell, ...] = (
    # ---- codex: config surface measured (S); runtime effect unproven (no L2)
    _codex("bash", CellStatus.SUPPORTED, "S",
           "sandbox_mode governs command execution; " + _CODEX_RECEIPT),
    _codex("read", CellStatus.SUPPORTED, "S",
           "sandbox_mode/read-only filesystem posture governs reads; " + _CODEX_RECEIPT),
    _codex("edit", CellStatus.SUPPORTED, "S",
           "sandbox_mode/writable roots govern writes; " + _CODEX_RECEIPT),
    _codex("network", CellStatus.UNKNOWN, "D",
           "official docs tie network posture to sandbox_mode/version "
           "(research-and-reuse.md); the pinned value set and effect are not "
           "measured in this tree"),
    _codex("mcp", CellStatus.UNSUPPORTED, "D+S",
           "the closed codex sandbox vocabulary (sandbox_mode + writable "
           "roots + network) carries no MCP-coverage field; MCP tools are "
           "governed by Permissions, not this sandbox"),
    # ---- claude: documented mechanisms only; nothing L2-proven in this tree
    _cell("claude-code", "bash", CellStatus.UNKNOWN, "D",
          "official docs: OS-level Bash sandbox (Linux/WSL2 bubblewrap, "
          "macOS Seatbelt); no repo-side write/read-back/behaviour probe yet",
          MatrixCellFields(harness_binary_pin=_CLAUDE_PIN,
                           os="linux/wsl2/macos documented; native windows "
                              "documented unsupported"),
          platform_note="native Windows unsupported for the Bash sandbox "
                        "(documented limit)"),
    _cell("claude-code", "read", CellStatus.UNSUPPORTED, "D",
          "documented sandbox scope is Bash/PowerShell/Monitor subprocesses "
          "only — it never covers Read-class tools",
          MatrixCellFields(harness_binary_pin=_CLAUDE_PIN)),
    _cell("claude-code", "edit", CellStatus.UNSUPPORTED, "D",
          "documented sandbox scope is Bash/PowerShell/Monitor subprocesses "
          "only — it never covers Edit-class tools",
          MatrixCellFields(harness_binary_pin=_CLAUDE_PIN)),
    _cell("claude-code", "mcp", CellStatus.UNSUPPORTED, "D",
          "documented sandbox scope excludes MCP tools; claiming MCP "
          "isolation from a Bash sandbox is the横向反例",
          MatrixCellFields(harness_binary_pin=_CLAUDE_PIN)),
    _cell("claude-code", "network", CellStatus.UNKNOWN, "D",
          "no repo-measured network knob in the pinned surface; documented "
          "network restriction exists but the effect on this pin is unproven",
          MatrixCellFields(harness_binary_pin=_CLAUDE_PIN)),
    # ---- pi: extension-backed; NO built-in brand sandbox config at all
    *tuple(
        _cell("pi", category, CellStatus.UNSUPPORTED, "D+S",
              "pi has no built-in native sandbox configuration; the official "
              "sandbox path is an optional extension replacing Bash and "
              "depends on an external runtime (harness-adapters.md), so the "
              "brand-level cell is a proven negative for built-in support",
              MatrixCellFields(harness_binary_pin=_PI_PIN))
        for category in ("bash", "read", "edit", "mcp", "network")),
)

#: sandbox.describe@1 option tables — the only menus a UI may show, and only
#: per (brand); never guessed from the brand name itself.
BRAND_OPTIONS: dict[str, tuple[DescribeOption, ...]] = {
    "codex": (
        DescribeOption("sandbox_mode=read-only", CellStatus.SUPPORTED,
                       "pinned vocabulary (posture_config._SANDBOX_STRICTNESS; "
                       "_WRITABLE_SANDBOX)", ("linux", "macos", "windows"),
                       ("bash", "read", "edit"),
                       "effect proof still requires bound evidence"),
        DescribeOption("sandbox_mode=workspace-write", CellStatus.SUPPORTED,
                       "pinned vocabulary (posture_config._SANDBOX_STRICTNESS; "
                       "_WRITABLE_SANDBOX)", ("linux", "macos", "windows"),
                       ("bash", "read", "edit"),
                       "effect proof still requires bound evidence"),
        DescribeOption("sandbox_mode=danger-full-access", CellStatus.UNSUPPORTED,
                       "in the native vocabulary but outside the writable "
                       "set (_WRITABLE_SANDBOX): never offered",
                       ("linux", "macos", "windows"), ()),
    ),
    "claude-code": (
        DescribeOption("bash_sandbox=enabled", CellStatus.UNKNOWN,
                       "documented mechanism (bubblewrap/Seatbelt); no L2 "
                       "probe on the current pin", ("linux", "wsl2", "macos"),
                       ("bash",)),
        DescribeOption("powershell_sandbox=enabled", CellStatus.UNKNOWN,
                       "documented subprocess kind; unproven in this tree",
                       ("windows",), ()),
        DescribeOption("monitor_sandbox=enabled", CellStatus.UNKNOWN,
                       "documented subprocess kind; unproven in this tree",
                       (), ()),
    ),
    "pi": (),
}

_CELLS_BY_KEY = {(cell.brand, cell.category): cell for cell in BRAND_MATRIX}


def matrix_cell(brand: str, category: str) -> MatrixCell | None:
    """The honest cell for (brand, category); None when there is no row."""
    return _CELLS_BY_KEY.get((brand, category))
