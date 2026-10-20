"""Candidate 2.6 authorship policy is phase-scoped, finite, and fail-closed."""
from __future__ import annotations

from pathlib import Path

import yaml
import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.orchestration.check_capabilities import (
    invariant_review_check_capabilities,
    mechanical_review_check_capabilities,
)
from ordessa_engineering.application.orchestration.decision_checks import (
    generic_decision_check_capability,
)
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.review_authorship import (
    NATIVE_DIFFERENT_UNIT,
    SOURCE_BOUND_POLICY,
    validate_authorship_policy,
)
from ordessa_engineering.methods import compile_method, load_method, validate_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource


REPO_ROOT = Path(__file__).resolve().parents[4]
CANDIDATE = REPO_ROOT / "methods/incremental-engineering/candidates/2.6.0"
AUTHORS = {
    "contract": "ordessa.review.authorship-policy/1",
    "source_rules": {
        "native_unit": "different_original_unit",
        "authenticated_material_submitter": "separately_assigned_reviewer_role",
    },
    "unknown_source": "refuse",
}
NATIVE_INDEPENDENCE = (
    "original_author_unit_identity_must_differ_from_original_reviewer_unit_identity"
)


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _fixture_capabilities() -> CompilationCapabilities:
    dispatch = tuple(
        descriptor for descriptor in owner_capabilities()
        if descriptor.capability_id == "engineering.executions.dispatch"
    )
    descriptors = (
        *command_capabilities().capabilities,
        *dispatch,
        *mechanical_review_check_capabilities().capabilities,
        *invariant_review_check_capabilities().capabilities,
        generic_decision_check_capability(),
    )
    return CompilationCapabilities(
        descriptors,
        registry_snapshot_ref="fixture:candidate-2.6-authorship-policy",
        trust_class="fixture",
    )


def _compiled_candidate():
    loaded_result = load_method(MethodSource(CANDIDATE), reader=FileResourceReader())
    assert loaded_result.ok and loaded_result.value is not None
    capabilities = _fixture_capabilities()
    report = validate_method(loaded_result.value, capabilities)
    assert report.valid, report.diagnostics
    result = compile_method(loaded_result.value, capabilities, "test.candidate-2.6-authorship/1")
    assert result.ok and result.value is not None, result.error
    return result.value


def test_conditional_authorship_strategy_is_exact_and_candidate_compiles_fixture_only():
    compiled = _compiled_candidate()
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    nodes = {node["id"]: node for node in workflow["steps"]}
    for node_id in ("source_review", "quality_review", "package_review"):
        assert nodes[node_id]["config"]["unit_submission_review_strategy"][
            "policy_revision"
        ] == 2
        assert nodes[node_id]["config"]["unit_submission_review_strategy"]["roles"][
            "identity_constraint"
        ] == AUTHORS
        assert nodes[node_id]["operation"] == "engineering.reviews.request"

    # Only these two exact source classes are allowed. Missing/unknown source is
    # explicitly refused; it does not fall back to a role label or caller field.
    assert set(AUTHORS["source_rules"]) == {
        "native_unit", "authenticated_material_submitter"
    }
    assert AUTHORS["unknown_source"] == "refuse"
    policy = _yaml(CANDIDATE / "policies/unit-submission-review.v1.yaml")
    assert policy["roles"]["authenticated_material_submitter_evidence"] == {
        "source": "original_journal_and_key",
        "required": "authenticated_principal_and_completed_command_bound_to_exact_fixed_artifact_revision",
        "establishes_human_identity": False,
        "establishes_native_unit_identity": False,
    }
    assert policy["policy_revision"] == 2
    assert compiled.identity.release_version == "2.6.0"


def test_report_and_acceptance_keep_strict_native_unit_independence():
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    nodes = {node["id"]: node for node in workflow["steps"]}
    for node_id in ("record_submission", "acceptance_review"):
        assert nodes[node_id]["config"]["unit_submission_review_strategy"][
            "policy_revision"
        ] == 2
        assert nodes[node_id]["config"]["unit_submission_review_strategy"]["roles"][
            "identity_constraint"
        ] == NATIVE_INDEPENDENCE
    assert nodes["record_submission"]["operation"] == "engineering.submissions.record_report"
    assert nodes["acceptance_review"]["operation"] == "engineering.reviews.request"


def test_unknown_or_unrecognized_source_does_not_acquire_an_authorship_rule():
    policy = AUTHORS
    # Closed vocabulary and explicit refusal are the negative policy boundary.
    assert policy["source_rules"].get("unknown") is None
    assert policy["source_rules"].get("human") is None
    assert policy["source_rules"].get("caller_asserted_unit") is None
    assert policy["unknown_source"] == "refuse"


def test_owner_authorship_policy_validator_accepts_only_exact_supported_shapes():
    assert validate_authorship_policy(None) is None
    assert validate_authorship_policy(NATIVE_DIFFERENT_UNIT) == NATIVE_DIFFERENT_UNIT
    assert validate_authorship_policy(AUTHORS) == SOURCE_BOUND_POLICY

    malformed = (
        {**AUTHORS, "contract": "ordessa.review.authorship-policy/2"},
        {**AUTHORS, "unknown_source": "manual"},
        {**AUTHORS, "source_rules": {**AUTHORS["source_rules"], "unknown": "allow"}},
        {
            **AUTHORS,
            "source_rules": {
                **AUTHORS["source_rules"],
                "authenticated_material_submitter": "different_original_unit",
            },
        },
        "ordessa.review.authorship-policy/1",
        (NATIVE_DIFFERENT_UNIT,),
    )
    for value in malformed:
        with pytest.raises(ApplicationError) as error:
            validate_authorship_policy(value)
        assert error.value.code == "UNIT_REVIEW_IDENTITY_CONSTRAINT_UNSUPPORTED"

