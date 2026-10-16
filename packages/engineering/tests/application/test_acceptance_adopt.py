"""Acceptance command transaction tests.

The closure/source adapters below are deliberately synthetic: they make no
claim that a real Submission, package, current method, or production Grant is
qualified. SQLite grant/control, review records, head CAS, journal, debit and
receipt paths remain the actual schema-14 implementations.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
from ordessa_engineering.domain.common.models.values import Digest
from test_review_usecases import (SyntheticAccess, SyntheticAdmission, _scope, _context,
    _create_source, _plan)
import test_conversation_approvals as conversation


class SyntheticAcceptanceAdmission:
    def __init__(self, factory): self.factory = factory
    @contextmanager
    def guard_intent(self, context, intent):
        assert not self.factory.library._connection.in_transaction
        assert intent.acceptance_use == 'adopt_content'
        yield


class SyntheticSubmissionSource:
    @contextmanager
    def guard_submission(self, context, submission, package):
        assert not context.scope.project_id == ''
        yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    from ordessa_engineering.application.usecases.support import clock
    monkeypatch.setattr(clock, 'utc_now', lambda: conversation._context(_scope(), 'clock').received_at)
    lib = EngineeringLibrary.create((tmp_path / 'adopt.sqlite').resolve(),
        library_id='acceptance-adopt-test', schema_version=14)
    factory = SQLiteUoWFactory(lib)
    access = SyntheticAccess()
    scope = _scope()
    target = _create_source(factory, scope)
    base = _plan(scope, target)
    req = replace(base.requirement, purpose='acceptance', phase_key='acceptance')
    plan = replace(base, requirement=req)
    blobs = SQLiteBlobStore(lib)
    review_admission = SyntheticAdmission(lib, blobs)
    reviews = ReviewUseCases(factory, access, review_admission, blobs=blobs)
    raw = conversation.POLICY_PATH.read_bytes()
    policy = conversation.ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 1,
        Digest('sha256', conversation.hashlib.sha256(raw).hexdigest()))

    @contextmanager
    def attestor_guard(context, policy_ref):
        assert not lib._connection.in_transaction
        assert context.principal_id == 'principal-1' and policy_ref == policy
        yield

    @contextmanager
    def intent_guard(context, intent):
        assert not lib._connection.in_transaction
        assert intent.required_review_requirements == (req,)
        yield

    admission = conversation.ConversationAdmission(raw, policy,
        attestor_guard=attestor_guard, intent_guard=intent_guard)
    source = conversation.ConversationSource('synthetic/test-answer', (),
        'Synthetic fixture only; no platform message ID or independent human authentication.',
        'principal-1', conversation._context(scope, 'capture').received_at)
    notice = conversation.ConversationNotice(scope, 'adopt-notice', (target,), target,
        'Synthetic exact artifact acceptance notice.', source, policy)
    intent = conversation.AuthorizationIntent(scope, 'adopt-intent', (target,), req.method_ref,
        notice.ref, policy, (req,), 'adopt_content', 'Accept this exact artifact.',
        '2026-10-09T00:00:00.000000Z', '2026-10-10T00:00:00.000000Z')
    acceptance_admission = SyntheticAcceptanceAdmission(factory)
    submission_source = SyntheticSubmissionSource()
    facade = EngineeringService(factory, access, review_admission=review_admission,
        blobs=blobs, conversation_admission=admission,
        acceptance_admission=acceptance_admission, submission_source=submission_source)
    try:
        yield locals()
    finally:
        lib.close()


def _call(env, op, params, request_id):
    return asyncio.run(env['facade'].execute(op, params,
        conversation._context(env['scope'], request_id)))


def _ready(env):
    call = _call
    call(env, 'engineering.reviews.request', {'plan': asdict(env['plan'])}, 'review-request')
    env['reviews'].record_response(env['plan'].review_id, conversation.RAW_RESPONSE,
        conversation._context(env['scope'], 'review-record'), expected_request_version=0, fence=1)
    call(env, 'engineering.notices.publish', {'notice': asdict(env['notice'])}, 'notice')
    call(env, 'engineering.approvals.prepare_intent', {'intent': asdict(env['intent'])}, 'intent')
    challenge = call(env, 'engineering.approvals.request', {'intent_id': env['intent'].intent_id,
        'intent_digest': asdict(env['intent'].digest)}, 'challenge')
    ev = conversation.ConversationEvidence('answer-1', 'Accept this artifact?',
        env['intent'].request_summary, 'Yes, I explicitly confirm this scope.', env['source'],
        env['policy'], env['intent'].digest, env['notice'].ref, 'confirm')
    grant = call(env, 'engineering.approvals.record_conversation', {
        'challenge_id': challenge.result['challenge']['challenge_id'], 'expected_version': 0,
        'nonce': challenge.result['nonce'], 'evidence': asdict(ev)}, 'answer')
    return decode_approval_ref(grant.result['approval_ref'])


def _synthetic_closure(env, monkeypatch):
    from ordessa_engineering.application.usecases.changes import acceptance_adopt as module
    with env['factory'].begin(env['scope'], 'read') as uow:
        revision = uow.engineering.resolve_revision(env['target'])
    submission = SimpleNamespace(ref=env['submission_ref'], output_refs=(env['target'],))
    package = SimpleNamespace(payload=SimpleNamespace(method_ref=env['intent'].method_ref))
    closure = SimpleNamespace(submission=submission, package=package,
        requirements=(env['plan'].requirement,), artifact_revisions=(revision,))
    monkeypatch.setattr(module, 'resolve_acceptance_intent', lambda uow, intent, ref: closure)
    return closure


def _setup_acceptance(env, monkeypatch):
    from ordessa_engineering.domain.reviews.refs import SubmissionRef
    env['submission_ref'] = SubmissionRef(env['scope'].realm_id, env['scope'].project_id,
        'synthetic-submission', Digest('sha256', 'e' * 64))
    _synthetic_closure(env, monkeypatch)
    with env['factory'].begin(env['scope'], 'read') as uow:
        artifact = uow.engineering.get_artifact(env['target'].artifact_id)
    head = None if artifact.head_revision_id is None else artifact.head_revision_id
    expected = {'artifact_id': env['target'].artifact_id, 'version': artifact.version,
        'head_ref': None if head is None else asdict(head)}
    params = {'submission_ref': asdict(env['submission_ref']), 'approval_ref': None,
        'expected_control_version': 0, 'targets': [{'target_ref': asdict(env['target']), 'expected': expected}]}
    return params


def _counts(env):
    db = env['lib']._connection
    return (db.execute('SELECT version,head_revision_id FROM eng_artifacts WHERE realm_id=? AND project_id=? AND artifact_id=?',
        (env['scope'].realm_id, env['scope'].project_id, env['target'].artifact_id)).fetchone(),
        db.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0],
        db.execute('SELECT count(*) FROM eng_acceptance_receipts').fetchone()[0],
        db.execute("SELECT count(*) FROM eng_commands WHERE operation='engineering.acceptance.adopt'").fetchone()[0])


def test_adopt_same_tx_receipt_and_command_replay_are_idempotent(env, monkeypatch):
    approval = _ready(env)
    params = _setup_acceptance(env, monkeypatch)
    params['approval_ref'] = asdict(approval)
    before = _counts(env)
    result = _call(env, 'engineering.acceptance.adopt', params, 'adopt-once')
    assert result.status == 'completed' and result.result['accepted'] is True
    after = _counts(env)
    assert after[0][0] == before[0][0] + 1 and after[0][1] is not None
    assert after[1:] == (before[1] + 1, before[2] + 1, before[3] + 1)
    assert _call(env, 'engineering.acceptance.adopt', params, 'adopt-once') == result
    assert _counts(env) == after


def test_missing_admission_ports_refuse_before_any_acceptance_effect(env):
    approval = _ready(env)
    from ordessa_engineering.domain.reviews.refs import SubmissionRef
    submission = SubmissionRef(env['scope'].realm_id, env['scope'].project_id,
        'missing-port-submission', Digest('sha256', 'f' * 64))
    params = {'submission_ref': asdict(submission), 'approval_ref': asdict(approval),
        'expected_control_version': 0, 'targets': [{'target_ref': asdict(env['target']),
            'expected': {'artifact_id': env['target'].artifact_id, 'version': 0, 'head_ref': None}}]}
    no_ports = EngineeringService(env['factory'], env['access'], review_admission=env['review_admission'],
        blobs=env['blobs'], conversation_admission=env['admission'])
    before = _counts(env)
    with pytest.raises(ApplicationError, match='ACCEPTANCE_ADMISSION_UNAVAILABLE'):
        asyncio.run(no_ports.execute('engineering.acceptance.adopt', params,
            conversation._context(env['scope'], 'missing-ports')))
    assert _counts(env) == before


def test_expired_grant_rolls_back_head_receipt_debit_and_command(env, monkeypatch):
    approval = _ready(env)
    params = _setup_acceptance(env, monkeypatch)
    params['approval_ref'] = asdict(approval)
    from ordessa_engineering.application.usecases.support import clock
    monkeypatch.setattr(clock, 'utc_now', lambda: '2026-10-11T00:00:00.000000Z')
    before = _counts(env)
    with pytest.raises(ApplicationError):
        _call(env, 'engineering.acceptance.adopt', params, 'adopt-expired')
    assert _counts(env) == before


def test_review_trust_rejection_prevents_adoption_effects(env, monkeypatch):
    approval = _ready(env)
    params = _setup_acceptance(env, monkeypatch)
    params['approval_ref'] = asdict(approval)
    env['review_admission'].revoke_trust = True
    before = _counts(env)
    with pytest.raises(ApplicationError):
        _call(env, 'engineering.acceptance.adopt', params, 'adopt-untrusted-review')
    assert _counts(env) == before


def test_revoked_grant_control_prevents_adoption_effects(env, monkeypatch):
    approval = _ready(env)
    params = _setup_acceptance(env, monkeypatch)
    params['approval_ref'] = asdict(approval)
    _call(env, 'engineering.approvals.revoke', {'approval_ref': asdict(approval),
        'expected_version': 0, 'reason': 'Synthetic fixture withdrawal.'}, 'withdraw-grant')
    before = _counts(env)
    with pytest.raises(ApplicationError, match='APPROVAL_CONTROL_CHANGED'):
        _call(env, 'engineering.acceptance.adopt', params, 'adopt-revoked')
    assert _counts(env) == before
