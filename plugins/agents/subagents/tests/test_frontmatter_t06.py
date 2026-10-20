"""T06 — strict frontmatter codec: round-trip proof + hostile-input refusals.

Positive column: everything the codec emits parses back identically. Negative
column (the load-bearing one): every complex/ambiguous YAML shape is
REFUSED with a typed error, not approximated — this is the L1 evidence that
no `!!python/object`, nested map, block scalar, CRLF, BOM, duplicate key or
unbalanced quote can sneak into a managed Claude document (G11).
"""
from __future__ import annotations

import pytest

from ordessa_assets_subagents import errors
from ordessa_assets_subagents.adapters import frontmatter
from ordessa_assets_subagents.adapters.frontmatter import (
    FrontmatterRefusal,
    emit_frontmatter,
    parse_frontmatter,
)

ROUND_TRIP_FIELDS = [
    ({"name": "code-reviewer"}, ""),
    ({"name": "a.b-c_d1", "description": "plain"}, "Body text."),
    ({"name": "x", "description": 'He said "hi" \\ ok'}, "line1\nline2\n"),
    ({"name": "x", "tools": ["read", "grep", "term:run"]}, "body"),
    ({"name": "x", "tools": ["a"], "model": "owner/model.rev:1"}, ""),
    ({"description": "tabs\there and\nnewlines\r\n-free"}, "b"),  # \r\n in body? no
    ({"description": "unicode ✓ 日本語 𝓧 non-bmp 🜲"}, "✓"),
    ({"description": "colon: inside value"}, "body"),
    ({"description": "# not a comment"}, "body"),
    ({"description": "trailing space "}, "body "),
    ({"description": "\b\f control escapes"}, "ok"),
]


@pytest.mark.parametrize("fields,body", ROUND_TRIP_FIELDS)
def test_emit_then_parse_is_identity(fields: dict, body: str):
    text = emit_frontmatter(fields, body)
    parsed_fields, parsed_body = parse_frontmatter(text)
    expected = {k: (v if isinstance(v, str) else tuple(v)) for k, v in fields.items()}
    assert parsed_fields == expected
    assert parsed_body == body


def test_block_list_form_parses_to_same_tuple_as_flow_form():
    flow = emit_frontmatter({"name": "x", "tools": ["a", "b"]}, "body")
    block = "---\nname: \"x\"\ntools:\n  - \"a\"\n  - \"b\"\n---\nbody"
    assert parse_frontmatter(flow) == parse_frontmatter(block)


# -- hostile inputs: every one refused, none approximated ----------------------

HOSTILE = {
    "no opening fence": "name: \"x\"\n---\nbody",
    "unclosed fence": "---\nname: \"x\"\nbody",
    "empty frontmatter": "---\n---\nbody",
    "crlf document": "---\r\nname: \"x\"\r\n---\r\nbody",
    "lone cr": "---\nname: \"x\"\n---\rbody",
    "bom prefix": "﻿---\nname: \"x\"\n---\nbody",
    "tab in line": "---\nname:\t\"x\"\n---\nbody",
    "tab indent": "---\n\tname: \"x\"\n---\nbody",
    "duplicate keys": "---\nname: \"a\"\nname: \"b\"\n---\nbody",
    "python object tag": "---\ndescription: !!python/object:os.system\n---\nbody",
    "block scalar": "---\ndescription: |\n  multi\n  line\n---\nbody",
    "folded scalar": "---\ndescription: >\n  folded\n---\nbody",
    "flow map": "---\ndescription: {a: 1}\n---\nbody",
    "nested map": "---\ntools:\n  read: true\n---\nbody",
    "unquoted scalar": "---\nname: bare\n---\nbody",
    "single quoted": "---\nname: 'x'\n---\nbody",
    "unbalanced quote": "---\nname: \"unclosed\n---\nbody",
    "trailing after quote": "---\nname: \"x\" junk\n---\nbody",
    "multiline quoted value": "---\nname: \"two\nlines\"\n---\nbody",
    "comment line": "---\n# note\nname: \"x\"\n---\nbody",
    "blank line inside": "---\nname: \"x\"\n\nkey2: \"y\"\n---\nbody",
    "empty flow list": "---\ntools: []\n---\nbody",
    "flow list unbalanced": "---\ntools: [\"a\", \"b\"\n---\nbody",
    "flow list bare item": "---\ntools: [a]\n---\nbody",
    "flow list comma sep without space": "---\ntools: [\"a\",\"b\"]\n---\nbody",
    "unknown escape": "---\nname: \"a\\qb\"\n---\nbody",
    "bad unicode escape": "---\nname: \"a\\u00zz\"\n---\nbody",
    "lone surrogate escape": "---\nname: \"a\\ud800\"\n---\nbody",
    "nul byte": "---\nname: \"a\x00b\"\n---\nbody",
    "anchor": "---\nname: &anchor x\n---\nbody",
    "directive inside": "---\n%YAML 1.2\nname: \"x\"\n---\nbody",
    "key with dot": "---\na.b: \"x\"\n---\nbody",
    "indented key": "---\n  name: \"x\"\n---\nbody",
    "block list empty": "---\ntools:\n---\nbody",
    "block list bare items": "---\ntools:\n  - a\n---\nbody",
    "equals token": "---\nname=a\n---\nbody",
}


@pytest.mark.parametrize("text", list(HOSTILE.values()), ids=list(HOSTILE))
def test_hostile_frontmatter_is_refused_not_approximated(text: str):
    with pytest.raises(errors.DomainError) as excinfo:
        parse_frontmatter(text)
    assert isinstance(excinfo.value, FrontmatterRefusal)
    assert excinfo.value.code == errors.DEFINITION_INVALID


def test_emitter_refuses_what_it_cannot_prove_round_trips():
    with pytest.raises(errors.DomainError):
        emit_frontmatter({"bad key": "v"}, "body")     # space in key
    with pytest.raises(errors.DomainError):
        emit_frontmatter({}, "body")                    # no fields
    with pytest.raises(errors.DomainError):
        emit_frontmatter({"name": "x"}, "body\x00")     # NUL in body
    with pytest.raises(errors.DomainError):
        emit_frontmatter({"name": "x"}, "a\r\nb")       # CRLF in body
    with pytest.raises(errors.DomainError):
        emit_frontmatter({"name": "x"}, "before\n---\nafter")  # fence in body
    with pytest.raises(errors.DomainError):
        emit_frontmatter({"name": 5}, "body")           # non-str value
    with pytest.raises(errors.DomainError):
        emit_frontmatter({"name": "x"}, "b\ud800")      # lone surrogate


def test_refusal_names_the_offending_field():
    with pytest.raises(errors.DomainError) as excinfo:
        parse_frontmatter('---\nmodel: |\n  block\n---\nb')
    assert excinfo.value.item_id == "model"


def test_body_is_preserved_verbatim():
    body = "# Reviewer\n\nDo *this*:\n\n- one\n- two\n"
    text = emit_frontmatter({"name": "x"}, body)
    assert parse_frontmatter(text)[1] == body
