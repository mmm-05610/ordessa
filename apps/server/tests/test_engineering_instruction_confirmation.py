"""Actual instance attestor and temporary Work owners; synthetic instruction only.

No real Slack source, user Grant, Unit, model, credential or history DB is used.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ENGINEERING_TESTS = Path(__file__).resolve().parents[3] / 'packages/engineering/tests/application'
if str(ENGINEERING_TESTS) not in sys.path:
    sys.path.insert(0, str(ENGINEERING_TESTS))
from test_instruction_approvals import instruction_case, INSTRUCTION, BUSINESS_CONTEXT  # noqa: E402
from test_real_source_chain import PRINCIPAL, SCOPE as DOMAIN_SCOPE  # noqa: E402

from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import (
    CapturedInstructionEvidence, ConversationEvidence, ConversationSource, WorkPackageNotice,
)
from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorizationIntent
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_infrastructure.encoding import decode_json
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessError, AccessGrant, InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_server.composition.conversation_attestor import RegisteredMainAgentAttestor
from ordessa_server.composition.engineering_chat_confirmation import (
    FrozenChatInstruction, MainAgentChatConfirmation, INSTRUCTION_BINDING_LIMITATION,
)
from ordessa_server.composition.engineering_human_source import SOURCE_LIMITATION

CAPS = ('engineering.notices.publish', 'engineering.approvals.prepare_intent',
        'engineering.approvals.request', 'engineering.approvals.get_challenge',
        'engineering.approvals.record_conversation', 'engineering.conversation.attest')


def _instant(value):
    return value.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


@contextmanager
def selected(tmp_path):
    with instruction_case(tmp_path) as f:
        scope = Scope(DOMAIN_SCOPE.realm_id, DOMAIN_SCOPE.project_id)
        authority = InstanceAccessAuthority(lambda: 'synthetic-instruction-token',
            principal_id=PRINCIPAL, legacy_principal=None, grants=(AccessGrant(scope, CAPS),))
        access = EngineeringCommandAccess(authority)
        caller = authority.authenticate('Bearer synthetic-instruction-token')
        now = datetime.now(timezone.utc)
        source = ConversationSource('chat://synthetic-instruction-thread',
            ('synthetic-user-directive-1', 'synthetic-user-directive-2'),
            SOURCE_LIMITATION + '; ' + INSTRUCTION_BINDING_LIMITATION,
            PRINCIPAL, _instant(now - timedelta(hours=2)))
        authorization = replace(f['authorization'], not_before=_instant(now - timedelta(hours=1)),
                                expires_at=_instant(now + timedelta(hours=1)))
        notice = WorkPackageNotice('selected-instruction-notice', authorization, INSTRUCTION,
                                   source, f['policy'])
        intent = WorkPackageAuthorizationIntent(authorization, notice.ref, f['policy'])
        frozen = FrozenChatInstruction(intent, notice, INSTRUCTION, BUSINESS_CONTEXT, source)
        attestor = RegisteredMainAgentAttestor(access, scope=scope, principal_id=PRINCIPAL,
                                               selected_policy_ref=f['policy'])
        admission = ConversationAdmission(f['raw_policy'], f['policy'], attestor_guard=attestor.guard,
                                         intent_guard=f['implementation_admission'].guard_intent)
        chat = MainAgentChatConfirmation(f['factory'], admission,
            conversation_locator=source.locator, instruction_binding=frozen)
        service = EngineeringService(f['factory'], access,
            review_admission=f['env'].admission, blobs=f['env'].blobs, conversation_admission=chat,
            method_guard=f['env'].controls, source_materials=f['env'].materials,
            source_review_bindings=f['env'].bindings)
        case = dict(f, source=source, notice=notice, intent=intent, authority=authority,
                    access=access, caller=caller, wire_scope=scope, chat=chat, frozen=frozen,
                    service=service, admission=admission)
        for operation, parameters, request_id in (
            (CAPS[0], {'notice': asdict(notice)}, 'selected-notice'),
            (CAPS[1], {'intent': asdict(intent)}, 'selected-intent'),
            (CAPS[2], {'intent_id': intent.intent_id, 'intent_digest': asdict(intent.digest)}, 'selected-challenge'),
        ):
            with access.admit(caller, scope, operation, request_id=request_id, trace_id=request_id) as ctx:
                result = asyncio.run(service.execute(operation, parameters, ctx))
        case['challenge'] = result
        yield case


def _record(case, *, review_admission='original', nonce=None, request_id='selected-record'):
    challenge = case['challenge'].result
    reviews = case['env'].admission if review_admission == 'original' else review_admission
    with case['access'].admit(case['caller'], case['wire_scope'], CAPS[4],
                             request_id=request_id, trace_id=request_id) as ctx:
        return case['chat'].record_instruction(case['access'], reviews, ctx,
            challenge_id=challenge['challenge']['challenge_id'], nonce=nonce or challenge['nonce'],
            expected_version=0, evidence_id='selected-instruction-evidence', disposition='confirm')


def _counts(case):
    db = case['env'].library._connection
    return tuple(db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                 for table in ('eng_approval_grants', 'eng_consent_receipts'))


def test_captured_instruction_registers_without_a_new_question_on_original_owners(tmp_path):
    with selected(tmp_path) as c:
        with c['access'].admit(c['caller'], c['wire_scope'], CAPS[3],
                               request_id='selected-read', trace_id='selected-read') as ctx:
            view = c['chat'].prepare(c['access'], ctx, c['challenge'].result['challenge']['challenge_id'])
        assert view['requires_user_reply'] is False
        assert view['evidence_kind'] == 'captured_instruction'
        assert 'question' not in view and 'user_answer' not in view
        assert view['instruction'] == INSTRUCTION
        declared = decode_json(view['necessary_context'].encode())
        assert declared['new_question_or_answer_presented'] is False
        assert declared['binding_origin'] == 'registered-main-agent'
        result = _record(c)
        assert result.result['state'] == 'granted'
        ref = decode_approval_ref(result.result['approval_ref'])
        with c['factory'].begin(DOMAIN_SCOPE, 'read') as uow:
            grant = uow.authorization.get_grant(ref)
            budget = uow.authorization.action_budget(ref)
        assert type(grant.evidence) is CapturedInstructionEvidence
        assert grant.evidence.instruction == INSTRUCTION
        assert grant.evidence.source == c['source']
        assert grant.evidence.source.captured_at < c['intent'].not_before
        assert grant.evidence.binding_origin == 'registered-main-agent'
        assert 'question' not in asdict(grant.evidence) and 'user_answer' not in asdict(grant.evidence)
        assert [row['limit'] for row in budget['actions']] == [1, 1]
        assert [row['consumed'] for row in budget['actions']] == [0, 0]
        assert _record(c) == result
        assert _counts(c) == (1, 1)


def test_source_binding_rejects_changed_text_context_old_qa_source_and_kind(tmp_path):
    with selected(tmp_path) as c:
        with c['access'].admit(c['caller'], c['wire_scope'], CAPS[4],
                               request_id='source-negatives', trace_id='source-negatives') as ctx:
            ev = CapturedInstructionEvidence('negative-evidence', INSTRUCTION, c['frozen'].context(),
                c['source'], c['policy'], c['intent'].digest, c['notice'].ref, 'confirm')
            changes = (
                (replace(ev, instruction='Changed instruction.'), 'CONSENT_SOURCE_CHANGED'),
                (replace(ev, necessary_context='Invented business scope.'), 'CONSENT_SOURCE_CHANGED'),
                (replace(ev, source=replace(ev.source, message_refs=('synthetic-old-consumed-qa',))), 'CONSENT_SOURCE_CHANGED'),
                (replace(ev, source=replace(ev.source, captured_at=c['intent'].not_before)), 'CONSENT_SOURCE_CHANGED'),
                (replace(ev, source=replace(ev.source, locator='chat://foreign')), 'CONSENT_SOURCE_UNAVAILABLE'),
                (replace(ev, source=replace(ev.source, attestor_id='foreign-attestor')), 'UNTRUSTED_CONSENT_ATTESTOR'),
                (replace(ev, intent_digest=Digest('sha256', '0' * 64)), 'CONSENT_BINDING_MISMATCH'),
            )
            for changed, code in changes:
                with pytest.raises(ApplicationError, match=code):
                    with c['chat'].guard_evidence(ctx, c['intent'], changed):
                        pytest.fail('changed instruction source admitted')
            qa = ConversationEvidence('invented-qa', 'Invented new question?', 'Invented context.',
                'Synthetic copied reply.', c['source'], c['policy'], c['intent'].digest, c['notice'].ref, 'confirm')
            with pytest.raises(ApplicationError, match='CONSENT_EVIDENCE_KIND_UNSUPPORTED'):
                with c['chat'].guard_evidence(ctx, c['intent'], qa):
                    pytest.fail('instruction was relabelled as new Q&A')
        assert _counts(c) == (0, 0)


def test_original_nonce_review_gate_and_real_attestor_revocation_are_preserved(tmp_path):
    with selected(tmp_path) as c:
        with pytest.raises(ApplicationError, match='CONSENT_BINDING_MISMATCH'):
            _record(c, nonce='synthetic-wrong-nonce', request_id='wrong-nonce')
        with pytest.raises(ApplicationError, match='REVIEW_AUTHORITY_UNAVAILABLE'):
            _record(c, review_admission=None, request_id='missing-reviews')
        assert _counts(c) == (0, 0)
        c['authority'].replace_grants((AccessGrant(c['wire_scope'], tuple(cap for cap in CAPS
                                            if cap != 'engineering.conversation.attest')),))
        with pytest.raises(AccessError, match='AUTHORIZATION_STALE'):
            _record(c, request_id='stale-principal')
        c['caller'] = c['authority'].authenticate('Bearer synthetic-instruction-token')
        with pytest.raises(ApplicationError, match='ACCESS_DENIED'):
            _record(c, request_id='revoked-attestor')
        assert _counts(c) == (0, 0)
