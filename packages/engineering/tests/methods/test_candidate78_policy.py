"""Candidate 2.6 policy and byte-lineage checks; never a publication test."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from ordessa_engineering.methods import compile_method, load_method, validate_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.orchestration.check_capabilities import (
    invariant_review_check_capabilities,
    mechanical_review_check_capabilities,
)
from ordessa_engineering.application.orchestration.decision_checks import generic_decision_check_capability
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities


REPO_ROOT = Path(__file__).resolve().parents[4]
CANDIDATE = REPO_ROOT / "methods/incremental-engineering/candidates/2.6.0"
PREVIOUS = REPO_ROOT / "methods/incremental-engineering/candidates/2.5.0"
PREVIOUS_INVENTORY_SHA256 = "e212ef383000f673f917575f27b5dff2f735329c78fc86efa387336cda2bc7fc"


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _fixture_capabilities() -> CompilationCapabilities:
    """Use exact descriptors from current owner functions, marked fixture-only."""
    dispatch = tuple(
        descriptor
        for descriptor in owner_capabilities()
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
        registry_snapshot_ref="fixture:candidate-2.6.0-current-owner-functions",
        trust_class="fixture",
    )


def test_candidate_26_loads_validates_and_compiles_with_fixture_warning_only():
    loaded_result = load_method(
        MethodSource(CANDIDATE), reader=FileResourceReader()
    )
    assert loaded_result.ok and loaded_result.value is not None
    loaded = loaded_result.value

    capabilities = _fixture_capabilities()
    manifest = _yaml(CANDIDATE / "method.yaml")
    expected = {
        (row["capability_id"], row["kind"], row["interface_version"], row["contract_digest"])
        for row in manifest["requires"]
    }
    assert {
        (row.capability_id, row.kind, row.interface_version, row.contract_digest)
        for row in capabilities.capabilities
    } >= expected
    report = validate_method(loaded, capabilities)
    assert report.valid, report.diagnostics
    assert any(
        diagnostic.code == "FIXTURE_CAPABILITIES_ONLY"
        and diagnostic.severity == "warning"
        for diagnostic in report.diagnostics
    )
    compiled = compile_method(loaded, capabilities, "test.candidate-2.6/1")
    assert compiled.ok and compiled.value is not None, compiled.error

    assert manifest["release_version"] == "2.6.0"
    assert manifest["metadata"]["candidate_binding_status"]["publication_allowed"] is False
    assert manifest["metadata"]["candidate_binding_status"]["execution_allowed"] is False


def test_claim_support_uses_its_declared_finite_decision_policy():
    standard = _yaml(CANDIDATE / "standards/source-review.yaml")
    criterion = next(row for row in standard["criteria"] if row["criterion_id"] == "claim_support")
    assert criterion["policy"] == {
        "satisfied": "pass",
        "violated": "block",
        "insufficient": "block",
        "unknown": "manual",
    }
    assert criterion["checks"][0]["capability_id"] == "ordessa.decision.evaluate"
    assert "quality_admission" not in criterion["checks"][0]["bindings"]
    conversion = criterion["checks"][0]["bindings"]["nominal_answer_conversion"]
    assert conversion["option_statuses"] == {
        "supported": "satisfied",
        "contradicted": "violated",
        "insufficient": "insufficient",
    }
    assert {
        conversion[key]
        for key in (
            "tie",
            "missing_answer",
            "incomplete_answer",
            "truncated_input",
            "unmapped_option",
        )
    } == {"unknown"}


def test_semantic_results_use_explicit_finite_choice_options():
    standard = _yaml(CANDIDATE / "standards/quality-review.yaml")
    assert standard["revision"] == "2.6.0"
    criteria = {row["criterion_id"]: row for row in standard["criteria"]}
    consistency = criteria["semantic_consistency"]
    assert consistency["answer_vocabulary"]["kind"] == "choice"
    assert consistency["checks"][0]["bindings"]["question_set"] == {
        "resource": "decision.change_consistency"
    }
    assert consistency["checks"][0]["bindings"]["question_ids"] == ["coverage"]
    assert [option["option_id"] for option in consistency["answer_vocabulary"]["options"]] == [
        "conflicting", "partial", "complete"
    ]
    consistency_map = consistency["checks"][0]["bindings"]["nominal_answer_conversion"]
    assert consistency_map == {
        "contract_version": "ordessa.nominal-choice-status/1",
        "answer_kind": "choice",
        "option_statuses": {
            "conflicting": "violated",
            "partial": "insufficient",
            "complete": "satisfied",
        },
        "tie": "unknown",
        "missing_answer": "unknown",
        "incomplete_answer": "unknown",
        "truncated_input": "unknown",
        "unmapped_option": "unknown",
    }
    assert consistency["policy"] == {
        "satisfied": "pass",
        "violated": "block",
        "insufficient": "block",
        "unknown": "manual",
    }

    drift = criteria["semantic_drift"]
    assert drift["answer_vocabulary"]["kind"] == "choice"
    assert drift["checks"][0]["bindings"]["question_set"] == {
        "resource": "decision.change_consistency"
    }
    assert drift["checks"][0]["bindings"]["question_ids"] == ["drift"]
    assert [option["option_id"] for option in drift["answer_vocabulary"]["options"]] == [
        "drift_detected", "no_drift_detected"
    ]
    drift_map = drift["checks"][0]["bindings"]["nominal_answer_conversion"]
    assert drift_map == {
        "contract_version": "ordessa.nominal-choice-status/1",
        "answer_kind": "choice",
        "option_statuses": {
            "drift_detected": "violated",
            "no_drift_detected": "satisfied",
        },
        "tie": "unknown",
        "missing_answer": "unknown",
        "incomplete_answer": "unknown",
        "truncated_input": "unknown",
        "unmapped_option": "unknown",
    }
    assert drift["policy"] == consistency["policy"]

    decisions = _yaml(CANDIDATE / "decisions/change-consistency.yaml")
    assert decisions["question_set_version"] == "2.0.0"
    assert decisions["input_mapping_version"] == "2.0.0"
    assert [question["kind"] for question in decisions["questions"]] == ["choice", "choice"]
    assert [question["question_revision"] for question in decisions["questions"]] == [
        "2.0.0", "2.0.0"
    ]
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    review_nodes = [
        node for node in workflow["steps"]
        if node.get("kind") == "operation" and node.get("operation") == "engineering.reviews.request"
    ]
    assert len(review_nodes) == 5
    for node in review_nodes:
        assert node["config"]["review_source"] == {
            "response_document_type": "unit-review-result",
            "response_schema": {"resource": "document.unit_review_result.schema"},
            "response_codec": "exact_check_key_status/1",
        }
    pending = _yaml(CANDIDATE / "pending-bindings.yaml")
    assert pending["semantic_decision_mappings"]["result_rules"]["status_mapping"].startswith(
        "apply_exact_selected_method_criterion_disposition"
    )
    assert "nominal-answer-status/2" not in (CANDIDATE / "standards/quality-review.yaml").read_text()
    assert "validated_quality_evaluation_required" not in (
        CANDIDATE / "pending-bindings.yaml"
    ).read_text(encoding="utf-8")

    # Existing finite choice declaration stays on v1 and is not reinterpreted.
    support = next(
        row for row in _yaml(CANDIDATE / "standards/source-review.yaml")["criteria"]
        if row["criterion_id"] == "claim_support"
    )
    assert support["checks"][0]["bindings"]["nominal_answer_conversion"]["contract_version"] == "ordessa.nominal-choice-status/1"


def test_2_5_snapshot_matches_complete_recorded_before_inventory():
    inventory = json.loads(
        (CANDIDATE / "docs/source-inventory-2.5.0.json").read_text(encoding="utf-8")
    )
    assert inventory["source_candidate"] == "2.5.0"
    assert len(inventory["files"]) == 74
    assert inventory["inventory_sha256"] == PREVIOUS_INVENTORY_SHA256
    rows = []
    for row in inventory["files"]:
        data = (PREVIOUS / row["path"]).read_bytes()
        assert len(data) == row["size"], row["path"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"], row["path"]
        rows.append(row)
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == inventory["inventory_sha256"]


def test_candidate_manifest_and_index_hashes_match_captured_resources():
    manifest = _yaml(CANDIDATE / "method.yaml")
    for resource in manifest["resources"]:
        data = (CANDIDATE / resource["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == resource["sha256"], resource["id"]

    index = json.loads((CANDIDATE / "candidate-index.json").read_text(encoding="utf-8"))
    rows = index["files"]
    expected_paths = sorted(
        p.relative_to(CANDIDATE).as_posix()
        for p in CANDIDATE.rglob("*")
        if p.is_file() and p.name != "candidate-index.json"
    )
    assert [row["path"] for row in rows] == expected_paths
    for row in rows:
        assert hashlib.sha256((CANDIDATE / row["path"]).read_bytes()).hexdigest() == row["sha256"]


def test_removed_evaluation_gate_preserves_required_inputs_and_negative_policy():
    cases = (
        ("standards/source-review.yaml", "claim_support"),
        ("standards/acceptance.yaml", "output_scope"),
        ("standards/acceptance.yaml", "test_evidence"),
        ("standards/quality-review.yaml", "intent_binding"),
        ("standards/rework-scope.yaml", "correction_within_approved_scope"),
    )
    for rel, criterion_id in cases:
        old_doc = _yaml(PREVIOUS / rel)
        new_doc = _yaml(CANDIDATE / rel)
        old = next(row for row in old_doc["criteria"] if row["criterion_id"] == criterion_id)
        new = next(row for row in new_doc["criteria"] if row["criterion_id"] == criterion_id)
        assert new["required_inputs"] == old["required_inputs"], (rel, criterion_id)
        assert new["checks"][0]["capability_id"] == old["checks"][0]["capability_id"]
        old_bindings = dict(old["checks"][0]["bindings"])
        new_bindings = dict(new["checks"][0]["bindings"])
        old_bindings.pop("quality_admission", None)
        assert new_bindings == old_bindings, (rel, criterion_id)
        assert new["policy"]["violated"] == old["policy"]["violated"]
        assert new["policy"]["insufficient"] == old["policy"]["insufficient"]
        assert new["policy"]["unknown"] == old["policy"]["unknown"]


def test_work_source_declares_all_21_waits_and_append_only_work_input_fields():
    manifest = _yaml(CANDIDATE / "method.yaml")
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    policy = manifest["metadata"]["work_source"]
    waits = {node["id"]: node for node in workflow["steps"] if node.get("kind") == "wait"}
    assert policy["contract_version"] == "ordessa.persisted-work-source/1"
    assert policy["input_document_slot"] == "work_inputs"
    assert policy["input_document_type"] == "work-inputs"
    assert set(policy["waits"]) == set(waits) and len(waits) == 21
    assert policy["waits"]["await_intent_ref"]["intent_result_slots"] == {
        "id": "intent_id", "digest": "intent_digest"
    }
    assert policy["waits"]["await_execution_capture"]["native_report_slot"] == "submission_record"
    schema = json.loads((CANDIDATE / "documents/work-inputs/schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["events"]["additionalProperties"] is False
    for node_id, node in waits.items():
        spec = policy["waits"][node_id]
        expected = {binding.removeprefix("event.") for binding in (node.get("bind") or {}).values() if binding.startswith("event.")}
        expected |= set((node.get("match") or {}))
        assert set(spec["event_slots"]) == expected, node_id
        doc_fields = {selector["field"] for selector in spec["event_slots"].values() if selector["source"] in {"work_input", "blob_utf8"}}
        assert set(schema["properties"]["events"]["properties"][node_id]["properties"]) == doc_fields, node_id
        assert not doc_fields & {"ready", "accepted", "permitted", "verified"}
    forbidden_truth_fields = schema["$defs"]["event_value"]["oneOf"][0]["propertyNames"]["not"]["enum"]
    assert {"ready", "accepted", "permitted", "verified", "approved", "authorized"} <= set(forbidden_truth_fields)
    assert policy["waits"]["await_implementation_permission"]["family"] == "object_exists"
    assert policy["waits"]["await_implementation_permission"]["refs"] == ["package_ref"]
    assert policy["waits"]["await_acceptance_response"]["event_slots"]["raw_response_utf8"] == {
        "source": "blob_utf8", "field": "raw_response_ref"
    }
    assert set(schema["properties"]["events"]["properties"]["await_intent_ref"]["properties"]) == {
        "intent_id", "intent_digest"
    }
    assert set(schema["properties"]["events"]["properties"]["await_execution_capture"]["properties"]) == {
        "submission_record"
    }
    assert "bind_inputs" in (CANDIDATE / "documents/work-inputs/template.md").read_text(encoding="utf-8")
