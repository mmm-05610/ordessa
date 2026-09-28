"""G10 — fixed-version loading evidence; unknown is never surfaced as offered.

verification.md G10 counter-examples covered here:
"官网新版能力误用于当前 pin" (a newer vendor-doc capability must not be
applied to the pinned version — the registry refuses evidence-less
`supported` facts at construction) and "品牌不支持却 offered"
(`unknown`/`unsupported` cells never appear as offered).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest

from ordessa_skills.harness_adapters import codex, claude, pi
from ordessa_skills.harness_adapters.base import (
    AdapterTarget, HarnessAdapterError, assess,
)
from ordessa_skills.harness_adapters.capabilities import (
    AXES, BRAND_PINS, BRAND_STATEMENTS, NO_EVIDENCE, SUPPORTED, UNSUPPORTED,
    UNKNOWN, CapabilityFact, CapabilityStatement, pin_for, statement_for,
)

BRAND_MODULES = {"pi": pi, "codex": codex, "claude-code": claude}
_CITATION = re.compile(r"[\w./+-]+:(\d+)")
_CITED_RANGE = re.compile(r"-(\d+)")
REPO_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# Citation verification (G10).
#
# docs/design/skills-v2/verification.md §G10 pins "Pi/Codex/Claude 固定版本
# 装载机制有据" with the counter-example "官网新版能力误用于当前 pin";
# docs/design/skills-v2/harness-adapters.md §7 requires every matrix cell to
# carry fixed-version evidence ("每个格子需固定 native/adapter 版本、受控入口、
# 优先级和卸载/恢复证据…无空模块冒充支持"). "有据" therefore means more than
# a string shaped like `file:line`: the file must exist in THIS repository,
# the line must be inside it, AND the cited line (or `:a-b` range) must
# actually carry the token/symbol the claim asserts — a citation that
# points at a plausible but WRONG line of a real file (e.g. any other line
# of codex/production.py while claiming the pin is 0.147.0) is evidence
# for nothing.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _files_by_basename(name: str) -> tuple[Path, ...]:
    return tuple(sorted(
        p for p in REPO_ROOT.rglob(name)
        if p.is_file() and ".venv" not in p.parts and "__pycache__" not in p.parts
        and "node_modules" not in p.parts))


def _resolve_citation(cite: str) -> Path:
    """The one repo file a `path:line` citation points at (or assert-fail)."""
    path_text, _line = cite.rsplit(":", 1)
    direct = REPO_ROOT / path_text
    if direct.is_file():
        return direct
    # A bare filename inside a parenthetical cross-reference (e.g. "...,
    # brand-matrix.md:19") must name exactly one file in the repo.
    matches = _files_by_basename(Path(path_text).name)
    assert len(matches) == 1, f"{cite}: {path_text!r} is not a repo file"
    return matches[0]


def _assert_citations_resolve(evidence: str, *, where: str,
                              tokens: tuple[str, ...]) -> None:
    """Every `file:line` citation in `evidence` must resolve to a repo file,
    sit inside it, and its cited line(s) must carry one of `tokens` — the
    version/symbol the claim asserts. `tokens` empty is a caller bug, not
    a licence to skip the content check."""
    assert tokens, f"{where}: no assertion token registered for this claim"
    citations = list(_CITATION.finditer(evidence))
    assert citations, f"{where}: evidence {evidence!r} cites no file:line at all"
    for match in citations:
        cite = match.group(0)
        resolved = _resolve_citation(cite)
        lines = resolved.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
        n_lines = len(lines)
        line_no = int(match.group(1))
        assert 1 <= line_no <= n_lines, (
            f"{where}: {cite} is beyond {resolved.relative_to(REPO_ROOT)} "
            f"({n_lines} lines)")
        # a `:start-end` citation stands for the whole span; a bare `:line`
        # for that one line only.
        span_end = _CITED_RANGE.match(evidence, match.end())
        end = min(int(span_end.group(1)), n_lines) if span_end else line_no
        cited_text = "\n".join(lines[line_no - 1:end])
        assert any(token in cited_text for token in tokens), (
            f"{where}: {cite} resolves into "
            f"{resolved.relative_to(REPO_ROOT)} but the cited line(s) carry "
            f"none of the asserted tokens {tokens!r} — the claim's evidence "
            f"is a real file at a wrong line:\n{cited_text!r}")


#: The token each SUPPORTED cell asserts. A version axis asserts the pin's
#: version string; the pin's `native_evidence` additionally vouches (pi)
#: that the run chain is PATH-resolved, and `resume` asserts the
#: session-continuation symbol the cited lines carry (`resume` / `session`
#: / `native_continuation`). An unregistered supported cell is a defect:
#: the guard refuses to grade what it cannot name.
def _claimed_tokens(harness_id: str, axis: str) -> tuple[str, ...]:
    pin = BRAND_PINS[harness_id]
    if axis == "native_version":
        return ((pin.native_version, "PATH") if harness_id == "pi"
                else (pin.native_version,))
    if axis == "adapter_version":
        return (pin.adapter_version,)
    if axis == "resume":
        return ("resume", "session", "continuation")
    raise AssertionError(
        f"{harness_id}/{axis}: a supported cell with no registered "
        "assertion-token rule — register its token or grade it honestly")


def _target(harness_id: str, native: str, adapter: str, entry: str = "acp"):
    return AdapterTarget(harness_id=harness_id, native_version=native,
                         adapter_version=adapter, entry=entry)


def _pinned(harness_id: str) -> AdapterTarget:
    pin = pin_for(harness_id)
    return _target(harness_id, pin.native_version, pin.adapter_version)


# -- version fail-closed ------------------------------------------------------

def test_native_version_drift_refuses_for_every_controlled_brand():
    for harness_id, module in BRAND_MODULES.items():
        pin = pin_for(harness_id)
        with pytest.raises(HarnessAdapterError) as exc:
            module.assess(_target(harness_id, "9.9.9-future", pin.adapter_version))
        assert exc.value.code == "HARNESS_VERSION_MISMATCH"


def test_adapter_version_drift_refuses_for_every_controlled_brand():
    for harness_id, module in BRAND_MODULES.items():
        pin = pin_for(harness_id)
        with pytest.raises(HarnessAdapterError) as exc:
            module.assess(_target(harness_id, pin.native_version, "0.0.1-dev"))
        assert exc.value.code == "HARNESS_VERSION_MISMATCH"


def test_a_newer_official_doc_version_is_not_the_pin():
    # Vendor docs describe newer Pi behaviour; the repo pin is 0.84.2, so a
    # run reporting anything else must be refused, not "assumed compatible".
    with pytest.raises(HarnessAdapterError):
        pi.assess(_target("pi", "0.99.0", "0.5.0"))


def test_exact_pins_assess_without_refusal():
    for harness_id, module in BRAND_MODULES.items():
        assessment = module.assess(_pinned(harness_id))
        assert assessment.harness_id == harness_id


def test_comment_grade_native_pin_is_reported_not_hidden():
    # Claude's CLI 2.1.274 is comment-only evidence (brand-matrix.md:24);
    # the assessment carries that weakness explicitly.
    assessment = claude.assess(_pinned("claude-code"))
    assert assessment.native_pin_is_machine_enforced is False
    assert assessment.statement.value("native_version") == UNKNOWN
    # ...yet the mismatch above still refused: unknown pin never softens
    # the fail-closed version gate.
    assert "native_version" in assessment.unknown_axes


def test_unregistered_brand_assess_refuses_no_pin_no_projection():
    with pytest.raises(HarnessAdapterError) as exc:
        assess(_target("hermes", "0.19.0", "0.0.0"), harness_id="hermes")
    assert exc.value.code == "HARNESS_BRAND_UNREGISTERED"


def test_brand_module_refuses_a_foreign_target():
    with pytest.raises(HarnessAdapterError) as exc:
        pi.assess(_target("codex", "0.147.0", "1.1.14"))
    assert exc.value.code == "HARNESS_ADAPTER_BRAND_MISMATCH"


def test_entry_string_never_grants_capability():
    # No in-repo evidence maps any entry to a skill capability, so the
    # offered surface must not move when only `entry` changes.
    a = assess(_target("codex", "0.147.0", "1.1.14", entry="acp"),
               harness_id="codex")
    b = assess(_target("codex", "0.147.0", "1.1.14", entry="cli"),
               harness_id="codex")
    assert a.offered_axes == b.offered_axes


# -- the offered surface -------------------------------------------------------

def test_unknown_cells_are_never_offered():
    for harness_id in BRAND_STATEMENTS:
        statement = statement_for(harness_id)
        for axis in AXES:
            fact = statement.fact(axis)
            assert fact.is_offered == (fact.value == SUPPORTED)
            if fact.value in (UNKNOWN, UNSUPPORTED):
                assert fact.is_offered is False
                assert axis not in statement.offered_axes()


def test_unregistered_brand_gets_an_unknown_shaped_statement():
    statement = statement_for("qwen-code")
    assert statement.synthesized is True
    assert all(statement.value(axis) == UNKNOWN for axis in AXES)
    assert statement.offered_axes() == ()
    assert all(statement.fact(axis).evidence == NO_EVIDENCE for axis in AXES)


def test_supported_claims_cite_repo_evidence_and_nothing_else_qualifies():
    # G10 "有据" verified at full strength: every `supported` cell's
    # citation resolves to a real file in this repo, at a line the file
    # actually has, and that cited line carries the version/symbol the
    # cell asserts (see §Citation verification above).
    for harness_id, statement in BRAND_STATEMENTS.items():
        for axis in AXES:
            fact = statement.fact(axis)
            if fact.value == SUPPORTED:
                assert fact.evidence != NO_EVIDENCE
                _assert_citations_resolve(
                    fact.evidence, where=f"{harness_id}/{axis}",
                    tokens=_claimed_tokens(harness_id, axis))
    for harness_id, pin in BRAND_PINS.items():
        _assert_citations_resolve(
            pin.native_evidence, where=f"{harness_id}/native_version pin",
            tokens=_claimed_tokens(harness_id, "native_version"))
        _assert_citations_resolve(
            pin.adapter_evidence, where=f"{harness_id}/adapter_version pin",
            tokens=_claimed_tokens(harness_id, "adapter_version"))


def test_a_supported_cell_without_a_token_rule_is_itself_a_defect():
    # fail-closed registry: a `supported` cell nobody registered an
    # assertion token for cannot pass the guard by accident.
    with pytest.raises(AssertionError):
        _claimed_tokens("pi", "reload")


def test_a_citation_to_the_wrong_line_of_a_real_file_is_refused():
    # The MINOR-4 counter-example: existence + in-range was satisfiable by
    # ANY line of the right file. `codex/production.py:1` is real and in
    # range, but line 1 says nothing about the pinned 0.147.0 — that is a
    # wrong citation, not evidence.
    with pytest.raises(AssertionError):
        _assert_citations_resolve(
            "plugins/harness/src/ordessa_harness/codex/production.py:1",
            where="wrong-line", tokens=("0.147.0",))
    # the same claim pointed at its actual line passes...
    _assert_citations_resolve(
        "plugins/harness/src/ordessa_harness/codex/production.py:88",
        where="right-line", tokens=("0.147.0",))
    # ...and a `:a-b` range citation covers the whole span, not just its
    # first line: claude/production.py:66 alone names the package, only
    # line 67 carries 0.81.2.
    with pytest.raises(AssertionError):
        _assert_citations_resolve(
            "plugins/harness/src/ordessa_harness/claude/production.py:66",
            where="first-line-of-range-only", tokens=("0.81.2",))
    _assert_citations_resolve(
        "plugins/harness/src/ordessa_harness/claude/production.py:66-67",
        where="full-range", tokens=("0.81.2",))


def test_a_bogus_citation_is_rejected_as_evidence():
    # The counter-example the old shape check missed: `x:1` string-shaped
    # but pointing nowhere. A `supported` claim may not rest on it.
    with pytest.raises(AssertionError):
        _assert_citations_resolve("nonexistent-file.py:1", where="bogus",
                                  tokens=("anything",))
    with pytest.raises(AssertionError):
        _assert_citations_resolve("specs/011-q1-skills/research/"
                                 "brand-matrix.md:999999", where="over-long",
                                 tokens=("anything",))
    with pytest.raises(AssertionError):
        _assert_citations_resolve("the vendor docs say so", where="no citation",
                                  tokens=("anything",))


def test_a_supported_fact_without_evidence_is_refused_at_construction():
    with pytest.raises(ValueError):
        CapabilityFact(axis="reload", value=SUPPORTED, evidence=NO_EVIDENCE)
    with pytest.raises(ValueError):
        CapabilityFact(axis="reload", value=SUPPORTED,
                       evidence="the vendor docs say so")


def test_unknown_and_unsupported_are_distinct_values_with_distinct_rules():
    # `unsupported` needs evidence of absence too; the two weak values are
    # separately surfaced on the Assessment and never conflated.
    for value in (UNKNOWN, UNSUPPORTED):
        fact = CapabilityFact(
            axis="reload", value=value,
            evidence=(NO_EVIDENCE if value == UNKNOWN
                      else "specs/011-q1-skills/research/brand-matrix.md:118"))
        assert fact.is_offered is False
    assert UNKNOWN != UNSUPPORTED
    base_facts = {axis: CapabilityFact(axis=axis, value=UNKNOWN,
                                      evidence=NO_EVIDENCE) for axis in AXES}
    base_facts["reload"] = CapabilityFact(
        axis="reload", value=UNSUPPORTED,
        evidence="specs/011-q1-skills/research/brand-matrix.md:118")
    statement = CapabilityStatement(harness_id="probe", facts=base_facts)
    assert statement.value("reload") == UNSUPPORTED
    assert statement.offered_axes() == ()
