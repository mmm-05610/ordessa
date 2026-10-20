"""Pure declaration decoding/round-trip tests; no owner/source proof is implied."""
from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator

from ordessa_engineering.methods import decode_review_groups
from ordessa_engineering.methods.compilation.encoding import (
    compiled_program_from_canonical, program_to_canonical,
)
from ordessa_engineering.methods.definitions.models.compiled import (
    CompiledProgram, FrozenObject, OperationNode, OutcomeBinding, OutcomeMap,
    ProgramBindings, SlotBinding, SlotMap, StopNode, TransitionTarget, WaitNode,
    WorkflowSpec, freeze_value,
    thaw_value,
)
from ordessa_engineering.methods.definitions.models.identity import ResourceRef
from ordessa_engineering.methods.definitions.schemas.v1 import REVIEW_GROUP_CONFIG_SCHEMA_V1


STANDARD = {"resource_id": "standard.source", "sha256": "a" * 64, "kind": "standard"}


def _operation(node_id, operation, config, outcomes, inputs=()):
    return OperationNode(id=node_id, kind="operation", operation=operation,
        outcomes=OutcomeMap(entries=tuple(OutcomeBinding(outcome=name, target=target) for name, target in outcomes)),
        inputs=SlotMap(entries=tuple(SlotBinding(name=name, slot=slot) for name, slot in inputs)),
        config=freeze_value(config))


def _workflow():
    group = {
        "contract": "ordessa.method-review-group/1",
        "group_id": "source-review",
        "subject_slot": "proposal_ref",
        "target_sources": [{"source": "slot", "slot": "proposal_ref",
            "document_types": ["did-change"], "role": "proposed"}],
        "material_sources": [{"name": "proposed-content", "source": "proposal_record"}],
        "members": [{"member_id": "source", "request_node": "request-source",
            "plan_slot": "source-plan", "standard": STANDARD,
            "response_wait": "await-source", "record_node": "record-source"}],
        "gate_wait": "source-gate", "required_members": "all_declared", "empty_members": "error",
    }
    binding = {"contract": "ordessa.method-review-binding/1", "anchor_node": "request-source",
        "group_id": "source-review", "member_id": "source"}
    request = _operation("request-source", "engineering.reviews.request", {
        "review_group": group, "review_binding": binding, "standards": [STANDARD],
    }, (("completed", TransitionTarget(next="await-source")),
        ("rejected", TransitionTarget(stop="revision_required"))), (("plan", "source-plan"),))
    response = WaitNode(id="await-source", kind="wait", event="engineering.work.current_condition",
        next="record-source")
    record = _operation("record-source", "engineering.reviews.record", {}, (
        ("completed", TransitionTarget(next="source-gate")),
        ("rejected", TransitionTarget(stop="revision_required"))),
    )
    gate = WaitNode(id="source-gate", kind="wait", event="engineering.work.current_condition", next="done")
    stop = StopNode(id="done", kind="stop", outcome="reviewed")
    return WorkflowSpec(schema_version=1, entry="request-source",
        steps=(request, response, record, gate, stop), stop_outcomes=("reviewed", "revision_required"),
        wait_kinds=("engineering.work.current_condition",),
        context_slots=("proposal_ref", "source-plan"))


def test_compiled_declaration_decodes_to_typed_closed_group_and_round_trips():
    workflow = _workflow()
    groups = decode_review_groups(workflow)
    assert len(groups) == 1
    group = groups[0]
    assert group.group_id == "source-review"
    assert group.members[0].standard_ref == ResourceRef(**STANDARD)
    assert group.members[0].plan_slot == "source-plan"
    assert group.target_sources[0].source == "slot"
    assert group.required_members == "all_declared" and group.empty_members == "error"

    program = CompiledProgram(compiler_version="test.review-binding/1", workflow=workflow,
        document_definitions=(), schema_definitions=(), standard_definitions=(),
        decision_definitions=(), skill_definitions=(), capability_bindings=())
    wire = program_to_canonical(program)
    restored = compiled_program_from_canonical(
        wire, ProgramBindings(standards=(), decisions=())
    )
    assert program_to_canonical(restored) == wire
    assert decode_review_groups(restored.workflow) == groups

    # Existing programs that omit both optional declarations preserve their
    # canonical wire unchanged and decode to no newly inferred groups.
    legacy_request = replace(workflow.steps[0], config=freeze_value({"standards": [STANDARD]}))
    legacy_workflow = replace(workflow, steps=(legacy_request, *workflow.steps[1:]))
    legacy_program = replace(program, workflow=legacy_workflow)
    legacy_wire = program_to_canonical(legacy_program)
    legacy_restored = compiled_program_from_canonical(
        legacy_wire, ProgramBindings(standards=(), decisions=())
    )
    assert program_to_canonical(legacy_restored) == legacy_wire
    assert decode_review_groups(legacy_restored.workflow) == ()


def test_group_schema_is_closed_and_source_projection_is_finite():
    request = _workflow().steps[0]
    config = thaw_value(request.config)
    group = config["review_group"]
    # The external schema checks symbolic resource references before the
    # compiler binds the immutable ResourceRef used by the decoder above.
    group = {**group, "members": [
        {**member, "standard": {"resource": member["standard"]["resource_id"]}}
        for member in group["members"]
    ]}
    assert Draft202012Validator(REVIEW_GROUP_CONFIG_SCHEMA_V1).is_valid(group)

    invalid_role = {**group, "target_sources": [{"source": "slot",
        "slot": "proposal_ref", "document_types": ["did-change"], "role": "proposed-change"}]}
    assert not Draft202012Validator(REVIEW_GROUP_CONFIG_SCHEMA_V1).is_valid(invalid_role)

    unknown = {**group, "infer_from_future_nodes": True}
    assert not Draft202012Validator(REVIEW_GROUP_CONFIG_SCHEMA_V1).is_valid(unknown)
    unbounded = {**group, "target_sources": [{"source": "arbitrary_path",
        "path": "proposal.whatever", "document_types": ["did-change"], "role": "target"}]}
    assert not Draft202012Validator(REVIEW_GROUP_CONFIG_SCHEMA_V1).is_valid(unbounded)
    wrong_slot = {**group, "material_sources": [{"name": "x", "source": "proposal_record", "slot": "guess"}]}
    # A record projection may name an exact slot, while a generic target
    # projection has no arbitrary slot selector.
    assert Draft202012Validator(REVIEW_GROUP_CONFIG_SCHEMA_V1).is_valid(wrong_slot)
    submission_targets = {**group, "target_sources": [{"source": "submission_output_revisions",
        "document_types": ["submission"], "role": "output"}]}
    assert Draft202012Validator(REVIEW_GROUP_CONFIG_SCHEMA_V1).is_valid(submission_targets)
    unbounded_target = {**group, "target_sources": [{"source": "submission_output_revisions",
        "document_types": ["submission"], "role": "output", "slot": "guess"}]}
    assert not Draft202012Validator(REVIEW_GROUP_CONFIG_SCHEMA_V1).is_valid(unbounded_target)
    slotted_targets_projection = {**group, "material_sources": [{"name": "x", "source": "targets", "slot": "guess"}]}
    assert not Draft202012Validator(REVIEW_GROUP_CONFIG_SCHEMA_V1).is_valid(slotted_targets_projection)


def test_decoder_rejects_nonclosed_path_or_unowned_binding():
    workflow = _workflow()
    request = workflow.steps[0]
    bad_request = replace(request, outcomes=OutcomeMap(entries=(
        OutcomeBinding(outcome="completed", target=TransitionTarget(next="source-gate")),
        OutcomeBinding(outcome="rejected", target=TransitionTarget(stop="revision_required")),
    )))
    bad = replace(workflow, steps=(bad_request, *workflow.steps[1:]))
    with pytest.raises(ValueError, match="path is not closed"):
        decode_review_groups(bad)

    bare = replace(request, config=freeze_value({"standards": [STANDARD],
        "review_binding": thaw_value(request.config)["review_binding"]}))
    unowned = replace(workflow, steps=(bare, *workflow.steps[1:]))
    with pytest.raises(ValueError, match="unowned"):
        decode_review_groups(unowned)


def test_group_allows_only_explicit_ordered_advance_waits_between_members():
    group = {
        "contract": "ordessa.method-review-group/1", "group_id": "source-review",
        "subject_slot": "proposal_ref",
        "target_sources": [{"source": "slot", "slot": "proposal_ref",
            "document_types": ["did-change"], "role": "proposed"}],
        "material_sources": [{"name": "proposed-content", "source": "proposal_record"}],
        "members": [
            {"member_id": "source", "request_node": "request-source", "plan_slot": "source-plan",
                "standard": STANDARD, "response_wait": "await-source", "record_node": "record-source",
                "advance_waits": ["await-source-gate", "await-quality-plan"]},
            {"member_id": "quality", "request_node": "request-quality", "plan_slot": "quality-plan",
                "standard": {**STANDARD, "resource_id": "standard.quality", "sha256": "b" * 64},
                "response_wait": "await-quality", "record_node": "record-quality"},
        ],
        "gate_wait": "await-quality-gate", "required_members": "all_declared", "empty_members": "error",
    }

    def request(node_id, member_id, plan, standard):
        binding = {"contract": "ordessa.method-review-binding/1", "anchor_node": "request-source",
            "group_id": "source-review", "member_id": member_id}
        config = {"review_binding": binding, "standards": [standard]}
        if node_id == "request-source":
            config["review_group"] = group
        return _operation(node_id, "engineering.reviews.request", config,
            (("completed", TransitionTarget(next=f"await-{member_id}")),
             ("rejected", TransitionTarget(stop="revision_required"))), (("plan", plan),))

    source_req = request("request-source", "source", "source-plan", STANDARD)
    source_response = WaitNode(id="await-source", kind="wait", event="engineering.work.current_condition", next="record-source")
    source_record = _operation("record-source", "engineering.reviews.record", {}, (
        ("completed", TransitionTarget(next="await-source-gate")),
        ("rejected", TransitionTarget(stop="revision_required"))))
    source_gate = WaitNode(id="await-source-gate", kind="wait", event="engineering.work.current_condition", next="await-quality-plan")
    plan_wait = WaitNode(id="await-quality-plan", kind="wait", event="engineering.work.current_condition", next="request-quality")
    quality_req = request("request-quality", "quality", "quality-plan", group["members"][1]["standard"])
    quality_response = WaitNode(id="await-quality", kind="wait", event="engineering.work.current_condition", next="record-quality")
    quality_record = _operation("record-quality", "engineering.reviews.record", {}, (
        ("completed", TransitionTarget(next="await-quality-gate")),
        ("rejected", TransitionTarget(stop="revision_required"))))
    final_gate = WaitNode(id="await-quality-gate", kind="wait", event="engineering.work.current_condition", next="done")
    done = StopNode(id="done", kind="stop", outcome="reviewed")
    workflow = WorkflowSpec(schema_version=1, entry="request-source",
        steps=(source_req, source_response, source_record, source_gate, plan_wait,
            quality_req, quality_response, quality_record, final_gate, done),
        stop_outcomes=("reviewed", "revision_required"),
        wait_kinds=("engineering.work.current_condition",),
        context_slots=("proposal_ref", "source-plan", "quality-plan"))

    decoded = decode_review_groups(workflow)
    assert decoded[0].members[0].advance_waits == ("await-source-gate", "await-quality-plan")
    reversed_steps = replace(workflow.steps[3], next="request-quality")
    broken = replace(workflow, steps=(source_req, source_response, source_record,
        reversed_steps, plan_wait, quality_req, quality_response, quality_record, final_gate, done))
    with pytest.raises(ValueError, match="ordered path"):
        decode_review_groups(broken)
