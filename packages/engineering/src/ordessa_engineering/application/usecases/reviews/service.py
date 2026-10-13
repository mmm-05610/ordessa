"""Review commands use the original journal/UoW and injected authority ports.

Verification and acquisition of original-owner guards happen outside SQLite.
Guards must hold the admitted method/trust/control facts through commit without
network, model, file IO or waiting inside the business transaction. Production
composition is deliberately unavailable until those original owners are bound.
"""
from ordessa_engineering.application.contracts.commands import read_set_projection
from dataclasses import asdict, replace
from contextlib import ExitStack
import hashlib
from typing import Protocol
from uuid import uuid4

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.reviews.refs import (ReviewRef)
from ....domain.common.models.values import (Digest)
from ....domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.reviews.identity import (RecordIdentity)
from ....domain.common.mechanisms.codec import (canonical_value)
from ....domain.reviews.models import (
    CurrentReviewTrust,
    ReviewControlExpectation,
    ReviewPlan,
    ReviewRecord,
    ReviewRequestState,
    ReviewRequirement,
    ReviewSetExpectation,
    ReviewSetKey,
)
from ....domain.common.models.values import (MAX_VERSION)
from ....domain.reviews.rules import evaluate_gate
from ordessa_engineering.application.contracts.commands import CommandContext, CommandResult, ReadSet, request_digest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.access import BlobStorePort
from ordessa_engineering.application.contracts.repositories import CommandAccessPort
from ordessa_engineering.application.contracts.transactions import UoWFactory

_MAX_RESPONSE_BYTES = 2097152


class ReviewAdmissionPort(Protocol):
    """Trusted composition, not a public bool or caller-supplied evidence DTO.

    guard_plan resolves the actual published method/criteria/applicability rules.
    verify_response reads a verified durable BlobRef and binds its bytes to the frozen plan/request and
    obtains reviewer and NA proof facts from their original owners. guard_trust
    revalidates every record's original verifier/roles/capability/trust version.
    No production implementation is claimed by this contract.
    """
    def guard_plan(self, context: CommandContext, plan: ReviewPlan): ...
    def verify_response(self, context: CommandContext, plan: ReviewPlan,
                        request: ReviewRequestState, raw_response: BlobRef) -> ReviewRecord: ...
    def guard_trust(self, context: CommandContext, records: tuple[ReviewRecord, ...]): ...


class ReviewControlPort(Protocol):
    """Acquire original-owner control permission; yield immutable evidence."""
    def guard_control(self, context: CommandContext,
                      expectations: tuple[ReviewControlExpectation, ...], *,
                      state: str, reason: str, replacement_ref: ReviewRef | None): ...


_FIELDS = {
    'engineering.reviews.request': ('plan',),
    'engineering.reviews.plan': ('plan',),
    'engineering.reviews.record': ('review_id', 'request_version', 'fence', 'raw_response_digest'),
    'engineering.reviews.withdraw': ('review_id', 'request_version', 'fence'),
    'engineering.reviews.control': ('expectations', 'state', 'reason', 'replacement_ref'),
}
_SCHEMA_BYTES = {op: canonical_bytes({'$schema': 'https://json-schema.org/draft/2020-12/schema',
    '$id': f'urn:ordessa:engineering:operations:{op}:input:1', 'type': 'object',
    'required': list(names), 'properties': {name: {} for name in names}, 'additionalProperties': False})
    for op, names in _FIELDS.items()}
_REFUSALS = frozenset({'NOT_FOUND', 'SCOPE_MISMATCH', 'READ_SET_CHANGED', 'REVIEW_SET_CHANGED',
    'REVIEW_CONTROL_CHANGED', 'REVIEW_REQUEST_CHANGED', 'REVIEW_STALE', 'REQUIREMENT_CONFLICT',
    'REVIEW_IDENTITY_CONFLICT', 'VERSION_EXHAUSTED', 'UNSUPPORTED_REFERENCE_KIND',
    'UNSUPPORTED_CLAIM', 'REVIEW_SCHEMA_REQUIRED', 'REVIEW_RAW_RESPONSE_INVALID', 'MATERIAL_LIMIT'})


def input_schema(operation):
    try:
        return canonical_value(_SCHEMA_BYTES[operation])
    except KeyError:
        raise ApplicationError('OPERATION_UNAVAILABLE') from None


def command_input_schema(operation):
    """Finite UTF-8 transport envelope; journal retains its original digest fields."""
    if operation != 'engineering.reviews.record':
        return input_schema(operation)
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
        '$id':'urn:ordessa:engineering:operations:engineering.reviews.record:command-input:1',
        'type':'object','additionalProperties':False,
        'required':['review_id','request_version','fence','raw_response_utf8'],
        'properties':{'review_id':{'type':'string','minLength':1},
            'request_version':{'type':'integer','minimum':0,'maximum':MAX_VERSION},
            'fence':{'type':'integer','minimum':1,'maximum':MAX_VERSION},
            'raw_response_utf8':{'type':'string','maxLength':_MAX_RESPONSE_BYTES}}}


def _input(value):
    try:
        return canonical_value(canonical_bytes(value))
    except (ReferenceError, TypeError, ValueError, RecursionError, OverflowError):
        raise ApplicationError('INVALID_INPUT') from None


def _trust(records, admitted):
    if type(admitted) is not tuple or any(type(item) is not CurrentReviewTrust for item in admitted):
        raise ApplicationError('REVIEW_TRUST_UNAVAILABLE')
    expected = {record.ref: (record.reviewer_evidence.verifier_id, record.reviewer_evidence.trust_version)
                for record in records}
    if len({item.review_ref for item in admitted}) != len(admitted):
        raise ApplicationError('UNTRUSTED_REVIEWER')
    actual = {item.review_ref: (item.verifier_id, item.trust_version) for item in admitted}
    if actual != expected:
        raise ApplicationError('UNTRUSTED_REVIEWER')
    return admitted


class ReviewUseCases:
    def __init__(self, factory: UoWFactory, access: CommandAccessPort | None,
                 admission: ReviewAdmissionPort | None, control: ReviewControlPort | None = None,
                 *, blobs: BlobStorePort | None = None):
        self.factory, self.access = factory, access
        self.admission, self.control = admission, control
        self.blobs = blobs

    def _authorize(self, context, operation):
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context, operation)

    def _admission(self):
        if self.admission is None:
            raise ApplicationError('REVIEW_AUTHORITY_UNAVAILABLE')
        return self.admission

    @staticmethod
    def _reads(context, reads):
        result = ReadSet(context.scope, ()) if reads is None else reads
        if type(result) is not ReadSet or result.scope != context.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        return result

    @staticmethod
    def _digest(operation, context, parameters, reads):
        schema = canonical_value(_SCHEMA_BYTES[operation])
        return request_digest(operation, context, parameters, read_set_projection(reads),
            input_schema_id=schema['$id'], input_schema_digest=Digest('sha256',
            hashlib.sha256(_SCHEMA_BYTES[operation]).hexdigest()), interface_version='1')

    def _replay(self, operation, parameters, context, reads):
        digest = self._digest(operation, context, parameters, reads)
        with self.factory.begin(context.scope, 'read') as uow:
            entry = uow.commands.get(context.key)
            if entry is None:
                return None
            if (entry.project_id != context.scope.project_id or entry.operation != operation
                    or entry.request_digest != digest):
                raise ApplicationError('REQUEST_IDENTITY_CONFLICT')
            return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)

    def _run(self, operation, parameters, context, reads, mutate):
        digest = self._digest(operation, context, parameters, reads)
        with self.factory.begin(context.scope) as uow:
            reservation = uow.commands.reserve(context.key, project_id=context.scope.project_id,
                operation=operation, operation_id=str(uuid4()), request_digest=digest)
            entry = reservation.entry
            if not reservation.created:
                return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)
            state = 'completed'
            try:
                with uow.isolate():
                    uow.engineering.check_read_set(reads)
                    result = mutate(uow)
            except ReferenceError:
                state, result = 'rejected', {'code': 'INVALID_INPUT'}
            except ApplicationError as exc:
                if exc.code not in _REFUSALS:
                    raise
                state, result = 'rejected', {'code': exc.code}
            final = uow.commands.complete(context.key, expected_version=entry.version,
                result_bytes=canonical_bytes(result), state=state)
            answer = CommandResult(uow.authority_id, final.operation_id, final.state, final.result_bytes)
            uow.commit()
            return answer

    def plan(self, plan: ReviewPlan, context: CommandContext, *, read_set=None):
        return self._plan('engineering.reviews.plan', plan, context, read_set=read_set)

    def request(self, parameters, context: CommandContext, *, read_set=None):
        self._authorize(context, 'engineering.reviews.request')
        from ....domain.reviews.codec import decode_plan
        try:
            parameters = _input(parameters)
            if type(parameters) is not dict or set(parameters) != {'plan'}:
                raise ApplicationError('INVALID_INPUT')
            plan = decode_plan(canonical_bytes(parameters['plan']))
        except (ReferenceError, TypeError, ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        return self._plan('engineering.reviews.request', plan, context, read_set=read_set)

    def _plan(self, operation, plan, context, *, read_set=None):
        self._authorize(context, operation)
        if type(plan) is not ReviewPlan or plan.scope != context.scope:
            raise ApplicationError('INVALID_INPUT')
        # Reconstruct through the strict codec before any authority callback.
        from ....domain.reviews.codec import encode_plan, decode_plan
        plan = decode_plan(encode_plan(plan))
        reads = self._reads(context, read_set)
        parameters = _input({'plan': asdict(plan)})
        replay = self._replay(operation, parameters, context, reads)
        if replay is not None:
            return replay
        with self._admission().guard_plan(context, plan):
            return self._run(operation, parameters, context, reads,
                lambda uow: {'request': asdict(uow.reviews.create_plan(plan))})

    @staticmethod
    def _request_arguments(review_id, expected_version, fence):
        from ....domain.common.models.values import (validate_id)
        try:
            validate_id(review_id)
        except (ReferenceError, TypeError, ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        if (type(expected_version) is not int or not 0 <= expected_version <= MAX_VERSION
                or type(fence) is not int or not 1 <= fence <= MAX_VERSION):
            raise ApplicationError('INVALID_INPUT')

    def record_command(self, parameters, context: CommandContext, *, read_set=None):
        """Record an exact UTF-8 envelope through the original response owner.

        Caller cannot supply a Plan, reviewer evidence, observations or verdict
        separately. Production admission verifies the original durable envelope.
        """
        self._authorize(context, 'engineering.reviews.record')
        parameters = _input(parameters)
        if (type(parameters) is not dict or set(parameters) !=
                {'review_id', 'request_version', 'fence', 'raw_response_utf8'}
                or type(parameters['raw_response_utf8']) is not str
                or len(parameters['raw_response_utf8']) > _MAX_RESPONSE_BYTES):
            raise ApplicationError('INVALID_INPUT')
        try:
            raw = parameters['raw_response_utf8'].encode('utf-8', errors='strict')
        except UnicodeError:
            raise ApplicationError('INVALID_INPUT') from None
        return self.record_response(parameters['review_id'], raw, context,
            expected_request_version=parameters['request_version'], fence=parameters['fence'],
            read_set=read_set)

    def record_response(self, review_id: str, raw_response: bytes, context: CommandContext, *,
                        expected_request_version: int, fence: int, read_set=None):
        operation = 'engineering.reviews.record'
        self._authorize(context, operation)
        self._request_arguments(review_id, expected_request_version, fence)
        if type(raw_response) is not bytes or len(raw_response) > _MAX_RESPONSE_BYTES:
            raise ApplicationError('INVALID_INPUT')
        parameters = _input({'review_id': review_id, 'request_version': expected_request_version,
            'fence': fence, 'raw_response_digest': hashlib.sha256(raw_response).hexdigest()})
        reads = self._reads(context, read_set)
        replay = self._replay(operation, parameters, context, reads)
        if replay is not None:
            return replay
        with self.factory.begin(context.scope, 'read') as uow:
            plan = uow.reviews.get_plan(review_id)
            request = uow.reviews.get_request(review_id)
        if (request.state != 'requested' or request.version != expected_request_version or request.fence != fence
                or type(expected_request_version) is not int or type(fence) is not int):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        admission = self._admission()
        if self.blobs is None or self.blobs.authority_id != self.factory.authority_id:
            raise ApplicationError('BLOB_AUTHORITY_UNAVAILABLE')
        expected_digest = Digest('sha256', parameters['raw_response_digest'])
        raw_ref = self.blobs.put_verified(raw_response, expected_digest, 'application/octet-stream')
        if (type(raw_ref) is not BlobRef or raw_ref.digest != expected_digest
                or raw_ref.byte_length != len(raw_response) or raw_ref.media_type != 'application/octet-stream'
                or self.blobs.read_verified(raw_ref) != raw_response):
            raise ApplicationError('REVIEW_RAW_RESPONSE_INVALID')
        record = admission.verify_response(context, plan, request, raw_ref)
        if (type(record) is not ReviewRecord or record.plan != plan
                or record.identity.schema_version != 2 or record.raw_response_ref != raw_ref
                or record.reviewer_evidence.raw_response_digest != expected_digest):
            raise ApplicationError('REVIEW_STALE')
        # Attribution/time belong to the admitted command, not response text.
        record = replace(record, identity=RecordIdentity(context.scope, review_id,
            context.received_at, context.authenticated_actor, schema_version=2))
        with admission.guard_plan(context, plan), admission.guard_trust(context, (record,)) as current:
            _trust((record,), current)
            return self._run(operation, parameters, context, reads,
                lambda uow: {'review_ref': asdict(uow.reviews.insert_review(record,
                    expected_request_version=expected_request_version, fence=fence)),
                    'verdict': record.verdict, 'plan_digest': asdict(plan.plan_digest),
                    'request_version': expected_request_version, 'fence': fence})

    def withdraw(self, review_id, context, *, expected_request_version, fence, read_set=None):
        operation = 'engineering.reviews.withdraw'
        self._authorize(context, operation)
        self._request_arguments(review_id, expected_request_version, fence)
        reads = self._reads(context, read_set)
        parameters = _input({'review_id': review_id, 'request_version': expected_request_version, 'fence': fence})
        return self._run(operation, parameters, context, reads,
            lambda uow: {'request': asdict(uow.reviews.withdraw_request(review_id,
                expected_version=expected_request_version, fence=fence))})

    def control_reviews(self, expectations, context, *, state, reason, replacement_ref=None, read_set=None):
        operation = 'engineering.reviews.control'
        self._authorize(context, operation)
        if (type(expectations) is not tuple or not expectations
                or any(type(item) is not ReviewControlExpectation for item in expectations)):
            raise ApplicationError('INVALID_INPUT')
        reads = self._reads(context, read_set)
        parameters = _input({'expectations': [asdict(item) for item in expectations],
            'state': state, 'reason': reason, 'replacement_ref': asdict(replacement_ref) if replacement_ref is not None else None})
        replay = self._replay(operation, parameters, context, reads)
        if replay is not None:
            return replay
        if self.control is None:
            raise ApplicationError('REVIEW_CONTROL_AUTHORITY_UNAVAILABLE')
        with self.control.guard_control(context, expectations, state=state, reason=reason,
                                       replacement_ref=replacement_ref) as evidence:
            if type(evidence) is not tuple or not evidence or any(type(item) is not Digest for item in evidence):
                raise ApplicationError('REVIEW_CONTROL_AUTHORITY_UNAVAILABLE')
            def mutate(uow):
                snapshot = uow.reviews.control_group(expectations, state=state, reason=reason,
                    evidence=evidence, replacement_ref=replacement_ref)
                return {'key': asdict(snapshot.key), 'set_version': snapshot.set_version}
            return self._run(operation, parameters, context, reads, mutate)

    def get_command(self, context: CommandContext):
        self._authorize(context, 'engineering.commands.get')
        with self.factory.begin(context.scope, 'read') as uow:
            entry = uow.commands.get(context.key)
            if entry is None:
                raise ApplicationError('COMMAND_NOT_FOUND')
            return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)

    def query_set(self, requirement: ReviewRequirement, context: CommandContext):
        self._authorize(context, 'engineering.reviews.query')
        if type(requirement) is not ReviewRequirement or requirement.scope != context.scope:
            raise ApplicationError('INVALID_INPUT')
        with self.factory.begin(context.scope, 'read') as uow:
            frozen = uow.reviews.get_requirement(requirement.requirement_id, requirement.requirement_version)
            if frozen != requirement:
                raise ApplicationError('REQUIREMENT_CONFLICT')
            snapshot = uow.reviews.read_set(ReviewSetKey.for_requirement(requirement))
            if any(item.record.plan.requirement != requirement for item in snapshot.reviews):
                raise ApplicationError('REQUIREMENT_CONFLICT')
            return snapshot

    def gate(self, requirement: ReviewRequirement, context: CommandContext):
        snapshot = self.query_set(requirement, context)
        records = tuple(item.record for item in snapshot.reviews if item.control.state == 'active')
        if any(record.identity.schema_version != 2 or record.raw_response_ref is None for record in records):
            raise ApplicationError('REVIEW_RAW_RESPONSE_REQUIRED')
        # Acquire current trust outside SQLite, then reread the full set under
        # its version fence. The result is a proposal/read-set, never a grant.
        admission = self._admission()
        with ExitStack() as guards:
            for record in records:
                guards.enter_context(admission.guard_plan(context, record.plan))
            current = guards.enter_context(admission.guard_trust(context, records))
            _trust(records, current)
            with self.factory.begin(context.scope, 'read') as uow:
                uow.reviews.check_expectations((ReviewSetExpectation(snapshot.key, snapshot.set_version),))
            return evaluate_gate(requirement, snapshot, current)
