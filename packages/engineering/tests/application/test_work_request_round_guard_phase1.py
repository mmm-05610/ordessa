"""Original-SQLite Work request round guards on the frozen 2.6.0 candidate.

The fixture proves the persisted request/journal correlation and round guard
against one real candidate snapshot and one EngineeringLibrary. Admission is a
controlled test port; this does not qualify production reviewer authority or a
complete method/product flow.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
from urllib.parse import urljoin

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import (
    SQLiteWorkReviewBindings, SQLiteWorkReviewReadiness,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WORK_CONTRACT
from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest
from ordessa_engineering.application.orchestration.method_content import document_spec
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, MethodContent, MethodPayload
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import ReviewRequestState
from ordessa_engineering.methods import compile_method, load_method
from ordessa_engineering.methods.compilation.encoding import program_plan_digest
from ordessa_engineering.methods.definitions.models import MethodSource, thaw_value

from test_persisted_method_work import (
    CANDIDATE, HostFixtureCatalog, _host_fixture_capabilities,
    persisted_source,
)
from test_proposal_usecases import _draft, _proposal_ref, _ctx, _usecases as proposal_usecases
from test_review_usecases import _context
from test_work_reader_phase1 import _append_v2_input


def _freeze_candidate(e):
    loaded = load_method(MethodSource(CANDIDATE), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    capabilities = _host_fixture_capabilities()
    compiled = compile_method(loaded.value, capabilities, "fixture:phase1-request-round-guard")
    assert compiled.ok and compiled.value is not None, compiled.error
    frozen = freeze_method(compiled.value, e["store"], e["store"],
        capability_catalog=HostFixtureCatalog(capabilities))
    assert frozen.ok and frozen.value is not None, frozen.error
    ref = frozen.value.ref
    method_ref = MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                           Digest("sha256", ref.snapshot_digest))
    from test_method_control_admission import TestManagement
    MethodUseCases(e["factory"], e["access"], e["store"], TestManagement()).adopt(
        method_ref, _context(e["input_revision"].scope, "phase1-adopt-round-guard-candidate"),
        expected_version=1)
    return method_ref, e["controls"].read_snapshot(method_ref)


def _candidate_proposal(e, method_ref):
    with e["factory"].begin(e["input_revision"].scope, "read") as uow:
        original = uow.proposals.get_proposal(e["proposal_ref"])
        mutation = original.mutations[0]
        base = uow.engineering.resolve_revision(mutation.base_ref)
        claim = next(item for item in base.claims if item.claim_id == original.claim_refs[0].claim_id)

    # A local review template pins the actual correction-plan revision so the
    # candidate's MethodBridge expands the identical target/check/standard.
    from ordessa_engineering.domain.reviews.models import CriterionSetRef
    from ordessa_engineering.domain.reviews.requirements import (
        ExactArtifactRevisionSelector, ReviewRequirementTemplate, TemplateCheck, TemplateTarget,
    )
    correction_ref = e["correction_ref"]
    standard = next(item for item in e["snapshot"].program.standard_definitions
                    if item.standard_id == "rework-scope")
    target = TemplateTarget("primary", ExactArtifactRevisionSelector(correction_ref))
    template = ReviewRequirementTemplate(
        e["input_revision"].scope, "phase1-rework-template", 1, "quality", (target,),
        method_ref, CriterionSetRef(standard.standard_id, 1,
            Digest("sha256", standard.resource_ref.sha256)),
        (TemplateCheck(target, "correction_within_approved_scope"),),
        ("independent_review_unit",), "rework_review")
    draft = _draft(method_ref, mutation.base_ref, mutation.proposed_ref, claim, template=False)
    draft["review_requirement_templates"] = [asdict(template)]
    created = proposal_usecases(e["factory"], e["access"]).create(
        {"change_id": None, "expected_version": 0, "draft": draft},
        _ctx(request_id="phase1-candidate-rework-proposal"))
    assert created.status == "completed", created.result
    return _proposal_ref(created.result["proposal_ref"])


def _append_correction_plan(e, method_ref):
    from ordessa_engineering.domain.reviews.refs import ReviewRef, SubmissionRef

    source_ref = e["input_revision"].ref
    digest = Digest("sha256", "c" * 64)
    scope = e["input_revision"].scope
    value = {
        "document_type": "correction-plan", "schema_version": 1,
        "approved_did_ref": asdict(source_ref), "approved_package_ref": asdict(source_ref),
        "failed_submission_ref": asdict(SubmissionRef(scope.realm_id, scope.project_id,
            "fixture-failed-submission", digest)),
        "failed_review_ref": asdict(ReviewRef(scope.realm_id, scope.project_id,
            "fixture-failed-review", digest)),
        "proposed_corrections": [{
            "failed_check_key": {"target": {"role": "primary", "ref": asdict(source_ref)},
                "criterion_id": "fixture-failed-criterion", "claim_id": None},
            "target_ref": asdict(source_ref), "change": "bounded fixture correction",
            "validation_steps": ["compare the exact stored revision"],
            "scope_basis_refs": [asdict(source_ref)],
        }],
    }
    spec = document_spec(e["snapshot"], "correction-plan")
    resource = next(item for item in e["snapshot"].resources
                    if item.resource_id == spec.schema_ref.resource_id)
    exact = ExactMethodResourceRef(method_ref, resource.logical_path,
        Digest("sha256", resource.digest), resource.resource_id)
    schema = thaw_value(spec.value_schema)
    schema_id = urljoin("https://ordessa.invalid/method/" + exact.logical_path,
                        schema.get("$id", ""))
    payload = MethodPayload("application/json", schema_id, MethodContent.from_value(exact, value))
    revision = ArtifactRevision(scope, "phase1-correction-plan", "correction-plan-r1",
        e["input_revision"].created_at, e["input_revision"].created_by, payload,
        schema_version=2, method_refs=(method_ref,))
    with e["factory"].begin(scope) as uow:
        uow.engineering.create(Artifact(scope, revision.artifact_id, "plan", revision.created_at))
        verify_material(revision, uow.engineering.validated_budget())
        uow.engineering.append_revision(revision, expected_version=0)
        uow.commit()
    e["correction_ref"] = revision.ref
    return revision


class _ControlledWorkAdmission:
    """Controlled admission delegates persisted checks to the real binding."""

    def __init__(self, bindings):
        self.bindings = bindings

    @contextmanager
    def guard_plan(self, context, plan, *, work_selector=None):
        with self.bindings.guard_plan_bindings(context, plan,
                work_selector=work_selector):
            yield object()

    def check_work_review_current(self, uow, context, plan, selector):
        return self.bindings.check_work_review_current(uow, context, plan, selector)

    def work_review_result(self, context, plan, selector, entry, *, request, work_facts):
        return self.bindings.work_review_result(context, plan, selector, entry,
            request=request, work_facts=work_facts)


class _UnitAuthorityMustNotRun:
    """Constructor-shaped observer; round mismatch must precede Unit access."""

    def __init__(self, factory, methods, bindings):
        self.factory, self.methods, self.bindings = factory, methods, bindings
        self.calls = []

    @contextmanager
    def guard_plan(self, context, plan):
        self.calls.append("guard_plan")
        yield object()

    def verify_response(self, *args):
        self.calls.append("verify_response")
        raise AssertionError("Unit response authority ran before source correlation")

    @contextmanager
    def guard_trust(self, context, records):
        self.calls.append("guard_trust")
        yield ()


def test_request_and_readiness_are_bound_to_the_persisted_candidate_round(persisted_source):
    e = persisted_source
    scope = e["input_revision"].scope
    method_ref, snapshot = _freeze_candidate(e)
    e["snapshot"] = snapshot

    correction = _append_correction_plan(e, method_ref)
    proposal_ref = _candidate_proposal(e, method_ref)

    initial_input = {
        "document_type": "work-inputs", "schema_version": 2,
        "run_id": "phase1-round-guard-run", "proposal_ref": asdict(proposal_ref),
        "events": {}, "events_by_round": {"1": {"await_rework_review_response": {}}},
    }
    input_revision = _append_v2_input(e, snapshot, method_ref, initial_input,
                                      "phase1-round-guard-input-r1")
    slots = {
        "method_ref": asdict(method_ref), "proposal_ref": asdict(proposal_ref),
        "work_inputs": asdict(input_revision.ref),
        "correction_plan_ref": asdict(correction.ref),
    }
    node_index = next(index for index, node in enumerate(snapshot.program.workflow.steps)
                      if node.id == "rework_review")
    context = _context(scope, "phase1-round-guard-request")
    marker = {
        "work_contract": WORK_CONTRACT, "scope": asdict(scope),
        "method_ref": asdict(method_ref),
        "compiled_plan_digest": program_plan_digest(snapshot.program),
    }
    run_id = "phase1-round-guard-run"
    with e["factory"].begin(scope) as uow:
        material_ref = uow.workflow.write_material(kind="method", stable_id=run_id,
            revision=1, body=marker, generated=False)
        uow.workflow.insert_run(run_id=run_id, method_ref=material_ref,
            registry_ref={"fixture": "candidate-2.6.0"},
            inputs={**marker, "slots": slots, "rounds": {"implementation-rework": 1}},
            now=context.received_at)
        uow.workflow.update_run(run_id=run_id, status="RUNNING", cursor=node_index,
            wait_reason=None, now=context.received_at)
        uow.commit()

    methods = e["controls"]
    bindings = SQLiteWorkReviewBindings(e["factory"], methods, scope=scope,
        blobs=SQLiteBlobStore(e["library"]))
    selection_context = _context(scope, "phase1-round-guard-selection")
    selector, plan = bindings.review_selection(selection_context, run_id=run_id,
        review_id="phase1-round-guard-review", subject_ref=correction.ref)
    assert selector.method_ref == method_ref
    assert selector.phase_key == "rework_review"
    assert plan.requirement.method_ref == method_ref
    assert plan.requirement.phase_key == "rework_review"
    assert plan.requirement.expected_targets.targets[0].ref == correction.ref
    assert plan.requirement.criterion_set_ref.criterion_set_id == "rework-scope"

    service = ReviewUseCases(e["factory"], e["access"], _ControlledWorkAdmission(bindings))
    requested = service.request({"plan": asdict(plan)}, context, work_selector=selector)
    assert requested.status == "completed", requested.result
    with e["factory"].begin(scope, "read") as uow:
        saved_plan = uow.reviews.get_plan(plan.review_id)
        request = uow.reviews.get_request(plan.review_id)
        row = uow.workflow.run_row(run_id)
    assert saved_plan == plan
    assert isinstance(request, ReviewRequestState) and request.state == "requested"
    assert row["inputs"]["rounds"]["implementation-rework"] == 1
    historical_selector, historical_row = bindings._historical_row(context, plan)
    assert historical_selector == selector
    assert historical_row["inputs"]["rounds"]["implementation-rework"] == 1

    # A genuine append-only child in the same loop round remains current.
    append_value = {
        **initial_input,
        "events_by_round": {"1": {"await_rework_review_response": {
            "review_id": plan.review_id}}},
    }
    appended = _append_v2_input(e, snapshot, method_ref, append_value,
        "phase1-round-guard-input-r1-child", parents=(input_revision.ref,))
    with e["factory"].begin(scope) as uow:
        current = uow.workflow.run_row(run_id)
        updated_inputs = {**current["inputs"], "slots": {
            **current["inputs"]["slots"], "work_inputs": asdict(appended.ref)}}
        uow.workflow.replace_run_inputs(run_id=run_id,
            expected_inputs=current["inputs"], inputs=updated_inputs)
        uow.commit()
    bindings.guard_current_request(context, plan, request)

    # The same request remains requested, but moving the persisted Work loop
    # to round two invalidates both the send guard and response readiness.
    raw = b'{"fixture":"round-two-response"}'
    raw_digest = Digest("sha256", hashlib.sha256(raw).hexdigest())
    raw_ref = SQLiteBlobStore(e["library"]).put_verified(raw, raw_digest, "application/json")
    round_two_input = {
        **append_value,
        "events_by_round": {
            "1": {"await_rework_review_response": {"review_id": plan.review_id}},
            "2": {"await_rework_review_response": {
                "review_id": plan.review_id, "request_version": request.version,
                "fence": request.fence, "raw_response_ref": asdict(raw_ref),
            }},
        },
    }
    changed_input = _append_v2_input(e, snapshot, method_ref, round_two_input,
        "phase1-round-guard-input-r2", parents=(appended.ref,))
    response_index = next(index for index, node in enumerate(snapshot.program.workflow.steps)
                          if node.id == "await_rework_review_response")
    with e["factory"].begin(scope) as uow:
        current = uow.workflow.run_row(run_id)
        updated_inputs = {**current["inputs"],
            "rounds": {**current["inputs"]["rounds"], "implementation-rework": 2},
            "slots": {**current["inputs"]["slots"], "work_inputs": asdict(changed_input.ref)}}
        uow.workflow.replace_run_inputs(run_id=run_id,
            expected_inputs=current["inputs"], inputs=updated_inputs)
        uow.workflow.update_run(run_id=run_id, status="RUNNING", cursor=response_index,
            wait_reason="await_rework_review_response", now=context.received_at)
        uow.commit()

    with e["factory"].begin(scope, "read") as uow:
        current = uow.workflow.run_row(run_id)
        still_requested = uow.reviews.get_request(plan.review_id)
    assert still_requested == request and still_requested.state == "requested"
    with pytest.raises(ApplicationError, match="WORK_REVIEW_STALE"):
        bindings.guard_current_request(context, plan, still_requested)

    current_row = {**current, "run_id": run_id}
    view = {"run_id": run_id, "row": current_row,
            "row_digest": run_wait_row_digest(current)}
    unit_authority = _UnitAuthorityMustNotRun(e["factory"], methods, bindings)
    readiness = SQLiteWorkReviewReadiness(e["factory"], methods,
        bindings=bindings, admission=unit_authority)
    readiness_context = _context(scope, "phase1-round-guard-readiness")
    with methods.guard_method(readiness_context, method_ref) as current_snapshot:
        with pytest.raises(ApplicationError, match="WORK_REVIEW_CORRELATION_MISMATCH"):
            with readiness.guard_response_ready(readiness_context, current_snapshot,
                    plan, still_requested, raw_ref, phase_key="rework_review",
                    input_ref=changed_input.ref, subject_ref=correction.ref, view=view):
                pass
    assert unit_authority.calls == []
    assert isinstance(raw_ref, BlobRef)
