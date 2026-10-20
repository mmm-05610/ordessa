"""Reusable review-group applicability on the current pure owners.

The 2.6 candidate's frozen capability pins are stale (see
``test_candidate78_policy.py``), so its *public* compile is now refused on a
capability-pin mismatch. The review-group invariants that the phase-1 slice
asserted through that public compile are therefore asserted directly on the
current owners that actually carry them:

* the declarative workflow validator (``_review_binding_diagnostics``), which
  decides which criteria of a reusable standard are applicable to a member's
  declared target types and which materials each applicable criterion needs; and
* the pure compiled-program validator (``validate_compiled_review_groups``),
  which rejects a wholly inapplicable standard.

The retired expectation — "the public compile of 2.6 succeeds with a fixture
catalog" — is stated explicitly below rather than being silently dropped.

No runtime authority, catalog or publication claim is made here.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.orchestration.check_capabilities import (
    invariant_review_check_capabilities, mechanical_review_check_capabilities,
)
from ordessa_engineering.application.orchestration.decision_checks import generic_decision_check_capability
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.methods import compile_method, load_method, validate_method
from ordessa_engineering.methods.compilation.compiler import (
    bind_program, compile_program_from_source)
from ordessa_engineering.methods.compilation.encoding import stored_program_from_canonical
from ordessa_engineering.methods.compilation.review_bindings import validate_compiled_review_groups
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource
from ordessa_engineering.methods.validation.workflow import _review_binding_diagnostics


CANDIDATE = Path(__file__).resolve().parents[4] / "methods/incremental-engineering/candidates/2.6.0"
STANDARD = "standard.engineering_content"


@pytest.fixture
def loaded_candidate():
    loaded = load_method(MethodSource(CANDIDATE), reader=FileResourceReader())
    assert loaded.ok, loaded.error
    return loaded.value


def _capabilities():
    """The exact descriptors from current owner functions, marked fixture-only."""
    return CompilationCapabilities((
        *command_capabilities().capabilities,
        *(c for c in owner_capabilities() if c.capability_id == "engineering.executions.dispatch"),
        *mechanical_review_check_capabilities().capabilities,
        *invariant_review_check_capabilities().capabilities,
        generic_decision_check_capability(),
    ), "fixture:current-owner-descriptors", "host")


def _pure_program(loaded):
    """The candidate's compiled program by the *pure* compiler, no pin gate.

    `compile_method` refuses before it ever builds a program (the capability
    pins are stale); the review-group validator is a pure function of the
    compiled program, so the program is built by the same pure compiler the
    product uses and fed to the validator directly.
    """
    program = compile_program_from_source(loaded, "fixture:phase1-pure")
    return bind_program(stored_program_from_canonical(program), loaded)


def _entry_workflow(loaded):
    resource_id = loaded.manifest["entry"]["resource"]
    resource = loaded.resources[resource_id]
    return resource_id, resource


def test_public_compile_of_candidate_26_is_retired_on_stale_capability_pins(loaded_candidate):
    """RETIRED: the old "compatible compile with a fixture catalog" expectation.

    The candidate still loads, but two of its frozen pins no longer match the
    current descriptors, so the public compile refuses by name. That is a
    capability-pin fact, not a review-group fact; the review-group invariants are
    asserted below on the pure owners instead of through this compile.
    """
    report = validate_method(loaded_candidate, _capabilities())
    assert not report.valid
    compiled = compile_method(loaded_candidate, _capabilities(), "fixture:phase1-retired")
    assert not compiled.ok and compiled.value is None
    assert compiled.error.code == "CAPABILITY_REQUIREMENT_MISMATCH"


def test_a_reusable_standard_applies_only_its_own_criteria_on_the_declarative_owner(loaded_candidate):
    """The same engineering-content standard has DID-only and package-only criteria.

    Neither group may demand the other group's document type. The declarative
    owner computes applicability from the member's declared target types, so the
    unmodified workflow produces no coverage diagnostic for either group.
    """
    resource_id, resource = _entry_workflow(loaded_candidate)
    diagnostics = _review_binding_diagnostics(
        loaded_candidate, deepcopy(resource.value), resource_id,
        resource.captured.logical_path)
    codes = {diagnostic.code for diagnostic in diagnostics}
    assert "REVIEW_GROUP_TARGET_COVERAGE_INVALID" not in codes
    assert "REVIEW_GROUP_MATERIAL_COVERAGE_INVALID" not in codes

    # The invariant is not vacuous: the standard really carries both groups, and
    # the package group really targets only one of them.
    standard = loaded_candidate.resources[STANDARD].value
    applied = {frozenset(criterion.get("applies_to", ())) for criterion in standard["criteria"]}
    assert frozenset({"did-change"}) in applied
    assert frozenset({"spec-kit-package"}) in applied
    group = next(step for step in resource.value["steps"]
                 if step["id"] == "package_review")["config"]["review_group"]
    targets = {document_type for source in group["target_sources"]
               for document_type in source["document_types"]}
    assert targets == {"spec-kit-package"}
    assert "did-change" not in targets


def test_source_group_still_rejects_empty_applicability_and_missing_material(loaded_candidate):
    loaded = loaded_candidate
    resource_id, resource = _entry_workflow(loaded)
    workflow = deepcopy(resource.value)
    group = next(n for n in workflow["steps"] if n["id"] == "package_review")["config"]["review_group"]
    group["target_sources"][0]["document_types"] = ["session-summary"]
    diagnostics = _review_binding_diagnostics(loaded, workflow, resource_id, resource.captured.logical_path)
    assert any(d.code == "REVIEW_GROUP_TARGET_COVERAGE_INVALID" for d in diagnostics)

    workflow = deepcopy(resource.value)
    group = next(n for n in workflow["steps"] if n["id"] == "package_review")["config"]["review_group"]
    group["material_sources"] = [s for s in group["material_sources"] if s["name"] != "implementation_intent"]
    diagnostics = _review_binding_diagnostics(loaded, workflow, resource_id, resource.captured.logical_path)
    assert any(d.code == "REVIEW_GROUP_MATERIAL_COVERAGE_INVALID" for d in diagnostics)


def test_pure_review_group_validator_accepts_the_candidate_and_rejects_an_empty_applicable_set(
        loaded_candidate):
    program = _pure_program(loaded_candidate)
    # The candidate's groups are consistent with their standards: every applicable
    # criterion's materials are declared and no group has an empty target set.
    validate_compiled_review_groups(program)

    # A standard made wholly inapplicable to its group's declared target types is
    # still rejected by the pure validator, whatever the public compile does.
    standards = tuple(
        replace(s, criteria=tuple(replace(c, applies_to=("method-feedback",))
                                  for c in s.criteria))
        if s.standard_id == "engineering-content" else s
        for s in program.standard_definitions)
    with pytest.raises(ValueError, match="empty applicable"):
        validate_compiled_review_groups(replace(program, standard_definitions=standards))
