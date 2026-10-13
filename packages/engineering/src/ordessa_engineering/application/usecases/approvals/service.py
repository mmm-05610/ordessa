"""Conversation Notice/Intent/Challenge/Grant on the original command journal.

The configured product policy admits a registered main agent's truthful report,
not arbitrary ActorRef fields. Current method/reviewer guards span the commit.
Only the actual artifact acceptance branch is available in this first group.
"""
from ordessa_engineering.application.contracts.commands import read_set_projection
from contextlib import contextmanager, ExitStack
from dataclasses import asdict
import hashlib
from uuid import uuid4

from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.commands import (
    CommandContext, CommandResult, ReadSet, request_digest,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import (
    ConversationNotice, AuthorizationIntent, ChangeAuthorizationIntent, ConsentChallenge, ConversationEvidence, ApprovalGrant,
)
from ordessa_engineering.domain.approvals.consent_codec import decode_record
from ordessa_engineering.domain.approvals.implementation import ImplementationAuthorizationIntent
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
from ordessa_engineering.domain.common.models.values import Digest, validate_id, validate_text
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.reviews.models import ReviewSetKey
from ordessa_engineering.domain.reviews.rules import evaluate_gate
from ..reviews.service import _trust


_FIELDS = {
    'engineering.work.bind_inputs': {'run_id':{'type':'string'},'input_ref':{'type':'object'},
        'expected_row_digest':{'type':'object'},'expected_next_step_ordinal':{'type':'integer','minimum':0}},
    'engineering.work.record_dispatch_step': {'run_id':{'type':'string'},'attempt':{'type':'integer','minimum':1,'maximum':4096},'expected_row_digest':{'type':'object'},'expected_next_step_ordinal':{'type':'integer','minimum':0}},
    'engineering.work.record_command_step': {'run_id':{'type':'string'},'operation_request_id':{'type':'string'},'expected_row_digest':{'type':'object'},'expected_next_step_ordinal':{'type':'integer','minimum':0}},
    'engineering.work.start': {'run_id': {'type':'string'}, 'selection': {
        'type':'object', 'additionalProperties':False,
        'required':['proposal_ref','initial_slot_refs'], 'properties':{
            'proposal_ref':{'type':'object'},
            'initial_slot_refs':{'type':'object','maxProperties':128,
                                 'additionalProperties':{'type':'object'}}}}},
    'engineering.runs.resume': {'run_id': {'type':'string'}, 'expected_row_digest': {'type':'object'}, 'expected_condition_digest': {'type':'object'}, 'expected_next_step_ordinal': {'type':'integer','minimum':0}},
    'engineering.acceptance.adopt': {'submission_ref': {'type':'object'}, 'approval_ref': {'type':'object'},
        'expected_control_version': {'type':'integer','minimum':0},
        'targets': {'type':'array','minItems':1,'maxItems':4096,'items': {'type':'object','properties':
            {'target_ref':{'type':'object'},'expected':{'type':'object'}},
            'required':['target_ref','expected'],'additionalProperties':False}}},
    'engineering.changes.apply': {'approval_ref': {'type': 'object'}},
    'engineering.notices.publish': {'notice': {'type': 'object'}},
    'engineering.approvals.prepare_intent': {'intent': {'type': 'object'}},
    'engineering.approvals.request': {'intent_id': {'type': 'string'}, 'intent_digest': {'type': 'object'}},
    'engineering.approvals.record_conversation': {'challenge_id': {'type': 'string'}, 'nonce': {'type': 'string'},
        'expected_version': {'type': 'integer', 'minimum': 0}, 'evidence': {'type': 'object'}},
    'engineering.approvals.revoke': {'approval_ref': {'type': 'object'},
        'expected_version': {'type': 'integer', 'minimum': 0}, 'reason': {'type': 'string'}},
}
_SCHEMA_BYTES = {op: canonical_bytes({'$schema': 'https://json-schema.org/draft/2020-12/schema',
    '$id': f'urn:ordessa:engineering:operations:{op}:input:1', 'type': 'object',
    'properties': props, 'required': [name for name in props if not
        (op == 'engineering.work.start' and name == 'selection')],
    'additionalProperties': False}) for op, props in _FIELDS.items()}
SUPPORTED_APPROVAL_COMMANDS = tuple(_FIELDS)


def input_schema(operation):
    try:
        return decode_json(_SCHEMA_BYTES[operation])
    except KeyError:
        raise ApplicationError('OPERATION_UNAVAILABLE') from None


class ApprovalUseCases:
    def __init__(self, factory, access, admission=None, review_admission=None):
        self.factory, self.access, self.admission, self.review_admission = factory, access, admission, review_admission

    @staticmethod
    def _decode(value, cls):
        try:
            return decode_record(canonical_bytes(value), cls)
        except (ReferenceError, TypeError, ValueError):
            raise ApplicationError('INVALID_INPUT') from None

    def _input(self, operation, parameters, context, read_set):
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context, operation)
        try:
            parameters = decode_json(canonical_bytes(parameters))
            if len(canonical_bytes(parameters)) > 2 * 1024 * 1024 or not Draft202012Validator(input_schema(operation)).is_valid(parameters):
                raise ApplicationError('INVALID_INPUT')
        except (TypeError, ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        reads = ReadSet(context.scope, ()) if read_set is None else read_set
        if type(reads) is not ReadSet or reads.scope != context.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        schema = input_schema(operation)
        digest = request_digest(operation, context, parameters, read_set_projection(reads),
            input_schema_id=schema['$id'], input_schema_digest=Digest('sha256', hashlib.sha256(_SCHEMA_BYTES[operation]).hexdigest()),
            interface_version='1')
        return parameters, reads, digest

    def _replay(self, operation, context, digest):
        with self.factory.begin(context.scope, 'read') as uow:
            entry = uow.commands.get(context.key)
            if entry is None:
                return None
            if entry.operation != operation or entry.project_id != context.scope.project_id or entry.request_digest != digest:
                raise ApplicationError('REQUEST_IDENTITY_CONFLICT')
            return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)

    def _run(self, operation, context, reads, digest, mutate):
        with self.factory.begin(context.scope) as uow:
            reservation = uow.commands.reserve(context.key, project_id=context.scope.project_id,
                operation=operation, operation_id=str(uuid4()), request_digest=digest)
            entry = reservation.entry
            if not reservation.created:
                return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)
            uow.engineering.check_read_set(reads)
            result = mutate(uow)
            final = uow.commands.complete(context.key, expected_version=entry.version,
                result_bytes=canonical_bytes(result), state='completed')
            answer = CommandResult(uow.authority_id, final.operation_id, final.state, final.result_bytes)
            uow.commit()
            return answer

    def _admission(self):
        if self.admission is None:
            raise ApplicationError('CONFIRMATION_AUTHORITY_UNAVAILABLE')
        return self.admission

    @staticmethod
    def _resolve(uow, intent):
        plan = None
        if type(intent) is ChangeAuthorizationIntent:
            from ..changes.apply import resolve_change_intent
            plan = resolve_change_intent(uow, intent)
        elif type(intent) is ImplementationAuthorizationIntent:
            from ..packages.authorization import resolve_implementation_intent
            plan = resolve_implementation_intent(uow, intent)
        elif type(intent) is not AuthorizationIntent:
            raise ApplicationError('ACTION_NOT_AUTHORIZED')
        for target in intent.targets:
            uow.engineering.resolve_revision(target)
        notice = uow.authorization.get_notice(intent.notice_ref)
        uow.engineering.resolve_revision(notice.summary_ref)
        if set(notice.targets) != set(intent.targets) or notice.policy_ref != intent.policy_ref:
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        return plan

    @contextmanager
    def _gates(self, context, intent):
        if self.review_admission is None:
            raise ApplicationError('REVIEW_AUTHORITY_UNAVAILABLE')
        with self.factory.begin(context.scope, 'read') as uow:
            snapshots = tuple(uow.reviews.read_set(ReviewSetKey.for_requirement(req))
                              for req in intent.required_review_requirements)
        with ExitStack() as guards:
            decisions = []
            for requirement, snapshot in zip(intent.required_review_requirements, snapshots):
                records = tuple(item.record for item in snapshot.reviews if item.control.state == 'active')
                if any(r.identity.schema_version != 2 or r.raw_response_ref is None for r in records):
                    raise ApplicationError('REVIEW_RAW_RESPONSE_REQUIRED')
                for record in records:
                    guards.enter_context(self.review_admission.guard_plan(context, record.plan))
                current = guards.enter_context(self.review_admission.guard_trust(context, records))
                _trust(records, current)
                decision = evaluate_gate(requirement, snapshot, current)
                if not decision.satisfied:
                    raise ApplicationError(decision.code)
                decisions.append(decision)
            if (type(intent) is ImplementationAuthorizationIntent
                    and set(intent.supporting_review_refs) != {ref for d in decisions for ref in d.used_review_refs}):
                raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            yield tuple(decisions)

    @staticmethod
    def _check_gates(uow, decisions):
        for gate in decisions:
            uow.reviews.check_expectations(gate.review_set_expectations, gate.control_expectations)

    def publish_notice(self, parameters, context, *, read_set=None):
        op = 'engineering.notices.publish'
        value, reads, digest = self._input(op, parameters, context, read_set)
        notice = self._decode(value['notice'], ConversationNotice)
        if notice.scope != context.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        replay = self._replay(op, context, digest)
        if replay is not None:
            return replay
        def mutate(uow):
            for target in notice.targets + (notice.summary_ref,):
                uow.engineering.resolve_revision(target)
            uow.authorization.put_notice(notice)
            return {'notice_ref': asdict(notice.ref), 'source_trust_grade': notice.source.trust_grade}
        with self._admission().guard_capture(context, notice.source, notice.policy_ref):
            return self._run(op, context, reads, digest, mutate)

    def prepare_intent(self, parameters, context, *, read_set=None):
        op = 'engineering.approvals.prepare_intent'
        value, reads, digest = self._input(op, parameters, context, read_set)
        intent = self._decode(value['intent'], AuthorizationIntent)
        if intent.scope != context.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        replay = self._replay(op, context, digest)
        if replay is not None:
            return replay
        def mutate(uow):
            self._resolve(uow, intent)
            # Persist declared exact requirements, never an agent-provided pass.
            for requirement in intent.required_review_requirements:
                uow.reviews.ensure_requirement(requirement)
            uow.authorization.put_intent(intent)
            return {'intent_id': intent.intent_id, 'intent_digest': asdict(intent.digest), 'actions': list(intent.actions)}
        with self._admission().guard_intent(context, intent):
            return self._run(op, context, reads, digest, mutate)

    def request(self, parameters, context, *, read_set=None):
        op = 'engineering.approvals.request'
        value, reads, digest = self._input(op, parameters, context, read_set)
        replay = self._replay(op, context, digest)
        if replay is not None:
            return replay
        with self.factory.begin(context.scope, 'read') as uow:
            intent = uow.authorization.get_intent(value['intent_id'])
        if value['intent_digest'] != asdict(intent.digest):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        nonce = str(uuid4())
        challenge = ConsentChallenge(context.scope, str(uuid4()), intent.intent_id, intent.digest,
            intent.notice_ref.digest, Digest('sha256', hashlib.sha256(nonce.encode()).hexdigest()), intent.expires_at)
        def mutate(uow):
            if not intent.not_before <= context.received_at < intent.expires_at:
                raise ApplicationError('CONSENT_EXPIRED')
            if uow.authorization.get_intent(intent.intent_id) != intent:
                raise ApplicationError('CONSENT_BINDING_MISMATCH')
            self._resolve(uow, intent)
            self._check_gates(uow, decisions)
            uow.authorization.put_challenge(challenge)
            return {'challenge': asdict(challenge), 'state': 'pending', 'version': 0, 'nonce': nonce}
        with self._admission().guard_intent(context, intent), self._gates(context, intent) as decisions:
            return self._run(op, context, reads, digest, mutate)

    def record_conversation(self, parameters, context, *, read_set=None):
        op = 'engineering.approvals.record_conversation'
        value, reads, digest = self._input(op, parameters, context, read_set)
        evidence = self._decode(value['evidence'], ConversationEvidence)
        replay = self._replay(op, context, digest)
        if replay is not None:
            return replay
        with self.factory.begin(context.scope, 'read') as uow:
            challenge, _state, _version = uow.authorization.get_challenge(value['challenge_id'])
            intent = uow.authorization.get_intent(challenge.intent_id)
        validate_id(value['nonce'])
        if Digest('sha256', hashlib.sha256(value['nonce'].encode()).hexdigest()) != challenge.nonce_digest:
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        def mutate(uow):
            current, state, version = uow.authorization.get_challenge(challenge.challenge_id)
            if current != challenge or state != 'pending' or version != value['expected_version']:
                raise ApplicationError('CONSENT_CHALLENGE_CHANGED')
            if not intent.not_before <= context.received_at < min(intent.expires_at, challenge.expires_at):
                raise ApplicationError('CONSENT_EXPIRED')
            self._resolve(uow, intent)
            self._check_gates(uow, decisions)
            if not uow.authorization.put_receipt(challenge, evidence):
                raise ApplicationError('CONSENT_RECEIPT_REPLAY')
            if evidence.disposition == 'ambiguous':
                return {'state': 'pending', 'receipt_id': evidence.evidence_id, 'reason': 'NEEDS_CLARIFICATION'}
            if evidence.disposition == 'decline':
                uow.authorization.transition_challenge(challenge.challenge_id, version, 'cancelled')
                return {'state': 'declined', 'receipt_id': evidence.evidence_id}
            grant = ApprovalGrant(str(uuid4()), intent, challenge.challenge_id, evidence, context.received_at)
            uow.authorization.put_grant(grant)
            uow.authorization.transition_challenge(challenge.challenge_id, version, 'granted')
            return {'state': 'granted', 'approval_ref': asdict(grant.ref),
                    'receipt_id': evidence.evidence_id, 'source_trust_grade': evidence.source.trust_grade}
        with self._admission().guard_evidence(context, intent, evidence), self._gates(context, intent) as decisions:
            return self._run(op, context, reads, digest, mutate)

    def revoke(self, parameters, context, *, read_set=None):
        op = 'engineering.approvals.revoke'
        value, reads, digest = self._input(op, parameters, context, read_set)
        ref = decode_approval_ref(value['approval_ref'])
        validate_text(value['reason'])
        replay = self._replay(op, context, digest)
        if replay is not None:
            return replay
        def mutate(uow):
            uow.authorization.revoke(ref, value['expected_version'], context.received_at, value['reason'], str(uuid4()))
            return {'approval_ref': asdict(ref), 'state': 'revoked', 'version': value['expected_version'] + 1}
        return self._run(op, context, reads, digest, mutate)
