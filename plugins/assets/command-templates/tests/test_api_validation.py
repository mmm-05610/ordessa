"""T03 / G01 / G02 / G20: DTO + schema refuse bad ids, bodies and reads.

Covers: invalid id/slug rejection, oversize and bad-encoding body rejection,
cross-owner (unauthorized) read refusal — and that a plain CRUD round-trip works
with only this domain present.
"""
from __future__ import annotations

import pytest

from ordessa_command_templates.api import dto, schema
from ordessa_command_templates.api.errors import (
    InvalidDocumentError,
    InvalidIdentifierError,
    UnauthorizedTargetError,
)
from conftest import make_template


def test_valid_and_invalid_ids():
    assert schema.validate_template_id("tmpl.review-1_a") == "tmpl.review-1_a"
    for bad in ["", "Upper", "has space", "no__double_underscore_ok?!", "-lead", "x" * 65,
                "with/slash", 123, None]:
        with pytest.raises(InvalidIdentifierError):
            schema.validate_template_id(bad)


def test_slug_and_param_and_route_grammar():
    assert schema.validate_slug("review") == "review"
    with pytest.raises(InvalidIdentifierError):
        schema.validate_slug("Re View")
    assert schema.validate_param_name("focus_1") == "focus_1"
    for bad in ["1abc", "with space", "ünicode", ""]:
        with pytest.raises(InvalidIdentifierError):
            schema.validate_param_name(bad)
    assert schema.validate_namespaced_route("template:review") == "template:review"
    with pytest.raises(InvalidIdentifierError):
        schema.validate_namespaced_route("/review")  # a bare slash is not a template route


def test_body_size_and_encoding_refused():
    with pytest.raises(InvalidDocumentError):
        schema.validate_body("x" * (schema.MAX_BODY_BYTES + 1))
    # A lone surrogate is not valid UTF-8 and must not be storable/hashable.
    with pytest.raises(InvalidDocumentError):
        schema.validate_body("\ud800")
    with pytest.raises(InvalidDocumentError):
        schema.validate_body(12345)


def test_display_name_and_description_bounds():
    with pytest.raises(InvalidDocumentError):
        schema.validate_text_field("n" * 200, "display_name", schema.MAX_DISPLAY_NAME_CHARS)
    with pytest.raises(InvalidDocumentError):
        schema.validate_text_field("   ", "display_name", 120)  # blank required rejected


def test_template_and_revision_construct_validates():
    t = dto.Template(id="tmpl.a", owner_principal="u1", display_name="A", slug="a",
                     created_at="2026-01-01")
    assert t.id == "tmpl.a"
    with pytest.raises(InvalidIdentifierError):
        dto.Template(id="BAD id", owner_principal="u1", display_name="A", slug="a")
    with pytest.raises(InvalidDocumentError):
        dto.Template(id="tmpl.a", owner_principal="u1", display_name="A", slug="a",
                     origin="marketplace")


def test_parameter_spec_rules():
    dto.ParameterSpec("k", "enum", True, choices=("x", "y"))
    with pytest.raises(InvalidDocumentError):
        dto.ParameterSpec("k", "enum", True, choices=("x", "x"))   # duplicate choices
    with pytest.raises(InvalidDocumentError):
        dto.ParameterSpec("k", "enum", True)                       # enum needs choices
    with pytest.raises(InvalidDocumentError):
        dto.ParameterSpec("k", "integer", True, choices=("a",))     # choices only on enum
    with pytest.raises(InvalidDocumentError):
        dto.ParameterSpec("k", "integer", True, minimum=10, maximum=1)
    with pytest.raises(InvalidDocumentError):
        dto.ParameterSpec("k", "string", True, default=5)           # str default must be str
    with pytest.raises(InvalidDocumentError):
        dto.ParameterSpec("k", "nonsense", True)


def test_duplicate_parameter_names_refused():
    with pytest.raises(InvalidDocumentError):
        dto.TemplateRevision(template_id="tmpl.a", revision=1, body="x",
                             parameters=[dto.ParameterSpec("a"), dto.ParameterSpec("a")])


def test_crud_roundtrip(service):
    make_template(service, tid="tmpl.crud", slug="crud", body="hi {{who}}")
    got = service.get(principal="u1", template_id="tmpl.crud")
    assert got.latest_revision == 1 and got.slug == "crud"
    assert [r.revision for r in service.revisions(principal="u1", template_id="tmpl.crud")] == [1]


def test_cross_owner_read_is_refused_not_empty(service):
    make_template(service, principal="owner-a", tid="tmpl.secret", slug="secret")
    with pytest.raises(UnauthorizedTargetError):
        service.get(principal="owner-b", template_id="tmpl.secret")
    # A list for another principal is their own (empty), never the other's rows.
    assert service.list(principal="owner-b") == []


def test_list_never_leaks_body(service):
    make_template(service, tid="tmpl.leak", slug="leak", body="SECRET {{x}}")
    listed = service.list(principal="u1")
    assert len(listed) == 1
    dumped = repr(listed)
    assert "SECRET" not in dumped  # body is not part of a list projection
