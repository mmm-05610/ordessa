"""T05 / G05–G07: closed parser + deterministic renderer.

The golden corpus (``golden_corpus.json``) pins byte-exact rendering and the
digest; the extra tests here cover escapes, non-recursion, project-ref through an
authorized port, forged-path refusal, the absent-port gap, output-size bound and
byte/digest reproducibility.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ordessa_command_templates.api import schema
from ordessa_command_templates.api.dto import ParameterSpec, Target
from ordessa_command_templates.api.errors import (
    InvalidDocumentError,
    OutputLimitError,
    ParameterInvalidError,
    UnknownParameterError,
    UnresolvedParameterError,
)
from ordessa_command_templates.expansion import digest as dig
from ordessa_command_templates.expansion import parser
from ordessa_command_templates.expansion.renderer import ProjectRef, render

CORPUS = json.loads((Path(__file__).parent / "golden_corpus.json").read_text(encoding="utf-8"))

_KIND_ERRORS = {
    "PARAMETER_INVALID": ParameterInvalidError,
    "PARAMETER_UNKNOWN": UnknownParameterError,
    "OUTPUT_LIMIT": OutputLimitError,
}


def _specs(items):
    return tuple(ParameterSpec(
        name=i["name"], kind=i.get("kind", "string"), required=i.get("required", True),
        default=i.get("default"), max_length=i.get("max_length"),
        minimum=i.get("minimum"), maximum=i.get("maximum"),
        choices=tuple(i["choices"]) if i.get("choices") else None) for i in items)


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["name"])
def test_golden_case(case):
    specs = _specs(case["parameters"])
    parsed = parser.parse(case["body"])
    if case.get("error"):
        with pytest.raises(_KIND_ERRORS[case["error"]]):
            render(parsed, specs, case["arguments"], principal="u1")
        return
    result = render(parsed, specs, case["arguments"], principal="u1")
    assert result.text == case["expect"]


def test_render_output_is_byte_stable_and_digest_matches():
    specs = [ParameterSpec("a", "string", True)]
    parsed = parser.parse("x {{a}}")
    r1 = render(parsed, specs, {"a": "y"}, principal="u1")
    r2 = render(parsed, specs, {"a": "y"}, principal="u1")
    assert r1.text == r2.text and r1.digest == r2.digest
    assert r1.digest == dig.rendered_digest("x y")


def test_crlf_body_same_digest_as_lf():
    assert dig.revision_digest("a\r\nb {{x}}", [ParameterSpec("x")]) == \
        dig.revision_digest("a\nb {{x}}", [ParameterSpec("x")])


def test_nfc_normalization_single_digest():
    # 'é' composed vs decomposed normalize to the same NFC digest.
    composed = "café {{x}}"
    decomposed = "cafe\u0301 {{x}}"
    assert dig.body_digest(composed) == dig.body_digest(decomposed)


def test_escape_consumes_backslash_only_before_braces():
    parsed = parser.parse("a\\{{b}} c\\d")
    # ``\{{`` becomes literal ``{{``; a lone ``\`` before 'd' stays a literal '\d'.
    text = "".join(s.text for s in parsed.segments if isinstance(s, parser.Literal))
    assert text == "a{{b}} c\\d"
    assert parser.parse("a\\{{b}} c\\d").placeholder_names == frozenset()


def test_unterminated_placeholder_rejected():
    with pytest.raises(InvalidDocumentError):
        parser.parse("open {{x")


def test_project_ref_resolves_via_port(service, resolver):
    service.create(principal="u1", template_id="tmpl.pr", display_name="PR", slug="pr",
                   operation_key="c")
    service.save_revision(principal="u1", template_id="tmpl.pr",
                          body="In {{project}} do work",
                          parameters=[ParameterSpec("project", "project-ref", True)],
                          expected_version=1, operation_key="r")
    service.approve(principal="u1", template_id="tmpl.pr", revision=1,
                    expected_version=2, operation_key="a")
    result = service.render_preview(target=Target(principal="u1", server_identity="s1"),
                                    template_id="tmpl.pr", revision=1,
                                    arguments={"project": "alpha"})
    assert result.text == "In Alpha Project do work"
    assert ("u1", "alpha") in resolver.calls


def test_project_ref_rejects_forged_absolute_path(service, resolver):
    service.create(principal="u1", template_id="tmpl.pr2", display_name="PR2", slug="pr2",
                   operation_key="c")
    service.save_revision(principal="u1", template_id="tmpl.pr2", body="{{project}}",
                          parameters=[ParameterSpec("project", "project-ref", True)],
                          expected_version=1, operation_key="r")
    parsed = parser.parse("{{project}}")
    for forged in ["/etc/passwd", "C:\\Windows", "..\\secret", "\\\\server\\share"]:
        with pytest.raises(ParameterInvalidError):
            render(parsed, [ParameterSpec("project", "project-ref", True)],
                   {"project": forged}, principal="u1", resolver=resolver)


def test_project_ref_rejects_unknown_reference(service, resolver):
    parsed = parser.parse("{{project}}")
    with pytest.raises(UnresolvedParameterError):
        render(parsed, [ParameterSpec("project", "project-ref", True)],
               {"project": "not-authorized"}, principal="u1", resolver=resolver)


def test_project_ref_without_port_is_a_refused_gap(bare_service):
    bare_service.create(principal="u1", template_id="tmpl.gap", display_name="Gap", slug="gap",
                        operation_key="c")
    bare_service.save_revision(principal="u1", template_id="tmpl.gap", body="{{project}}",
                               parameters=[ParameterSpec("project", "project-ref", True)],
                               expected_version=1, operation_key="r")
    bare_service.approve(principal="u1", template_id="tmpl.gap", revision=1,
                         expected_version=2, operation_key="a")
    with pytest.raises(UnresolvedParameterError):
        bare_service.render_preview(target=Target(principal="u1", server_identity="s1"),
                                    template_id="tmpl.gap", revision=1,
                                    arguments={"project": "alpha"})


def test_render_output_size_bound():
    specs = [ParameterSpec("s", "string", True)]
    parsed = parser.parse("{{s}}")
    huge = "x" * (schema.MAX_RENDERED_BYTES + 10)
    with pytest.raises(OutputLimitError):
        render(parsed, specs, {"s": huge}, principal="u1")


def test_argument_values_not_reexpanded_by_slash_at_draft():
    # A value that begins with '/' must render literally and keep byte identity.
    parsed = parser.parse("{{v}}")
    r = render(parsed, [ParameterSpec("v", "string", True)], {"v": "/review --force"},
               principal="u1")
    assert r.text == "/review --force"
    assert r.digest == dig.rendered_digest("/review --force")
