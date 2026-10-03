"""EXT-01/EXT-05 (brand-narrowed) — the prompts three-semantic table."""
from __future__ import annotations

import re

import pytest

from ordessa_prompts.harness_adapters.capabilities import (
    BRAND_STATEMENTS, IMPLEMENTATION_DISPOSITION, IMPLEMENTED_BRANDS,
    NO_EVIDENCE, QWEN_REMOVAL_NOTE, SEMANTICS, SUPPORTED, UNKNOWN,
    UNSUPPORTED, all_brand_rows, statement_for,
)

TOML = "plugins/harness/src/ordessa_harness/harnesses.toml"


def test_every_brand_accounts_for_all_three_semantics():
    assert set(all_brand_rows()) == {"pi", "codex", "claude", "hermes",
                                     "opencode", "dsh", "kilo", "qwen"}
    assert set(BRAND_STATEMENTS) | {"qwen"} == set(all_brand_rows())
    for statement in BRAND_STATEMENTS.values():
        assert set(statement.cells) == set(SEMANTICS)


def test_every_cell_carries_evidence_and_counterexample_discipline():
    # the evidence path constant must be the REAL doc path (round 1: a
    # mangled replace() produced docs/design/prompts/prompts/...)
    from ordessa_prompts.harness_adapters import capabilities as cap
    assert cap.HM == "docs/design/prompts/harness-adapters.md"
    #: cells allowed to carry NO counterexample: only the no-evidence
    #: unknowns (nothing observed → nothing to warn about yet); every
    #: graded/cited cell must name its standing counterexample
    for harness_id, statement in BRAND_STATEMENTS.items():
        for semantic, cell in statement.cells.items():
            assert cell.semantic == semantic
            if cell.value == SUPPORTED:
                assert cell.evidence != NO_EVIDENCE
            if cell.evidence != NO_EVIDENCE:
                assert re.search(r"[\w./+-]+:\d+", cell.evidence), (
                    harness_id, semantic, cell.evidence)
                assert cell.evidence.startswith("docs/design/prompts/"
                                                "harness-adapters.md") or                     "plugins/harness" in cell.evidence or                     "harnesses.toml" in cell.evidence, (
                    harness_id, semantic, cell.evidence)
                assert cell.counterexample, (
                    harness_id, semantic,
                    "a cited cell must name its standing counterexample")


def test_implemented_brands_instruction_cells_are_unknown_not_supported():
    # the registry declares NO instruction target and the routes are
    # vendor-doc — tonight's honest grade, cited identically per brand
    for brand in ("pi", "codex", "claude"):
        cell = statement_for(brand).cells["instruction"]
        assert cell.value == UNKNOWN, brand
        assert "registry/schema.py:64" in cell.evidence
        assert cell.counterexample, brand


def test_persona_is_unsupported_on_the_three_implemented_brands():
    # HM:9 — no evidenced independent persona interface; the design rule
    # itself is the first-hand evidence for the refusal
    for brand in ("pi", "codex", "claude"):
        cell = statement_for(brand).cells["persona"]
        assert cell.value == UNSUPPORTED, brand
        assert "harness-adapters.md:9" in cell.evidence
        assert cell.counterexample


def test_system_replacement_stays_unknown_with_counterexamples():
    for brand in ("pi", "codex", "claude"):
        cell = statement_for(brand).cells["systemReplacement"]
        assert cell.value == UNKNOWN, brand
        assert cell.counterexample, brand


def test_opencode_merge_semantics_counterexample_constrains_replacement():
    cell = statement_for("opencode").cells["systemReplacement"]
    assert cell.value == UNKNOWN
    assert "MERGE" in cell.counterexample or "merge" in cell.counterexample


def test_dsh_persona_carries_the_composition_counterexample():
    cell = statement_for("dsh").cells["persona"]
    assert cell.value == UNKNOWN
    assert "replacement→persona→instructions" in cell.counterexample


def test_qwen_row_is_the_removal_note_with_every_qwen_face_named():
    assert "qwen" not in BRAND_STATEMENTS
    for face in ("QWEN.md", "context.fileName", "import",
                 "includeDirectories"):
        assert face in QWEN_REMOVAL_NOTE, face
    assert IMPLEMENTATION_DISPOSITION["qwen"] == "removed-by-ruling"


def test_dispositions_match_the_brand_priority_ruling():
    assert IMPLEMENTED_BRANDS == ("pi", "codex", "claude")
    for brand in ("hermes", "opencode", "dsh", "kilo"):
        assert IMPLEMENTATION_DISPOSITION[brand] == "phase2-design", brand


    with pytest.raises(KeyError):
        statement_for("mystery-brand")
