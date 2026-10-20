"""T07 — TOML writer: adversarial round-trip equals the input (L1 proof).

Every document this writer emits is re-parsed with stdlib `tomllib` and
compared to the intended structure inside `render_document` itself; these
tests hammer that with the shapes that break naive hand-rolled writers —
embedded quotes, backslashes, control bytes, `]`, `#`, non-BMP codepoints —
and prove the refusals for what TOML (or this writer's schema) cannot
represent. This is the L1 evidence the Codex format is right without the
Codex CLI (which is absent, so no L2-exec exists).
"""
from __future__ import annotations

import tomllib

import pytest

from ordessa_assets_subagents import errors
from ordessa_assets_subagents.adapters.tomlwriter import (
    TomlRefusal,
    quote_string,
    render_document,
    verify_roundtrip,
)

ADVERSARIAL_VALUES = [
    'plain',
    'He said "hi"',
    "single 'quotes' too",
    "back\\slash and \\\" combo",
    "newline\ninside",
    "tab\tinside",
    "carriage\rreturn",
    "form\ffeed and \bbackspace",
    "nul-adjacent \x01 \x1f control",
    "DEL \x7f",
    "closing ] bracket and [ opening",
    "# hash lead and mid#",
    "= equals sign =",
    "unicode ✓ 日本語",
    "non-BMP 𝓧 𝕌𝓝𝓘𝓒𝓞𝓓𝓮 🜲",
    "emoji 🎉",
    "quote-ending string at end\"",
    "trailing backslash\\",
    "dotted.key=with:colons",
    "",
]


@pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
def test_string_value_round_trips_through_stdlib_tomllib(value: str):
    text = render_document({"name": value})
    assert tomllib.loads(text) == {"name": value}


@pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
def test_string_array_items_round_trip(value: str):
    doc = {"tools": [value, "other"], "name": "x"}
    parsed = tomllib.loads(render_document(doc))
    assert parsed == {"tools": [value, "other"], "name": "x"}


def test_nul_is_refused_not_dropped():
    with pytest.raises(errors.DomainError) as excinfo:
        quote_string("a\x00b", item="x")
    assert excinfo.value.code == errors.DEFINITION_INVALID
    assert "NUL" in excinfo.value.detail


def test_scalar_types_render_and_verify():
    doc = {"flag": True, "off": False, "count": -17, "name": "a"}
    text = render_document(doc)
    parsed = tomllib.loads(text)
    assert parsed["flag"] is True and isinstance(parsed["flag"], bool)
    assert parsed["off"] is False
    assert parsed["count"] == -17


def test_tables_render_and_verify():
    doc = {"name": "top", "profile": {"name": "p", "enabled": True}}
    parsed = tomllib.loads(render_document(doc))
    assert parsed == {"name": "top", "profile": {"name": "p", "enabled": True}}


# -- refusals: schema and grammar ----------------------------------------------


def test_unsupported_value_types_are_refused():
    for bad_doc in ({"a": 1.5}, {"a": None}, {"a": {}}, {"a": []}, {"a": b"bytes"},
                    {"a": {"b": {"c": 1}}}, {"a": (2 ** 63,)}):
        with pytest.raises(errors.DomainError):
            render_document(bad_doc)


def test_key_grammar_is_enforced():
    # (uppercase is legal in TOML bare keys, so it is *not* in this list; the
    # agent-name grammar refusal lives in the adapters, not the writer)
    for bad_key in ("a b", "a.b", "/abs", "~home", "", "a$b", "中文", "a]b"):
        with pytest.raises(errors.DomainError):
            render_document({bad_key: "v"})


def test_empty_document_refused():
    with pytest.raises(errors.DomainError):
        render_document({})
    with pytest.raises(errors.DomainError):
        render_document("not a mapping")  # type: ignore[arg-type]


def test_table_name_grammar_enforced():
    with pytest.raises(errors.DomainError):
        render_document({"bad table": {"k": "v"}})


# -- the validator is real: it catches a lying emitter --------------------------


def test_verify_roundtrip_catches_tampered_text():
    doc = {"name": "intended"}
    with pytest.raises(errors.DomainError) as excinfo:
        verify_roundtrip(doc, 'name = "tampered"\n')
    assert "differs from the intended structure" in excinfo.value.detail


def test_verify_roundtrip_catches_unparseable_text():
    with pytest.raises(errors.DomainError) as excinfo:
        verify_roundtrip({"name": "x"}, "this is not toml [[[\n")
    assert "does not parse" in excinfo.value.detail


def test_verify_roundtrip_catches_unescaped_raw_control_text():
    # text that LOOKS like our output but carries a raw newline inside the
    # string: not parseable TOML, so the validator must refuse it.
    with pytest.raises(errors.DomainError):
        verify_roundtrip({"name": "a\nb"}, 'name = "a\nb"\n')


def test_deterministic_output_bytes():
    doc = {"b": "2", "a": "1"}
    assert render_document(doc) == render_document({"b": "2", "a": "1"})
