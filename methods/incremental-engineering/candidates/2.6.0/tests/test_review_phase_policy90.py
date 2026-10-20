"""Static declaration checks for candidate 2.6 review-stage wiring.

These assertions cover method-owned workflow and input declarations only. They do
not qualify production source bindings, reviewers, or publication.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


CANDIDATE = Path(__file__).resolve().parents[1]


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_review_groups_declare_complete_ordered_single_plan_members():
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    steps = {node["id"]: node for node in workflow["steps"]}
    operations = [
        node for node in workflow["steps"]
        if node["kind"] == "operation" and node.get("operation") == "engineering.reviews.request"
    ]
    groups = {
        node["config"]["review_group"]["group_id"]: node["config"]["review_group"]
        for node in operations if "review_group" in node["config"]
    }
    assert set(groups) == {
        "proposal_reviews", "package_reviews", "submission_acceptance", "correction_review"
    }
    expected_members = {
        "proposal_reviews": ["source", "quality", "content", "summary"],
        "package_reviews": ["package_quality", "package_content"],
        "submission_acceptance": ["acceptance"],
        "correction_review": ["rework"],
    }
    for group_id, member_ids in expected_members.items():
        group = groups[group_id]
        assert group["required_members"] == "all_declared"
        assert group["empty_members"] == "error"
        assert [member["member_id"] for member in group["members"]] == member_ids
        for member in group["members"]:
            request = steps[member["request_node"]]
            assert request["config"]["review_binding"] == {
                "contract": "ordessa.method-review-binding/1",
                "anchor_node": group["members"][0]["request_node"],
                "group_id": group_id,
                "member_id": member["member_id"],
            }
            assert request["config"]["standards"] == [member["standard"]]
            assert steps[member["response_wait"]]["kind"] == "wait"
            assert steps[member["record_node"]]["operation"] == "engineering.reviews.record"
            assert steps[member["request_node"]]["outcomes"]["completed"]["next"] == member["response_wait"]


def test_response_and_plan_waits_are_distinct_and_correlated():
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    steps = {node["id"]: node for node in workflow["steps"]}
    for request_id, response_id, record_id, prefix in (
        ("source_review", "await_source_response", "record_source_review", "source"),
        ("quality_review", "await_quality_response", "record_quality_review", "quality"),
        ("quality_content_review", "await_quality_content_response", "record_quality_content_review", "content"),
        ("summary_review", "await_summary_response", "record_summary_review", "summary"),
        ("package_review", "await_package_review_response", "record_package_review", "package_quality"),
        ("package_content_review", "await_package_content_response", "record_package_content_review", "package_content"),
        ("acceptance_review", "await_acceptance_response", "record_acceptance_review", "acceptance"),
        ("rework_review", "await_rework_review_response", "record_rework_review", "rework"),
    ):
        response = steps[response_id]
        assert response["next"] == record_id
        assert response["bind"][f"{prefix}_review_id"] == "event.review_id"
        assert response["bind"][f"{prefix}_request_version"] == "event.request_version"
        assert response["bind"][f"{prefix}_review_fence"] == "event.fence"
        assert response["bind"][f"{prefix}_raw_response_utf8"] == "event.raw_response_utf8"
        assert steps[request_id]["outcomes"]["completed"]["next"] == response_id
    assert steps["await_proposal"]["next"] == "source_review"
    assert steps["await_quality_plan"]["kind"] == "wait"
    assert steps["await_quality_plan"]["next"] == "quality_review"
    assert steps["await_submission"]["next"] == "await_acceptance_plan"
    assert steps["await_acceptance_plan"]["kind"] == "wait"
    rework_match = steps["await_rework_review_plan"]["match"]
    assert set(rework_match) == {
        "submission", "acceptance_request_id", "did", "package", "method"
    }
    assert "review_ref" not in rework_match and "request_version" not in rework_match


def test_method_work_source_wait_declarations_and_append_policy_are_closed():
    method = _yaml(CANDIDATE / "method.yaml")
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    schema = json.loads((CANDIDATE / "documents/work-inputs/schema.json").read_text())
    work_source = method["metadata"]["work_source"]
    assert set(work_source) == {
        "contract_version", "input_document_slot", "input_document_type", "waits", "input_revision_policy"
    }
    assert work_source["input_revision_policy"] == {
        "contract": "ordessa.append-only-work-inputs/2",
        "event_values": "immutable_once_present",
        "round_events": "events_by_round",
    }
    waits = work_source["waits"]
    assert set(waits) == {node["id"] for node in workflow["steps"] if node["kind"] == "wait"}
    assert "metadata" not in workflow
    assert len(waits) == 32
    slots = set(workflow["context_slots"])
    event_properties = schema["properties"]["events"]["properties"]
    round_properties = schema["properties"]["events_by_round"]["additionalProperties"]["properties"]
    assert sum(value["event_map"] == "events_by_round" for value in waits.values()) == 8
    for wait_id, declaration in waits.items():
        compiled_wait = next(node for node in workflow["steps"] if node["id"] == wait_id)
        event_names = set(compiled_wait.get("match", {}))
        event_names.update(
            value[6:] for value in compiled_wait.get("bind", {}).values()
            if isinstance(value, str) and value.startswith("event.")
        )
        assert set(declaration["event_slots"]) == event_names, wait_id
        properties = round_properties if declaration["event_map"] == "events_by_round" else event_properties
        for selector in declaration["event_slots"].values():
            if selector["source"] == "slot":
                assert selector["slot"] in slots, (wait_id, selector)
            elif selector["source"] == "work_input":
                assert selector["field"] in properties[wait_id]["properties"], (wait_id, selector)
            elif selector["source"] == "blob_utf8":
                assert selector["field"] in properties[wait_id]["properties"], (wait_id, selector)
            else:
                raise AssertionError((wait_id, selector))
    assert method["metadata"]["candidate_binding_status"]["publication_allowed"] is False
    assert method["metadata"]["candidate_binding_status"]["execution_allowed"] is False


def test_review_target_sources_keep_missing_producers_explicit():
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    groups = {
        node["config"]["review_group"]["group_id"]: node["config"]["review_group"]
        for node in workflow["steps"]
        if node["kind"] == "operation" and "review_group" in node.get("config", {})
    }
    proposal_targets = groups["proposal_reviews"]["target_sources"]
    assert {target["source"] for target in proposal_targets} == {"proposal_proposed_revisions", "slot"}
    summary = next(target for target in proposal_targets if target["source"] == "slot")
    assert summary == {
        "source": "slot", "slot": "summary_ref", "document_types": ["session-summary"], "role": "support"
    }
    assert groups["package_reviews"]["target_sources"] == [{
        "source": "slot", "slot": "package_draft_ref", "document_types": ["spec-kit-package"], "role": "primary"
    }]
    assert groups["submission_acceptance"]["target_sources"] == [{
        "source": "submission_output_revisions", "document_types": ["submission"], "role": "output"
    }]
    assert groups["correction_review"]["target_sources"] == [{
        "source": "slot", "slot": "correction_plan_ref", "document_types": ["correction-plan"], "role": "primary"
    }]
    pending = _yaml(CANDIDATE / "pending-bindings.yaml")
    assert pending["review_phase_groups90"]["publication_allowed"] is False
    assert pending["review_phase_groups90"]["proposal_reviews"]["summary_source"] == "original_Proposal_frozen_ExactArtifactRevisionSelector"
    assert pending["review_phase_groups90"]["submission_acceptance"]["observations_source"] == "current_independent_review_not_a_prerequisite"
    for relative in ("standards/acceptance.yaml", "decisions/output-scope.yaml", "decisions/test-evidence.yaml"):
        assert "independent_review_observations" not in (CANDIDATE / relative).read_text()
    assert any("frozen original Package" in item for item in pending["review_phase_groups90"]["package_reviews"]["unresolved"])
    assert pending["work_input_append_only_policy"]["round_source"] == "original_MethodRun_inputs_rounds_only"


def test_candidate_resource_and_index_digests_match_current_bytes():
    method = _yaml(CANDIDATE / "method.yaml")
    for resource in method["resources"]:
        raw = (CANDIDATE / resource["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == resource["sha256"], resource["id"]
    index = json.loads((CANDIDATE / "candidate-index.json").read_text(encoding="utf-8"))
    actual_paths = sorted(
        path.relative_to(CANDIDATE).as_posix()
        for path in CANDIDATE.rglob("*")
        if path.is_file() and path.name != "candidate-index.json"
        and not any(part in ("__pycache__", ".pytest_cache") for part in path.parts)
    )
    assert [row["path"] for row in index["files"]] == actual_paths
    for row in index["files"]:
        assert hashlib.sha256((CANDIDATE / row["path"]).read_bytes()).hexdigest() == row["sha256"]
