"""Cross-check the frozen 2.6 rework loop against its declared Work bindings.

This is a candidate-contract test only. It does not exercise publication,
production reviewer sources, a Unit, or an end-to-end engineering run.
"""
from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
CANDIDATE = REPO_ROOT / "methods/incremental-engineering/candidates/2.6.0"


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step(workflow, step_id):
    return next(step for step in workflow["steps"] if step["id"] == step_id)


def test_rework_loop_is_two_bounded_rounds_and_returns_to_same_package_permission():
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    method = _yaml(CANDIDATE / "method.yaml")
    bindings = _yaml(CANDIDATE / "pending-bindings.yaml")

    loop = next(row for row in workflow["loops"] if row["loop_id"] == "implementation-rework")
    assert loop == {
        "loop_id": "implementation-rework",
        "from_step": "record_rework_review",
        "to_step": "await_implementation_permission",
        "max_rounds": 2,
        "on_exhausted": "revision_required",
    }
    rework = _step(workflow, "record_rework_review")
    assert rework["outcomes"]["completed"]["next"] == "await_implementation_permission"
    assert rework["result_routing"]["path"] == "/verdict"
    assert rework["result_routing"]["outcomes"] == {
        "pass": {"next": "await_implementation_permission"},
        "fail": {"stop": "revision_required"},
        "indeterminate": {"stop": "unknown"},
    }

    permission = _step(workflow, "await_implementation_permission")
    dispatch = _step(workflow, "dispatch")
    assert permission["bind"] == {"dispatch_input": "event.dispatch_input"}
    assert permission["match"] == {"package": "package_ref", "method": "method_ref"}
    assert dispatch["config"]["package_slot"] == "package_ref"
    assert dispatch["outcomes"]["unknown"] == {"stop": "unknown"}
    assert workflow["automatic_side_effect_retry"] == "forbidden_when_outcome_unknown"
    assert "package_ref" in workflow["context_slots"]
    assert "package_ref" not in permission["bind"]  # the loop preserves the frozen binding

    loop_policy = bindings["method76_bindings"]["ordinary_rework"]
    assert loop_policy["maximum_rounds"] == loop["max_rounds"]
    assert loop_policy["exhaustion"] == loop["on_exhausted"]
    requirements = [" ".join(item.split()) for item in loop_policy["source_and_guard_requirements"]]
    assert any("current action Grant and remaining budget for the same exact frozen package" in item
               for item in requirements)
    assert any("never reuse spent budget or replace its authorization refs" in item for item in requirements)
    assert any("no automatic package renewal" in item for item in requirements)
    assert method["release_version"] == "2.6.0"


def test_round_two_inputs_bind_new_submission_and_fresh_review_to_immutable_lineage():
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    method = _yaml(CANDIDATE / "method.yaml")
    input_schema = _yaml(CANDIDATE / "documents/work-inputs/schema.json")
    bindings = _yaml(CANDIDATE / "pending-bindings.yaml")

    waits = method["metadata"]["work_source"]["waits"]
    round_specific = (
        "await_implementation_permission",
        "await_execution_capture",
        "await_submission",
        "await_acceptance_plan",
        "await_acceptance_response",
        "await_acceptance_gate",
        "await_rework_review_plan",
        "await_rework_review_response",
    )
    assert all(waits[step]["event_map"] == "events_by_round" for step in round_specific)
    assert method["metadata"]["work_source"]["input_revision_policy"] == {
        "contract": "ordessa.append-only-work-inputs/2",
        "event_values": "immutable_once_present",
        "round_events": "events_by_round",
    }
    version_two = next(
        clause["then"] for clause in input_schema["allOf"]
        if clause.get("if", {}).get("properties", {}).get("schema_version", {}).get("const") == 2
    )
    assert "events_by_round" in version_two["required"]
    assert input_schema["additionalProperties"] is False

    capture = _step(workflow, "await_execution_capture")
    record = _step(workflow, "record_submission")
    submitted = _step(workflow, "await_submission")
    acceptance_plan = _step(workflow, "await_acceptance_plan")
    acceptance_response = _step(workflow, "await_acceptance_response")
    assert capture["bind"] == {"submission_record": "event.submission_record"}
    assert capture["match"] == {"package": "package_ref", "method": "method_ref"}
    assert record["operation"] == "engineering.submissions.record_report"
    assert record["outcomes"]["completed"]["next"] == "await_submission"
    assert submitted["bind"] == {"submission_ref": "event.submission_ref"}
    assert acceptance_plan["match"] == {"submission": "submission_ref", "method": "method_ref"}
    assert acceptance_response["match"] == {
        "plan": "acceptance_review_plan",
        "submission": "submission_ref",
        "method": "method_ref",
    }
    response_wait = waits["await_acceptance_response"]
    assert response_wait["subject_slot"] == "submission_ref"
    assert response_wait["review_id_slot"] == "acceptance_review_id"
    assert response_wait["request_version_slot"] == "acceptance_request_version"
    assert response_wait["fence_slot"] == "acceptance_review_fence"

    rework_plan = _step(workflow, "await_rework_review_plan")
    assert rework_plan["match"]["submission"] == "submission_ref"
    assert rework_plan["match"]["package"] == "package_ref"
    assert rework_plan["match"]["method"] == "method_ref"
    assert rework_plan["match"]["acceptance_request_id"] == "acceptance_review_id"
    rework_response_wait = waits["await_rework_review_response"]
    assert rework_response_wait["subject_slot"] == "correction_plan_ref"
    assert rework_response_wait["review_id_slot"] == "rework_review_id"
    assert rework_response_wait["request_version_slot"] == "rework_request_version"
    assert rework_response_wait["fence_slot"] == "rework_review_fence"

    policy = bindings["method76_bindings"]["ordinary_rework"]
    assert any("new exact report/SubmissionRef" in item and "fresh independent review" in item
               for item in policy["source_and_guard_requirements"])
    strategy = record["config"]["unit_submission_review_strategy"]
    assert strategy["rework"]["new_delivery"] == (
        "new exact ArtifactRevisionRef and original SubmissionRef, retain old source/submission/review facts"
    )


def test_candidate_does_not_turn_unknown_or_failed_review_into_another_attempt():
    workflow = _yaml(CANDIDATE / "workflows/change-cycle.yaml")
    method = _yaml(CANDIDATE / "method.yaml")

    for step_id in ("record_acceptance_review", "record_rework_review"):
        result = _step(workflow, step_id)["result_routing"]["outcomes"]
        assert result["indeterminate"] == {"stop": "unknown"}
    assert _step(workflow, "dispatch")["outcomes"]["unknown"] == {"stop": "unknown"}
    assert _step(workflow, "record_rework_review")["result_routing"]["outcomes"]["fail"] == {
        "stop": "revision_required"
    }
    assert workflow["automatic_side_effect_retry"] == "forbidden_when_outcome_unknown"

    candidate_status = method["metadata"]["candidate_binding_status"]
    assert candidate_status["publication_allowed"] is False
    assert candidate_status["execution_allowed"] is False
