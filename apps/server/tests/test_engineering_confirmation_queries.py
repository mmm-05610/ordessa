"""Real HTTP exact queries over original typed SQLite fixture records.

Records are seeded through the original repositories solely to qualify reads.
No fake reviewer/main Agent guard is installed in the product, and these fixture
grants are not evidence of real user approval or a production approval command.
"""
from dataclasses import asdict, replace
import hashlib
import json
import pytest
from .test_engineering_slice import runtime, call, parameters, SCOPE
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.target_codec import decode_subject_ref
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.reviews.models import ReviewRequirement, CriterionSetRef, CheckKey
from ordessa_engineering.domain.approvals.consent import (
    ConsentPolicyRef, ConversationSource, ConversationNotice, AuthorizationIntent,
    ConsentChallenge, ConversationEvidence, ApprovalGrant,
)

def wire_record(value):
    return json.loads(json.dumps(asdict(value)))

@pytest.fixture
def records(runtime):
    raw = call(runtime, 'engineering.artifacts.create', parameters())['result']['result']['revision_ref']
    target = decode_subject_ref(raw)
    scope = Scope(SCOPE.realm_id, SCOPE.project_id)
    source = ConversationSource('test-only/query-fixture', (),
        'Seeded read fixture; no real user consent or independently authenticated human.',
        'local', '2026-10-11T00:00:00.000000Z')
    policy = ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 1, Digest('sha256', 'a'*64))
    notice = ConversationNotice(scope, 'fixture-notice', (target,), target,
        'Seeded query fixture only.', source, policy)
    method = MethodRef('fixture-method', '1.0', 1, Digest('sha256', 'b'*64))
    t = Target('primary', target)
    requirement = ReviewRequirement(scope, 'fixture-requirement', 1, 'quality', TargetSet((t,)), method,
        CriterionSetRef('fixture-criteria', 1, Digest('sha256', 'c'*64)),
        (CheckKey(t, 'fixture-check'),), ('reviewer',), 'fixture-phase')
    intent = AuthorizationIntent(scope, 'fixture-intent', (target,), method, notice.ref, policy,
        (requirement,), 'reference', 'Seeded fixture acceptance.',
        '2026-10-11T00:00:00.000000Z', '2026-10-12T00:00:00.000000Z')
    challenge = ConsentChallenge(scope, 'challenge-a', intent.intent_id, intent.digest,
        notice.digest, Digest('sha256', 'd'*64), intent.expires_at)
    evidence = ConversationEvidence('fixture-answer', 'Fixture question?', 'Fixture context.',
        'Fixture answer.', source, policy, intent.digest, notice.ref, 'confirm')
    grant = ApprovalGrant('fixture-grant', intent, challenge.challenge_id, evidence,
        '2026-10-11T01:00:00.000000Z')
    plugin = next(p for p in runtime.plugin_selection if p.descriptor().id == 'ordessa.engineering')
    factory = SQLiteUoWFactory(plugin.library)
    with factory.begin(scope, 'write') as uow:
        repo = uow.authorization
        repo.put_notice(notice)
        repo.put_intent(intent)
        repo.put_challenge(challenge)
        repo.put_receipt(challenge, evidence)
        repo.put_grant(grant)
        repo.transition_challenge(challenge.challenge_id, 0, 'granted')
        for identity in ('challenge-b', 'challenge-c'):
            alternate = replace(intent, intent_id='intent-'+identity)
            repo.put_intent(alternate)
            repo.put_challenge(replace(challenge, challenge_id=identity,
                intent_id=alternate.intent_id, binding_digest=alternate.digest,
                nonce_digest=Digest('sha256', hashlib.sha256(identity.encode()).hexdigest())))
        uow.commit()
    return notice, intent, challenge, grant, factory

def result(runtime, query, parameters):
    value = call(runtime, query, parameters)
    assert 'error' not in value, value
    return value['result']

def test_six_public_queries_read_exact_original_records_and_keyset_pages(runtime, records):
    notice, intent, challenge, grant, _ = records
    for query, args, kind, expected in [
        ('engineering.notices.get', {'notice_ref':wire_record(notice.ref)}, 'ConversationNotice', wire_record(notice)),
        ('engineering.approvals.get_intent', {'intent_id':intent.intent_id}, 'AuthorizationIntent', wire_record(intent)),
        ('engineering.approvals.get', {'approval_ref':wire_record(grant.ref)}, 'ApprovalGrant', wire_record(grant)),
        ('engineering.approvals.get_control', {'approval_ref':wire_record(grant.ref)}, 'ApprovalControl', {'state':'granted','version':0,'revoked_at':None}),
        ('engineering.approvals.get_challenge', {'challenge_id':challenge.challenge_id}, 'ApprovalChallenge',
            {'challenge':wire_record(challenge),'state':'granted','version':1}),
    ]:
        wire = result(runtime, query, args)
        assert wire['record_type'] == kind and wire['data'] == expected
    page = result(runtime, 'engineering.approvals.list_pending', {'limit':1,'after_challenge_id':None})
    assert page['record_type'] == 'PendingApprovals'
    assert page['data']['items'][0]['challenge']['challenge_id'] == 'challenge-b'
    assert page['data']['next_after_challenge_id'] == 'challenge-b'
    tail = result(runtime, 'engineering.approvals.list_pending', {'limit':1,'after_challenge_id':'challenge-b'})['data']
    assert tail['items'][0]['challenge']['challenge_id'] == 'challenge-c'
    assert tail['next_after_challenge_id'] is None
    assert 'nonce' not in page['data']['items'][0]
    assert result(runtime, 'engineering.references.resolve', {'ref':wire_record(grant.ref)})['data'] == wire_record(grant)
    assert result(runtime, 'engineering.references.resolve', {'ref':wire_record(notice.ref)})['data'] == wire_record(notice)

@pytest.mark.parametrize('limit', [True, 0, 101, '1'])
def test_pending_input_is_strict(runtime, records, limit):
    assert call(runtime, 'engineering.approvals.list_pending', {'limit':limit,'after_challenge_id':None})['error']['code']=='INVALID_REQUEST'

def test_exact_digest_scope_and_revocation_read_current_control(runtime, records):
    notice, intent, _, grant, factory = records
    bad = wire_record(notice.ref)
    bad['digest']['hex'] = '0'*64
    assert 'error' in call(runtime, 'engineering.notices.get', {'notice_ref':bad})
    assert call(runtime, 'engineering.approvals.get_intent', {'intent_id':intent.intent_id},
        scope=type(SCOPE)(SCOPE.realm_id,'foreign'))['error']['code']=='FORBIDDEN'
    with factory.begin(intent.scope, 'write') as uow:
        uow.authorization.revoke(grant.ref, 0, '2026-10-11T02:00:00.000000Z', 'Fixture withdrawal.', 'fixture-revoke')
        uow.commit()
    assert result(runtime, 'engineering.approvals.get_control', {'approval_ref':wire_record(grant.ref)})['data']['state']=='revoked'
    assert result(runtime, 'engineering.approvals.get', {'approval_ref':wire_record(grant.ref)})['data']==wire_record(grant)
