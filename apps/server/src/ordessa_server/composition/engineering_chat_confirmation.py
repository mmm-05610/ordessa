"""Main Agent Q&A on the original Notice/Intent/Challenge/Grant owners.

The configured Agent attests that it displayed these exact bytes and captured
the verbatim answer. This is the selected product policy's chat provenance,
not independent human authentication. No answer or permission is inferred.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import (
    ConversationEvidence, ConversationSource, CapturedInstructionEvidence,
)
from ordessa_engineering.domain.approvals.consent import WorkPackageNotice
from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorizationIntent
from ordessa_engineering.domain.common.models.values import utc_instant
from ordessa_engineering.application.usecases.approvals.service import ApprovalUseCases

from .engineering_human_source import SOURCE_LIMITATION


HUMAN_PRESENTATION_CONTRACT = 'ordessa.work-package-chat-human/1'
CANONICAL_PRESENTATION_CONTRACT = 'ordessa.product-chat-confirmation/1'
INSTRUCTION_CONTRACT = 'ordessa.captured-user-instruction/1'
INSTRUCTION_BINDING_LIMITATION = (
    'new Work/Intent/Notice identifiers registered by main agent; '
    'not presented to the user as new question and answer')
_PRESENTATION_MARKER = 'presentation_contract='


@dataclass(frozen=True)
class FrozenChatPresentation:
    """A trusted composition selects a renderer for one immutable Intent.

    This is not wire input or an equivalence assertion. The renderer is a
    deployment port; captured text must still equal its output byte for byte.
    """
    intent: object
    notice: object
    presented_at: str
    renderer: object
    contract_id: str = HUMAN_PRESENTATION_CONTRACT

    def __post_init__(self):
        if (type(self.intent) is not WorkPackageAuthorizationIntent
                or type(self.notice) is not WorkPackageNotice
                or self.contract_id != HUMAN_PRESENTATION_CONTRACT
                or not callable(self.renderer)
                or self.intent.notice_ref != self.notice.ref
                or self.intent.policy_ref != self.notice.policy_ref
                or self.intent.authorization != self.notice.authorization):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        utc_instant(self.presented_at)
        if not self.intent.not_before <= self.presented_at < self.intent.expires_at:
            raise ApplicationError('CONSENT_EXPIRED')

    def render(self, intent, notice):
        if intent != self.intent or notice != self.notice:
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        value = self.renderer(intent, notice, presented_at=self.presented_at)
        if (type(value) is not dict or set(value) != {'question', 'necessary_context'}
                or any(type(text) is not str or not text.strip() for text in value.values())
                or value['question'].count(value['necessary_context']) != 1):
            raise ApplicationError('CONSENT_PRESENTATION_CHANGED')
        return value


@dataclass(frozen=True)
class FrozenChatInstruction:
    """Trusted composition binds unchanged captured instructions to one Work.

    The capture may predate this intent. Its source identity and capture time
    stay unchanged; registering a new mechanical binding is not a new reply.
    No wire input can select or replace this binding.
    """
    intent: WorkPackageAuthorizationIntent
    notice: WorkPackageNotice
    instruction: str
    business_context: str
    source: ConversationSource

    def __post_init__(self):
        if (type(self.intent) is not WorkPackageAuthorizationIntent
                or type(self.notice) is not WorkPackageNotice
                or type(self.source) is not ConversationSource
                or type(self.instruction) is not str or not self.instruction.strip()
                or type(self.business_context) is not str or not self.business_context.strip()
                or self.intent.notice_ref != self.notice.ref
                or self.intent.policy_ref != self.notice.policy_ref
                or self.intent.authorization != self.notice.authorization
                or self.notice.source != self.source
                or self.notice.actual_text != self.instruction):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        if (SOURCE_LIMITATION not in self.source.limitations
                or INSTRUCTION_BINDING_LIMITATION not in self.source.limitations):
            raise ApplicationError('CONSENT_SOURCE_UNAVAILABLE')

    def context(self):
        return canonical_bytes({
            'contract': INSTRUCTION_CONTRACT,
            'original_business_context': self.business_context,
            'binding_origin': 'registered-main-agent',
            'new_question_or_answer_presented': False,
            'intent': asdict(self.intent), 'notice': asdict(self.notice),
            'source_limitation': SOURCE_LIMITATION,
        }).decode('utf-8')


def confirmation_presentation(intent, notice):
    """Exact original objects/actions; a review answer cannot authorize them."""
    if notice.ref != intent.notice_ref or notice.policy_ref != intent.policy_ref:
        raise ApplicationError('CONSENT_BINDING_MISMATCH')
    return {
        'question': '是否批准下列冻结对象及动作范围？请明确答复；审核通过不等于批准实施。',
        'necessary_context': canonical_bytes({
            'contract': 'ordessa.product-chat-confirmation/1',
            'intent': asdict(intent), 'notice': asdict(notice),
            'source_limitation': SOURCE_LIMITATION,
        }).decode('utf-8'),
    }


class MainAgentChatConfirmation:
    """Selected locator plus original policy/attestor/intent admission.

    Trusted deployment selects this object; wire cannot choose its locator or
    admission. A registered Agent supplies actual Q&A and its classification,
    disclosing the shared bearer limitation. Original gates, nonce, expiry,
    receipt deduplication and COMMIT are still ApprovalUseCases' responsibility.
    """
    def __init__(self, factory, admission, *, conversation_locator, presentation_binding=None,
                 instruction_binding=None):
        if (factory is None or admission is None or type(conversation_locator) is not str
                or not conversation_locator.strip()):
            raise ApplicationError('CONFIRMATION_AUTHORITY_UNAVAILABLE')
        self.factory, self.admission = factory, admission
        self.locator = conversation_locator
        self.policy_ref = admission.policy_ref
        self.evidence_kinds = getattr(admission, 'evidence_kinds', ('question_answer',))
        if presentation_binding is not None and (
                type(presentation_binding) is not FrozenChatPresentation
                or presentation_binding.intent.policy_ref != self.policy_ref):
            raise ApplicationError('CONFIRMATION_AUTHORITY_UNAVAILABLE')
        self.presentation_binding = presentation_binding
        if instruction_binding is not None and (
                presentation_binding is not None
                or type(instruction_binding) is not FrozenChatInstruction
                or instruction_binding.intent.policy_ref != self.policy_ref
                or instruction_binding.source.locator != self.locator
                or 'captured_instruction' not in self.evidence_kinds):
            raise ApplicationError('CONFIRMATION_AUTHORITY_UNAVAILABLE')
        self.instruction_binding = instruction_binding

    def _instruction(self, intent, notice):
        binding = self.instruction_binding
        if binding is None or intent != binding.intent or notice != binding.notice:
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        return binding

    def _presentation(self, intent, notice):
        binding = self.presentation_binding
        # Match the stable id first. A changed scope, digest or notice for this
        # selected id must refuse; it cannot choose the historical encoding.
        if binding is not None and intent.intent_id == binding.intent.intent_id:
            return binding.render(intent, notice), binding.contract_id
        return confirmation_presentation(intent, notice), CANONICAL_PRESENTATION_CONTRACT

    @staticmethod
    def _check_presentation_contract(source, contract):
        markers = [part.strip() for part in source.limitations.split(';')
                   if part.strip().startswith(_PRESENTATION_MARKER)]
        expected = ([] if contract == CANONICAL_PRESENTATION_CONTRACT else
                    [_PRESENTATION_MARKER + contract])
        if markers != expected:
            raise ApplicationError('CONSENT_PRESENTATION_CHANGED')

    @contextmanager
    def guard_capture(self, context, source, policy_ref):
        if (source.locator != self.locator or SOURCE_LIMITATION not in source.limitations
                or not source.message_refs and 'message references unavailable' not in source.limitations):
            raise ApplicationError('CONSENT_SOURCE_UNAVAILABLE')
        with self.admission.guard_capture(context, source, policy_ref):
            yield

    @contextmanager
    def guard_intent(self, context, intent):
        with self.admission.guard_intent(context, intent):
            yield

    @contextmanager
    def guard_evidence(self, context, intent, evidence):
        with self.guard_capture(context, evidence.source, evidence.policy_ref), self.admission.guard_evidence(context, intent, evidence):
            with self.factory.begin(context.scope, 'read') as uow:
                notice = uow.authorization.get_notice(intent.notice_ref)
            if type(evidence) is CapturedInstructionEvidence:
                binding = self._instruction(intent, notice)
                if (evidence.source != binding.source or evidence.instruction != binding.instruction
                        or evidence.necessary_context != binding.context()):
                    raise ApplicationError('CONSENT_SOURCE_CHANGED')
                yield
                return
            if (self.instruction_binding is not None
                    and intent.intent_id == self.instruction_binding.intent.intent_id):
                raise ApplicationError('CONSENT_EVIDENCE_KIND_UNSUPPORTED')
            presentation, contract = self._presentation(intent, notice)
            self._check_presentation_contract(evidence.source, contract)
            if contract == HUMAN_PRESENTATION_CONTRACT and not (
                    self.presentation_binding.presented_at <= evidence.source.captured_at
                    < intent.expires_at):
                raise ApplicationError('INVALID_CONSENT_TIME')
            if (evidence.question != presentation['question']
                    or evidence.necessary_context != presentation['necessary_context']
                    or not evidence.user_answer.strip()):
                raise ApplicationError('CONSENT_PRESENTATION_CHANGED')
            yield

    def prepare(self, access, context, challenge_id):
        """Read original pending challenge; returns no approval or nonce."""
        access.require(context, 'engineering.approvals.get_challenge')
        with self.factory.begin(context.scope, 'read') as uow:
            challenge, state, version = uow.authorization.get_challenge(challenge_id)
            intent = uow.authorization.get_intent(challenge.intent_id)
            notice = uow.authorization.get_notice(intent.notice_ref)
        if state != 'pending' or challenge.binding_digest != intent.digest:
            raise ApplicationError('CONSENT_CHALLENGE_CHANGED')
        with self.guard_intent(context, intent):
            if (self.instruction_binding is not None
                    and intent.intent_id == self.instruction_binding.intent.intent_id):
                binding = self._instruction(intent, notice)
                return {'evidence_kind': 'captured_instruction', 'requires_user_reply': False,
                        'instruction': binding.instruction, 'necessary_context': binding.context(),
                        'challenge_id': challenge_id, 'expected_version': version,
                        'intent_digest': asdict(intent.digest), 'state': state}
            presentation, contract = self._presentation(intent, notice)
            display = (presentation['question'] if contract == HUMAN_PRESENTATION_CONTRACT else
                       presentation['question'] + '\n\n' + presentation['necessary_context'])
            return {**presentation, 'presentation_contract': contract, 'display_text': display,
                'challenge_id': challenge_id, 'expected_version': version,
                'intent_digest': asdict(intent.digest), 'state': state}

    def project_confirmation(self, access, context, original_challenge):
        """Optional original query projection; answered history is not reasked."""
        if original_challenge['state'] != 'pending':
            return {'available': False, 'reason': 'CHALLENGE_ALREADY_ANSWERED'}
        prepared = self.prepare(access, context, original_challenge['challenge']['challenge_id'])
        if prepared['expected_version'] != original_challenge['version']:
            raise ApplicationError('CONSENT_CHALLENGE_CHANGED')
        return {'available': True, **prepared}

    def record(self, access, review_admission, context, *, challenge_id, nonce,
               expected_version, evidence_id, question, necessary_context,
               user_answer, disposition, message_refs, captured_at):
        """Registered Agent reports actual Q&A once via the original command.

        disposition is the Agent's explicit assessment (confirm/decline/
        ambiguous); it is never guessed from a generic 'continue', silence or
        an earlier review. The captured text remains verbatim in the receipt.
        """
        if type(message_refs) is not tuple or type(user_answer) is not str or not user_answer.strip():
            raise ApplicationError('CONSENT_SOURCE_UNAVAILABLE')
        limitations = SOURCE_LIMITATION
        if not message_refs:
            limitations += '; message references unavailable'
        with self.factory.begin(context.scope, 'read') as uow:
            challenge, _, _ = uow.authorization.get_challenge(challenge_id)
            intent = uow.authorization.get_intent(challenge.intent_id)
            notice = uow.authorization.get_notice(intent.notice_ref)
        _, contract = self._presentation(intent, notice)
        if contract != CANONICAL_PRESENTATION_CONTRACT:
            limitations += '; ' + _PRESENTATION_MARKER + contract
        evidence = ConversationEvidence(evidence_id, question, necessary_context, user_answer,
            ConversationSource(self.locator, message_refs, limitations, context.principal_id, captured_at),
            self.policy_ref, intent.digest, intent.notice_ref, disposition)
        return ApprovalUseCases(self.factory, access, self, review_admission).record_conversation({
            'challenge_id': challenge_id, 'nonce': nonce, 'expected_version': expected_version,
            'evidence': asdict(evidence)}, context)

    def record_instruction(self, access, review_admission, context, *, challenge_id, nonce,
                           expected_version, evidence_id, disposition):
        """Record the already captured instruction, never manufacture a Q&A.

        The registered main Agent supplies its explicit disposition. Original
        request admission, current review/intent gates, nonce, expiry, source
        deduplication and Grant creation remain in ApprovalUseCases.
        """
        access.require(context, 'engineering.approvals.record_conversation')
        with self.factory.begin(context.scope, 'read') as uow:
            challenge, _, _ = uow.authorization.get_challenge(challenge_id)
            intent = uow.authorization.get_intent(challenge.intent_id)
            notice = uow.authorization.get_notice(intent.notice_ref)
        binding = self._instruction(intent, notice)
        evidence = CapturedInstructionEvidence(
            evidence_id, binding.instruction, binding.context(), binding.source,
            self.policy_ref, intent.digest, intent.notice_ref, disposition)
        return ApprovalUseCases(self.factory, access, self, review_admission).record_conversation({
            'challenge_id': challenge_id, 'nonce': nonce, 'expected_version': expected_version,
            'evidence': asdict(evidence)}, context)
