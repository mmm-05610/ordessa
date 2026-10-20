"""Brand x category matrix cells: honestly filled, no green without proof."""
from __future__ import annotations

import pytest

from ordessa_sandbox_api import (
    BRAND_MATRIX,
    MATRIX_CELL_FIELDS,
    UNKNOWN_FIELD,
    CellStatus,
    ToolCategory,
    matrix_cell,
)

BRANDS = ("codex", "claude-code", "pi")
CATEGORIES = tuple(category.value for category in ToolCategory)


def test_matrix_has_every_brand_by_category_cell():
    for brand in BRANDS:
        for category in CATEGORIES:
            cell = matrix_cell(brand, category)
            assert cell is not None, f"missing cell {brand}/{category}"


def test_every_cell_declares_all_per_cell_fields():
    for cell in BRAND_MATRIX:
        for field in MATRIX_CELL_FIELDS:
            assert getattr(cell.fields, field) is not None
            # unproven fields must carry the explicit UNKNOWN sentinel, not
            # an empty string that could read as "nothing to say".
            assert getattr(cell.fields, field) != ""


def test_no_supported_cell_without_observed_receipt():
    # The anti-fake-green rule: a cell may only read SUPPORTED when its
    # observed receipt (repo measurement or L2 proof) is filled in.
    for cell in BRAND_MATRIX:
        if cell.status is CellStatus.SUPPORTED:
            assert cell.fields.observed_receipt != UNKNOWN_FIELD, (
                f"{cell.brand}/{cell.category} is marked green without a receipt")
            assert cell.fields.negative_probe != UNKNOWN_FIELD, (
                f"{cell.brand}/{cell.category} is marked green without a "
                "negative probe")


def test_pi_cells_are_unsupported_not_unknown():
    # Pi has no built-in native sandbox at all: the honest answer is
    # UNSUPPORTED (an extension-backed path), never a silent unknown.
    for category in CATEGORIES:
        cell = matrix_cell("pi", category)
        assert cell.status is CellStatus.UNSUPPORTED


def test_codex_config_surface_cells_are_supported_on_repo_measurement():
    # S-level evidence in this tree: pinned mode vocabulary measured in
    # posture_config.py and the bridge ProfileConfig.Sandbox field.
    for category in ("bash", "read", "edit"):
        cell = matrix_cell("codex", category)
        assert cell.status is CellStatus.SUPPORTED
        assert "posture_config" in cell.basis or "runtime.go" in cell.basis


def test_codex_mcp_and_network_coverage_is_not_claimed_green():
    # The横向反例: a Bash-sandbox brand must not宣称 MCP isolation. Codex
    # network/mcp effect has no L2 proof in this tree.
    for category in ("mcp", "network"):
        cell = matrix_cell("codex", category)
        assert cell.status is not CellStatus.SUPPORTED


def test_claude_windows_bash_cell_is_platform_unsupported():
    cell = matrix_cell("claude-code", "bash")
    assert "windows" in cell.platform_note.lower()
    assert "unsupported" in cell.platform_note.lower()


def test_unknown_cells_stay_a_separate_status():
    statuses = {cell.status for cell in BRAND_MATRIX}
    assert CellStatus.UNKNOWN in statuses
    assert CellStatus.UNSUPPORTED in statuses
    assert CellStatus.SUPPORTED in statuses
