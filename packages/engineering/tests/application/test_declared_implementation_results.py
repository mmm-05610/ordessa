"""Declared implementation result flow over the original schema-17 owners.

This fixture uses the real Work, Grant, dispatch, Submission, review plan,
ReviewRecord, assignment, and journal repositories. Native execution/review
peers are explicit controlled authorities; no Unit or model is started.
"""
import asyncio
import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.assembly import (
    EngineeringPorts, build_declared_unit_report_source, build_engineering_service,
    build_reviewer_assignment_usecases,
)
from ordessa_engineering.application.api import ASSIGN_REVIEWER
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.reviewer_admission import (
    CriterionAnswer, SourceReviewBinding, VerifiedReviewResponse,
)
from ordessa_engineering.application.usecases.reviews.admission import (
    EngineeringReviewAdmission, review_observations,
)
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch
from ordessa_engineering.application.usecases.owner_operations import EngineeringOwnerOperations
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy, CheckKey, CheckPolicy, CriterionSetRef, CurrentReviewTrust,
    ReviewPlan, ReviewRequirement,
)
from ordessa_engineering.domain.reviews.refs import SubmissionRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.methods.definitions.models.compiled import (
    CheckDefinition, CriterionDefinition, DispositionSpec, ReductionSpec,
    StandardDefinition, freeze_value,
)
from test_real_source_chain import NOW, SCOPE, context
from test_work_package_dispatch_v2 import dispatch_fixture
from test_work_package_report_v2 import (
    _install_controlled_capture, _profile, _grant_ref, _report_value,
)


_REVIEWER_REF = {
    "environmentNamespace": "test-review-environment",
    "unitId": "controlled-independent-reviewer",
    "ownerProviderRef": {"provider": "controlled-review-source"},
    "sourceRevision": "reviewer-unit-r1",
}
_VERIFIER_ID = "controlled-review-verifier"
_VERIFIER_VERSION = "test-v1"


def _reviewer_actor(assignment):
    return ActorRef(record_digest("unit-reviewer-actor", {
        "unit_ref": assignment.reviewer_unit_ref,
        "assignment": asdict(assignment.ref),
    }).hex, "agent", "ordessa-unit-records")


class _WorkAccess:
    """Test-only Work-step access that delegates ordinary command checks."""

    def __init__(self, original):
        self.original = original

    def require(self, ctx, operation):
        return self.original.require(ctx, operation)

    def check_work_capability(self, ctx, operation):
        self.require(ctx, operation)
        return True

    @contextmanager
    def guard_current_capability(self, ctx, scope, capability):
        if scope != SCOPE or ctx.scope != scope:
            raise ApplicationError("ACCESS_DENIED")
        self.require(ctx, capability)
        # This fixture's access object is the explicit controlled authority
        # selected for both Work and reviewer assignment.
        yield SimpleNamespace(principal_id=ctx.principal_id, credential_epoch=7)

    @contextmanager
    def admit_work_step(self, ctx, operation, *, request_id):
        self.require(ctx, operation)
        yield replace(ctx, request_id=request_id)

    @contextmanager
    def consume_effect_write(self, handoff, ctx, *, invocation_key, action_instances):
        with self.original.consume_effect_write(
                handoff, ctx, invocation_key=invocation_key,
                action_instances=action_instances):
            yield


class _UnitPeers:
    """Delegate controlled ACP receipts and echo explicitly selected Unit refs."""

    def __init__(self, acp):
        self.acp = acp
        self.unit_calls = []

    def acp_turn_query_digest(self, *args, **kwargs):
        return self.acp.acp_turn_query_digest(*args, **kwargs)

    def query_acp_turn(self, *args, **kwargs):
        return self.acp.query_acp_turn(*args, **kwargs)

    def resolve_unit_reference(self, ref, invocation, *, input_digest):
        self.unit_calls.append((dict(ref), invocation.facts["purpose"], input_digest))
        return SimpleNamespace(public_ref=dict(ref))


def _unit_query(_ctx, ref, plan, request, *, purpose):
    return (SimpleNamespace(facts={"purpose": purpose, "review_id": plan.review_id,
                              "request_version": request.version, "fence": request.fence}),
            "controlled-unit-query:" + ref["unitId"])


class _PlanFactory:
    """Plan comes from the released method resource and is bound to one report."""

    def __init__(self, factory, methods):
        self.factory, self.methods = factory, methods
        self.standards = {}

    def implementation_plan(self, ctx, work, *, review_id, submission, package,
                            reviewer_profile_ref, requirement_id, resources):
        del package, reviewer_profile_ref, resources
        with self.methods.guard(ctx, work.method_ref) as declaration:
            resource = next(ref for ref in declaration.resources
                            if ref.resource_id == "implementation-review-criteria")
            exact_resources = tuple(self.methods.resource_ref(
                ctx, work.method_ref, ref.resource_id) for ref in declaration.resources)
        target = Target("primary", submission.ref)
        check = CheckKey(target, "implementation-report")
        criterion = CriterionDefinition(
            criterion_id="implementation-report",
            statement="Controlled fixture review of the exact declared report.",
            checks=(CheckDefinition(capability_id="controlled.review",
                interface_version="1", bindings=freeze_value({})),),
            policy=DispositionSpec(satisfied="pass", violated="block",
                insufficient="insufficient", unknown="insufficient"),
        )
        standard = StandardDefinition(
            schema_version=1, standard_id="implementation-review-criteria", revision="1",
            criteria=(criterion,),
            reduction=ReductionSpec(required_criteria="all_applicable",
                empty_applicable_set="error", priority=("block", "manual", "pass")),
            resource_ref=resource, purpose="acceptance",
        )
        requirement = ReviewRequirement(
            scope=ctx.scope, requirement_id=requirement_id, requirement_version=1,
            purpose="acceptance", expected_targets=TargetSet((target,)),
            method_ref=work.method_ref,
            criterion_set_ref=CriterionSetRef(standard.standard_id, 1,
                Digest("sha256", resource.sha256)),
            required_check_keys=(check,), eligible_reviewer_roles=("reviewer",),
            phase_key="review", schema_version=2, method_resource_refs=exact_resources,
        )
        plan = ReviewPlan(review_id, requirement, (CheckPolicy(check, True, True),),
            AggregationPolicy(), ("reviewer",))
        self.standards[review_id] = standard
        return plan


class _DeclaredBindings:
    """Add exact declared-report binding while delegating the original DID source."""

    def __init__(self, factory, original, plan_factory):
        self.factory, self.original, self.plan_factory = factory, original, plan_factory

    def resolve_declared_submission_plan(self, ctx, plan, declaration):
        del ctx, declaration
        standard = self.plan_factory.standards.get(plan.review_id)
        if standard is None:
            raise ApplicationError("METHOD_REVIEW_PLAN_CHANGED")
        return SourceReviewBinding(plan, standard)

    def resolve_source_plan(self, *args, **kwargs):
        return self.original.resolve_source_plan(*args, **kwargs)


class _ControlledReviewSource:
    """Controlled report reviewer backed by the persisted reviewer assignment."""

    def __init__(self, factory, blobs, bindings, assignments, base_source):
        self.factory, self.blobs = factory, blobs
        self.bindings, self.assignments, self.base_source = bindings, assignments, base_source
        self.assignment_refs = {}
        self.answers = {}
        self.calls = []

    def verify_response(self, ctx, plan, request, raw_ref, *, standard):
        if not any(type(target.ref) is SubmissionRef
                   for target in plan.requirement.expected_targets.targets):
            return self.base_source.verify_response(ctx, plan, request, raw_ref, standard=standard)
        raw = self.blobs.read_verified(raw_ref)
        value = json.loads(raw.decode("utf-8"))
        expected = self.answers.get(plan.review_id)
        assignment_ref = self.assignment_refs.get(plan.review_id)
        if (expected is None or assignment_ref is None or value.get("review_id") != plan.review_id
                or value.get("request_version") != request.version or value.get("fence") != request.fence
                or value.get("plan_digest") != plan.plan_digest.hex
                or value.get("assignment_ref") != asdict(assignment_ref)
                or value.get("roles") != list(plan.reviewer_requirements)
                or value.get("answer") != expected):
            raise ApplicationError("REVIEW_SOURCE_INVALID")
        with self.factory.begin(ctx.scope, "read") as uow:
            assignment = uow.reviewer_assignments.get(assignment_ref)
            active, control = uow.reviewer_assignments.active_for_review(plan.review_id)
        if (active.ref != assignment_ref or control.state != "active"
                or assignment.review_id != plan.review_id
                or assignment.roles != plan.reviewer_requirements
                or assignment.reviewer_unit_ref != _REVIEWER_REF):
            raise ApplicationError("UNTRUSTED_REVIEWER")
        actor = _reviewer_actor(assignment)
        if (value.get("reviewer_actor") != asdict(actor)
                or value.get("trust_version") != control.version):
            raise ApplicationError("UNTRUSTED_REVIEWER")
        check = plan.requirement.required_check_keys[0]
        answer_status = {"pass": "satisfied", "fail": "violated",
                         "unknown": "unknown"}[expected]
        answers = (CriterionAnswer(check, answer_status, (),
            "Controlled reviewer source bound to the persisted assignment."),)
        observations = review_observations(plan, standard, answers)
        evidence = VerifiedReviewerEvidence(
            scope=ctx.scope, reviewer=actor, roles=assignment.roles,
            verifier_id=_VERIFIER_ID, verifier_version=_VERIFIER_VERSION,
            trust_version=control.version, request_digest=plan.request_digest,
            raw_response_digest=raw_ref.digest,
            observations_digest=__import__(
                "ordessa_engineering.domain.reviews.models",
                fromlist=["observations_digest"],
            ).observations_digest(observations),
            capability_digest=Digest("sha256", hashlib.sha256(canonical_bytes({
                "assignment_ref": asdict(assignment_ref), "roles": assignment.roles,
                "reviewer_actor": asdict(actor), "request_digest": asdict(plan.request_digest),
                "trust_version": control.version,
            })).hexdigest()),
        )
        self.calls.append((plan.review_id, request.version, request.fence, assignment_ref))
        return VerifiedReviewResponse(evidence, answers)

    @contextmanager
    def guard_trust(self, ctx, records):
        from ordessa_engineering.domain.reviews.models import CurrentReviewTrust
        declared = tuple(record for record in records
                         if self.assignment_refs.get(record.plan.review_id) is not None)
        original = tuple(record for record in records
                         if self.assignment_refs.get(record.plan.review_id) is None)
        trust = []
        with self.base_source.guard_trust(ctx, original) as original_trust:
            trust.extend(original_trust)
            with self.factory.begin(ctx.scope, "read") as uow:
                for record in declared:
                    assignment_ref = self.assignment_refs.get(record.plan.review_id)
                    assignment = uow.reviewer_assignments.get(assignment_ref)
                    active, control = uow.reviewer_assignments.active_for_review(record.plan.review_id)
                    evidence = record.reviewer_evidence
                    actor = _reviewer_actor(assignment)
                    if (active.ref != assignment_ref or control.state != "active"
                            or evidence.reviewer != actor
                            or evidence.roles != assignment.roles
                            or evidence.verifier_id != _VERIFIER_ID
                            or evidence.verifier_version != _VERIFIER_VERSION
                            or evidence.trust_version != control.version):
                        raise ApplicationError("UNTRUSTED_REVIEWER")
                    trust.append(CurrentReviewTrust(record.ref, _VERIFIER_ID, control.version))
            yield tuple(trust)


def _assembly(fixture, peers, review_answer, *, access=None, expected_scope=SCOPE):
    base_service = fixture["service"]
    env, factory = fixture["env"], fixture["factory"]
    # `_install_controlled_capture` closes over its synthetic ACP records. This
    # adapter keeps those exact receipts while adding the original UnitRecords
    # resolver used by ReviewerAssignmentUseCases.
    old_access = base_service._access
    access = _WorkAccess(old_access) if access is None else access
    query_factory = base_service._execution_query_factory
    fixture["transport"].records = peers
    fixture["transport"].query_factory = query_factory
    plan_factory = _PlanFactory(factory, env.controls)
    bindings = _DeclaredBindings(factory, env.bindings, plan_factory)
    assignments = build_reviewer_assignment_usecases(
        factory, method_control=env.controls, records=peers,
        expected_access=access, expected_scope=expected_scope,
        unit_query_factory=_unit_query,
    )
    reviewer_source = _ControlledReviewSource(factory, env.blobs, bindings,
        assignments, env.admission.source)
    admission = EngineeringReviewAdmission(factory, env.controls, bindings, reviewer_source,
        source_materials=env.materials, method_guard=env.controls,
        source_review_bindings=env.bindings)
    original_approvals = base_service._packages.approvals
    report_source = build_declared_unit_report_source(
        factory, method_control=env.controls, blobs=env.blobs)

    async def run_review(ctx, plan, request):
        # The review-request step already owns ctx.request_id. Give the
        # controlled child issuer its own stable journal identity.
        assignment_request_id = f"{ctx.request_id}:reviewer-assignment"
        with access.admit_work_step(ctx, ASSIGN_REVIEWER,
                                    request_id=assignment_request_id) as assignment_ctx:
            result = assignments.assign_reviewer(
                assignment_ctx, review_id=plan.review_id,
                expected_plan_digest=plan.plan_digest,
                request_version=request.version, fence=request.fence,
                reviewer_unit_ref=_REVIEWER_REF,
            )
        assignment_ref_data = result.result["assignment_ref"]
        from ordessa_engineering.domain.reviews.assignments import ReviewerAssignmentRef
        from ordessa_engineering.domain.common.models.identity import Scope
        assignment_ref = ReviewerAssignmentRef(
            Scope(**assignment_ref_data["scope"]), assignment_ref_data["assignment_id"],
            Digest(assignment_ref_data["digest"]["algorithm"], assignment_ref_data["digest"]["hex"]))
        reviewer_source.assignment_refs[plan.review_id] = assignment_ref
        reviewer_source.answers[plan.review_id] = review_answer
        with factory.begin(SCOPE, "read") as uow:
            assignment = uow.reviewer_assignments.get(assignment_ref)
            _, assignment_control = uow.reviewer_assignments.active_for_review(plan.review_id)
        reviewer_actor = _reviewer_actor(assignment)
        value = {"review_id": plan.review_id, "plan_digest": plan.plan_digest.hex,
            "request_version": request.version, "fence": request.fence,
            "assignment_ref": asdict(assignment_ref),
            "reviewer_actor": asdict(reviewer_actor),
            "roles": list(plan.reviewer_requirements), "trust_version": assignment_control.version,
            "answer": review_answer}
        raw = canonical_bytes(value)
        return env.blobs.put_verified(raw, Digest("sha256", hashlib.sha256(raw).hexdigest()),
                                      "application/json")

    service = build_engineering_service(factory, EngineeringPorts(
        access=access, review_admission=admission, blobs=env.blobs,
        conversation_admission=original_approvals._admission(),
        review_control=original_approvals.review_admission,
        submission_report_source=report_source, execution_records=peers,
        execution_query_factory=query_factory, source_materials=env.materials,
        method_guard=env.controls, source_review_bindings=env.bindings,
        reviewer_assignments=assignments, review_run=run_review,
        review_plan_factory=plan_factory,
    ))
    dispatch = ImplementationDispatch(factory, access,
        approval_usecases=service._packages.approvals, execution=fixture["transport"],
        selection=fixture["selection"], blobs=env.blobs,
        method_guard=env.controls, source_materials=env.materials)
    fixture["transport"].dispatch = dispatch
    owner = EngineeringOwnerOperations(factory, packages=service._packages,
        dispatch=dispatch, submissions=service._submission_reports,
        records=peers, blobs=env.blobs, access=access, unit_ref_resolver=lambda *_: __import__(
            "test_work_package_dispatch_v2", fromlist=["UNIT"]).UNIT)
    service._execution_dispatch = owner
    fixture.update(service=service, records=peers, review_source=reviewer_source,
                   assignments=assignments,
                   plan_factory=plan_factory, access=access)
    return fixture


def _table_refs(fixture, table, column):
    query = f"SELECT {column} FROM {table} WHERE realm_id=? AND project_id=? ORDER BY {column}"
    return tuple(row[0] for row in fixture["env"].library._connection.execute(
        query, (SCOPE.realm_id, SCOPE.project_id)).fetchall())


def _prepare_flow(fixture, review_answer, request_id):
    fixture["grant_ref"] = _grant_ref(fixture)
    with fixture["factory"].begin(SCOPE, "read") as uow:
        package = uow.implementation.resolve_package(fixture["package_ref"])
    environment = dict(fixture["authorization"].scope_by_action)[
        "edit_repository"].environment_refs[0]
    report = _report_value(package, environment)
    records, _captured = _install_controlled_capture(fixture, report_value=report)
    peers = _UnitPeers(records)
    fixture["transport"].records = peers
    fixture["transport"].query_factory = fixture["service"]._execution_query_factory
    fixture = _assembly(fixture, peers, review_answer)
    profile = _profile(environment)
    parameters = {"work_id": fixture["authorization"].work_id,
        "action_id": "incremental.implement-package",
        "inputs": {"package": asdict(fixture["package_ref"]), "profile": profile,
                   "reviewer_profile": profile, "method": asdict(fixture["env"].method)}}
    return (fixture, parameters, context(request_id),
            _table_refs(fixture, "eng_submissions", "submission_id"),
            _table_refs(fixture, "eng_reviews", "review_id"))


def _assert_added_once(fixture, before_submissions, before_reviews):
    submissions = _table_refs(fixture, "eng_submissions", "submission_id")
    reviews = _table_refs(fixture, "eng_reviews", "review_id")
    assert len(submissions) == len(before_submissions) + 1
    assert set(before_submissions).issubset(submissions)
    assert len(set(submissions) - set(before_submissions)) == 1
    assert len(reviews) == len(before_reviews) + 1
    assert set(before_reviews).issubset(reviews)
    assert len(set(reviews) - set(before_reviews)) == 1


def test_report_cannot_change_manifest_revision_while_reusing_profile_id_and_digest(tmp_path, monkeypatch):
    import sys
    module = sys.modules[__name__]
    original = module._report_value
    def wrong_revision(package, environment):
        value = original(package, environment)
        value['profile_ref']['manifestRevision'] += 1
        return value
    monkeypatch.setattr(module, '_report_value', wrong_revision)
    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        fixture, parameters, ctx, before_submissions, before_reviews = _prepare_flow(
            fixture, 'pass', 'wrong-report-profile-revision')
        with pytest.raises(ApplicationError, match='SUBMISSION_REPORT_BINDING_MISMATCH'):
            asyncio.run(fixture['service'].execute('engineering.work.invoke', parameters, ctx))
        assert _table_refs(fixture, 'eng_submissions', 'submission_id') == before_submissions
        assert _table_refs(fixture, 'eng_reviews', 'review_id') == before_reviews
        assert fixture['transport'].sends == 1


@pytest.mark.parametrize("review_answer, expected_disposition", [
    ("pass", "accepted"), ("fail", "rejected"), ("unknown", "unknown"),
])
def test_implementation_report_review_disposition_replays_from_original_work_journal(
        tmp_path, monkeypatch, review_answer, expected_disposition):
    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        request_id = f"implementation-results-{review_answer}"
        (fixture, parameters, request_context, before_submissions,
         before_reviews) = _prepare_flow(fixture, review_answer, request_id)
        # A report-only plan producer must not advertise the unrelated DID
        # source-review action, whose assembly requires a callable producer.
        assert not callable(fixture['plan_factory'])
        capabilities = fixture['service']._work_step_capabilities()
        assert 'jev-review-explicit-change' not in capabilities
        assert 'independently-review-report' in capabilities
        result = asyncio.run(fixture["service"].execute(
            "engineering.work.invoke", parameters, request_context))
        assert result.status == "completed"
        method_result = result.result["method_result"]
        assert method_result["disposition"] == expected_disposition
        assert method_result["accepted"] is (review_answer == "pass")
        assert method_result["retry_allowed"] is False
        if review_answer == "fail":
            rework = method_result["rework_request"]
            assert rework is not None
            assert rework["max_additional_attempts"] == 1
            assert rework["requires_caller_approval"] is True
            assert rework["automatic_retry"] is False
        else:
            assert method_result["rework_request"] is None
        assert fixture["transport"].sends == 1
        assert len(fixture["review_source"].calls) == 1
        assert len(fixture["query_factory_calls"]) == 1

        replay = asyncio.run(fixture["service"].execute(
            "engineering.work.invoke", parameters, request_context))
        assert replay.result_bytes == result.result_bytes
        assert fixture["transport"].sends == 1
        assert len(fixture["review_source"].calls) == 1
        assert len(fixture["query_factory_calls"]) == 1

        with fixture["factory"].begin(SCOPE, "read") as uow:
            submission_rows = fixture["env"].library._connection.execute(
                "SELECT COUNT(*) FROM eng_submissions").fetchone()[0]
            review_rows = fixture["env"].library._connection.execute(
                "SELECT COUNT(*) FROM eng_reviews").fetchone()[0]
            work_result = uow.commands.get(request_context.key)
        assert submission_rows == len(before_submissions) + 1
        assert review_rows == len(before_reviews) + 1
        _assert_added_once(fixture, before_submissions, before_reviews)
        assert work_result is not None and work_result.state == "completed"
        assert fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_acceptance_receipts").fetchone()[0] == 0


@pytest.mark.parametrize("revoked_authority", ["assignment", "grant"])
def test_final_work_commit_rechecks_revoked_assignment_or_grant(
        tmp_path, monkeypatch, revoked_authority):
    request_id = f"implementation-results-revoked-{revoked_authority}"
    with dispatch_fixture(tmp_path, monkeypatch) as original_fixture:
        (fixture, parameters, request_context, before_submissions,
         before_reviews) = _prepare_flow(original_fixture, "pass", request_id)
        original_finish = fixture["service"]._works.finish_invoke
        revoked = False

        def revoke_before_finish(ctx, operation_id, result, *, state="completed", validate=None):
            nonlocal revoked
            if not revoked:
                if revoked_authority == "assignment":
                    review_id, assignment_ref = next(iter(
                        fixture["review_source"].assignment_refs.items()))
                    with fixture["factory"].begin(SCOPE, "read") as uow:
                        _assignment, control = uow.reviewer_assignments.active_for_review(review_id)
                    revoke_context = context(request_id + ":revoke-assignment")
                    receipt = fixture["assignments"].revoke_reviewer(
                        revoke_context, assignment_ref=assignment_ref,
                        expected_control_version=control.version,
                        reason="controlled precommit reviewer revocation")
                    assert receipt.status == "completed"
                else:
                    with fixture["factory"].begin(SCOPE) as uow:
                        uow.authorization.revoke(fixture["grant_ref"], 0, NOW,
                            "controlled precommit Grant revocation",
                            "implementation-results-grant-revoke")
                        uow.commit()
                revoked = True
            return original_finish(ctx, operation_id, result, state=state, validate=validate)

        monkeypatch.setattr(fixture["service"]._works, "finish_invoke", revoke_before_finish)
        with pytest.raises(ApplicationError):
            asyncio.run(fixture["service"].execute(
                "engineering.work.invoke", parameters, request_context))
        assert revoked is True
        assert fixture["transport"].sends == 1
        assert len(fixture["review_source"].calls) == 1
        assert len(fixture["query_factory_calls"]) == 1

        with fixture["factory"].begin(SCOPE, "read") as uow:
            pending = uow.commands.get(request_context.key)
            submission_rows = fixture["env"].library._connection.execute(
                "SELECT COUNT(*) FROM eng_submissions").fetchone()[0]
            review_rows = fixture["env"].library._connection.execute(
                "SELECT COUNT(*) FROM eng_reviews").fetchone()[0]
        assert pending is not None and pending.state == "pending" and pending.result_bytes is None
        assert submission_rows == len(before_submissions) + 1
        assert review_rows == len(before_reviews) + 1
        _assert_added_once(fixture, before_submissions, before_reviews)

        replay = asyncio.run(fixture["service"].execute(
            "engineering.work.invoke", parameters, request_context))
        assert replay.status == "pending" and replay.result_bytes is None
        assert fixture["transport"].sends == 1
        assert len(fixture["review_source"].calls) == 1
        assert len(fixture["query_factory_calls"]) == 1

