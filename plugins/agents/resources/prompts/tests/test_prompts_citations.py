"""Round-3: the capability table's citations must be FALSIFIABLE.

A citation that is never opened is document-grade, not evidence-grade.
These spot-checks open the cited files and assert the claimed fact
actually sits at the cited line — the same standard the EXT review
demanded. They deliberately check a SMALL, stable subset (line-precise);
wholesale re-derivation belongs to the doc owners.
"""
from __future__ import annotations

from pathlib import Path

from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog

REPO = Path(__file__).resolve().parents[5]
TOML = capture_selected_harness_catalog().registry_bytes.decode("utf-8")
SCHEMA = REPO / "packages/execution/agents/src/ordessa_agents/harness/providers/declarations/schema.py"
HM = REPO / "docs/implementation/design/prompts/harness-adapters.md"


def _line(path: Path | str, number: int) -> str:
    text = path.read_text(encoding="utf-8") if isinstance(path, Path) else path
    return text.splitlines()[number - 1]


# Test-only migration audit; not a production resolver for historical evidence.
# Startup source already had version_probe at107 and a Grok comment at405.
# Intended Claude/Pi mappings follow the implemented three-brand statement,
# NOT a claim that the old physical line citations were valid.
_INSTRUCTION_CITATION_AUDIT = ((31, 'codex', 'plugins/harness/codex/src/ordessa_harness_codex/_registration_declarations/harness.toml', 29, 'd7fd08ac9b26dd2f62abdcaecfdbaf1d647c4be2c07983786b4905878221ad52'), (107, 'claude-code', 'plugins/harness/claude-code/src/ordessa_harness_claude_code/_registration_declarations/harness.toml', 35, '506b5f2d39f76e6d367c21ccb28cc56f0007aed7a0fd56c1e24367deefc747bf'), (405, 'pi', 'plugins/harness/pi/src/ordessa_harness_pi/_registration_declarations/harness.toml', 33, '17ea491648af8f9f75815790f24d4f64b2f937e4f767751fa124b2b77debada7'))


def _checked_instruction_slot(text: str, number: int) -> str:
    line = _line(text, number)
    assert line.startswith("slots ="), (number, line)
    assert "instruction" in line, number
    return line


def test_toml_slot_lines_name_instruction():
    import hashlib
    import tomllib

    captured = {row["identity"]["harness_type"]: row
                for row in tomllib.loads(TOML)["harness"]}
    assert {brand for _, brand, _, _, _ in _INSTRUCTION_CITATION_AUDIT} == {
        "codex", "claude-code", "pi"}
    for historical_label, brand, relative, number, expected_sha in _INSTRUCTION_CITATION_AUDIT:
        raw = (REPO / relative).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected_sha, historical_label
        text = raw.decode("utf-8")
        assert "instruction" in _checked_instruction_slot(text, number), number
        own = tomllib.loads(text)["harness"]
        assert len(own) == 1
        assert own[0]["identity"]["harness_type"] == brand
        assert captured[brand]["profile"]["slots"] == own[0]["profile"]["slots"]
        assert "instruction" in captured[brand]["profile"]["slots"]


def test_wrong_physical_line_is_not_accepted_as_instruction_evidence():
    import pytest

    # Preserve rejection of the two already-stale historical lines in actual
    # captured bytes, and explicit unrelated-line counterexamples.
    for number in (107, 405):
        with pytest.raises(AssertionError):
            _checked_instruction_slot(TOML, number)
    for text in ('version_probe = ["--version"]', '# instruction claim only',
                 'slots = ["skill"]'):
        with pytest.raises(AssertionError):
            _checked_instruction_slot(text, 1)


def test_instruction_citation_audit_does_not_upgrade_semantic_support():
    from ordessa_prompts.harness_adapters.capabilities import UNKNOWN, statement_for

    for _, brand, _, _, _ in _INSTRUCTION_CITATION_AUDIT:
        # The historical Prompts statement id remains "claude"; its current
        # declaration resource is owned by the canonical claude-code brand.
        statement = statement_for("claude" if brand == "claude-code" else brand)
        assert statement.value("instruction") == UNKNOWN
        assert ":31,107,405" in statement.cells["instruction"].evidence


def test_toml_has_no_instruction_target_anywhere():
    # the GAP claim: zero instruction target declarations in the registry
    text = TOML
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
    harness_src = REPO / "plugins/harness"
    sources = [path for path in harness_src.rglob("*.py")
               if "src" in path.relative_to(harness_src).parts
               and "build" not in path.relative_to(harness_src).parts]
    assert sources, "the actual brand source scan must not be empty"
    assert SCHEMA.is_file()
    sources.append(SCHEMA)
    offenders = []
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "instruction_target" in text or "instruction_key" in text:
            offenders.append(str(path.relative_to(REPO)))
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
