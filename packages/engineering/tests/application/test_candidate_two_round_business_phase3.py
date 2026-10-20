"""Actual 2.6 candidate materials and Work entry on original SQLite owners.

The checkpoints qualify candidate freeze/adoption, exact Proposal review
requirements over DID-change/summary material, and the public Work start.
WorkInput-driven review progression, dispatch, delivery rounds, and acceptance
are not qualified here.
The fixture method catalogue and external Work input author are controlled test
peers; Engineering storage and Work guards are the original implementations.
"""
import asyncio
import hashlib
import json
from dataclasses import asdict

import pytest

from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
from ordessa_engineering.application.assembly import build_method_run_bindings
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import (
    SQLiteWorkReviewBindings, SQLiteWorkReviewReadiness,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_content import document_spec
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.domain.artifacts.codec import encode_revision
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, MethodContent, MethodPayload
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.codec import encode_plan
from ordessa_engineering.methods.definitions.models import thaw_value
from ordessa_infrastructure.encoding import canonical_bytes

from urllib.parse import urljoin

from test_persisted_method_work import persisted_source
from test_review_usecases import _context
from test_work_reader_phase1 import _append_v2_input
from test_work_request_round_guard_phase1 import (
    _append_correction_plan,
    _candidate_proposal,
    _freeze_candidate,
)


def _append_candidate_document(e, snapshot, method_ref, document_type, artifact_id,
                               revision_id, value, *, claims=()):
    from jsonschema import Draft202012Validator

    definition = document_spec(snapshot, document_type)
    schema = thaw_value(definition.value_schema)
    schema_errors = tuple(Draft202012Validator(schema).iter_errors(value))
    assert not schema_errors, "method document schema errors: " + "; ".join(
        f"path=/{'/'.join(str(part) for part in error.absolute_path)} "
        f"validator={error.validator} message={error.message}"
        for error in schema_errors)
    resource = next(item for item in snapshot.resources
                    if item.resource_id == definition.schema_ref.resource_id)
    exact = ExactMethodResourceRef(method_ref, resource.logical_path,
        Digest("sha256", resource.digest), resource.resource_id)
    schema_id = urljoin("https://ordessa.invalid/method/" + exact.logical_path,
                        schema.get("$id", ""))
    payload = MethodPayload("application/json", schema_id,
        MethodContent.from_value(exact, value))
    source = e["input_revision"]
    revision = ArtifactRevision(source.scope, artifact_id, revision_id,
        source.created_at, source.created_by, payload, schema_version=2,
        claims=claims, method_refs=(method_ref,))
    with e["factory"].begin(revision.scope) as uow:
        uow.engineering.create(Artifact(revision.scope, artifact_id, "plan", revision.created_at))
        verify_material(revision, uow.engineering.validated_budget())
        uow.engineering.append_revision(revision, expected_version=0)
        uow.commit()
    return revision


def _create_historical_summary_and_did(e, snapshot, method_ref):
    old = e["proposal_ref"]
    old_reference = {
        "object_id": old.proposal_id,
        "revision": old.digest.hex,
        "digest": old.digest.hex,
        "locator": (f"original-proposal://{old.realm_id}/{old.project_id}/"
                    f"{old.change_id}/{old.proposal_id}"),
    }
    did = _append_candidate_document(e, snapshot, method_ref, "did",
        "phase3-next-did", "phase3-next-did-r1", {
            "document_type": "did", "schema_version": 1,
            "title": "Controlled candidate business-chain fixture",
            "intent": "Exercise original candidate Work source with exact material.",
            "claims": [{"claim_id": "fixture-scope", "kind": "design_choice",
                "statement": "This fixture checks exact method-bound material only.",
                "source_ids": [], "counter_source_ids": []}],
            "goals": ["Persist schema-valid candidate documents."],
            "non_goals": ["Claim a human-approved DID or production execution."],
            "change_plan": [{"path": "fixture.txt", "change": "Record a controlled sample.",
                "reason_claim_ids": ["fixture-scope"]}],
            "risks": [], "rollback": "Remove the controlled fixture artifacts.",
            "acceptance": [{"acceptance_id": "schema-roundtrip",
                "description": "Exact candidate schemas validate and bytes read back.",
                "test_ids": ["test_candidate_two_round_business_phase3"]}],
            "open_questions": [],
        })
    summary = _append_candidate_document(e, snapshot, method_ref, "session-summary",
        "phase3-next-summary", "phase3-next-summary-r1", {
            "document_type": "session-summary", "schema_version": 2,
            "proposal_ref": old_reference,
            "changes": ["Created exact candidate DID fixture material."],
            "retained_constraints": ["Summary source is the identified historical Proposal."],
            "deleted_promises": [], "tradeoffs": [], "risks": [],
            "open_questions": [], "next_action": "Continue through the original Work wait.",
            "feedback_route": "Controlled test fixture only.",
        })
    return did, summary


def _create_candidate_did_change(e, snapshot, method_ref, summary):
    """Create the document type required by the candidate content-review phase."""
    old = e["proposal_ref"]
    historical = {
        "object_id": old.proposal_id,
        "revision": old.digest.hex,
        "digest": old.digest.hex,
        "locator": (f"original-proposal://{old.realm_id}/{old.project_id}/"
                    f"{old.change_id}/{old.proposal_id}"),
    }
    summary_ref = {
        "object_id": summary.artifact_id,
        "revision": summary.revision_id,
        "digest": summary.digest.hex,
        "locator": (f"artifact-revision://{summary.scope.realm_id}/"
                    f"{summary.scope.project_id}/{summary.artifact_id}/{summary.revision_id}"),
    }
    from ordessa_engineering.domain.artifacts.provenance import Claim
    from ordessa_engineering.domain.common.models.selection import ContentSelector
    claim_text = "The candidate schema accepts a DID-change with an exact summary reference."
    claim = Claim("phase3-material-claim", ContentSelector("json_pointer", pointer="/claims/0/statement"),
        Digest("sha256", hashlib.sha256(canonical_bytes(claim_text)).hexdigest()))
    return _append_candidate_document(e, snapshot, method_ref, "did-change",
        "phase3-next-did-change", "phase3-next-did-change-r1", {
            "document_type": "did-change", "schema_version": 2,
            "baseline_ref": historical,
            "target_snapshot_ref": historical,
            "decision_context_ref": historical,
            "standard_profile_ref": historical,
            "changes": [{
                "change_id": "phase3-material-check",
                "operation": "add",
                "target_locator": "fixture/phase3-material-check",
                "before": "No candidate document.",
                "after": "Schema-valid candidate DID-change material.",
                "basis_refs": [historical],
                "semantic_support": "Controlled schema fixture; not a human decision.",
                "authority_kind": "hypothesis",
                "impact": ["Material validation only."],
                "disposition": "proposed",
            }],
            "ecp": {
                "reason": "Exercise the frozen candidate document schema.",
                "scope": "Controlled fixture only.",
                "affected_owners": ["test fixture"],
                "consumer_and_assembly_impacts": [],
                "data_and_migration_impacts": [],
                "tradeoffs": [],
                "risks": ["This is not an approved engineering change."],
            },
            "claims": [{
                "claim_id": "phase3-material-claim",
                "statement": claim_text,
                "source_ids": [], "counter_source_ids": [], "kind": "design_choice",
            }],
            "summary_ref": summary_ref,
            "open_questions": [],
        }, claims=(claim,))


def _candidate_proposal_with_exact_material(e, snapshot, method_ref, did_change, summary):
    """Build frozen templates from the four declared candidate review phases."""
    from dataclasses import asdict
    from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
    from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
    from ordessa_engineering.application.usecases.changes.proposals import ProposalUseCases
    from ordessa_engineering.domain.artifacts.provenance import ClaimRef
    from ordessa_engineering.domain.changes.models import Mutation
    from ordessa_engineering.domain.common.models.identity import Scope
    from ordessa_engineering.domain.reviews.models import CriterionSetRef
    from ordessa_engineering.domain.reviews.requirements import (
        ExactArtifactRevisionSelector, ReviewRequirementTemplate, SubjectSelector,
        TemplateCheck, TemplateTarget,
    )
    from ordessa_engineering.domain.reviews.targets import Target, TargetSet
    from ordessa_engineering.methods.definitions.models.compiled import thaw_value

    did_target = TemplateTarget("proposed", SubjectSelector("proposed_mutation", 0))
    summary_target = TemplateTarget("support", ExactArtifactRevisionSelector(summary.ref))
    selected_targets = ((did_target, "did-change", did_change),
                        (summary_target, "session-summary", summary))
    templates = []
    phase_bindings = []
    nodes = {node.id: node for node in snapshot.program.workflow.steps}
    for phase_key in ("source_review", "quality_review", "quality_content_review", "summary_review"):
        config = thaw_value(nodes[phase_key].config)
        standard_ids = {
            ref["resource_id"] for ref in config["standards"]
        }
        standards = tuple(standard for standard in snapshot.program.standard_definitions
            if standard.resource_ref.resource_id in standard_ids)
        assert len(standards) == len(standard_ids)
        purpose = config["purpose"]
        relevant = tuple((target, doc_type, revision) for target, doc_type, revision in selected_targets
            if any(not criterion.applies_to or doc_type in criterion.applies_to
                   for standard in standards for criterion in standard.criteria))
        bridge_targets = tuple(Target(target.role, revision.ref) for target, _, revision in relevant)
        target_types = tuple((Target(target.role, revision.ref), doc_type)
                             for target, doc_type, revision in relevant)
        required_inputs = tuple(sorted({name for standard in standards for criterion in standard.criteria
            for name in (criterion.required_inputs or ())}))
        bindings = EngineeringTargetBindings(
            did_change.scope, TargetSet(bridge_targets), target_types, required_inputs,
            ("independent_review_unit",), phase_key, workflow_node_id=phase_key,
            review_purpose=purpose)
        phase_bindings.append(bindings)
        for standard in standards:
            applicable = tuple((target, doc_type, revision) for target, doc_type, revision in relevant
                if any(not criterion.applies_to or doc_type in criterion.applies_to
                       for criterion in standard.criteria))
            expected = tuple(target for target, _, _ in applicable)
            checks = []
            for target, doc_type, revision in applicable:
                for criterion in standard.criteria:
                    if criterion.applies_to and doc_type not in criterion.applies_to:
                        continue
                    if criterion.required is False:
                        continue
                    iteration = any(thaw_value(check.bindings).get("iteration") == "each_evidence_required_claim"
                                    for check in criterion.checks)
                    claim_ids = tuple(claim.claim_id for claim in revision.claims) if iteration else (None,)
                    checks.extend(TemplateCheck(target, criterion.criterion_id, claim_id)
                                  for claim_id in claim_ids)
            templates.append(ReviewRequirementTemplate(
                did_change.scope, f"phase3-{phase_key}-{standard.standard_id}", 1,
                standard.purpose, expected, method_ref,
                CriterionSetRef(standard.standard_id, 1,
                    Digest("sha256", standard.resource_ref.sha256)),
                tuple(checks), ("independent_review_unit",), phase_key))

    from ordessa_engineering.domain.artifacts.provenance import ClaimRef
    from ordessa_engineering.domain.changes.refs import ProposalRef
    draft = {
        "intent": "Exercise exact candidate DID-change and summary review binding.",
        "rationale": "Controlled candidate material tests original requirement expansion.",
        "mutations": [asdict(Mutation(did_change.artifact_id, "create", None, did_change.ref))],
        "basis_sources": [],
        "claim_refs": [asdict(ClaimRef(did_change.ref, claim.claim_id, claim.statement_digest))
                       for claim in did_change.claims],
        "evidence_links": [], "method_ref": asdict(method_ref),
        "review_requirement_templates": [asdict(template) for template in templates],
        "implementation_intent": None, "supersedes_refs": [],
    }
    created = ProposalUseCases(e["factory"], e["access"]).create(
        {"change_id": None, "expected_version": 0, "draft": draft},
        _context(did_change.scope, "phase3-next-exact-material-proposal"))
    assert created.status == "completed", created.result
    from test_proposal_usecases import _proposal_ref
    proposal_ref = _proposal_ref(created.result["proposal_ref"])
    with e["factory"].begin(did_change.scope, "read") as uow:
        proposal = uow.proposals.get_proposal(proposal_ref)
        artifacts = (uow.engineering.get_artifact(did_change.artifact_id),)
        revisions = (uow.engineering.resolve_revision(did_change.ref),
                     uow.engineering.resolve_revision(summary.ref))
    admitted = MethodBridge().proposal_review_requirements(snapshot, tuple(phase_bindings),
        proposal=proposal, artifacts=artifacts, revisions=revisions)
    plans = tuple(MethodBridge().review_plan(snapshot, binding, requirement,
        f"phase3-{requirement.phase_key}-plan", proposal=proposal, artifacts=artifacts,
        revisions=revisions, phase_bindings=tuple(phase_bindings))
        for binding in phase_bindings for requirement in admitted
        if requirement.phase_key == binding.phase_key)
    return proposal, proposal_ref, tuple(phase_bindings), admitted, plans


def _candidate_entry_material(e, snapshot, method_ref, proposal_ref, summary, source_plan):
    from ordessa_engineering.domain.changes.repository_baseline import seal_repository_baseline

    scope = e["input_revision"].scope
    old = e["proposal_ref"]
    historical = {
        "object_id": old.proposal_id, "revision": old.digest.hex, "digest": old.digest.hex,
        "locator": (f"original-proposal://{old.realm_id}/{old.project_id}/"
                    f"{old.change_id}/{old.proposal_id}"),
    }
    decision = _append_candidate_document(e, snapshot, method_ref, "decision-context",
        "phase3-next-decisions", "phase3-next-decisions-r1", {
            "document_type": "decision-context", "schema_version": 2,
            "session_ref": historical,
            "records": [{
                "decision_id": "controlled-fixture-question",
                "kind": "open_question", "validity": "needs_clarification",
                "context": "Material fixture input; not an approval record.",
                "statement": "Does this controlled sample match the expected method shape?",
                "scope": "This test fixture only.", "source": historical,
                "quote": "No human decision is asserted.",
                "locator_limitations": "Historical Proposal reference is context only.",
                "supersedes": [], "unresolved_neighbors": [],
            }],
            "source_refs": [], "open_questions": ["This is not a trusted human decision."],
        })
    profile = _append_candidate_document(e, snapshot, method_ref, "standard-profile",
        "phase3-next-profile", "phase3-next-profile-r1", {
            "document_type": "standard-profile", "schema_version": 2,
            "status": "candidate", "acceptance_ref": historical,
            "standards": [{
                "standard_id": standard.standard_id, "revision": str(standard.revision),
                "source_ref": historical,
                "applicable_clauses": [criterion.criterion_id for criterion in standard.criteria],
                "tailoring": [],
            } for standard in snapshot.program.standard_definitions],
            "review_scope": ["Controlled method-content material only."],
        })
    baseline = seal_repository_baseline(scope, "phase3-next-repository", "none", None, ())
    with e["factory"].begin(scope) as uow:
        uow.implementation.create_repository_baseline(baseline)
        uow.commit()
    run_id = "phase3-next-source-review-run"
    events = {
        "proposal_ref": asdict(proposal_ref),
        "summary_ref": asdict(summary.ref),
        "baseline_ref": asdict(baseline.ref),
        "source_review_plan": json.loads(encode_plan(source_plan)),
        "method_ref": asdict(method_ref),
        "decisions_ref": asdict(decision.ref),
        "standard_profile_ref": asdict(profile.ref),
    }
    work_inputs_value = {
        "document_type": "work-inputs", "schema_version": 2,
        "run_id": run_id, "proposal_ref": asdict(proposal_ref),
        "events": {"await_proposal": events}, "events_by_round": {},
    }
    # Diagnose the exact frozen WorkInputs schema before the original material
    # closure repeats this validation during append. This preserves that guard
    # while making an authoring-shape mismatch actionable.
    from jsonschema import Draft202012Validator
    work_inputs_schema = thaw_value(document_spec(snapshot, "work-inputs").value_schema)
    work_inputs_errors = tuple(
        Draft202012Validator(work_inputs_schema).iter_errors(work_inputs_value))
    assert not work_inputs_errors, "WorkInputs schema errors: " + "; ".join(
        f"path=/{'/'.join(str(part) for part in error.absolute_path)} "
        f"validator={error.validator} message={error.message}"
        for error in work_inputs_errors)
    input_revision = _append_v2_input(e, snapshot, method_ref, work_inputs_value,
        "phase3-next-source-review-input-r1")
    return run_id, input_revision, baseline, decision, profile


def test_candidate_26_public_work_start_enters_actual_await_proposal(persisted_source):
    e = persisted_source
    method_ref, snapshot = _freeze_candidate(e)
    e["snapshot"] = snapshot

    # Reuse the original Proposal creation path and give it the candidate's
    # exact rework requirement. No MethodRun row or cursor is pre-inserted.
    _append_correction_plan(e, method_ref)
    proposal_ref = _candidate_proposal(e, method_ref)
    run_id = "phase3-next-candidate-entry"
    initial_input = {
        "document_type": "work-inputs",
        "schema_version": 2,
        "run_id": run_id,
        "proposal_ref": asdict(proposal_ref),
        "events": {},
        "events_by_round": {},
    }
    input_revision = _append_v2_input(
        e, snapshot, method_ref, initial_input, "phase3-next-entry-input-r1")

    source = SQLitePersistedMethodWorkSource(e["factory"], e["controls"],
        blobs=SQLiteBlobStore(e["library"]))
    registry = {
        "registry_id": "phase3-next-controlled-current-owner-descriptors",
        "revision": 1,
        "registry_digest": "sha256:" + "c" * 64,
    }
    bindings = build_method_run_bindings(
        e["factory"], method_control=e["controls"],
        work_condition_source=source, registry_loader=lambda: registry)
    service = EngineeringService(e["factory"], e["access"],
        current_wait_bindings=bindings)
    context = _context(e["input_revision"].scope, "phase3-next-start")
    started = asyncio.run(service.execute("engineering.work.start", {
        "run_id": run_id,
        "selection": {
            "proposal_ref": asdict(proposal_ref),
            "initial_slot_refs": {"work_inputs": asdict(input_revision.ref)},
        },
    }, context))

    assert started.status == "completed", started.result
    assert started.result["status"] == "WAITING_FOR_CONDITION"
    assert started.result["dispatched"] is False
    entry_index = next(index for index, node in enumerate(snapshot.program.workflow.steps)
                       if node.id == "await_proposal")
    assert started.result["cursor"] == entry_index
    with e["factory"].begin(context.scope, "read") as uow:
        row = uow.workflow.run_row(run_id)
    assert row["status"] == "WAITING_FOR_CONDITION"
    assert row["cursor"] == entry_index
    assert row["wait_reason"] == "await_proposal"
    assert row["inputs"]["slots"]["proposal_ref"] == asdict(proposal_ref)
    assert row["inputs"]["slots"]["work_inputs"] == asdict(input_revision.ref)

    # The start itself creates no readiness fact. The exact source-review
    # event (including its method-bound plan and source refs) must be appended
    # before the original current-condition owner can advance this wait.
    with pytest.raises(ApplicationError, match="WORK_INPUT_DOCUMENT_INVALID"):
        asyncio.run(service.query("engineering.work.current_condition",
            {"run_id": run_id}, _context(context.scope, "phase3-next-empty-entry-wait")))


def test_candidate_26_did_and_historical_summary_are_exact_schema_material(persisted_source):
    e = persisted_source
    method_ref, snapshot = _freeze_candidate(e)
    did, summary = _create_historical_summary_and_did(e, snapshot, method_ref)
    did_change = _create_candidate_did_change(e, snapshot, method_ref, summary)

    with e["factory"].begin(e["input_revision"].scope, "read") as uow:
        did_read = uow.engineering.resolve_revision(did.ref)
        summary_read = uow.engineering.resolve_revision(summary.ref)
        did_change_read = uow.engineering.resolve_revision(did_change.ref)
    assert did_read.ref == did.ref
    assert summary_read.ref == summary.ref
    assert encode_revision(did_read) == encode_revision(did)
    assert encode_revision(summary_read) == encode_revision(summary)
    assert did_change_read.ref == did_change.ref
    assert encode_revision(did_change_read) == encode_revision(did_change)
    assert did_change_read.payload.content.value["summary_ref"]["digest"] == summary.digest.hex
    assert did_read.payload.content.value["claims"][0]["kind"] == "design_choice"
    old = e["proposal_ref"]
    stored_summary_ref = summary_read.payload.content.value["proposal_ref"]
    assert stored_summary_ref["object_id"] == old.proposal_id
    assert stored_summary_ref["digest"] == old.digest.hex
    assert stored_summary_ref["locator"] == (
        f"original-proposal://{old.realm_id}/{old.project_id}/"
        f"{old.change_id}/{old.proposal_id}")
    proposal, proposal_ref, phases, requirements, plans = _candidate_proposal_with_exact_material(
        e, snapshot, method_ref, did_change, summary)
    assert proposal.ref == proposal_ref
    assert {phase.phase_key for phase in phases} == {
        "source_review", "quality_review", "quality_content_review", "summary_review"}
    assert {requirement.phase_key for requirement in requirements} == {
        "source_review", "quality_review", "quality_content_review", "summary_review"}
    assert len(plans) == len(requirements)
    assert any(
        type(target.selector).__name__ == "ExactArtifactRevisionSelector"
        and target.selector.artifact_revision_ref == summary.ref
        for template in proposal.review_requirement_templates
        for target in template.expected_targets)


def test_candidate_26_public_wait_reaches_original_source_review_request(persisted_source):
    """Advance the original start/source wait and record its actual request.

    The author-provided decision/profile documents and repository baseline are
    controlled local inputs. Candidate freeze, Proposal closure, ReviewPlan
    readiness, Work cursor, Review request, and journal consumption use the
    original Engineering owners.
    """
    e = persisted_source
    method_ref, snapshot = _freeze_candidate(e)
    did, summary = _create_historical_summary_and_did(e, snapshot, method_ref)
    did_change = _create_candidate_did_change(e, snapshot, method_ref, summary)
    proposal, proposal_ref, phases, requirements, plans = _candidate_proposal_with_exact_material(
        e, snapshot, method_ref, did_change, summary)
    source_plan = next(plan for plan in plans if plan.requirement.phase_key == "source_review")
    run_id, input_revision, baseline, decision, profile = _candidate_entry_material(
        e, snapshot, method_ref, proposal_ref, summary, source_plan)

    blobs = SQLiteBlobStore(e["library"])
    review_bindings = SQLiteWorkReviewBindings(e["factory"], e["controls"],
        scope=e["input_revision"].scope, blobs=blobs)
    review_readiness = SQLiteWorkReviewReadiness(e["factory"], e["controls"],
        bindings=review_bindings)
    source = SQLitePersistedMethodWorkSource(e["factory"], e["controls"],
        phase_bindings=tuple(phases),
        blobs=blobs, review_bindings=review_bindings, review_readiness=review_readiness)
    registry = {
        "registry_id": "phase3-next-controlled-current-owner-descriptors",
        "revision": 1,
        "registry_digest": "sha256:" + "c" * 64,
    }
    bindings = build_method_run_bindings(e["factory"], method_control=e["controls"],
        work_condition_source=source, registry_loader=lambda: registry)
    from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
    review_admission = EngineeringReviewAdmission(e["factory"], e["controls"], review_bindings)
    service = EngineeringService(e["factory"], e["access"], review_admission=review_admission,
        current_wait_bindings=bindings)
    scope = e["input_revision"].scope
    start_context = _context(scope, "phase3-next-start-source-review")
    started = asyncio.run(service.execute("engineering.work.start", {
        "run_id": run_id,
        "selection": {
            "proposal_ref": asdict(proposal_ref),
            "initial_slot_refs": {
                "work_inputs": asdict(input_revision.ref),
                "summary_ref": asdict(summary.ref),
                "baseline_ref": asdict(baseline.ref),
                "decisions_ref": asdict(decision.ref),
                "standard_profile_ref": asdict(profile.ref),
            },
        },
    }, start_context))
    assert started.status == "completed", started.result
    assert started.result["status"] == "WAITING_FOR_CONDITION"
    condition = asyncio.run(service.query("engineering.work.current_condition",
        {"run_id": run_id}, _context(scope, "phase3-next-read-proposal-condition")))
    assert condition["ready"] is True
    resumed = asyncio.run(service.execute("engineering.runs.resume", {
        "run_id": run_id,
        "expected_row_digest": condition["row_digest"],
        "expected_condition_digest": condition["condition_digest"],
        "expected_next_step_ordinal": condition["next_step_ordinal"],
    }, _context(scope, "phase3-next-resume-source-review")))
    assert resumed.status == "completed", resumed.result
    assert resumed.result["status"] == "RUNNING"
    source_index = next(index for index, node in enumerate(snapshot.program.workflow.steps)
                        if node.id == "source_review")
    assert resumed.result["cursor"] == source_index

    # Preserve the review ID embedded in the native MethodBridge plan so the
    # source-selected plan equals the exact plan used for readiness.
    review_id = source_plan.review_id
    selector, selected_plan = review_bindings.review_selection(
        _context(scope, "phase3-next-source-review-selection"), run_id=run_id,
        review_id=review_id, subject_ref=proposal_ref)
    assert selected_plan == source_plan
    request_context = _context(scope, review_id)
    row = e["library"].run_row(run_id)
    request_node = snapshot.program.workflow.steps[source_index]
    with source.guard_step_completion(request_context, snapshot, request_node,
            {"run_id": run_id, "row": row}) as request_reads:
        requested = asyncio.run(service.execute("engineering.reviews.request",
            {"plan": asdict(selected_plan)}, request_context,
            read_set=request_reads, work_selector=selector))
    assert requested.status == "completed", requested.result
    with e["factory"].begin(scope, "read") as uow:
        stored_request = uow.reviews.get_request(review_id)
        stored_plan = uow.reviews.get_plan(review_id)
    assert stored_plan == selected_plan
    assert stored_request.state == "requested"

    work_view = asyncio.run(service.query("engineering.work.get", {"run_id": run_id},
        _context(scope, "phase3-next-read-source-review-step")))
    recorded = asyncio.run(service.execute("engineering.work.record_command_step", {
        "run_id": run_id, "operation_request_id": review_id,
        "expected_row_digest": work_view["row_digest"],
        "expected_next_step_ordinal": work_view["next_step_ordinal"],
    }, _context(scope, "phase3-next-record-source-review-request")))
    assert recorded.status == "completed", recorded.result
    response_index = next(index for index, node in enumerate(snapshot.program.workflow.steps)
                          if node.id == "await_source_response")
    assert recorded.result["status"] == "WAITING_FOR_CONDITION"
    assert recorded.result["cursor"] == response_index
