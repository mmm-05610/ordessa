"""Round-3: the capability table's citations must be FALSIFIABLE.

A citation that is never opened is document-grade, not evidence-grade.
These spot-checks open the cited files and assert the claimed fact
actually sits at the cited line — the same standard the EXT review
demanded. They deliberately check a SMALL, stable subset (line-precise);
wholesale re-derivation belongs to the doc owners.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
TOML = REPO / "plugins/harness/src/ordessa_harness/harnesses.toml"
SCHEMA = REPO / "plugins/harness/src/ordessa_harness/registry/schema.py"
HM = REPO / "docs/design/prompts/harness-adapters.md"


def _line(path: Path, number: int) -> str:
    return path.read_text(encoding="utf-8").splitlines()[number - 1]


def test_toml_slot_lines_name_instruction():
    # cited as {TOML}:31,107,405 (slots lists carrying "instruction")
    for number in (31, 107, 405):
        assert "instruction" in _line(TOML, number), number


def test_toml_has_no_instruction_target_anywhere():
    # the GAP claim: zero instruction target declarations in the registry
    text = TOML.read_text(encoding="utf-8")
    assert "instruction_target" not in text
    assert "instruction_key" not in text
    # contrast: the other slots DO declare targets
    assert "skill_target" in text and "mcp_target" in text
    assert "hooks_target" in text


def test_no_instruction_target_consumer_in_harness_src():
    # the GAP claim, at full strength: NO harness source file at all
    # references an instruction target (registry schema included — the
    # schema never parses one, which is the claim). Line-precise
    # spot-checks above deliberately hardcode line numbers: a doc/registry
    # edit that shifts them turns these red ON PURPOSE, forcing the
    # citations to be re-pinned together with the facts they vouch for.
    harness_src = REPO / "plugins/harness/src"
    offenders = []
    for path in harness_src.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "instruction_target" in text or "instruction_key" in text:
            offenders.append(str(path.relative_to(harness_src)))
    assert offenders == []


def test_schema_line_64_is_the_profile_field_gate():
    # cited as registry/schema.py:64 — the field-set check that would
    # have to name an instruction target field and does not
    line = _line(SCHEMA, 64)
    assert "native_home" in line and "slots" in line
    assert "instruction_target" not in line


def test_harness_adapters_md_lines_carry_the_rulings():
    # HM:9 persona rule; HM:7 replacement scope; HM:15-17 vendor routes
    assert "persona" in _line(HM, 9)
    assert "system-replacement" in _line(HM, 7) or "替换" in _line(HM, 7)
    assert "APPEND_SYSTEM" in _line(HM, 15)
    assert "developer_instructions" in _line(HM, 16)
    assert "preset" in _line(HM, 17)
