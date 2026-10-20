"""Candidate 2.5.0 declaration qualification; fixture descriptors are not host registration."""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.orchestration.check_capabilities import (
    invariant_review_check_capabilities,
    mechanical_review_check_capabilities,
)
from ordessa_engineering.application.orchestration.decision_checks import (
    generic_decision_check_capability,
)
from ordessa_engineering.application.orchestration.owner_capabilities import (
    owner_capabilities,
)
from ordessa_engineering.methods import compile_method, validate_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource
from ordessa_engineering.methods.loading.loader import load_method


ROOT = Path(__file__).resolve().parents[1] / "candidates" / "2.5.0"


def _fixture_descriptors() -> CompilationCapabilities:
    """Use real descriptor functions, explicitly downgraded to fixture trust."""
    check_descriptors = (
        *mechanical_review_check_capabilities().capabilities,
        *invariant_review_check_capabilities().capabilities,
        generic_decision_check_capability(),
    )
    all_descriptors = (
        *EngineeringService.operation_capabilities().capabilities,
        *owner_capabilities(),
        *check_descriptors,
    )
    rows = yaml.safe_load((ROOT / "method.yaml").read_text())["requires"]
    descriptors = []
    for row in rows:
        matches = [
            item for item in all_descriptors
            if item.capability_id == row["capability_id"]
            and item.kind == row["kind"]
            and item.interface_version == row["interface_version"]
            and item.contract_digest == row["contract_digest"]
        ]
        assert len(matches) == 1, f"expected one exact real descriptor: {row['capability_id']}"
        descriptors.append(matches[0])
    # Reclassify the complete descriptor set as fixture trust. This constructs
    # no source or host registration and preserves the compiler warning.
    return CompilationCapabilities(
        tuple(descriptors), trust_class="fixture"
    )


def test_candidate76_loads_validates_and_compiles_bounded_policy() -> None:
    capabilities = _fixture_descriptors()
    loaded = load_method(MethodSource(ROOT), FileResourceReader())
    assert loaded.ok, loaded.error

    validation = validate_method(loaded.value, capabilities)
    assert validation.valid, validation.diagnostics
    assert any(item.code == "FIXTURE_CAPABILITIES_ONLY" for item in validation.diagnostics)

    compiled = compile_method(loaded.value, capabilities, "ordessa.methods/v1")
    assert compiled.ok, compiled.error

    resources = loaded.value.resources
    workflow = resources["workflow.change_cycle"].value
    nodes = {node["id"]: node for node in workflow["steps"]}
    assert nodes["record_acceptance_review"]["result_routing"]["outcomes"] == {
        "pass": {"next": "await_acceptance_gate"},
        "fail": {"next": "await_rework_review_plan"},
        "indeterminate": {"stop": "unknown"},
    }
    assert nodes["record_rework_review"]["result_routing"]["outcomes"] == {
        "pass": {"next": "await_implementation_permission"},
        "fail": {"stop": "revision_required"},
        "indeterminate": {"stop": "unknown"},
    }
    assert nodes["adopt"]["inputs"] == {
        "submission_ref": "submission_ref",
        "approval_ref": "adoption_approval_ref",
        "expected_control_version": "adoption_control_version",
        "targets": "adoption_targets",
    }
    assert nodes["rework_review"]["config"]["purpose"] == "quality"
    assert nodes["await_rework_review_plan"]["bind"]["correction_plan_ref"] == "event.correction_plan_ref"
    assert nodes["await_rework_review_plan"]["match"]["correction_plan"] == "correction_plan_ref"
    assert nodes["await_rework_review_response"]["match"]["correction_plan"] == "correction_plan_ref"
    assert nodes["await_rework_review_plan"]["match"]["acceptance_review"] == "acceptance_review_ref"
    assert nodes["await_rework_review_plan"]["match"]["acceptance_plan_digest"] == "acceptance_record_plan_digest"
    assert nodes["await_rework_review_plan"]["match"]["acceptance_request_version"] == "acceptance_record_request_version"
    assert nodes["await_rework_review_plan"]["match"]["acceptance_fence"] == "acceptance_record_fence"
    assert workflow["loops"] == [{
        "loop_id": "implementation-rework",
        "from_step": "record_rework_review",
        "to_step": "await_implementation_permission",
        "max_rounds": 2,
        "on_exhausted": "revision_required",
    }]
    assert workflow["outputs"] == {
        "submission_ref": "submission_ref",
        "adoption_ref": "adoption_ref",
    }
    decision = resources["decision.rework_scope"].value
    criterion = resources["standard.rework_scope"].value["criteria"][0]
    assert resources["standard.rework_scope"].value["purpose"] == "quality"
    assert criterion["applies_to"] == ["correction-plan"]
    assert decision["required_input_slots"] == criterion["required_inputs"]
    assert decision["questions"][0]["criterion_refs"] == [{
        "resource": "standard.rework_scope",
        "criterion_id": "correction_within_approved_scope",
    }]
    assert criterion["checks"][0]["capability_id"] == "ordessa.decision.evaluate"
    correction = resources["document.correction_plan.schema"].value
    assert correction["properties"]["document_type"] == {"const": "correction-plan"}
    assert set(correction["required"]) == {
        "document_type", "schema_version", "approved_did_ref", "approved_package_ref",
        "failed_submission_ref", "failed_review_ref", "proposed_corrections",
    }
    assert "permission" not in correction["properties"]
    assert "grant" not in correction["properties"]
    row_properties = correction["properties"]["proposed_corrections"]["items"]["properties"]
    assert set(row_properties) == {
        "failed_check_key", "target_ref", "change", "validation_steps", "scope_basis_refs",
    }
    check_key = correction["$defs"]["check_key"]
    assert set(check_key["required"]) == {"target", "criterion_id", "claim_id"}
    assert check_key["properties"]["criterion_id"]["minLength"] == 1
    assert check_key["properties"]["claim_id"]["type"] == ["string", "null"]
    assert workflow["automatic_side_effect_retry"] == "forbidden_when_outcome_unknown"

    frozen_workflow_sha = "c864c2e56eca935846043473693bf03f6327378bc09dc2479c5c058026e62d04"
    for release in ("2.2.0", "2.3.0", "2.4.0"):
        historic = ROOT.parent / release / "workflows" / "change-cycle.yaml"
        assert hashlib.sha256(historic.read_bytes()).hexdigest() == frozen_workflow_sha

