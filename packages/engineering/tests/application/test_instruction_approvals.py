"""Captured-instruction evidence on real temporary schema17 Work/Grant owners.

All instructions, attestor guards and review providers are explicitly synthetic.
No real user source, model, Unit or production database is used.
"""
import asyncio
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.packages.authorization import ImplementationIntentAdmission
from ordessa_engineering.domain.approvals.consent import (
    CapturedInstructionEvidence, ConversationEvidence, ConversationSource, ConsentPolicyRef,
    WorkPackageNotice,
)
from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorizationIntent
from ordessa_engineering.domain.approvals.consent_codec import encode_record, decode_record
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
from ordessa_engineering.domain.approvals.refs import NoticeRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError

from test_work_package_approval_flow_v2 import build_work_package_approval
from test_real_source_chain import NOW, PRINCIPAL, SCOPE, context

ROOT = Path(__file__).resolve().parents[4]
POLICY_PATH = ROOT / 'methods/incremental-engineering/policies/product-chat-confirmation.v2.yaml'
INSTRUCTION = 'Synthetic user instruction: finish this same frozen package; model calls are not effect debits.'
BUSINESS_CONTEXT = 'Synthetic original business context: same package, repository scope and checks only.'


@contextmanager
def instruction_case(tmp_path, *, message_refs=('synthetic-message-1', 'synthetic-message-2')):
    with build_work_package_approval(tmp_path) as original:
        env = original['env']
        raw = POLICY_PATH.read_bytes()
        policy = ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 2,
                                  Digest('sha256', sha256(raw).hexdigest()))
        source = ConversationSource('controlled-test/instruction', message_refs,
            'Synthetic fixture; source references unavailable.' if not message_refs else 'Synthetic fixture only.',
            PRINCIPAL, '2026-10-13T12:00:00.000000Z')
        authorization = original['authorization']
        notice = WorkPackageNotice('instruction-notice', authorization, INSTRUCTION, source, policy)
        intent = WorkPackageAuthorizationIntent(authorization, notice.ref, policy)
        implementation = ImplementationIntentAdmission(original['factory'], env.controls, object())
        @contextmanager
        def attestor(ctx, selected):
            if ctx.principal_id != PRINCIPAL or selected != policy:
                raise ApplicationError('UNTRUSTED_CONSENT_ATTESTOR')
            yield
        admission = ConversationAdmission(raw, policy, attestor_guard=attestor,
                                         intent_guard=implementation.guard_intent)
        service = EngineeringService(original['factory'], env.service._access,
            review_admission=env.admission, blobs=env.blobs, conversation_admission=admission,
            method_guard=env.controls, source_materials=env.materials, source_review_bindings=env.bindings)
        yield dict(original, service=service, source=source, policy=policy, admission=admission,
                   raw_policy=raw, notice=notice, intent=intent, implementation_admission=implementation)


def call(f, operation, parameters, request_id, **changes):
    ctx = replace(context(request_id), **changes)
    return asyncio.run(f['service'].execute(operation, parameters, ctx))


def ready(f, *, suffix=''):
    call(f, 'engineering.notices.publish', {'notice': asdict(f['notice'])}, 'instruction-notice' + suffix)
    call(f, 'engineering.approvals.prepare_intent', {'intent': asdict(f['intent'])}, 'instruction-intent' + suffix)
    return call(f, 'engineering.approvals.request', {'intent_id': f['intent'].intent_id,
                'intent_digest': asdict(f['intent'].digest)}, 'instruction-challenge' + suffix)


def evidence(f, *, evidence_id='instruction-evidence', disposition='confirm'):
    return CapturedInstructionEvidence(evidence_id, INSTRUCTION, BUSINESS_CONTEXT, f['source'],
        f['policy'], f['intent'].digest, f['notice'].ref, disposition)


def reply(f, challenge, value, *, request_id='instruction-record', **changes):
    return call(f, 'engineering.approvals.record_conversation', {
        'challenge_id': challenge.result['challenge']['challenge_id'], 'nonce': challenge.result['nonce'],
        'expected_version': 0, 'evidence': asdict(value)}, request_id, **changes)


def test_instruction_grant_uses_original_journal_owner_and_budget(tmp_path):
    with instruction_case(tmp_path) as f:
        challenge = ready(f)
        value = evidence(f)
        assert value.source.captured_at < f['intent'].not_before
        assert 'question' not in asdict(value) and 'user_answer' not in asdict(value)
        result = reply(f, challenge, value)
        assert result.result['state'] == 'granted'
        assert reply(f, challenge, value) == result
        ref = decode_approval_ref(result.result['approval_ref'])
        with f['factory'].begin(SCOPE, 'read') as uow:
            grant = uow.authorization.get_grant(ref)
            control = uow.authorization.get_control(ref)
            budget = uow.authorization.action_budget(ref)
            assert uow.authorization.get_challenge(challenge.result['challenge']['challenge_id'])[1:] == ('granted', 1)
        assert type(grant.evidence) is CapturedInstructionEvidence
        assert grant.evidence == value
        assert decode_record(encode_record(grant), type(grant)) == grant
        assert control == {'state': 'granted', 'version': 0, 'revoked_at': None}
        assert budget['actions'] == [dict(action='edit_repository', limit=1, consumed=0),
                                     dict(action='run_checks', limit=1, consumed=0)]
        # The instruction permits model work; it does not change either formal
        # effect budget. Exercise the original same-TX consumption owner.
        with f['factory'].begin(SCOPE) as uow:
            for action in ('edit_repository', 'run_checks'):
                uow.authorization.consume_action(ref, action=action,
                    action_instance_id='instruction-effect-' + action,
                    target_digest=f['package_ref'].digest, now=NOW)
            uow.commit()
        with pytest.raises(ApplicationError, match='ACTION_BUDGET_EXHAUSTED'):
            with f['factory'].begin(SCOPE) as uow:
                uow.authorization.consume_action(ref, action='edit_repository',
                    action_instance_id='instruction-extra-effect',
                    target_digest=f['package_ref'].digest, now=NOW)
                uow.commit()
        with f['factory'].begin(SCOPE, 'read') as uow:
            assert [row['consumed'] for row in uow.authorization.action_budget(ref)['actions']] == [1, 1]
        call(f, 'engineering.approvals.revoke', {'approval_ref': asdict(ref), 'expected_version': 0,
             'reason': 'Synthetic explicit withdrawal.'}, 'instruction-revoke')
        with f['factory'].begin(SCOPE, 'read') as uow:
            assert uow.authorization.get_control(ref)['state'] == 'revoked'
            assert uow.authorization.get_grant(ref) == grant


@pytest.mark.parametrize('refs', [('synthetic-source-1', 'synthetic-source-2'), ()])
def test_same_instruction_cannot_mint_another_grant_by_recapture_or_renaming(tmp_path, refs):
    with instruction_case(tmp_path, message_refs=refs) as f:
        first = ready(f)
        reply(f, first, evidence(f))
        old = f['intent'].authorization
        scopes = tuple((action, replace(scope, implementation_intent_id='instruction-intent-2'))
                       for action, scope in old.scope_by_action)
        authorization = replace(old, intent_id='instruction-intent-2', scope_by_action=scopes)
        source = replace(f['source'], captured_at=NOW, message_refs=tuple(reversed(refs)))
        notice = WorkPackageNotice('instruction-notice-2', authorization, INSTRUCTION, source, f['policy'])
        intent = WorkPackageAuthorizationIntent(authorization, notice.ref, f['policy'])
        second_f = dict(f, source=source, notice=notice, intent=intent)
        second = ready(second_f, suffix='-2')
        renamed = replace(evidence(second_f, evidence_id='renamed-evidence'),
                          necessary_context='Changed derived binding, still the same user instruction.')
        with pytest.raises(ApplicationError, match='CONSENT_RECEIPT_CONFLICT'):
            reply(second_f, second, renamed, request_id='recaptured-instruction')
        with f['factory'].begin(SCOPE, 'read') as uow:
            assert uow.authorization.get_challenge(second.result['challenge']['challenge_id'])[1:] == ('pending', 0)
        assert f['env'].library._connection.execute('SELECT count(*) FROM eng_approval_grants').fetchone()[0] == 1
        assert f['env'].library._connection.execute('SELECT count(*) FROM eng_consent_receipts').fetchone()[0] == 1


def test_instruction_keeps_original_expiry_and_review_admission(tmp_path):
    with instruction_case(tmp_path) as f:
        challenge = ready(f)
        for index, change in enumerate(({'schema_version': 3}, {'evidence_kind': 'invented'},
                                         {'question': 'Fake question?'})):
            invalid = dict(asdict(evidence(f)), **change)
            with pytest.raises(ApplicationError, match='INVALID_INPUT'):
                call(f, 'engineering.approvals.record_conversation', {
                    'challenge_id': challenge.result['challenge']['challenge_id'],
                    'nonce': challenge.result['nonce'], 'expected_version': 0,
                    'evidence': invalid}, 'instruction-invalid-' + str(index))
        with pytest.raises(ApplicationError, match='CONSENT_EXPIRED'):
            reply(f, challenge, evidence(f), received_at=f['intent'].expires_at)
        f_without_reviews = dict(f, service=EngineeringService(f['factory'], f['env'].service._access,
            blobs=f['env'].blobs, conversation_admission=f['admission'],
            method_guard=f['env'].controls, source_materials=f['env'].materials,
            source_review_bindings=f['env'].bindings))
        with pytest.raises(ApplicationError, match='REVIEW_AUTHORITY_UNAVAILABLE'):
            reply(f_without_reviews, challenge, evidence(f), request_id='no-review-gate')
        assert f['env'].library._connection.execute('SELECT count(*) FROM eng_approval_grants').fetchone()[0] == 0
        assert f['env'].library._connection.execute('SELECT count(*) FROM eng_consent_receipts').fetchone()[0] == 0


def test_explicit_codec_kind_preserves_qa_bytes_and_v1_refuses_instruction():
    policy_raw = (ROOT / 'methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml').read_bytes()
    policy = ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 1,
                              Digest('sha256', sha256(policy_raw).hexdigest()))
    source = ConversationSource('synthetic-codec', ('synthetic-ref',), 'Synthetic only.', 'attestor', NOW)
    ref = NoticeRef(Scope('realm', 'project'), 'notice', Digest('sha256', 'a' * 64))
    old = ConversationEvidence('qa', 'Actual synthetic question?', 'Actual context.', 'Actual answer.',
                               source, policy, Digest('sha256', 'b' * 64), ref, 'confirm')
    raw = canonical_bytes(asdict(old))
    assert encode_record(old) == raw
    assert decode_record(raw, ConversationEvidence) == old
    value = CapturedInstructionEvidence('directive', INSTRUCTION, BUSINESS_CONTEXT, source,
                                       policy, old.intent_digest, ref, 'confirm')
    assert decode_record(encode_record(value), ConversationEvidence) == value
    for change in ({'schema_version': 3}, {'schema_version': True}, {'evidence_kind': 'unrecognized'},
                   {'binding_origin': 'platform-verified'}, {'question': 'invented'}):
        changed = dict(asdict(value), **change)
        with pytest.raises(ReferenceError, match='INVALID_CONSENT_RECORD'):
            decode_record(canonical_bytes(changed), ConversationEvidence)
    # Noncanonical numeric versions are refused at the original byte boundary.
    float_version = encode_record(value).replace(b'"schema_version":2', b'"schema_version":2.0')
    assert float_version != encode_record(value)
    with pytest.raises(ReferenceError, match='INVALID_RECORD_BYTES'):
        decode_record(float_version, ConversationEvidence)
    admission = ConversationAdmission(policy_raw, policy, attestor_guard=lambda *a: nullcontext(),
                                     intent_guard=lambda *a: nullcontext())
    with pytest.raises(ApplicationError, match='CONSENT_EVIDENCE_KIND_UNSUPPORTED'):
        with admission.guard_evidence(object(), object(), value):
            pytest.fail('v1 admitted a questionless instruction')
