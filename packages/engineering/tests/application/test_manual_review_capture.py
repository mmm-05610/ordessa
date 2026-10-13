"""Manual reply capture over real schema10 Review and Artifact command owners.

Human/reviewer authorities here are explicitly synthetic fixture ports. These
tests do not establish a production human confirmation or Grant workflow.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json

import pytest
from ordessa_infrastructure.encoding import canonical_bytes

from test_method_control_admission import env, build_plan, context
from test_proposal_usecases import SyntheticAccess
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.manual_reviews import ManualReviewReply
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.application.usecases.reviews.manual import ManualReviewCapture
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.domain.approvals.consent import ConversationSource
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.models import ReviewSetKey


def _reply(plan, *, omit=None):
    source = ConversationSource('conversation://fixture/thread-1', ('message-1',),
                                'synthetic fixture source; not authenticated', 'fixture-agent',
                                '2026-10-11T12:00:00.000000Z')
    answers = tuple(CriterionAnswer(key, 'satisfied', (), 'captured structured answer')
                    for key in plan.check_keys if key != omit)
    return ManualReviewReply('Should this be accepted?', 'Exact frozen review context.',
                             'Yes, with the stated caveat.', source, answers)


class _SyntheticManualAuthority:
    """Test-only human authority; evidence is not production attestation."""
    def __init__(self, scope, actor=None, *, on_guard=None, digest_override=None):
        self.scope = scope
        self.actor = actor or ActorRef('fixture-human', 'human', 'synthetic-manual-test')
        self.on_guard = on_guard
        self.digest_override = digest_override
        self.guarded = False

    @contextmanager
    def guard_reply(self, ctx, plan, request, reply):
        assert ctx.scope == self.scope and request.state == 'requested'
        if self.on_guard is not None:
            self.on_guard()
        raw_digest = Digest('sha256', hashlib.sha256(canonical_bytes(asdict(reply))).hexdigest())
        if self.digest_override is not None:
            raw_digest = self.digest_override
        evidence = VerifiedReviewerEvidence(
            self.scope, self.actor, ('reviewer',), 'synthetic-manual-owner', '1', 1,
            plan.request_digest, raw_digest, Digest('sha256', 'a' * 64), Digest('sha256', 'b' * 64))
        self.guarded = True
        try:
            yield evidence
        finally:
            self.guarded = False


@pytest.fixture
def manual_env(env):
    lib, method, factory, _, controls = env
    plan, bindings = build_plan(env)
    access = SyntheticAccess()
    blobs = SQLiteBlobStore(lib)
    admission = EngineeringReviewAdmission(factory, controls, bindings)
    reviews = ReviewUseCases(factory, access, admission, blobs=blobs)
    requested = reviews.plan(plan, context('manual-request'))
    request = requested.result['request']
    return lib, method, factory, controls, plan, access, blobs, admission, reviews, request


def _capture(manual_env, authority):
    _, _, factory, _, _, access, blobs, admission, _, _ = manual_env
    return ManualReviewCapture(factory, access, review_admission=admission,
                               manual_authority=authority, blobs=blobs)


def test_missing_manual_authority_or_plan_owner_refuses(manual_env):
    lib, _, factory, _, plan, access, blobs, admission, _, request = manual_env
    reply = _reply(plan)
    with pytest.raises(ApplicationError, match='MANUAL_REVIEW_AUTHORITY_UNAVAILABLE'):
        ManualReviewCapture(factory, access, review_admission=admission, blobs=blobs).capture(
            plan.review_id, reply, context('missing-human-owner'),
            expected_request_version=request['version'], fence=request['fence'])
    with pytest.raises(ApplicationError, match='MANUAL_REVIEW_AUTHORITY_UNAVAILABLE'):
        ManualReviewCapture(factory, access, manual_authority=_SyntheticManualAuthority(plan.scope),
                            blobs=blobs).capture(
            plan.review_id, reply, context('missing-plan-owner'),
            expected_request_version=request['version'], fence=request['fence'])


def test_checker_actor_cannot_satisfy_manual_human_requirement(manual_env):
    _, _, _, _, plan, _, _, _, _, request = manual_env
    authority = _SyntheticManualAuthority(plan.scope,
        ActorRef('machine-checker', 'checker', 'synthetic-machine-test'))
    capture = _capture(manual_env, authority)
    with pytest.raises(ApplicationError, match='UNTRUSTED_REVIEWER'):
        capture.capture(plan.review_id, _reply(plan), context('checker-cannot-human'),
                        expected_request_version=request['version'], fence=request['fence'])


def test_manual_reply_requires_every_frozen_check(manual_env):
    _, _, _, _, plan, _, _, _, _, request = manual_env
    capture = _capture(manual_env, _SyntheticManualAuthority(plan.scope))
    with pytest.raises(ApplicationError, match='MANUAL_REVIEW_REPLY_INCOMPLETE'):
        capture.capture(plan.review_id, _reply(plan, omit=plan.check_keys[-1]), context('missing-check'),
                        expected_request_version=request['version'], fence=request['fence'])


def test_reply_capture_creates_only_pending_artifact_and_no_review_or_grant(manual_env):
    lib, _, factory, _, plan, _, blobs, _, _, request = manual_env
    capture = _capture(manual_env, _SyntheticManualAuthority(plan.scope))
    result = capture.capture(plan.review_id, _reply(plan), context('capture-pending-reply'),
                            expected_request_version=request['version'], fence=request['fence'])
    assert result.status == 'completed'
    with factory.begin(plan.scope, 'read') as uow:
        snapshot = uow.reviews.read_set(ReviewSetKey.for_requirement(plan.requirement))
        assert not snapshot.reviews
        entry = uow.commands.get(context('capture-pending-reply').key)
        assert entry.operation == 'engineering.artifacts.create' and entry.state == 'completed'
        assert uow.engineering.access.execute(
            'SELECT COUNT(*) FROM eng_approval_grants WHERE realm_id=? AND project_id=?',
            (plan.scope.realm_id, plan.scope.project_id)).fetchone()[0] == 0
        receipt = json.loads(result.result_bytes)
        from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
        revision_ref = ArtifactRevisionRef(receipt['revision_ref']['realm_id'],
            receipt['revision_ref']['project_id'], receipt['revision_ref']['artifact_id'],
            receipt['revision_ref']['revision_id'], Digest(**receipt['revision_ref']['digest']))
        revision = uow.engineering.resolve_revision(revision_ref)
    captured = json.loads(blobs.read_verified(revision.payload.blob_ref))
    assert captured['quality_disposition'] == 'manual' and captured['grant_created'] is False


def test_manual_source_must_bind_exact_raw_reply_digest(manual_env):
    _, _, _, _, plan, _, _, _, _, request = manual_env
    authority = _SyntheticManualAuthority(plan.scope, digest_override=Digest('sha256', 'c' * 64))
    with pytest.raises(ApplicationError, match='MANUAL_REVIEW_REPLY_CHANGED'):
        _capture(manual_env, authority).capture(
            plan.review_id, _reply(plan), context('bad-reply-digest'),
            expected_request_version=request['version'], fence=request['fence'])


def test_request_withdrawal_while_source_guarded_prevents_artifact_commit(manual_env):
    _, _, factory, _, plan, _, _, admission, reviews, request = manual_env

    def withdraw_during_guard():
        result = reviews.withdraw(plan.review_id, context('withdraw-during-manual-guard'),
                                  expected_request_version=request['version'], fence=request['fence'])
        assert result.status == 'completed'

    authority = _SyntheticManualAuthority(plan.scope, on_guard=withdraw_during_guard)
    result = _capture(manual_env, authority).capture(
        plan.review_id, _reply(plan), context('capture-after-withdraw'),
        expected_request_version=request['version'], fence=request['fence'])
    assert result.status == 'rejected'
    assert b'REVIEW_REQUEST_CHANGED' in result.result_bytes
    with factory.begin(plan.scope, 'read') as uow:
        entry = uow.commands.get(context('capture-after-withdraw').key)
        assert entry.operation == 'engineering.artifacts.create' and entry.state == 'rejected'
        assert entry.result_bytes == result.result_bytes
        assert not uow.reviews.read_set(ReviewSetKey.for_requirement(plan.requirement)).reviews
        artifact_count = uow.engineering.access.execute('SELECT COUNT(*) FROM eng_artifacts').fetchone()[0]
        assert artifact_count == 1  # only the original method-test artifact exists

