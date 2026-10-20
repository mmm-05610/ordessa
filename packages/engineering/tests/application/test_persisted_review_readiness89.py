"""Narrow Work-source readiness transport checks.

The original SQLite proposal, plan, request, and raw blob are real. The test
provider and tiny topology/input-event projection are deliberately synthetic;
they qualify the adapter contract only, not a production review source or
method publication.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace

import pytest

from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
from ordessa_engineering.application.contracts.commands import (
    ReadSet, ReadVersion,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.run_waits import ReviewReadiness
from ordessa_engineering.domain.reviews.models import ReviewRequestExpectation
from ordessa_engineering.methods.definitions.models.compiled import (
    OperationNode, OutcomeMap, SlotBinding, SlotMap, StopNode,
    TransitionTarget, WaitNode,
)

from submission_wait_business_fixture import build_submission_wait_fixture


class _ReadinessPeer:
    """Synthetic test peer; it asserts the original exact inputs it receives."""

    def __init__(self, factory, methods):
        self.factory = factory
        self.methods = methods
        self.plan_value = None
        self.response_value = None
        self.entered = []

    @contextmanager
    def guard_plan_ready(self, context, snapshot, plan, *, phase_key,
                         input_ref, subject_ref, view):
        assert phase_key == plan.requirement.phase_key
        assert input_ref == self.plan_value.input_ref
        assert subject_ref == self.plan_value.subject_ref
        self.entered.append("plan")
        try:
            # This is the regression boundary: the source's original read UoW
            # must already be closed before a provider opens another one.
            with self.factory.begin(context.scope, "read"):
                self.entered.append("provider-read")
            yield self.plan_value
        finally:
            self.entered.append("plan-closed")

    @contextmanager
    def guard_response_ready(self, context, snapshot, plan, request,
                             raw_response_ref, *, phase_key, input_ref,
                             subject_ref, view):
        assert phase_key == plan.requirement.phase_key
        assert request.review_id == plan.review_id
        assert raw_response_ref == self.response_value.raw_response_ref
        assert input_ref == self.response_value.input_ref
        assert subject_ref == self.response_value.subject_ref
        self.entered.append("response")
        try:
            with self.factory.begin(context.scope, "read"):
                self.entered.append("provider-read")
            yield self.response_value
        finally:
            self.entered.append("response-closed")


def _assert_readiness_projection(actual, original):
    assert actual.plan == original.plan
    assert actual.input_ref == original.input_ref
    assert actual.subject_ref == original.subject_ref
    assert actual.raw_response_ref == original.raw_response_ref
    assert actual.read_set.scope == original.read_set.scope
    assert set(original.read_set.versions) <= set(actual.read_set.versions)
    assert {"proposal_control", "change", "artifact"} <= {
        item.kind for item in actual.read_set.versions}
    assert actual.read_set.review_requests == original.read_set.review_requests
    assert actual.read_set.review_sets == ()
    assert actual.read_set.review_controls == ()


def _source(e, peer):
    source = SQLitePersistedMethodWorkSource(
        e["factory"], e["controls"], blobs=e["blobs"],
        review_bindings=e["bindings"], review_readiness=peer)
    original = source._manifest_policy(e["snapshot"])

    def use_wait(spec):
        def policy(snapshot):
            waits = {}
            for step in snapshot.program.workflow.steps:
                if isinstance(step, WaitNode):
                    waits[step.id] = (spec if step.id == "await_acceptance"
                                      else original["waits"].get(step.id))
            return {**original, "waits": waits}
        source._manifest_policy = policy

    return source, use_wait


def _with_wait(e, source, *, mode, event_document=None, incoming_subject=False,
               request_edge=True, nonadjacent=False):
    """Create a local adapter-boundary topology over the real frozen snapshot."""
    from dataclasses import replace as dc_replace

    original_steps = e["snapshot"].program.workflow.steps
    request = next(step for step in original_steps
                   if isinstance(step, OperationNode)
                   and step.operation == "engineering.reviews.request"
                   and step.id == "acceptance_review")
    wait = next(step for step in original_steps
                if isinstance(step, WaitNode) and step.id == "await_acceptance")
    slots = dict(e["view"]["row"]["inputs"]["slots"])
    if not incoming_subject:
        slots["submission_ref"] = asdict(e["submission"].ref)

    if mode == "plan":
        selected_plan = replace(e["plan"], review_id="unrequested-plan")
        slots["acceptance_plan"] = asdict(selected_plan)
        bind = (SlotMap(entries=(SlotBinding("submission_ref", "event.submission_ref"),))
                if incoming_subject else None)
        wait = dc_replace(wait, next=request.id, bind=bind, match=None)
        steps = (wait, request)
        cursor = 0
    else:
        if request_edge:
            request = dc_replace(request, outcomes=OutcomeMap(entries=tuple(
                dc_replace(binding, target=TransitionTarget(wait=wait.id))
                if binding.outcome == "completed" else binding
                for binding in request.outcomes.entries)))
        record = dc_replace(request, id="record_acceptance",
                            operation="engineering.reviews.record")
        bind = SlotMap(entries=(
            SlotBinding("bound_review_id", "event.review_id"),
            SlotBinding("bound_request_version", "event.request_version"),
            SlotBinding("bound_fence", "event.fence"),
            SlotBinding("bound_response", "event.response"),
        ))
        wait = dc_replace(wait, next=record.id, bind=bind, match=None)
        if nonadjacent:
            other = next(step for step in original_steps
                         if isinstance(step, OperationNode)
                         and step.operation == "engineering.reviews.request"
                         and step.id == "quality_review")
            steps = (request, other, wait, record)
            cursor = 2
        else:
            steps = (request, wait, record)
            cursor = 1
    workflow = dc_replace(e["snapshot"].program.workflow, steps=steps)
    program = dc_replace(e["snapshot"].program, workflow=workflow)
    snapshot = dc_replace(e["snapshot"], program=program)
    row = {**e["view"]["row"], "cursor": cursor,
           "inputs": {**e["view"]["row"]["inputs"], "slots": slots}}
    from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest
    with e["factory"].begin(e["scope"], "read") as uow:
        native_row = uow.workflow.run_row(e["view"]["run_id"])
    digest_row = {**native_row, "cursor": cursor, "inputs": row["inputs"]}
    view = {**e["view"], "row": row,
            "row_digest": run_wait_row_digest(digest_row)}
    if event_document is not None:
        # Isolate event-selector validation from production document creation;
        # the referenced bytes are still read from the original BlobStore.
        source._input_document = lambda _uow, _snapshot, _policy, _slots, *, run_id: (
            e["inputs"].ref, event_document, e["proposal"].ref)
    return snapshot, wait, view


def test_plan_readiness_resolves_incoming_subject_and_holds_readset_to_write(tmp_path):
    e = build_submission_wait_fixture(tmp_path)
    try:
        peer = _ReadinessPeer(e["factory"], e["controls"])
        source, use_wait = _source(e, peer)
        input_ref = e["inputs"].ref
        subject_ref = e["submission"].ref
        readiness = ReviewReadiness(
            e["plan"], input_ref, subject_ref,
            ReadSet(e["scope"], (ReadVersion("artifact", input_ref.artifact_id, 1),)))
        # The plan deliberately has no stored request; readiness is pre-request.
        readiness = replace(readiness, plan=replace(readiness.plan,
                                                      review_id="unrequested-plan"))
        peer.plan_value = readiness
        event_document = {"document_type": "test-work-inputs", "schema_version": 1,
            "run_id": "work-source-run", "proposal_ref": asdict(e["proposal"].ref),
            "events": {"await_acceptance": {"submission_ref": asdict(subject_ref)}}}
        use_wait({"family": "review_plan_ready", "plan_slot": "acceptance_plan",
                  "phase_key": "acceptance_review", "subject_slot": "submission_ref",
                  "event_slots": {"submission_ref": {"source": "work_input",
                                                        "field": "submission_ref"}}})
        snapshot, node, view = _with_wait(e, source, mode="plan",
                                          event_document=event_document,
                                          incoming_subject=True)
        assert "submission_ref" not in view["row"]["inputs"]["slots"]

        with source.guard_condition(e["context"], snapshot, node, view) as selected:
            assert selected.condition.family == "review_plan_ready"
            _assert_readiness_projection(selected.condition.readiness, readiness)
            assert selected.event_values["submission_ref"] == asdict(subject_ref)
            assert peer.entered == ["plan", "provider-read"]
            # Starting a new original write UoW is safe here; its begin path
            # rechecks the still-active merged source ReadSet.
            with e["factory"].begin(e["scope"], "write") as uow:
                uow.engineering.check_read_set(selected.condition.readiness.read_set)
                uow.commit()
            assert peer.entered == ["plan", "provider-read"]
        assert peer.entered == ["plan", "provider-read", "plan-closed"]
    finally:
        e["library"].close()


def test_response_readiness_requires_exact_original_request_and_blob(tmp_path):
    e = build_submission_wait_fixture(tmp_path)
    try:
        request, readiness, peer, source, use_wait, input_document = _response_setup(e)
        snapshot, node, view = _with_wait(e, source, mode="response",
                                          event_document=input_document,
                                          nonadjacent=True)

        with source.guard_condition(e["context"], snapshot, node, view) as selected:
            assert selected.condition.family == "review_response_ready"
            _assert_readiness_projection(selected.condition.readiness, readiness)
            assert selected.event_values["response"] == e["blobs"].read_verified(
                readiness.raw_response_ref).decode("utf-8")
            assert peer.entered == ["response", "provider-read"]
        assert peer.entered == ["response", "provider-read", "response-closed"]
    finally:
        e["library"].close()


def _response_setup(e, *, request_version=None, fence=None):
    with e["factory"].begin(e["scope"], "read") as uow:
        request = uow.reviews.get_request(e["plan"].review_id)
    input_ref = e["inputs"].ref
    expected = ReviewRequestExpectation(
        e["scope"], request.review_id, e["plan"].plan_digest,
        request.version, request.fence)
    readiness = ReviewReadiness(e["plan"], input_ref, e["submission"].ref,
        ReadSet(e["scope"], (ReadVersion("artifact", input_ref.artifact_id, 1),),
                review_requests=(expected,)), raw_response_ref=e["blob"])
    peer = _ReadinessPeer(e["factory"], e["controls"])
    peer.response_value = readiness
    source, use_wait = _source(e, peer)
    input_document = {"document_type": "test-work-inputs", "schema_version": 1,
        "run_id": "work-source-run", "proposal_ref": asdict(e["proposal"].ref),
        "events": {"await_acceptance": {
            "review_id": request.review_id,
            "request_version": request.version if request_version is None else request_version,
            "fence": request.fence if fence is None else fence,
            "response": asdict(e["blob"])}}}
    use_wait({"family": "review_response_ready", "plan_slot": "acceptance_plan",
        "phase_key": "acceptance_review", "subject_slot": "submission_ref",
        "review_id_slot": "bound_review_id", "request_version_slot": "bound_request_version",
        "fence_slot": "bound_fence", "response_event": "response",
        "event_slots": {
            "review_id": {"source": "work_input", "field": "review_id"},
            "request_version": {"source": "work_input", "field": "request_version"},
            "fence": {"source": "work_input", "field": "fence"},
            "response": {"source": "blob_utf8", "field": "response"},
        }})
    return request, readiness, peer, source, use_wait, input_document


def test_response_readiness_rejects_stale_request_version_before_provider(tmp_path):
    e = build_submission_wait_fixture(tmp_path)
    try:
        with e["factory"].begin(e["scope"], "read") as uow:
            request = uow.reviews.get_request(e["plan"].review_id)
        request, readiness, peer, source, use_wait, input_document = _response_setup(
            e, request_version=request.version + 1)
        snapshot, node, view = _with_wait(e, source, mode="response",
                                          event_document=input_document)

        with pytest.raises(ApplicationError) as raised:
            with source.guard_condition(e["context"], snapshot, node, view):
                pass
        assert raised.value.code == "WORK_REVIEW_BINDING_MISMATCH"
        assert peer.entered == []
    finally:
        e["library"].close()


def test_response_readiness_rejects_adjacent_request_without_declared_edge(tmp_path):
    e = build_submission_wait_fixture(tmp_path)
    try:
        _request, _readiness, peer, source, _use_wait, input_document = _response_setup(e)
        snapshot, node, view = _with_wait(e, source, mode="response",
            event_document=input_document, request_edge=False, nonadjacent=False)
        with pytest.raises(ApplicationError) as raised:
            with source.guard_condition(e["context"], snapshot, node, view):
                pass
        assert raised.value.code == "WORK_REVIEW_BINDING_MISMATCH"
        assert peer.entered == []
    finally:
        e["library"].close()


@pytest.mark.parametrize("field", ["request_version", "fence"])
def test_response_readiness_rejects_boolean_integer_alias(tmp_path, field):
    e = build_submission_wait_fixture(tmp_path)
    try:
        request, _readiness, peer, source, _use_wait, _document = _response_setup(e)
        if field == "request_version":
            assert request.version == 0
            kwargs = {"request_version": False}
        else:
            assert request.fence == 1
            kwargs = {"fence": True}
        _request, _readiness, peer, source, _use_wait, input_document = _response_setup(e, **kwargs)
        snapshot, node, view = _with_wait(e, source, mode="response",
                                          event_document=input_document,
                                          nonadjacent=True)
        with pytest.raises(ApplicationError) as raised:
            with source.guard_condition(e["context"], snapshot, node, view):
                pass
        assert raised.value.code == "WORK_REVIEW_BINDING_MISMATCH"
        assert peer.entered == []
    finally:
        e["library"].close()

