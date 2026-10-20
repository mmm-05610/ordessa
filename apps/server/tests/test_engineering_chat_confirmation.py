"""Original SQLite fixtures + real instance attestor; no actual user Grant.

The original fixture records are read test data. The intent guard below is
explicitly synthetic; tests prove source/presentation and original refusal,
not production method/review gate qualification or a real human answer.
"""
from contextlib import contextmanager
from dataclasses import replace

import pytest
from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import ConversationSource, ConversationEvidence, ConsentChallenge
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_server.composition.conversation_attestor import RegisteredMainAgentAttestor
from ordessa_server.composition.engineering_chat_confirmation import MainAgentChatConfirmation, confirmation_presentation
from ordessa_server.composition.engineering_human_source import SOURCE_LIMITATION
from .test_engineering_confirmation_queries import records
from .test_engineering_slice import runtime, SCOPE

CAPS = ('engineering.approvals.get_challenge', 'engineering.approvals.record_conversation',
        'engineering.conversation.attest')


def selected(records):
    notice, intent, _, _, factory = records
    authority = InstanceAccessAuthority(lambda: 'synthetic-chat-source-token',
        principal_id='registered-main-agent', legacy_principal=None,
        grants=(AccessGrant(SCOPE, CAPS),))
    access = EngineeringCommandAccess(authority)
    @contextmanager
    def fixture_intent_guard(context, actual):
        assert actual.notice_ref == notice.ref
        yield
    # Real policy bytes; replace the historical fixture's deliberately fake
    # policy digest in this guard-only test. No persisted intent is re-labelled.
    from pathlib import Path
    import hashlib
    from ordessa_engineering.domain.common.models.values import Digest
    raw = (Path(__file__).resolve().parents[3]/'methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml').read_bytes()
    policy = replace(notice.policy_ref, digest=Digest('sha256', hashlib.sha256(raw).hexdigest()))
    attestor = RegisteredMainAgentAttestor(access, scope=SCOPE,
        principal_id=authority.principal_id, selected_policy_ref=policy)
    base = ConversationAdmission(raw, policy, attestor_guard=attestor.guard,
        intent_guard=fixture_intent_guard)
    notice = replace(notice, notice_id='chat-notice', policy_ref=policy)
    intent = replace(intent, intent_id='chat-intent', notice_ref=notice.ref, policy_ref=policy,
        not_before='2026-01-01T00:00:00.000000Z', expires_at='2027-01-01T00:00:00.000000Z')
    nonce='test-chat-nonce'
    challenge=ConsentChallenge(intent.scope,'chat-pending',intent.intent_id,intent.digest,notice.digest,
        Digest('sha256',hashlib.sha256(nonce.encode()).hexdigest()),intent.expires_at)
    with factory.begin(intent.scope, 'write') as uow:
        uow.authorization.put_notice(notice);uow.authorization.put_intent(intent)
        uow.authorization.put_challenge(challenge);uow.commit()
    source = MainAgentChatConfirmation(factory, base, conversation_locator='chat://synthetic-test')
    return authority, access, source, authority.authenticate('Bearer synthetic-chat-source-token'), policy, notice, intent


def test_exact_pending_presentation_is_read_only_and_contains_action_scope(runtime, records):
    authority, access, source, caller, _, notice, intent = selected(records)
    with access.admit(caller, SCOPE, CAPS[0], request_id='presentation', trace_id='presentation') as context:
        view = source.prepare(access, context, 'chat-pending')
        assert view['state'] == 'pending' and view['expected_version'] == 0
        assert 'accept_artifact' in view['necessary_context']
        assert SOURCE_LIMITATION in view['necessary_context'] and 'nonce' not in view
        with records[-1].begin(context.scope, 'read') as uow:
            assert uow.authorization.get_challenge('chat-pending')[1:] == ('pending', 0)


@pytest.mark.parametrize('change', ['locator', 'limitations', 'question', 'context', 'empty_answer'])
def test_wrong_source_or_changed_display_refuses_without_grant(runtime, records, change):
    _, access, source, caller, policy, notice, intent = selected(records)
    with access.admit(caller, SCOPE, CAPS[1], request_id='answer', trace_id='answer') as context:
        capture = ConversationSource(source.locator, ('synthetic-message',), SOURCE_LIMITATION,
            context.principal_id, context.received_at)
        view = confirmation_presentation(intent, notice)
        evidence = ConversationEvidence('test-evidence', view['question'], view['necessary_context'],
            'synthetic explicit answer only', capture, policy, intent.digest, intent.notice_ref, 'confirm')
        if change == 'locator': evidence = replace(evidence, source=replace(capture, locator='chat://foreign'))
        if change == 'limitations': evidence = replace(evidence, source=replace(capture, limitations='fixture'))
        if change == 'question': evidence = replace(evidence, question='Continue?')
        if change == 'context': evidence = replace(evidence, necessary_context='previous version')
        if change == 'empty_answer': evidence = replace(evidence, user_answer=' ')
        expected = 'CONSENT_SOURCE_UNAVAILABLE' if change in ('locator','limitations') else 'CONSENT_PRESENTATION_CHANGED'
        with pytest.raises(ApplicationError, match=expected):
            with source.guard_evidence(context, intent, evidence):
                pytest.fail('changed display/source accepted')
        with records[-1].begin(context.scope, 'read') as uow:
            assert uow.authorization.get_challenge('chat-pending')[1:] == ('pending', 0)


def test_actual_qa_entry_keeps_pending_without_original_review_gate(runtime, records):
    _, access, source, caller, _, _, _ = selected(records)
    with access.admit(caller, SCOPE, CAPS[0], request_id='presentation', trace_id='presentation') as context:
        displayed = source.prepare(access, context, 'chat-pending')
    with access.admit(caller, SCOPE, CAPS[1], request_id='reply', trace_id='reply') as context:
        # Synthetic Q&A only. A real attestor source is necessary but never
        # substitutes for the original complete current review/intent gates.
        with pytest.raises(ApplicationError, match='REVIEW_AUTHORITY_UNAVAILABLE'):
            source.record(access, None, context, challenge_id='chat-pending', nonce='test-chat-nonce',
                expected_version=0, evidence_id='synthetic-answer', question=displayed['question'],
                necessary_context=displayed['necessary_context'], user_answer='Synthetic explicit scoped answer.',
                disposition='confirm', message_refs=('synthetic-question','synthetic-answer'),
                captured_at=context.received_at)
        with records[-1].begin(context.scope, 'read') as uow:
            assert uow.authorization.get_challenge('chat-pending')[1:] == ('pending', 0)


def test_authenticated_original_query_exposes_selected_chat_display_without_click(runtime, records):
    import asyncio
    from ordessa_system_access_bindings.engineering_wire import EngineeringWireBinding, EngineeringApplicationPorts
    authority, _, source, caller, _, _, _ = selected(records)
    binding=EngineeringWireBinding(records[-1],authority,scope=SCOPE,
        application_ports_factory=lambda *_: EngineeringApplicationPorts(conversation_admission=source))
    value=asyncio.run(binding.invoke(CAPS[0], {'scope': {'realm_id':SCOPE.realm_id,'project_id':SCOPE.project_id},
        'requestId':'read-chat-presentation','parameters':{'challenge_id':'chat-pending'}},caller))
    display=value['data']['conversation_confirmation']
    assert display['available'] and display['state']=='pending'
    assert 'accept_artifact' in display['necessary_context'] and 'nonce' not in display
    history=asyncio.run(binding.invoke(CAPS[0], {'scope': {'realm_id':SCOPE.realm_id,'project_id':SCOPE.project_id},
        'requestId':'read-history','parameters':{'challenge_id':records[2].challenge_id}},caller))
    assert history['data']['conversation_confirmation']=={'available':False,'reason':'CHALLENGE_ALREADY_ANSWERED'}


def test_explicit_source_capture_holds_real_attestor_capability_and_revocation(runtime, records):
    from ordessa_interfaces.system_access.access_control.authentication import AccessError
    authority, access, source, caller, policy, _, _ = selected(records)
    with access.admit(caller, SCOPE, CAPS[1], request_id='capture', trace_id='capture') as context:
        capture = ConversationSource(source.locator, (), SOURCE_LIMITATION+'; message references unavailable',
            context.principal_id, context.received_at)
        with source.guard_capture(context, capture, policy):
            with pytest.raises(AccessError, match='AUTHORIZATION_GUARD_ACTIVE'):
                authority.replace_grants(())
    authority.replace_grants(())
    with pytest.raises(AccessError):
        with access.admit(caller, SCOPE, CAPS[1], request_id='revoked', trace_id='revoked'):
            pytest.fail('revoked Agent accepted')
