"""AC-2: the frontmatter validator speaks the Agent Skills specification.

The legacy regex parser accepted only flat scalars and refused legal skills;
these tests pin the canonical behaviour: required fields, the name rules,
optional nested `metadata`, retained unknown fields, and typed refusals.

Ported from `plugins/assets/tests/test_frontmatter_spec.py` @ 752f148b1b
(imports repointed `ordessa_assets.contracts` -> `ordessa_skills.api`; every
assertion unchanged).
"""
from __future__ import annotations

import pytest

from ordessa_skills.api.errors import SkillAssetError
from ordessa_skills.formats.agent_skills.frontmatter import parse_frontmatter

MINIMAL = "---\nname: hello-world\ndescription: Says hello.\n---\n\n# Hello\n"


def test_minimal_skill_parses_to_the_two_required_fields():
    facts = parse_frontmatter(MINIMAL)
    assert facts.name == "hello-world"
    assert facts.description == "Says hello."
    assert facts.metadata == {}
    assert facts.body.strip().startswith("# Hello")


def test_official_optional_nested_metadata_passes_and_is_preserved():
    text = (
        "---\nname: hello-world\ndescription: Says hello.\n"
        "license: MIT\ncompatibility: needs bash\nallowed-tools: Bash(read) WebFetch\n"
        "metadata:\n  author: someone\n  version: \"2\"\n---\nbody\n"
    )
    facts = parse_frontmatter(text)
    assert facts.metadata == {"author": "someone", "version": "2"}
    assert facts.retained["license"] == "MIT"
    assert facts.retained["compatibility"] == "needs bash"
    assert facts.retained["allowed-tools"] == "Bash(read) WebFetch"


def test_unknown_but_legal_fields_are_retained_not_rejected():
    text = "---\nname: hello-world\ndescription: d\ncustom-extra: keep me\n---\n"
    facts = parse_frontmatter(text)
    assert facts.retained["custom-extra"] == "keep me"


@pytest.mark.parametrize("text,code", [
    ("no fences at all", "SKILL_FRONTMATTER_MISSING"),
    ("---\nname: x\n", "SKILL_FRONTMATTER_MISSING"),
    ("---\n[name]: x\ndescription: d\n---\n", "SKILL_FRONTMATTER_INVALID"),
    ("---\n- a\n- b\n---\n", "SKILL_FRONTMATTER_INVALID"),
    ("---\nname: x\nname: y\ndescription: d\n---\n", "SKILL_FRONTMATTER_INVALID"),
])
def test_structural_refusals_are_typed(text, code):
    with pytest.raises(SkillAssetError) as refusal:
        parse_frontmatter(text)
    assert refusal.value.code == code


@pytest.mark.parametrize("name", [
    "", "UPPER", "-lead", "trail-", "dou--ble", "a" * 65, "under_score", "space out",
])
def test_illegal_names_are_refused(name):
    text = f"---\nname: {name}\ndescription: d\n---\n"
    with pytest.raises(SkillAssetError) as refusal:
        parse_frontmatter(text)
    assert refusal.value.code == "SKILL_NAME_INVALID"


@pytest.mark.parametrize("name", ["a", "a1", "a-b-c", "0-9", "a" * 64])
def test_legal_names_pass(name):
    facts = parse_frontmatter(f"---\nname: {name}\ndescription: d\n---\n")
    assert facts.name == name


def test_description_bounds():
    with pytest.raises(SkillAssetError) as missing:
        parse_frontmatter("---\nname: ok\n---\n")
    assert missing.value.code == "SKILL_DESCRIPTION_MISSING"
    with pytest.raises(SkillAssetError) as long:
        parse_frontmatter(f"---\nname: ok\ndescription: {'x' * 1025}\n---\n")
    assert long.value.code == "SKILL_DESCRIPTION_INVALID"
    parse_frontmatter(f"---\nname: ok\ndescription: {'x' * 1024}\n---\n")


def test_compatibility_bound_is_enforced():
    with pytest.raises(SkillAssetError) as refusal:
        parse_frontmatter(
            "---\nname: ok\ndescription: d\ncompatibility: " + "x" * 501 + "\n---\n")
    assert refusal.value.code == "SKILL_FRONTMATTER_INVALID"


def test_metadata_must_map_strings_to_strings():
    with pytest.raises(SkillAssetError) as refusal:
        parse_frontmatter(
            "---\nname: ok\ndescription: d\nmetadata:\n  count: 3\n---\n")
    assert refusal.value.code == "SKILL_FRONTMATTER_INVALID"


def test_oversized_frontmatter_is_refused_before_parsing():
    text = "---\nname: ok\ndescription: d\njunk: " + "x" * (64 * 1024 + 1) + "\n---\n"
    with pytest.raises(SkillAssetError) as refusal:
        parse_frontmatter(text)
    assert refusal.value.code == "SKILL_FRONTMATTER_INVALID"


def test_directory_name_must_match_the_frontmatter_name():
    with pytest.raises(SkillAssetError) as refusal:
        parse_frontmatter(MINIMAL, directory_name="other-name")
    assert refusal.value.code == "SKILL_NAME_MISMATCH"
    parse_frontmatter(MINIMAL, directory_name="hello-world")
