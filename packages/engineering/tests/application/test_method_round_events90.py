"""Round-addressed input selection over the original persisted Work counter."""
from types import SimpleNamespace

import pytest

from ordessa_engineering.adapters.method_work import (
    parse_round_event_key,
    selected_wait_input_event,
    validate_work_input_progression,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_runs import (
    _loop_round,
    observed_loop_round,
)
from ordessa_engineering.methods.definitions.models.compiled import (
    LoopSpec,
    OperationNode,
    OutcomeBinding,
    OutcomeMap,
    StopNode,
    TransitionTarget,
    WaitNode,
    WorkflowSpec,
)


def _program():
    wait = WaitNode(id="round_wait", kind="wait", event="wake", next="round_step")
    step = OperationNode(
        id="round_step", kind="operation", operation="engineering.test.noop",
        outcomes=OutcomeMap(entries=(OutcomeBinding(
            outcome="again", target=TransitionTarget(next="round_wait")),)),
    )
    outside = WaitNode(id="outside_wait", kind="wait", event="wake", next="finished")
    finished = StopNode(id="finished", kind="stop", outcome="done")
    workflow = WorkflowSpec(
        schema_version=1, entry="outside_wait", steps=(wait, step, outside, finished),
        stop_outcomes=("done",), wait_kinds=("owner_reconciliation",),
        loops=(LoopSpec(loop_id="rework", from_step="round_step", to_step="round_wait",
                        max_rounds=2, on_exhausted="done"),),
    )
    return SimpleNamespace(workflow=workflow)


def _policy():
    return {
        "input_revision_policy": {
            "contract": "ordessa.append-only-work-inputs/2",
            "event_values": "immutable_once_present",
            "round_events": "events_by_round",
        },
        "waits": {
            "round_wait": {"event_map": "events_by_round"},
            "outside_wait": {"event_map": "events"},
        },
    }


def _document():
    return {
        "document_type": "work-inputs", "schema_version": 2,
        "run_id": "work-rounds", "proposal_ref": {"kind": "fixture"},
        "events": {"outside_wait": {"comment": "static"}},
        "events_by_round": {
            "1": {"round_wait": {"comment": "first"}},
            "2": {"round_wait": {"comment": "second"}},
        },
    }


def test_selects_only_the_original_work_round_and_keeps_legacy_non_loop_map():
    program = _program()
    row = {"inputs": {"rounds": {"rework": 2}}}
    policy, document = _policy(), _document()

    assert observed_loop_round(program, row, "round_wait") == ("rework", 2)
    assert _loop_round(program, row, "outside_wait") == 1
    assert observed_loop_round(program, row, "outside_wait") is None
    assert selected_wait_input_event(policy, document, "round_wait", row, program) == {
        "comment": "second"}
    assert selected_wait_input_event(policy, document, "outside_wait", row, program) == {
        "comment": "static"}


def test_loop_wait_does_not_fall_back_when_current_round_is_missing():
    program, row, policy, document = _program(), {"inputs": {"rounds": {"rework": 2}}}, _policy(), _document()
    del document["events_by_round"]["2"]
    document["events"]["round_wait"] = {"comment": "stale-static"}
    with pytest.raises(ApplicationError, match="WORK_INPUT_EVENT_MISSING"):
        selected_wait_input_event(policy, document, "round_wait", row, program)


def test_explicit_map_must_match_compiled_loop_membership():
    program = _program()
    document = _document()
    row = {"inputs": {"rounds": {"rework": 1}}}
    policy = _policy()
    policy["waits"]["round_wait"]["event_map"] = "events"
    with pytest.raises(ApplicationError, match="WORK_INPUT_EVENT_MAP_MISMATCH"):
        selected_wait_input_event(policy, document, "round_wait", row, program)


def test_round_keys_are_canonical_nonnegative_decimal_strings():
    assert parse_round_event_key("0") == 0
    assert parse_round_event_key("1") == 1
    for invalid in ("01", "-1", "+1", "1.0", "", 1, True):
        with pytest.raises(ApplicationError, match="WORK_INPUT_DOCUMENT_INVALID"):
            parse_round_event_key(invalid)


def test_append_preserves_every_prior_round_and_only_adds_new_values():
    policy = _policy()
    previous = _document()
    current = _document()
    current["events_by_round"]["2"]["round_wait"]["revision"] = "new-input"
    current["events_by_round"]["1"]["additional"] = "first-round-extension"
    validate_work_input_progression(policy, previous, current)

    changed = _document()
    changed["events_by_round"]["1"]["round_wait"]["comment"] = "rewritten"
    with pytest.raises(ApplicationError, match="WORK_INPUT_EVENT_CHANGED"):
        validate_work_input_progression(policy, previous, changed)


def test_append_rejects_cross_run_and_removal_of_a_prior_round():
    policy = _policy()
    previous = _document()
    cross_run = _document()
    cross_run['run_id'] = 'another-work-run'
    with pytest.raises(ApplicationError, match='WORK_INPUT_DOCUMENT_MISMATCH'):
        validate_work_input_progression(policy, previous, cross_run)

    missing_round = _document()
    del missing_round['events_by_round']['1']
    with pytest.raises(ApplicationError, match='WORK_INPUT_EVENT_CHANGED'):
        validate_work_input_progression(policy, previous, missing_round)


def test_schema_v1_keeps_its_original_static_event_interpretation():
    legacy_policy = {"waits": {"round_wait": {"family": "object_exists"}}}
    legacy_document = {
        "document_type": "work-inputs", "schema_version": 1,
        "run_id": "legacy", "proposal_ref": {"kind": "fixture"},
        "events": {"round_wait": {"comment": "legacy-static"}},
    }
    assert selected_wait_input_event(
        legacy_policy, legacy_document, "round_wait",
        {"inputs": {"rounds": {"rework": 2}}}, _program()) == {
            "comment": "legacy-static"}
