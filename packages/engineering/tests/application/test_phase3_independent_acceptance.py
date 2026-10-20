"""Stage-3 report/review/acceptance boundary checks.

The controlled peers in this module are fixture-only; they do not represent a
production UnitRecords, human reviewer, or human approval authority.
"""
from dataclasses import replace
from dataclasses import asdict
import asyncio
import hashlib
from pathlib import Path
import runpy
from contextlib import contextmanager

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.submissions import SubmissionUseCases


@pytest.fixture
def independent_reviewer_env(tmp_path):
    # Reuse the original schema-15 public assignment fixture. The UnitRecords
    # and issuer are explicitly synthetic controlled peers.
    from test_reviewer_assignments_schema15 import env as assignment_env
    generator = assignment_env.__wrapped__(tmp_path)
    value = next(generator)
    try:
        yield value
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


@pytest.fixture
def phase1_chain(tmp_path):
    from test_phase1_public_engineering_chain import chain as phase1_fixture
    generator = phase1_fixture.__wrapped__(tmp_path)
    value = next(generator)
    try:
        yield value
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


def test_report_usecase_fails_closed_without_method_bound_report_source(phase1_chain):
    """A report is never accepted merely because a caller supplies content."""
    env = phase1_chain
    # The method, Proposal and original public phase-1 review setup are reused;
    # this pure typed Submission is only malformed-source test input, never
    # persisted or treated as a real dispatch, package, or Grant.
    submission = runpy.run_path(str(Path(__file__).parents[1] / "domain/test_submission_binding.py"))["fixture"]()[0]
    from ordessa_engineering.application.contracts.commands import CommandContext
    record = replace(submission, scope=env["scope"], created_by=env["actor"],
        created_at=env["proposal"].created_at, method_content=env["method_content"],
        resulting_snapshots=(), file_changes=(), commit_refs=(), test_evidence=(),
        effect_observations=(), output_refs=(env["design"].ref,),
        coverage=tuple(replace(item, output_refs=(env["design"].ref,), file_change_ids=())
            for item in submission.coverage))
    context = CommandContext(env["scope"], "controlled-fixture-principal", env["actor"],
        "phase3-report-source-unavailable", env["proposal"].created_at, "phase3-independent-acceptance")
    usecase = SubmissionUseCases(env["factory"], env["access"], report_source=None)
    with pytest.raises(ApplicationError, match="SUBMISSION_REPORT_SOURCE_UNAVAILABLE"):
        usecase.record_report(record, context, records=None,
            blobs=env["blobs"], query_invocation=None)


def test_record_report_persists_new_submission_after_public_reviewed_grant(tmp_path):
    """Historical method/material premise; new grant and report use original owners."""
    from ordessa_infrastructure.encoding import canonical_bytes
    from types import SimpleNamespace
    from ordessa_engineering.application.api.service import EngineeringService
    from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
    from ordessa_engineering.application.usecases.changes.submissions import SubmissionUseCases
    from ordessa_engineering.application.usecases.approvals.service import ApprovalUseCases
    from ordessa_engineering.domain.approvals.consent import (
        ConsentPolicyRef, ConversationSource, ConversationNotice, ConversationEvidence,
    )
    from ordessa_engineering.domain.approvals.implementation import ImplementationAuthorizationIntent
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.reviews.models import ReviewPlan, CheckPolicy, AggregationPolicy, ReviewSetKey
    from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
    from submission_wait_native_fixture import persist_historical_dispatch
    from test_review_usecases import SyntheticAccess, SyntheticAdmission
    from test_persisted_submission_source81 import _fixture as source_fixture, _query_digest
    import test_conversation_approvals as conversation

    env = source_fixture(tmp_path)
    try:
        scope = env["scope"]
        context = env["context"]
        access = SyntheticAccess()
        old_intent = env["grant"].intent
        assert type(old_intent) is ImplementationAuthorizationIntent
        review_port = SyntheticAdmission(env["library"], env["blobs"])
        reviews = ReviewUseCases(env["factory"], access, review_port, blobs=env["blobs"])
        review_refs = []
        requirements = old_intent.required_review_requirements
        for index, requirement in enumerate(requirements):
            plan = ReviewPlan("phase3-report-review-" + str(index), requirement,
                tuple(CheckPolicy(key, required=True, blocking=True)
                    for key in requirement.required_check_keys),
                AggregationPolicy(), requirement.eligible_reviewer_roles)
            requested = reviews.request({"plan": asdict(plan)},
                replace(context, request_id="phase3-report-review-request-" + str(index)))
            assert requested.status == "completed"
            reviews.record_response(plan.review_id, b'{"answer":"synthetic required review"}',
                replace(context, request_id="phase3-report-review-record-" + str(index)),
                expected_request_version=0, fence=1)
            with env["factory"].begin(scope, "read") as uow:
                read_set = uow.reviews.read_set(ReviewSetKey.for_requirement(requirement))
            assert len(read_set.reviews) == 1
            review_refs.append(read_set.reviews[0].record.ref)

        policy_bytes = conversation.POLICY_PATH.read_bytes()
        policy = ConsentPolicyRef("ordessa.product.v1.chat-attested-confirmation", 1,
            Digest("sha256", hashlib.sha256(policy_bytes).hexdigest()))
        source = ConversationSource("phase3-report-grant-conversation", (),
            "Synthetic test answer; no platform message or human authentication.",
            context.principal_id, context.received_at)
        notice = ConversationNotice(scope, "phase3-report-notice", old_intent.targets,
            old_intent.targets[0], "Review this exact historical method implementation request.", source, policy)
        intent = replace(old_intent, intent_id="phase3-report-implementation-intent",
            notice_ref=notice.ref, policy_ref=policy,
            supporting_review_refs=tuple(review_refs), not_before=context.received_at,
            expires_at="2026-10-14T00:00:00.000000Z")

        @contextmanager
        def attestor_guard(ctx, policy_ref):
            assert not env["library"]._connection.in_transaction
            assert ctx.principal_id == context.principal_id and policy_ref == policy
            yield

        authorized_intents = [intent]

        @contextmanager
        def intent_guard(ctx, candidate):
            assert not env["library"]._connection.in_transaction
            assert candidate in authorized_intents
            yield

        admission = ConversationAdmission(policy_bytes, policy,
            attestor_guard=attestor_guard, intent_guard=intent_guard)
        facade = EngineeringService(env["factory"], access, review_admission=review_port,
            blobs=env["blobs"], conversation_admission=admission)

        def call(operation, parameters, request_id):
            return asyncio.run(facade.execute(operation, parameters,
                replace(context, request_id=request_id)))

        assert call("engineering.notices.publish", {"notice": asdict(notice)},
            "phase3-report-publish-notice").status == "completed"
        assert call("engineering.approvals.prepare_intent", {"intent": asdict(intent)},
            "phase3-report-prepare-intent").status == "completed"
        challenge = call("engineering.approvals.request", {"intent_id": intent.intent_id,
            "intent_digest": asdict(intent.digest)}, "phase3-report-request-approval")
        evidence = ConversationEvidence("phase3-report-answer", "Confirm this implementation request?",
            intent.request_summary, "Yes, confirm the exact controlled request.", source,
            policy, intent.digest, notice.ref, "confirm")
        grant_result = call("engineering.approvals.record_conversation", {
            "challenge_id": challenge.result["challenge"]["challenge_id"],
            "expected_version": 0, "nonce": challenge.result["nonce"],
            "evidence": asdict(evidence)}, "phase3-report-record-answer")
        assert grant_result.result["state"] == "granted"
        from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
        grant_ref = decode_approval_ref(grant_result.result["approval_ref"])
        with env["factory"].begin(scope, "read") as uow:
            grant = uow.authorization.get_grant(grant_ref)

        # Freeze an immutable package that carries the newly issued exact Grant
        # and reviewed requirement references. The native dispatch fact below
        # is a controlled fixture record, never a claim that a Unit ran.
        package = replace(env["package"], package_id="phase3-report-package",
            payload=replace(env["package"].payload, authorization_refs=(grant.ref,),
                required_review_refs=tuple(review_refs),
                derivation=replace(env["package"].payload.derivation,
                    intent_digest=grant.intent.digest)))
        operation_ref = "phase3-record-report-operation"
        receipt = dict(env["records"].receipt)
        receipt["operationRef"] = operation_ref
        receipt_bytes = canonical_bytes(receipt)
        capture_ref = env["blobs"].put_verified(receipt_bytes,
            Digest("sha256", hashlib.sha256(receipt_bytes).hexdigest()), "application/json")
        execution = replace(env["submission"].execution_ref, operation_ref=operation_ref,
            captured_observation_ref=capture_ref)
        prompt_digest = "sha256:" + execution.prompt_input_digest.hex
        query_digest = _query_digest(env["unit_ref"], operation_ref, prompt_digest)
        records = env["records"]
        records.receipt = receipt
        persist_historical_dispatch({"factory": env["factory"], "run_id": "phase3-report-run",
            "created_at": context.received_at, "registry": {"registry_id": "source81-fixture",
                "revision": 1, "registry_digest": "sha256:" + "0" * 64, "operations": {}}},
            snapshot=env["snapshot"], package=package, grant=grant,
            submission_execution_ref=execution, unit_ref=env["unit_ref"], prompt_ref=capture_ref,
            prompt_digest=execution.prompt_input_digest, query_digest=query_digest)
        record = replace(env["submission"], submission_id="phase3-report-submission",
            created_at=context.received_at, created_by=context.authenticated_actor,
            authorization_refs=(grant.ref,), package_ref=package.ref, execution_ref=execution)
        usecase = SubmissionUseCases(env["factory"], access,
            approval_usecases=ApprovalUseCases(env["factory"], access, admission, review_port),
            report_source=env["adapter"].report_source)
        report_context = replace(context, request_id="phase3-record-report")
        result = usecase.record_report(record, report_context, records=records, blobs=env["blobs"],
            query_invocation=SimpleNamespace(facts={"inputDigest": query_digest}))
        assert result.status == "completed"
        with env["factory"].begin(scope, "read") as uow:
            stored = uow.submissions.resolve(record.ref)
        assert stored == record
        assert result.result["workflow_state"] == "submitted"
        assert result.result["review_status"] == "pending_review"
        assert result.result["accepted"] is False

        # Continue with this exact newly persisted report. The review binding
        # names its SubmissionRef explicitly; it does not reuse the historical
        # submission from source_fixture.
        from ordessa_engineering.adapters.review_sources import ConfiguredReviewPhase, SQLiteReviewBindings
        from ordessa_engineering.application.usecases.changes.acceptance_closure import resolve_submission_acceptance
        from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
        from ordessa_engineering.application.assembly import build_submission_acceptance_admission
        from ordessa_engineering.domain.approvals.consent import AuthorizationIntent
        from ordessa_engineering.domain.reviews.models import ReviewPlan, CheckPolicy, AggregationPolicy
        bindings = SQLiteReviewBindings(env["factory"], env["controls"], scope=scope,
            proposal_ref=package.payload.change_set.proposal_refs[0], phases=(
                ConfiguredReviewPhase("acceptance_review", ("reviewer",),
                    workflow_node_id="acceptance_review", submission_ref=record.ref,
                    review_purpose="acceptance"),))
        with env["factory"].begin(scope, "read") as uow:
            closure = resolve_submission_acceptance(uow, record.ref)
        phase_bindings = bindings.resolve_submission_bindings(context, package.payload.method_ref, record.ref)
        plans = MethodBridge().submission_review_plans(env["snapshot"], phase_bindings,
            requirements=closure.requirements, revisions=closure.artifact_revisions,
            review_ids={item.requirement_id: "phase3-new-report-acceptance-" + str(i)
                for i, item in enumerate(closure.requirements)})
        for index, plan in enumerate(plans):
            requested = reviews.request({"plan": asdict(plan)},
                replace(context, request_id="phase3-new-report-acceptance-request-" + str(index)))
            assert requested.status == "completed"
            reviews.record_response(plan.review_id, b'{"answer":"synthetic independent acceptance review"}',
                replace(context, request_id="phase3-new-report-acceptance-record-" + str(index)),
                expected_request_version=0, fence=1)
        target_refs = tuple(closure.submission.output_refs)
        accept_notice = ConversationNotice(scope, "phase3-new-report-acceptance-notice",
            target_refs, target_refs[0], "Accept this exact newly reported submission output.", source, policy)
        accept_intent = AuthorizationIntent(scope, "phase3-new-report-acceptance-intent",
            target_refs, closure.package.payload.method_ref, accept_notice.ref, policy,
            closure.requirements, "adopt_content", "Accept this exact newly reported output.",
            context.received_at, "2026-10-14T00:00:00.000000Z")
        authorized_intents.append(accept_intent)
        acceptance_admission = build_submission_acceptance_admission(env["factory"],
            method_control=env["controls"], bindings=bindings)
        facade = EngineeringService(env["factory"], access, review_admission=review_port,
            blobs=env["blobs"], conversation_admission=admission,
            acceptance_admission=acceptance_admission,
            submission_source=env["adapter"])

        assert call("engineering.notices.publish", {"notice": asdict(accept_notice)},
            "phase3-new-report-acceptance-publish").status == "completed"
        assert call("engineering.approvals.prepare_intent", {"intent": asdict(accept_intent)},
            "phase3-new-report-acceptance-prepare").status == "completed"
        accept_challenge = call("engineering.approvals.request", {"intent_id": accept_intent.intent_id,
            "intent_digest": asdict(accept_intent.digest)}, "phase3-new-report-acceptance-request-grant")
        accept_evidence = ConversationEvidence("phase3-new-report-acceptance-answer",
            "Accept this exact submission?", accept_intent.request_summary,
            "Yes, accept this exact controlled output.", source, policy,
            accept_intent.digest, accept_notice.ref, "confirm")
        accept_grant = call("engineering.approvals.record_conversation", {
            "challenge_id": accept_challenge.result["challenge"]["challenge_id"],
            "expected_version": 0, "nonce": accept_challenge.result["nonce"],
            "evidence": asdict(accept_evidence)}, "phase3-new-report-acceptance-answer")
        assert accept_grant.result["state"] == "granted"
        accept_ref = accept_grant.result["approval_ref"]
        expected_targets = []
        with env["factory"].begin(scope, "read") as uow:
            for target in target_refs:
                artifact = uow.engineering.get_artifact(target.artifact_id)
                expected_targets.append({"target_ref": asdict(target), "expected": {
                    "artifact_id": target.artifact_id, "version": artifact.version,
                    "head_ref": None if artifact.head_revision_id is None else asdict(artifact.head_revision_id)}})
            from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
            control = uow.authorization.get_control(decode_approval_ref(accept_ref))
            before_count = env["library"]._connection.execute(
                "SELECT COUNT(*) FROM eng_acceptance_receipts").fetchone()[0]
        wrong_ref = asdict(env["design"].ref)
        wrong_target = {"target_ref": wrong_ref, "expected": {"artifact_id": wrong_ref["artifact_id"],
            "version": 1, "head_ref": wrong_ref}}
        with pytest.raises(ApplicationError, match="CONSENT_BINDING_MISMATCH"):
            call("engineering.acceptance.adopt", {"submission_ref": asdict(record.ref),
                "approval_ref": accept_ref, "expected_control_version": control["version"],
                "targets": [wrong_target]}, "phase3-new-report-wrong-output")
        assert env["library"]._connection.execute(
            "SELECT COUNT(*) FROM eng_acceptance_receipts").fetchone()[0] == before_count
        adopted = call("engineering.acceptance.adopt", {"submission_ref": asdict(record.ref),
            "approval_ref": accept_ref, "expected_control_version": control["version"],
            "targets": expected_targets}, "phase3-new-report-acceptance-adopt")
        assert adopted.status == "completed" and adopted.result["accepted"] is True
        with env["factory"].begin(scope, "read") as uow:
            receipt = uow.acceptance.resolve(adopted.result["acceptance_receipt_ref"]["adoption_id"])
        assert receipt is not None and receipt.plan.submission_ref == record.ref
    finally:
        env["library"].close()


def test_independent_reviewer_assignment_rejects_author_and_accepts_distinct_unit(independent_reviewer_env):
    from test_reviewer_assignments_schema15 import _assign, _unit
    env = independent_reviewer_env
    with pytest.raises(ApplicationError, match="UNTRUSTED_REVIEWER"):
        _assign(env, env["author"], "phase3-same-author")
    result = _assign(env, _unit("phase3-independent-reviewer"), "phase3-distinct-reviewer")
    assert result.status == "completed"
    with env["factory"].begin(env["plan"].scope, "read") as uow:
        assignment, _control = uow.reviewer_assignments.active_for_review(env["plan"].review_id)
    assert assignment.author_unit_ref_bytes != assignment.reviewer_unit_ref_bytes


def test_public_acceptance_adopts_exact_historical_submission_with_independent_review(tmp_path):
    """Controlled historical package/Grant premise; real public review/Q&A/adopt path."""
    from ordessa_engineering.application.api.service import EngineeringService
    from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
    from ordessa_engineering.application.assembly import build_submission_acceptance_admission
    from ordessa_engineering.domain.approvals.consent import (
        ConsentPolicyRef, ConversationSource, ConversationNotice,
        AuthorizationIntent, ConversationEvidence,
    )
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
    from test_review_usecases import SyntheticAccess, SyntheticAdmission
    from submission_wait_business_fixture import build_submission_wait_fixture
    import test_conversation_approvals as conversation

    env = build_submission_wait_fixture(tmp_path, report_phase=True)
    try:
        # This fixture starts from an explicitly controlled historical
        # implementation Grant/package/submission. It does not claim a real
        # Unit or report-source run. The acceptance review, acceptance Grant,
        # business closure and adoption below use original SQLite use cases.
        scope, principal, actor, now = (env["scope"], env["context"].principal_id,
            env["context"].authenticated_actor, env["context"].received_at)
        access = SyntheticAccess()
        review_port = SyntheticAdmission(env["library"], env["blobs"])
        reviews = ReviewUseCases(env["factory"], access, review_port, blobs=env["blobs"])
        review_request = reviews.request({"plan": asdict(env["plan"])},
            replace(env["context"], request_id="phase3-acceptance-review-request"))
        assert review_request.status == "completed"
        reviews.record_response(env["plan"].review_id, b'{"answer":"synthetic independent review"}',
            replace(env["context"], request_id="phase3-acceptance-review-record"),
            expected_request_version=0, fence=1)

        policy_bytes = conversation.POLICY_PATH.read_bytes()
        policy = ConsentPolicyRef("ordessa.product.v1.chat-attested-confirmation", 1,
            Digest("sha256", hashlib.sha256(policy_bytes).hexdigest()))
        source = ConversationSource("phase3-controlled-conversation", (),
            "Synthetic test answer; no platform message or human authentication.", principal, now)
        closure = env["closure"]
        target_refs = tuple(closure.submission.output_refs)
        notice = ConversationNotice(scope, "phase3-acceptance-notice", target_refs,
            target_refs[0], "Accept this exact historical submission output.", source, policy)
        intent = AuthorizationIntent(scope, "phase3-acceptance-intent", target_refs,
            closure.package.payload.method_ref, notice.ref, policy, closure.requirements,
            "adopt_content", "Accept this exact controlled submission output.",
            "2026-10-11T00:00:00.000000Z", "2026-10-14T00:00:00.000000Z")

        @contextmanager
        def attestor_guard(context, policy_ref):
            assert not env["library"]._connection.in_transaction
            assert context.principal_id == principal and policy_ref == policy
            yield

        @contextmanager
        def intent_guard(context, candidate):
            assert not env["library"]._connection.in_transaction
            assert candidate == intent
            yield

        admission = ConversationAdmission(policy_bytes, policy,
            attestor_guard=attestor_guard, intent_guard=intent_guard)
        acceptance_admission = build_submission_acceptance_admission(
            env["factory"], method_control=env["controls"], bindings=env["bindings"])

        class HistoricalSubmissionSource:
            """Controlled historical submission binding; not a Unit authority."""
            @contextmanager
            def guard_submission(self, context, submission, package):
                with env["factory"].begin(context.scope, "read") as uow:
                    assert uow.submissions.resolve(submission.ref) == submission
                    assert uow.implementation.resolve_package(package.ref) == package
                yield

        facade = EngineeringService(env["factory"], access, review_admission=review_port,
            blobs=env["blobs"], conversation_admission=admission,
            acceptance_admission=acceptance_admission,
            submission_source=HistoricalSubmissionSource())

        def call(operation, parameters, request_id):
            context = replace(env["context"], request_id=request_id)
            return asyncio.run(facade.execute(operation, parameters, context))

        assert call("engineering.notices.publish", {"notice": asdict(notice)},
            "phase3-acceptance-publish").status == "completed"
        assert call("engineering.approvals.prepare_intent", {"intent": asdict(intent)},
            "phase3-acceptance-prepare").status == "completed"
        challenge = call("engineering.approvals.request", {"intent_id": intent.intent_id,
            "intent_digest": asdict(intent.digest)}, "phase3-acceptance-request")
        evidence = ConversationEvidence("phase3-acceptance-answer", "Accept this submission?",
            intent.request_summary, "Yes, accept this exact output for the controlled test.",
            source, policy, intent.digest, notice.ref, "confirm")
        granted = call("engineering.approvals.record_conversation", {
            "challenge_id": challenge.result["challenge"]["challenge_id"],
            "expected_version": 0, "nonce": challenge.result["nonce"],
            "evidence": asdict(evidence)}, "phase3-acceptance-answer")
        assert granted.result["state"] == "granted"
        approval_ref = granted.result["approval_ref"]

        targets = []
        with env["factory"].begin(scope, "read") as uow:
            for target in target_refs:
                artifact = uow.engineering.get_artifact(target.artifact_id)
                head = None if artifact.head_revision_id is None else artifact.head_revision_id
                targets.append({"target_ref": asdict(target), "expected": {
                    "artifact_id": target.artifact_id, "version": artifact.version,
                    "head_ref": None if head is None else asdict(head)}})
            from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
            approval = decode_approval_ref(approval_ref)
            control = uow.authorization.get_control(approval)
            before_acceptance_count = env["library"]._connection.execute(
                "SELECT COUNT(*) FROM eng_acceptance_receipts").fetchone()[0]
        wrong_target = asdict(env["design"].ref)
        wrong_artifact = {"target_ref": wrong_target, "expected": {
            "artifact_id": wrong_target["artifact_id"], "version": 1, "head_ref": wrong_target}}
        with pytest.raises(ApplicationError, match="CONSENT_BINDING_MISMATCH"):
            call("engineering.acceptance.adopt", {
                "submission_ref": asdict(closure.submission.ref), "approval_ref": approval_ref,
                "expected_control_version": control["version"], "targets": [wrong_artifact]},
                "phase3-acceptance-wrong-output")
        assert env["library"]._connection.execute(
            "SELECT COUNT(*) FROM eng_acceptance_receipts").fetchone()[0] == before_acceptance_count
        result = call("engineering.acceptance.adopt", {
            "submission_ref": asdict(closure.submission.ref), "approval_ref": approval_ref,
            "expected_control_version": control["version"], "targets": targets},
            "phase3-acceptance-adopt")
        assert result.status == "completed" and result.result["accepted"] is True
        with env["factory"].begin(scope, "read") as uow:
            receipt = uow.acceptance.resolve(result.result["acceptance_receipt_ref"]["adoption_id"])
        assert receipt is not None and receipt.plan.submission_ref == closure.submission.ref
    finally:
        env["library"].close()
