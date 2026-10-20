"""Actual SQLite approval loop with explicit synthetic host/reviewer guards.

The v1 policy bytes are real; host guards and reviewer responses are controlled
fixtures, not production main-agent registration or a JEV model call.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import (
    ConsentPolicyRef, ConversationSource, ConversationNotice, AuthorizationIntent, ConversationEvidence,
)
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
from ordessa_engineering.domain.approvals.consent_codec import encode_record
from ordessa_engineering.domain.reviews.codec import encode_plan
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from test_review_usecases import SyntheticAccess, SyntheticAdmission, _scope, _context, _create_source, _plan, RAW_RESPONSE


ROOT = Path(__file__).resolve().parents[4]
POLICY_PATH = ROOT / 'methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml'


@pytest.fixture
def env(tmp_path):
    lib = EngineeringLibrary.create((tmp_path / 'consent.sqlite').resolve(), library_id='conversation-test', schema_version=8)
    factory = SQLiteUoWFactory(lib)
    access = SyntheticAccess()
    scope = _scope()
    target = _create_source(factory, scope)
    plan = _plan(scope, target)
    review_admission = SyntheticAdmission(lib, SQLiteBlobStore(lib), factory=factory)
    reviews = ReviewUseCases(factory, access, review_admission, blobs=review_admission.blobs)
    raw = POLICY_PATH.read_bytes()
    policy = ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 1,
                             Digest('sha256', hashlib.sha256(raw).hexdigest()))
    guard_depth = [0]
    @contextmanager
    def attestor_guard(context, policy_ref):
        assert not lib._connection.in_transaction
        if context.principal_id != 'principal-1' or policy_ref != policy:
            raise ApplicationError('UNTRUSTED_CONSENT_ATTESTOR')
        guard_depth[0] += 1
        try:
            yield
        finally:
            assert not lib._connection.in_transaction
            guard_depth[0] -= 1
    @contextmanager
    def intent_guard(context, intent):
        assert not lib._connection.in_transaction
        if intent.required_review_requirements != (plan.requirement,):
            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        yield
    admission = ConversationAdmission(raw, policy, attestor_guard=attestor_guard, intent_guard=intent_guard)
    facade = EngineeringService(factory, access, review_admission=review_admission,
        blobs=review_admission.blobs, conversation_admission=admission)
    source = ConversationSource('test-conversation/original-question-and-answer', (),
        'Synthetic fixture; no platform message ID or independent human authentication.',
        'principal-1', _context(scope, 'capture').received_at)
    notice = ConversationNotice(scope, 'notice-1', (target,), target, 'Actual scoped proposal text in test conversation.', source, policy)
    intent = AuthorizationIntent(scope, 'intent-1', (target,), plan.requirement.method_ref, notice.ref,
        policy, (plan.requirement,), 'reference', 'Accept this exact artifact for reference.',
        '2026-10-09T00:00:00.000000Z', '2026-10-10T00:00:00.000000Z')
    try:
        yield dict(lib=lib, factory=factory, facade=facade, scope=scope, plan=plan, reviews=reviews,
            review_admission=review_admission, notice=notice, intent=intent, source=source,
            policy=policy, admission=admission, guard_depth=guard_depth, raw_policy=raw)
    finally:
        lib.close()


def call(env, operation, parameters, request_id, **context_changes):
    ctx = replace(_context(env['scope'], request_id), **context_changes)
    return asyncio.run(env['facade'].execute(operation, parameters, ctx))


def ready(env, *, record_review=True):
    request = call(env, 'engineering.reviews.request', {'plan': json.loads(encode_plan(env['plan']))}, 'review-request')
    assert request.status == 'completed' and request.result['request']['state'] == 'requested'
    if record_review:
        env['reviews'].record_response(env['plan'].review_id, RAW_RESPONSE,
            _context(env['scope'], 'review-record'), expected_request_version=0, fence=1)
    notice = call(env, 'engineering.notices.publish', {'notice': json.loads(encode_record(env['notice']))}, 'notice')
    assert notice.result['notice_ref'] == asdict(env['notice'].ref)
    call(env, 'engineering.approvals.prepare_intent', {'intent': json.loads(encode_record(env['intent']))}, 'intent')
    return call(env, 'engineering.approvals.request', {'intent_id': env['intent'].intent_id,
        'intent_digest': asdict(env['intent'].digest)}, 'challenge')


def evidence(env, disposition='confirm', identity='answer-1'):
    return ConversationEvidence(identity, 'Accept this exact version for reference?',
        env['intent'].request_summary, 'Yes, I explicitly confirm that scope.' if disposition == 'confirm' else 'Needs clarification.',
        env['source'], env['policy'], env['intent'].digest, env['notice'].ref, disposition)


def reply(env, challenge, ev, request_id='answer', **changes):
    args = {'challenge_id': challenge.result['challenge']['challenge_id'],
        'expected_version': 0, 'nonce': challenge.result['nonce'], 'evidence': json.loads(encode_record(ev))}
    args.update(changes)
    return call(env, 'engineering.approvals.record_conversation', args, request_id)


def read(env, name, parameters, **context_changes):
    context = replace(_context(env['scope'], 'authenticated-read'), **context_changes)
    return asyncio.run(env['facade'].query(name, parameters, context))


def test_public_pending_and_exact_reads_follow_current_control(env):
    challenge = ready(env)
    pending = read(env, 'engineering.approvals.list_pending', {'limit': 1, 'after_challenge_id': None})
    assert len(pending['items']) == 1 and pending['next_after_challenge_id'] is None
    item = pending['items'][0]
    assert item['challenge'] == challenge.result['challenge']
    assert item['intent'] == asdict(env['intent']) and item['notice'] == asdict(env['notice'])
    assert 'nonce' not in item
    assert read(env, 'engineering.approvals.get_challenge',
        {'challenge_id': item['challenge']['challenge_id']}) == {
            'challenge': item['challenge'], 'state': 'pending', 'version': 0}
    assert read(env, 'engineering.approvals.get_intent', {'intent_id': env['intent'].intent_id}) == env['intent']
    for query, key in [('engineering.notices.get', 'notice_ref'), ('engineering.references.resolve', 'ref')]:
        assert read(env, query, {key: asdict(env['notice'].ref)}) == env['notice']
    grant = reply(env, challenge, evidence(env))
    ref = grant.result['approval_ref']
    stored = read(env, 'engineering.approvals.get', {'approval_ref': ref})
    assert stored.intent == env['intent'] and asdict(stored.ref) == ref
    assert read(env, 'engineering.references.resolve', {'ref': ref}) == stored
    assert read(env, 'engineering.approvals.list_pending', {'limit': 1, 'after_challenge_id': None})['items'] == []
    call(env, 'engineering.approvals.revoke', {'approval_ref': ref, 'expected_version': 0,
        'reason': 'Explicit test withdrawal.'}, 'revoke-read')
    assert read(env, 'engineering.approvals.get_control', {'approval_ref': ref})['state'] == 'revoked'
    assert read(env, 'engineering.approvals.get', {'approval_ref': ref}) == stored


@pytest.mark.parametrize('limit', [True, 0, 101, '1'])
def test_pending_page_rejects_unbounded_or_noninteger_limits(env, limit):
    before = env['lib']._connection.execute('SELECT count(*) FROM eng_commands').fetchone()[0]
    with pytest.raises(ApplicationError, match='INVALID_INPUT'):
        read(env, 'engineering.approvals.list_pending', {'limit': limit, 'after_challenge_id': None})
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_commands').fetchone()[0] == before


def test_pending_page_is_stable_and_original_access_can_refuse(env):
    first = ready(env)
    second_intent = replace(env['intent'], intent_id='intent-2')
    call(env, 'engineering.approvals.prepare_intent', {'intent': json.loads(encode_record(second_intent))}, 'intent-second')
    second = call(env, 'engineering.approvals.request', {'intent_id': second_intent.intent_id,
        'intent_digest': asdict(second_intent.digest)}, 'challenge-second')
    page = read(env, 'engineering.approvals.list_pending', {'limit': 1, 'after_challenge_id': None})
    next_page = read(env, 'engineering.approvals.list_pending', {'limit': 1,
        'after_challenge_id': page['next_after_challenge_id']})
    identifiers = [p['items'][0]['challenge']['challenge_id'] for p in (page, next_page)]
    assert identifiers == sorted([first.result['challenge']['challenge_id'], second.result['challenge']['challenge_id']])
    assert next_page['next_after_challenge_id'] is None
    assert read(env, 'engineering.approvals.list_pending', {'limit': 1, 'after_challenge_id': None}) == page
    class RefusingAccess:
        def require(self, context, operation):
            raise ApplicationError('ACCESS_DENIED')
    refused = EngineeringService(env['factory'], RefusingAccess())
    with pytest.raises(ApplicationError, match='ACCESS_DENIED'):
        asyncio.run(refused.query('engineering.approvals.list_pending',
            {'limit': 1, 'after_challenge_id': None}, _context(env['scope'], 'refused-read')))


def test_public_confirmation_reads_cannot_cross_scope_or_change_exact_digest(env):
    challenge = ready(env)
    from ordessa_engineering.domain.common.models.identity import Scope
    foreign = Scope(env['scope'].realm_id, 'foreign-project')
    for name, params in [
        ('engineering.approvals.get_intent', {'intent_id': env['intent'].intent_id}),
        ('engineering.approvals.get_challenge', {'challenge_id': challenge.result['challenge']['challenge_id']}),
        ('engineering.approvals.list_pending', {'limit': 1, 'after_challenge_id': challenge.result['challenge']['challenge_id']}),
    ]:
        with pytest.raises(ApplicationError, match='NOT_FOUND'):
            read(env, name, params, scope=foreign)
    assert read(env, 'engineering.approvals.list_pending', {'limit': 1, 'after_challenge_id': None},
        scope=foreign)['items'] == []
    changed = asdict(env['notice'].ref)
    changed['digest']['hex'] = '0' * 64
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        read(env, 'engineering.notices.get', {'notice_ref': changed})
    with pytest.raises(ApplicationError, match='INVALID_INPUT'):
        read(env, 'engineering.approvals.list_pending', {'limit': 1, 'after_challenge_id': None,
            'project_id': foreign.project_id})


def test_real_request_notice_intent_chat_grant_replay_and_revocation(env):
    challenge = ready(env)
    assert challenge.result['state'] == 'pending'
    grant = reply(env, challenge, evidence(env))
    assert grant.result['state'] == 'granted' and grant.result['source_trust_grade'] == 'agent-attested'
    assert reply(env, challenge, evidence(env)) == grant
    ref = decode_approval_ref(grant.result['approval_ref'])
    with env['factory'].begin(env['scope'], 'read') as uow:
        stored = uow.authorization.get_grant(ref)
        assert stored.evidence.source.message_refs == ()
        assert 'no platform' in stored.evidence.source.limitations
        assert uow.authorization.get_control(ref)['state'] == 'granted'
    revoked = call(env, 'engineering.approvals.revoke', {'approval_ref': asdict(ref),
        'expected_version': 0, 'reason': 'User withdrew this exact acceptance.'}, 'revoke')
    assert revoked.result['state'] == 'revoked'
    with pytest.raises(ApplicationError, match='APPROVAL_CONTROL_CHANGED'):
        call(env, 'engineering.approvals.revoke', {'approval_ref': asdict(ref),
            'expected_version': 0, 'reason': 'Again'}, 'revoke-again')
    assert env['guard_depth'] == [0]


@pytest.mark.parametrize('disposition,state', [('ambiguous', 'pending'), ('decline', 'declined')])
def test_nonconfirming_answers_preserve_evidence_without_grant(env, disposition, state):
    answer = reply(env, ready(env), evidence(env, disposition))
    assert answer.result['state'] == state
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_approval_grants').fetchone() == (0,)
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_consent_receipts').fetchone() == (1,)


@pytest.mark.parametrize('change,code', [({'nonce': 'different-nonce'}, 'CONSENT_BINDING_MISMATCH'),
                                      ({'expected_version': 2}, 'CONSENT_CHALLENGE_CHANGED')])
def test_nonce_and_challenge_version_must_match(env, change, code):
    challenge = ready(env)
    with pytest.raises(ApplicationError, match=code):
        reply(env, challenge, evidence(env), **change)
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_consent_receipts').fetchone() == (0,)


def test_empty_requirements_self_verified_and_questionless_evidence_reject(env):
    with pytest.raises(ReferenceError):
        replace(env['intent'], required_review_requirements=())
    challenge = ready(env)
    body = json.loads(encode_record(evidence(env)))
    body['approved'] = True
    with pytest.raises(ApplicationError, match='INVALID_INPUT'):
        reply(env, challenge, evidence(env), evidence=body)
    with pytest.raises(ReferenceError):
        replace(evidence(env), question='')


def test_wrong_attestor_and_changed_target_do_not_issue_grant(env):
    challenge = ready(env)
    ev = replace(evidence(env), source=replace(env['source'], attestor_id='another-agent'))
    with pytest.raises(ApplicationError, match='UNTRUSTED_CONSENT_ATTESTOR'):
        reply(env, challenge, ev)
    ev = replace(evidence(env), intent_digest=Digest('sha256', '0' * 64))
    with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
        reply(env, challenge, ev)


def test_incomplete_and_revoked_review_trust_blocks_confirmation(env):
    with pytest.raises(ApplicationError, match='REVIEW_INCOMPLETE'):
        ready(env, record_review=False)
    env['reviews'].record_response(env['plan'].review_id, RAW_RESPONSE,
        _context(env['scope'], 'review-record'), expected_request_version=0, fence=1)
    challenge = call(env, 'engineering.approvals.request', {'intent_id': env['intent'].intent_id,
        'intent_digest': asdict(env['intent'].digest)}, 'challenge')
    env['review_admission'].revoke_trust = True
    with pytest.raises(ApplicationError, match='UNTRUSTED_REVIEWER'):
        reply(env, challenge, evidence(env))
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_approval_grants').fetchone() == (0,)


def test_grant_write_failure_rolls_back_receipt_nonce_and_journal(env, monkeypatch):
    from ordessa_engineering.adapters.persistence.sqlite.authorization_repository import SQLiteAuthorizationRepository
    challenge = ready(env)
    original = SQLiteAuthorizationRepository.put_grant
    def fail(repository, grant):
        original(repository, grant)
        raise ApplicationError('STORAGE_UNAVAILABLE')
    monkeypatch.setattr(SQLiteAuthorizationRepository, 'put_grant', fail)
    with pytest.raises(ApplicationError, match='STORAGE_UNAVAILABLE'):
        reply(env, challenge, evidence(env))
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_consent_receipts').fetchone() == (0,)
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_approval_grants').fetchone() == (0,)
    assert env['lib']._connection.execute('SELECT state,version FROM eng_consent_challenges').fetchone() == ('pending', 0)
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_commands WHERE request_id=?', ('answer',)).fetchone() == (0,)


def test_product_policy_cannot_be_replaced_by_method_selected_or_elevated_policy(env):
    with pytest.raises(ApplicationError, match='INVALID_CONSENT_POLICY'):
        ConversationAdmission(env['raw_policy'], replace(env['policy'], digest=Digest('sha256', '0' * 64)),
            attestor_guard=lambda *args: None, intent_guard=lambda *args: None)
    with pytest.raises(ReferenceError, match='UNSUPPORTED_CONSENT_SOURCE'):
        replace(env['source'], trust_grade='platform-verified')


def test_renaming_evidence_id_cannot_rebind_one_answer_to_new_challenge(env):
    first = ready(env)
    reply(env, first, evidence(env))
    second = call(env, 'engineering.approvals.request', {'intent_id': env['intent'].intent_id,
        'intent_digest': asdict(env['intent'].digest)}, 'new-challenge')
    with pytest.raises(ApplicationError, match='CONSENT_RECEIPT_CONFLICT'):
        reply(env, second, evidence(env, identity='renamed-answer'), request_id='renamed-request')
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_approval_grants').fetchone() == (1,)


def test_pending_challenge_is_unique_and_binding_is_immutable(env):
    challenge = ready(env)
    with pytest.raises(ApplicationError, match='STORAGE_CONSTRAINT'):
        call(env, 'engineering.approvals.request', {'intent_id': env['intent'].intent_id,
            'intent_digest': asdict(env['intent'].digest)}, 'duplicate-pending')
    with pytest.raises(sqlite3.IntegrityError, match='CONSENT_BINDING_IMMUTABLE'):
        env['lib']._connection.execute('UPDATE eng_consent_challenges SET binding_digest=?', ('0' * 64,))
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_consent_challenges').fetchone() == (1,)


def test_expired_challenge_and_review_set_race_do_not_consume_nonce(env):
    challenge = ready(env)
    args = {'challenge_id': challenge.result['challenge']['challenge_id'], 'expected_version': 0,
        'nonce': challenge.result['nonce'], 'evidence': json.loads(encode_record(evidence(env)))}
    with pytest.raises(ApplicationError, match='CONSENT_EXPIRED'):
        call(env, 'engineering.approvals.record_conversation', args, 'expired-answer',
             received_at='2026-10-11T12:00:00.000000Z')
    def change_review_set():
        env['lib']._connection.execute('UPDATE eng_review_sets SET set_version=set_version+1')
    env['review_admission'].on_trust = change_review_set
    with pytest.raises(ApplicationError, match='REVIEW_SET_CHANGED'):
        reply(env, challenge, evidence(env))
    assert env['lib']._connection.execute('SELECT count(*) FROM eng_consent_receipts').fetchone() == (0,)


def test_revoked_control_and_grant_body_cannot_be_rewritten(env):
    grant = reply(env, ready(env), evidence(env))
    ref = grant.result['approval_ref']
    call(env, 'engineering.approvals.revoke', {'approval_ref': ref,
        'expected_version': 0, 'reason': 'Withdraw'}, 'revoke')
    with pytest.raises(sqlite3.IntegrityError, match='APPROVAL_REVOCATION_IRREVERSIBLE'):
        env['lib']._connection.execute("UPDATE eng_approval_controls SET state='granted',revoked_at=NULL,version=version+1")
    with pytest.raises(sqlite3.IntegrityError, match='IMMUTABLE_RECORD'):
        env['lib']._connection.execute("UPDATE eng_approval_grants SET digest='changed'")
