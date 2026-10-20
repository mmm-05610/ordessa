"""Schema-17 SQLite approval of an exact declared Work/package.

The source, method and review provider are controlled test authorities. These
tests exercise the original repositories and admission flow; they do not claim
production human authentication or a live reviewer/model call.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
from pathlib import Path

import pytest

from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.packages.authorization import ImplementationIntentAdmission
from ordessa_engineering.domain.approvals.consent import (
    ConsentPolicyRef, ConversationEvidence, ConversationSource, WorkPackageNotice,
)
from ordessa_engineering.domain.approvals.implementation import (
    ActionBudgetSlot, WorkPackageAuthorization, WorkPackageAuthorizationIntent,
)
from ordessa_engineering.domain.approvals.scope import (
    ActionScope, EnvironmentRef, PathRule, RepositoryScope,
)
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.application.contracts.work_context import (
    WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX,
)

from test_itemized_source_chain import build_itemized_chain
from test_real_source_chain import (
    NOW, PRINCIPAL, SCOPE, close_chain, context, run_full_chain,
)


ROOT = Path(__file__).resolve().parents[4]
POLICY_PATH = ROOT / "methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml"
WORK_ID = "approval-work-package"


def _method_ref_wire(ref):
    return {"method_id": ref.method_id, "release_version": ref.release_version,
            "schema_version": ref.schema_version,
            "snapshot_digest": {"algorithm": "sha256", "hex": ref.snapshot_digest.hex}}


def _open_work(env, package_ref):
    return asyncio.run(env.service.execute("engineering.work.start", {
        "work_id": WORK_ID, "revision": 1, "method_ref": _method_ref_wire(env.method),
        "associations": [{"kind": "package", "ref": asdict(package_ref)}],
    }, context("approval-work-open")))


class _Admission:
    """Compose the selected conversation policy with the original method guard."""
    def __init__(self, conversation, implementation_admission):
        self.conversation = conversation
        self.implementation_admission = implementation_admission

    def guard_capture(self, *args):
        return self.conversation.guard_capture(*args)

    def guard_evidence(self, *args):
        return self.conversation.guard_evidence(*args)

    @contextmanager
    def guard_intent(self, ctx, intent):
        with self.conversation.guard_intent(ctx, intent):
            with self.implementation_admission.guard_intent(ctx, intent):
                yield


@contextmanager
def build_work_package_approval(tmp_path, *, issue_grant=False, environment_ref=None):
    env = build_itemized_chain(tmp_path)
    try:
        chain = run_full_chain(env)
        assert env.method.release_version == "2.7.2"
        opened = _open_work(env, chain.package_ref)
        assert opened.status == "completed"
        # The real Work/package records are written first; schema17 is then
        # explicitly applied to this isolated fixture database.
        migrations.migrate_schema16(env.library, backup_path=(tmp_path / "schema16-backup.sqlite").resolve())
        # Schema migration mutates this isolated EngineeringLibrary in place;
        # retain its original factory so every authority shares its identity.
        factory = env.factory
        with factory.begin(SCOPE, "read") as uow:
            head = uow.workflow.head_ref(WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX + WORK_ID)
        assert head is not None and head.revision == 1

        raw_policy = POLICY_PATH.read_bytes()
        policy = ConsentPolicyRef(
            "ordessa.product.v1.chat-attested-confirmation", 1,
            Digest("sha256", hashlib.sha256(raw_policy).hexdigest()))
        source = ConversationSource("controlled-test/transcript", (),
            "Synthetic captured test transcript; no platform identity is asserted.", PRINCIPAL, NOW)
        intent_id = "work-package-approval-intent"
        repository_scope = RepositoryScope("test-repository", (
            PathRule("src", "subtree", ("modify",)),))
        environment_refs = () if environment_ref is None else (environment_ref,)
        if environment_ref is not None and type(environment_ref) is not EnvironmentRef:
            raise TypeError("environment_ref must be an EnvironmentRef")
        action_scope = ActionScope(SCOPE.project_id, (repository_scope,), environment_refs,
                                   (), (), intent_id)
        authorization = WorkPackageAuthorization(
            scope=SCOPE, intent_id=intent_id, work_id=WORK_ID, work_revision=head.revision,
            work_digest=Digest("sha256", head.digest.removeprefix("sha256:")),
            action_id="incremental.implement-package", step_id="implement",
            package_ref=chain.package_ref, method_ref=env.method,
            actions=("edit_repository", "run_checks"),
            scope_by_action=(("edit_repository", action_scope), ("run_checks", action_scope)),
            action_budgets=(ActionBudgetSlot("edit_repository", 1), ActionBudgetSlot("run_checks", 1)),
            request_summary="Approve implementation of this exact frozen package.",
            not_before=NOW, expires_at="2026-10-15T12:00:00.000000Z")
        notice = WorkPackageNotice("work-package-approval-notice", authorization,
            "Approve this exact frozen Work/package.", source, policy)
        intent = WorkPackageAuthorizationIntent(authorization, notice.ref, policy)

        @contextmanager
        def attestor_guard(ctx, selected_policy):
            if ctx.principal_id != PRINCIPAL or selected_policy != policy:
                raise ApplicationError("UNTRUSTED_CONSENT_ATTESTOR")
            yield

        @contextmanager
        def intent_guard(ctx, selected_intent):
            if selected_intent.method_ref != env.method or selected_intent.authorization.work_id != WORK_ID:
                raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
            yield

        conversation = ConversationAdmission(raw_policy, policy,
            attestor_guard=attestor_guard, intent_guard=intent_guard)
        implementation_admission = ImplementationIntentAdmission(factory, env.controls, bindings=object())
        admission = _Admission(conversation, implementation_admission)
        service = EngineeringService(factory, env.service._access,
            review_admission=env.admission, blobs=env.blobs, conversation_admission=admission,
            method_guard=env.controls, source_materials=env.materials,
            source_review_bindings=env.bindings)
        fixture = {"env": env, "factory": factory, "service": service, "head": head,
                   "authorization": authorization, "notice": notice, "intent": intent,
                   "source": source, "policy": policy, "package_ref": chain.package_ref}
        if issue_grant:
            _notice, _prepared, challenge = _start_approval(fixture)
            fixture["challenge"] = challenge
            fixture["grant_result"] = _answer(fixture, challenge)
        yield fixture
    finally:
        close_chain(env)


@pytest.fixture
def work_approval(tmp_path):
    with build_work_package_approval(tmp_path) as fixture:
        yield fixture


def _call(env, operation, params, request_id):
    return asyncio.run(env["service"].execute(operation, params, context(request_id)))


def _evidence(env, *, evidence_id="controlled-confirmation"):
    intent, notice, source = env["intent"], env["notice"], env["source"]
    return ConversationEvidence(evidence_id, "Approve this exact frozen package?",
        intent.authorization.request_summary,
        "Yes, this exact package is approved for the declared action.",
        source, env["policy"], intent.digest, notice.ref, "confirm")


def _start_approval(env):
    notice = _call(env, "engineering.notices.publish", {"notice": asdict(env["notice"])}, "approval-notice")
    intent = _call(env, "engineering.approvals.prepare_intent", {"intent": asdict(env["intent"])}, "approval-intent")
    challenge = _call(env, "engineering.approvals.request", {
        "intent_id": env["intent"].intent_id, "intent_digest": asdict(env["intent"].digest)}, "approval-challenge")
    return notice, intent, challenge


def _answer(env, challenge):
    return _call(env, "engineering.approvals.record_conversation", {
        "challenge_id": challenge.result["challenge"]["challenge_id"],
        "expected_version": 0, "nonce": challenge.result["nonce"],
        "evidence": asdict(_evidence(env))}, "approval-answer")


def test_schema17_sqlite_approves_exact_work_package_through_original_challenge_and_grant(work_approval):
    env = work_approval
    notice, prepared, challenge = _start_approval(env)
    assert notice.status == prepared.status == challenge.status == "completed"
    assert challenge.result["state"] == "pending"
    granted = _answer(env, challenge)
    assert granted.result["state"] == "granted"
    with env["factory"].begin(SCOPE, "read") as uow:
        stored_notice = uow.authorization.get_notice(env["notice"].ref)
        stored_intent = uow.authorization.get_intent(env["intent"].intent_id)
        stored_challenge, state, _version = uow.authorization.get_challenge(
            challenge.result["challenge"]["challenge_id"])
        from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
        grant = uow.authorization.get_grant(decode_approval_ref(granted.result["approval_ref"]))
    assert stored_notice == env["notice"] and stored_intent == env["intent"]
    assert stored_challenge.binding_digest == env["intent"].digest
    assert stored_challenge.presented_digest == env["notice"].ref.digest
    assert stored_challenge.intent_id == env["intent"].intent_id and state == "granted"
    assert grant.intent == env["intent"] and grant.evidence.notice_ref == env["notice"].ref


def test_v2_notice_cannot_be_rebound_to_another_real_work_authorization(work_approval):
    env = work_approval
    from ordessa_engineering.domain.approvals.consent import WorkPackageNotice
    stale = replace(env["authorization"],
        work_digest=Digest("sha256", "f" * 64),
        request_summary="A stale Work authorization.")
    stale_notice = WorkPackageNotice("approval-notice-stale", stale,
        "Different package approval text.", env["source"], env["policy"])
    # The actual repository resolver rejects its changed seal against the
    # persisted schema17 Work head before the notice can be admitted.
    with pytest.raises(ApplicationError) as stale_error:
        _call(env, "engineering.notices.publish",
            {"notice": asdict(stale_notice)}, "approval-notice-stale")
    assert stale_error.value.code == "WORK_PACKAGE_AUTHORIZATION_WORK_CHANGED"

    published = _call(env, "engineering.notices.publish",
        {"notice": asdict(env["notice"])}, "approval-notice-valid")
    assert published.status == "completed"
    changed = replace(env["authorization"], request_summary="A different exact authorization.")
    rebound = WorkPackageAuthorizationIntent(changed, env["notice"].ref, env["policy"])
    with pytest.raises(ApplicationError) as binding_error:
        _call(env, "engineering.approvals.prepare_intent",
            {"intent": asdict(rebound)}, "approval-intent-rebound")
    assert binding_error.value.code == "CONSENT_BINDING_MISMATCH"
    with env["factory"].begin(SCOPE, "read") as uow:
        with pytest.raises(ApplicationError):
            uow.authorization.get_intent(rebound.intent_id)


def test_v2_wrong_nonce_cannot_create_a_grant(work_approval):
    env = work_approval
    _notice, _intent, challenge = _start_approval(env)
    params = {"challenge_id": challenge.result["challenge"]["challenge_id"],
              "expected_version": 0, "nonce": "wrong-nonce", "evidence": asdict(_evidence(env))}
    with pytest.raises(ApplicationError, match="CONSENT_BINDING_MISMATCH"):
        _call(env, "engineering.approvals.record_conversation", params, "approval-answer-wrong-nonce")
    assert env["env"].library._connection.execute("SELECT count(*) FROM eng_approval_grants").fetchone()[0] == 0
