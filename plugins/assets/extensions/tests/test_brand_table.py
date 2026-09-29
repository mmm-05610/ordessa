"""EXT-4 — the eight-brand hooks support table with per-cell evidence."""
from __future__ import annotations

import pytest

from ordessa_extensions.capabilities import (
    AXES, BRAND_STATEMENTS, IMPLEMENTATION_DISPOSITION, IMPLEMENTED_BRANDS,
    SUPPORTED, UNKNOWN, UNSUPPORTED, QWEN_REMOVAL_NOTE, all_brand_rows,
    statement_for,
)

TOML = "plugins/harness/src/ordessa_harness/harnesses.toml"


def test_every_brand_is_accounted_for():
    assert set(all_brand_rows()) == {"pi", "codex", "claude", "hermes",
                                     "opencode", "dsh", "kilo", "qwen"}
    assert set(BRAND_STATEMENTS) | {"qwen"} == set(all_brand_rows())


def test_every_cell_of_every_graded_brand_is_complete_and_cited():
    import re
    for harness_id, statement in BRAND_STATEMENTS.items():
        assert set(statement.facts) == set(AXES), harness_id
        for axis, fact in statement.facts.items():
            assert fact.axis == axis
            if fact.value == SUPPORTED:
                assert fact.evidence != "no in-repo evidence", (harness_id,
                                                                axis)
            if fact.evidence != "no in-repo evidence":
                assert re.search(r"[\w./+-]+:\d+", fact.evidence), (
                    harness_id, axis, fact.evidence)


def test_only_codex_and_claude_have_a_native_slot():
    assert statement_for("codex").value("native_slot") == SUPPORTED
    assert statement_for("claude").value("native_slot") == SUPPORTED
    for brand in ("pi", "hermes", "opencode", "dsh", "kilo"):
        assert statement_for(brand).value("native_slot") == UNSUPPORTED, brand


def test_projection_path_is_unsupported_everywhere_runtime_gap():
    # first-hand in-repo: registry parses hooks_target/hooks_key but no
    # runtime consumer exists — registered as AR-3
    for harness_id in BRAND_STATEMENTS:
        assert statement_for(harness_id).value("projection_path") == \
            UNSUPPORTED, harness_id


def test_blocking_semantics_cell_is_unsupported_on_every_face():
    # EXT-6: no brand face supports an enforcement claim
    for harness_id in BRAND_STATEMENTS:
        assert statement_for(harness_id).value("blocking_semantics") == \
            UNSUPPORTED, harness_id
        assert "classification.md" in \
            statement_for(harness_id).fact("blocking_semantics").evidence


def test_qwen_row_is_the_removal_note_not_a_grade():
    assert "qwen" not in BRAND_STATEMENTS
    assert "已除名" in QWEN_REMOVAL_NOTE
    assert IMPLEMENTATION_DISPOSITION["qwen"] == "removed-by-ruling"


def test_implementation_dispositions_match_brand_priority_ruling():
    assert IMPLEMENTATION_DISPOSITION["codex"] == "implement"
    assert IMPLEMENTATION_DISPOSITION["claude"] == "implement"
    assert IMPLEMENTATION_DISPOSITION["pi"] == "ar-registered"
    for brand in ("hermes", "opencode", "dsh", "kilo"):
        assert IMPLEMENTATION_DISPOSITION[brand] == "phase2-design", brand
    assert IMPLEMENTED_BRANDS == ("codex", "claude")


def test_unknown_brand_gets_no_synthesized_grade():
    with pytest.raises(KeyError):
        statement_for("mystery-brand")
