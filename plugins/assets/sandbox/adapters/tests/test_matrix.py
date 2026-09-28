"""T05 — per-cell adapter matrix (harness-adapters.md §逐品牌测试填表).

Every capability cell records the twelve required fields; wherever this tree
gives no proof the value is exactly ``UNKNOWN`` and the cell may NOT be marked
``supported``/green. An UNKNOWN cell is never treated as proven isolation — the
success criteria forbid "unknown marked green".
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from ordessa_sandbox_api import CellStatus, MATRIX_CELL_FIELDS

from ordessa_sandbox_adapters import (
    ADAPTER_CAPABILITY_CELLS,
    MATRIX_FIELDS,
    UNKNOWN_FIELD,
    AdapterCapabilityCell,
)


def test_the_twelve_matrix_fields_match_the_domain_contract():
    assert MATRIX_FIELDS == tuple(MATRIX_CELL_FIELDS)
    assert len(MATRIX_FIELDS) == 12


def test_every_cell_carries_the_twelve_fields():
    for cell in ADAPTER_CAPABILITY_CELLS:
        assert isinstance(cell, AdapterCapabilityCell)
        for name in MATRIX_FIELDS:
            assert hasattr(cell.fields, name)


def test_three_brands_are_present():
    brands = {cell.harness_id for cell in ADAPTER_CAPABILITY_CELLS}
    assert {"codex", "claude-code", "pi"} <= brands


def test_no_supported_cell_is_green_without_evidence_or_on_unknown():
    for cell in ADAPTER_CAPABILITY_CELLS:
        if cell.status is CellStatus.SUPPORTED:
            assert cell.evidence, f"{cell.harness_id}/{cell.capability} green w/o evidence"
            for field in cell.required_matrix_fields:
                value = getattr(cell.fields, field)
                assert value != UNKNOWN_FIELD, (
                    f"{cell.harness_id}/{cell.capability} is supported but "
                    f"required field {field!r} is UNKNOWN")


def test_unknown_cells_never_assert_a_value():
    # a field that cannot be proven stays the literal UNKNOWN, not a guess
    for cell in ADAPTER_CAPABILITY_CELLS:
        for field in MATRIX_FIELDS:
            value = getattr(cell.fields, field)
            assert isinstance(value, str) and value.strip()
            if value == UNKNOWN_FIELD:
                # UNKNOWN is only ever admissible on a non-green cell
                assert cell.status is not CellStatus.SUPPORTED or \
                    field not in cell.required_matrix_fields


def test_pi_and_effect_rows_are_honestly_not_supported():
    # Pi has no built-in native sandbox and no adapter may certify it green;
    # the per-brand native-effect rows are UNKNOWN pending T05 probes.
    pi_compile = next(c for c in ADAPTER_CAPABILITY_CELLS
                      if c.harness_id == "pi" and c.capability == "config-compile")
    assert pi_compile.status is CellStatus.UNSUPPORTED
    effect_rows = [c for c in ADAPTER_CAPABILITY_CELLS
                   if c.capability == "native-effect-verify"]
    assert effect_rows and all(c.status is not CellStatus.SUPPORTED
                               for c in effect_rows)


# ------------------------------------------------------------- T022 guards
# A cell may only be SUPPORTED because of evidence that EXISTS: every
# `tests/test_*.py[::test_id]` citation in any cell must resolve to a real
# file and a real test function in this package, and the applied-effect
# fields of a supported cell must name a QUALIFIED test id, not a bare file
# (the pre-T022 matrix cited `tests/test_controlled_c4_l2.py` while no such
# test existed — that fake-green must never come back).

_TEST_ID = re.compile(
    r"tests/(?P<file>test_[a-z0-9_]+\.py)(?:::(?P<func>test_[A-Za-z0-9_]+))?")
_QUALIFIED_FIELDS = ("application_path", "observed_receipt", "negative_probe")
_TESTS_DIR = Path(__file__).resolve().parent


def _cell_texts(cell: AdapterCapabilityCell):
    yield "evidence", cell.evidence or ""
    yield "note", cell.note or ""
    for name in MATRIX_FIELDS:
        yield name, getattr(cell.fields, name)


def test_every_cited_test_file_and_test_id_exists():
    for cell in ADAPTER_CAPABILITY_CELLS:
        for where, text in _cell_texts(cell):
            for match in _TEST_ID.finditer(text):
                path = _TESTS_DIR / match["file"]
                assert path.is_file(), (
                    f"{cell.harness_id}/{cell.capability}.{where} cites "
                    f"missing test file {match['file']}")
                if match["func"]:
                    body = path.read_text(encoding="utf-8")
                    assert f"def {match['func']}(" in body, (
                        f"{cell.harness_id}/{cell.capability}.{where} cites "
                        f"missing test id {match['file']}::{match['func']}")


def test_supported_apply_effect_fields_name_an_existing_test_id():
    # "upgraded to supported" == naming a proof that exists, at id level
    for cell in ADAPTER_CAPABILITY_CELLS:
        if cell.status is not CellStatus.SUPPORTED:
            continue
        for name in _QUALIFIED_FIELDS:
            if name not in cell.required_matrix_fields:
                continue
            value = getattr(cell.fields, name)
            assert value != UNKNOWN_FIELD, (
                f"{cell.harness_id}/{cell.capability} supported while "
                f"{name} is UNKNOWN")
            assert re.search(r"tests/test_[a-z0-9_]+\.py::test_[A-Za-z0-9_]+",
                             value), (
                f"{cell.harness_id}/{cell.capability}.{name} must cite a "
                "qualified tests/test_*.py::test_* id to back a supported "
                "application/receipt/negative claim")


def test_controlled_fixture_cells_never_read_as_production():
    for cell in ADAPTER_CAPABILITY_CELLS:
        if "controlled-fixture" in cell.capability:
            assert "CONTROLLED FIXTURE ONLY" in cell.note, (
                f"{cell.harness_id}/{cell.capability} must state it is a "
                "controlled fixture, not a production path")


def test_production_observation_gaps_stay_unknown():
    # the production installation observer, the real native effect/readback
    # and cross-instance atomicity remain unproven in this tree: the
    # per-brand native-effect-verify rows stay UNKNOWN and no cell may
    # claim a production application path
    for cell in ADAPTER_CAPABILITY_CELLS:
        if cell.capability == "native-effect-verify":
            assert cell.status is CellStatus.UNKNOWN
            assert cell.evidence is None
        assert "production application" not in (cell.evidence or "")
    # every UNKNOWN sentinel in a SUPPORTED cell is outside its required
    # fields (unknown is never coerced into a protected claim)
    for cell in ADAPTER_CAPABILITY_CELLS:
        if cell.status is not CellStatus.SUPPORTED:
            continue
        for name in MATRIX_FIELDS:
            value = getattr(cell.fields, name)
            if value == UNKNOWN_FIELD:
                assert name not in cell.required_matrix_fields
