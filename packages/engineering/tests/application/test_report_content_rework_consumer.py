"""Approval and replay boundaries for report-content-rework consumption."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.commands import CommandContext, CommandKey
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.report_content_rework import (
    ReportContentReworkConsumer, _contains_session_id)
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest


@dataclass
class Entry:
    key: object
    project_id: str
    operation: str
    operation_id: str
    request_digest: object
    state: str = 'pending'
    result_bytes: bytes | None = None
    version: int = 1


class Journal:
    def __init__(self):
        self.entries = {}

    def reserve(self, key, *, project_id, operation, operation_id, request_digest):
        entry = self.entries.get(key)
        if entry is not None:
            return type('Reservation', (), {'entry': entry, 'created': False})()
        entry = Entry(key, project_id, operation, operation_id, request_digest)
        self.entries[key] = entry
        return type('Reservation', (), {'entry': entry, 'created': True})()

    def get(self, key):
        return self.entries.get(key)


class Factory:
    authority_id = 'authority-a'

    def __init__(self):
        self.commands = Journal()

    @contextmanager
    def begin(self, _scope, _mode='write'):
        yield type('UnitOfWork', (), {
            'commands': self.commands, 'authority_id': self.authority_id,
            'commit': lambda _self: None})()


class Access:
    def __init__(self):
        self.context = None

    def current_context(self):
        return self.context

    def require(self, context, operation):
        assert context is self.context
        assert operation == 'engineering.work.invoke'


class Blobs:
    def __init__(self, ref, content):
        self.ref, self.content = ref, content

    def read_verified(self, ref):
        assert ref == self.ref
        return self.content


class Approval:
    def __init__(self, factory, access, blobs, proof_ref):
        self.factory, self.access, self.blobs = factory, access, blobs
        self.proof_ref = proof_ref
        self.calls = 0

    @contextmanager
    def guard(self, context, *, plan_ref):
        assert self.access.current_context() is context
        assert plan_ref == PLAN_REF
        self.calls += 1
        yield self.proof_ref


PLAN_REF = BlobRef(Digest('sha256', '1' * 64), 10, 'application/json', 'plan-a')
APPROVAL_BYTES = canonical_bytes({'contract': 'ordessa.report-content-rework-approval/1',
    'plan_ref': {'digest': {'algorithm': 'sha256', 'hex': '1' * 64},
        'byte_length': 10, 'media_type': 'application/json', 'storage_object_id': 'plan-a'},
    'principal_id': 'person-a', 'decision': 'approved',
    'not_before': '2026-10-18T00:00:00+00:00',
    'expires_at': '2026-10-19T00:00:00+00:00', 'max_uses': 1})
APPROVAL_REF = BlobRef(Digest('sha256', hashlib.sha256(APPROVAL_BYTES).hexdigest()),
                       len(APPROVAL_BYTES), 'application/json', 'approval-a')


class Source:
    def __init__(self):
        self.prompts = 0
        self.plan = {'origin': {'execution_operation_ref': 'business-op-a'}}

    def prepare_plan(self, context, **_kwargs):
        return {'plan_ref': PLAN_REF, 'plan': self.plan,
                'operation_ref': 'report-content-rework/' + PLAN_REF.digest.hex}

    def claim_key(self, plan):
        suffix = hashlib.sha256(plan['origin']['execution_operation_ref'].encode()).hexdigest()[:48]
        return CommandKey('realm-a', 'person-a', 'report-content-rework-' + suffix)

    def claim_digest(self, plan_ref, approval_ref):
        from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
        from dataclasses import asdict
        return record_digest('report-content-rework-claim', {
            'plan_ref': asdict(plan_ref), 'approval_ref': asdict(approval_ref)})

    def claim_operation_id(self, plan):
        return 'report-content-rework-claim/' + hashlib.sha256(
            plan['origin']['execution_operation_ref'].encode()).hexdigest()

    def prompt(self, _context, _plan_ref, _approval_ref):
        self.prompts += 1
        return {'prompt': [{'type': 'text', 'text': 'report-only'}]}

    def _unused_completion_port(self, *_args, **_kwargs):
        raise AssertionError('prepare must not enter report completion')

    load_plan = validate_checkpoint = record = guard_report = _unused_completion_port
    review_evidence = review_materials = _unused_completion_port


class Service:
    def __init__(self, context, approval=None):
        self._access = Access()
        self._access.context = context
        self._factory = Factory()
        self._blobs = Blobs(APPROVAL_REF, _proof(context))
        self._works = type('Works', (), {'_input': lambda _self, *_args: (
            {'work_id': 'work-a', 'action_id': 'action-a', 'inputs': {}}, None,
            Digest('sha256', '3' * 64))})()
        self._report_correction_source = lambda: type('SourceOwner', (), {
            'content_rework': SOURCE, 'content_rework_approval': approval})()

    def _report_correction_work(self, _context, _value):
        return object(), {},

    def _report_correction_tail_inputs(self, *_args, **_kwargs):
        return {}, {}, {}


def _proof(context):
    assert context.principal_id == 'person-a'
    return APPROVAL_BYTES


def _context():
    return CommandContext(Scope('realm-a', 'project-a'), 'person-a',
        ActorRef('person-a', 'human', 'local'), 'request-a',
        '2026-10-18T07:00:00.000000Z', 'trace-a')


def setup_function():
    global SOURCE
    SOURCE = Source()


def _parameters():
    return {'invoke_parameters': {'work_id': 'work-a', 'action_id': 'action-a', 'inputs': {}},
            'origin': {'parent_operation_id': 'parent-op', 'expected_parent_version': 1,
                       'review_ref': {}, 'submission_ref': {}},
            'supplement_refs': []}


def test_prepare_requires_approval_before_claim_or_prompt():
    context = _context()
    service = Service(context)
    result = ReportContentReworkConsumer(service).prepare(_parameters(), context)
    assert result == {'state': 'approval_required', 'plan_ref': {
        'digest': {'algorithm': 'sha256', 'hex': '1' * 64}, 'byte_length': 10,
        'media_type': 'application/json', 'storage_object_id': 'plan-a'},
        'operation_ref': 'report-content-rework/' + '1' * 64, 'params': None}
    assert service._factory.commands.entries == {}
    assert SOURCE.prompts == 0


def test_prepare_sends_prompt_only_for_first_claim_and_queries_pending_replay():
    context = _context()
    factory = Factory()
    access = Access()
    access.context = context
    blobs = Blobs(APPROVAL_REF, _proof(context))
    approval = Approval(factory, access, blobs, APPROVAL_REF)
    service = Service(context, approval)
    service._factory, service._access, service._blobs = factory, access, blobs
    first = ReportContentReworkConsumer(service).prepare(_parameters(), context)
    second = ReportContentReworkConsumer(service).prepare(_parameters(), context)
    assert first['state'] == 'ready'
    assert first['params'] == {'prompt': [{'type': 'text', 'text': 'report-only'}]}
    assert first['operation_ref'] == second['operation_ref'] == 'report-content-rework/' + '1' * 64
    assert second['state'] == 'pending_query_only' and second['params'] is None
    assert SOURCE.prompts == 1


def test_prepare_enforces_closed_input_and_rejects_host_supplied_session_id():
    assert _contains_session_id({'prompt': [{'text': {'sessionId': 'host'}}]})
    assert not _contains_session_id({'prompt': [{'text': 'safe'}]})
    context = _context()
    with pytest.raises(ApplicationError, match='REPORT_CONTENT_REWORK_INPUT_INVALID'):
        ReportContentReworkConsumer(Service(context)).prepare(
            {**_parameters(), 'unexpected': True}, context)


@pytest.mark.parametrize('change,code', [
    ({'principal_id': 'another-person'}, 'APPROVAL_INVALID'),
    ({'decision': 'denied'}, 'APPROVAL_INVALID'),
    ({'max_uses': 2}, 'APPROVAL_INVALID'),
    ({'max_uses': True}, 'APPROVAL_INVALID'),
    ({'expires_at': '2026-10-18T06:00:00+00:00'}, 'APPROVAL_EXPIRED'),
])
def test_invalid_selected_approval_never_reserves_claim(change, code):
    from ordessa_infrastructure.encoding import decode_json
    context = _context()
    service = Service(context)
    raw = canonical_bytes(dict(decode_json(APPROVAL_BYTES), **change))
    ref = BlobRef(Digest('sha256', hashlib.sha256(raw).hexdigest()),
                  len(raw), 'application/json', 'invalid-proof')
    service._blobs = Blobs(ref, raw)
    approval = Approval(service._factory, service._access, service._blobs, ref)
    service._report_correction_source = lambda: type('SourceOwner', (), {
        'content_rework': SOURCE, 'content_rework_approval': approval})()
    with pytest.raises(ApplicationError, match='REPORT_CONTENT_REWORK_' + code):
        ReportContentReworkConsumer(service).prepare(_parameters(), context)
    assert service._factory.commands.entries == {} and SOURCE.prompts == 0
