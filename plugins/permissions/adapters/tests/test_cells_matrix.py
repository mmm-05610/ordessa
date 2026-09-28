"""T03 red/green: capability cells and the per-brand fill-in matrix.

`harness-adapters.md` requires every cell of the per-brand table to be filled
with evidence or marked `UNKNOWN`, and the success criterion forbids an
"unknown marked green". These tests enforce exactly that over `cells.py` and
`matrix.py`: a `supported` cell must name repo evidence **and** every matrix
field it declares as required must be non-UNKNOWN; a cell without evidence may
only be `unsupported`/`unknown` - and the adapters must then refuse, never
allow, for that capability.
"""
from __future__ import annotations

import pytest

from ordessa_permissions_adapters import (
    BRAND_MATRIX,
    CAPABILITY_CELLS,
    MATRIX_FIELDS,
    UNKNOWN,
    ClaudeAdapter,
    CodexAdapter,
    MatrixCell,
    PiAdapter,
    SupportOutcome,
)

BRANDS = ("pi", "codex", "claude-code")
CELL_STATUSES = {"supported", "unsupported", "unknown"}


def cells(harness: str, capability: str):
    return [c for c in CAPABILITY_CELLS if c.harness_id == harness
            and c.capability == capability]


def test_matrix_shape() -> None:
    assert set(BRAND_MATRIX) == set(BRANDS)
    for brand, row in BRAND_MATRIX.items():
        assert set(row) == set(MATRIX_FIELDS), brand
        for field, cell in row.items():
            assert isinstance(cell, MatrixCell), (brand, field)
            if cell.evidence is None:
                assert cell.value == UNKNOWN, f"{brand}.{field} claims {cell.value!r} without evidence"
            else:
                assert cell.value != UNKNOWN
                assert ":" in cell.evidence, "evidence must name file:line"


def test_no_supported_cell_is_unproven() -> None:
    for cell in CAPABILITY_CELLS:
        assert cell.status in CELL_STATUSES, cell
        if cell.status == "supported":
            assert cell.evidence, f"{cell.harness_id}/{cell.capability} supported without evidence"
            row = BRAND_MATRIX[cell.harness_id]
            for field in cell.required_matrix_fields:
                assert row[field].value != UNKNOWN, \
                    f"{cell.harness_id}/{cell.capability} green on UNKNOWN {field}"
        else:
            # unsupported/unknown cells never lean on a green claim
            assert cell.status != "supported"


def test_pre_effect_gate_is_not_claimed_for_any_brand() -> None:
    # G1 (api-requests.md): there is no pre-effect authorization gate in this
    # tree, so no brand may have a supported gate cell here.
    for brand in BRANDS:
        for cell in cells(brand, "pre-effect-gate"):
            assert cell.status in {"unknown", "unsupported"}, cell
            assert cell.status != "supported"


def test_pi_compile_without_extension_evidence_only_refuses() -> None:
    # "Cells without evidence ... must support ONLY explicit refusal - never
    # allow" - the Pi compile cell is evidence-free for a bare Pi.
    pi_cells = cells("pi", "policy-compile")
    assert pi_cells and all(c.status in {"unsupported", "unknown"} for c in pi_cells)
    adapter = PiAdapter()
    from ordessa_permissions_adapters import (
        PolicyCompileSnapshot, SupportEvidence,
    )
    from _permissions_adapters_helpers import make_ceiling
    result = adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id="pi", native_version="2.0", ceiling=make_ceiling()))
    assert result.outcome == "refusal"
    assert not hasattr(result, "fields"), "no intent may be emitted for an unevidenced cell"


def test_every_unsupported_or_unknown_answer_is_named() -> None:
    # unsupported and unknown are distinct outcomes and every one of them
    # carries a reason (FR-09: stable code + understandable diagnostic).
    for adapter in (PiAdapter(), CodexAdapter(), ClaudeAdapter()):
        report = adapter.supports(None)
        assert report.outcome in {SupportOutcome.UNSUPPORTED, SupportOutcome.UNKNOWN}
        assert report.reason and report.code


def test_matrix_covers_the_twelve_recorded_fields() -> None:
    assert MATRIX_FIELDS == (
        "harness_binary_pin", "native_adapter_version", "os", "entry_point",
        "tool_coverage", "administrator_ceiling", "scope", "application_path",
        "reset_default", "observed_receipt", "negative_probe",
        "cross_session_impact",
    )
    # honestly UNKNOWN in this tree (no evidence): OS, receipt plumbing and
    # cross-session behaviour for every brand.
    for brand in BRANDS:
        for field in ("os", "cross_session_impact"):
            assert BRAND_MATRIX[brand][field].value == UNKNOWN, (brand, field)
        assert BRAND_MATRIX[brand]["harness_binary_pin"].value != UNKNOWN
