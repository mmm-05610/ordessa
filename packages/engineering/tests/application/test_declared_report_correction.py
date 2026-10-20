"""RC1 report correction source boundary and Pi journal lineage checks.

The controlled peers below are isolated unit doubles; they do not establish a
native UnitRecords or Server end-to-end completion.
"""
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.assembly import build_declared_unit_report_source
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.declared_report import (
    DeclaredWorkReportSource, REWORK_PLAN_CONTRACT, REWORK_RULE,
    declared_review_operation_ref,
)
from ordessa_engineering.domain.common.models.values import Digest


class _Peer:
    authority_id = 'authority-a'

    def read_verified(self, ref):
        raise AssertionError('no blob is read by these tests')

    def put_verified(self, raw, digest, media_type):
        raise AssertionError('no blob is written by these tests')


def _factory():
    return SimpleNamespace(authority_id='authority-a')


class _Methods:
    def __init__(self, factory):
        self.factory = factory

    def guard(self, *args, **kwargs):
        raise AssertionError('no method guard in these tests')

    def resource_ref(self, *args, **kwargs):
        raise AssertionError('no method resource in these tests')

    def read_resource(self, *args, **kwargs):
        raise AssertionError('no method resource in these tests')


class _Access:
    def __init__(self, operation='engineering.work.invoke'):
        self.operation = operation

    def require(self, context, operation):
        if operation != self.operation:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        assert context.scope == SCOPE


_UNSET = object()


def _ports(*, factory=None, blobs=None, records=None, access=_UNSET,
           with_query=True, with_unit=True, with_material=True):
    values = dict(factory=factory, blobs=blobs, records=records or object(),
                  access=_Access() if access is _UNSET else access,
                  paths=('/repo/catalog/views.py',))
    if with_query:
        values['query'] = lambda *args, **kwargs: None
    if with_unit:
        values['read_unit'] = lambda *args, **kwargs: None
    if with_material:
        values['read_material'] = lambda *args, **kwargs: None
    return SimpleNamespace(**values)


@pytest.mark.parametrize('operation', [
    'engineering.reviews.request', 'engineering.reviews.record',
    'engineering.work.invoke'])
def test_registered_correction_projection_uses_the_current_allowed_capability(operation):
    context = _context()
    source = object.__new__(DeclaredWorkReportSource)
    source.correction_ports = SimpleNamespace(access=_Access(operation))
    source._require_registered_correction_access(context)


def test_registered_correction_projection_rejects_unrelated_current_capability():
    context = _context()
    source = object.__new__(DeclaredWorkReportSource)
    source.correction_ports = SimpleNamespace(access=_Access('engineering.artifacts.read'))
    with pytest.raises(ApplicationError, match='ACCESS_AUTHORITY_UNAVAILABLE'):
        source._require_registered_correction_access(context)


def test_factory_retains_one_source_with_the_same_correction_ports():
    factory, blobs, methods = _factory(), _Peer(), _Methods(_factory())
    methods.factory = factory
    ports = _ports(factory=factory, blobs=blobs)
    source = build_declared_unit_report_source(factory, method_control=methods,
                                              blobs=blobs, correction_ports=ports)
    assert type(source) is DeclaredWorkReportSource
    assert source.correction_ports is ports
    retained = build_declared_unit_report_source(factory, method_control=methods,
                                                 blobs=blobs, source=source,
                                                 correction_ports=ports)
    assert retained is source


def test_factory_never_defaults_a_correction_source():
    factory, blobs = _factory(), _Peer()
    methods = _Methods(factory)
    source = build_declared_unit_report_source(factory, method_control=methods, blobs=blobs)
    assert source.correction_ports is None
    other = _ports(factory=factory, blobs=blobs)
    with pytest.raises(ApplicationError) as refused:
        build_declared_unit_report_source(factory, method_control=methods, blobs=blobs,
                                          source=source, correction_ports=other)
    assert refused.value.code == 'SUBMISSION_REPORT_CORRECTION_UNAVAILABLE'


@pytest.mark.parametrize('ports', [
    _ports(factory=SimpleNamespace(authority_id='other')),
    _ports(blobs=_Peer()),
    _ports(records=None),
    _ports(access=None),
    _ports(with_query=False),
    _ports(with_unit=False),
    _ports(with_material=False),
])
def test_ports_must_be_the_same_graph_with_the_full_read_only_surface(ports):
    factory, blobs = _factory(), _Peer()
    with pytest.raises(ApplicationError) as refused:
        build_declared_unit_report_source(factory, method_control=_Methods(factory), blobs=blobs,
                                          correction_ports=ports)
    assert refused.value.code == 'SUBMISSION_REPORT_CORRECTION_UNAVAILABLE'


def test_source_never_discovers_a_correction_on_the_ordinary_path():
    blobs = _Peer()
    factory = _factory()
    source = DeclaredWorkReportSource(factory, _Methods(factory), blobs)
    assert source.declared_work_reports is True
    assert source.correction_ports is None


def test_declared_review_operation_identity_is_shared_and_stable():
    from ordessa_engineering.domain.common.models.identity import Scope
    from ordessa_engineering.domain.reviews.assignments import ReviewerAssignmentRef
    plan = SimpleNamespace(plan_digest=Digest('sha256', '1' * 64))
    assignment = SimpleNamespace(ref=ReviewerAssignmentRef(
        Scope('realm-a', 'project-a'), 'assignment-a', Digest('sha256', '2' * 64)))
    operation = declared_review_operation_ref(plan, assignment)
    assert operation == declared_review_operation_ref(plan, assignment)
    assert operation.startswith('declared-review/')
    assert operation != declared_review_operation_ref(
        SimpleNamespace(plan_digest=Digest('sha256', '3' * 64)), assignment)


def _review_permission(tool_id='command-a', *, request_id=17):
    return {'raw': {'jsonrpc': '2.0', 'id': request_id,
        'method': 'session/request_permission', 'params': {
            'toolCallId': tool_id, 'approval': 'command',
            'toolCall': {'toolCallId': tool_id, 'kind': 'execute',
                         'rawInput': {'command': 'check-suite --offline'}},
            'options': [{'optionId': 'allow-once', 'kind': 'allow_once'}]}}}


def _review_update(tool_id, status, decision=None, approval=None):
    params = {'type': 'tool_call_update', 'toolCallId': tool_id, 'status': status,
              'update': {'sessionUpdate': 'tool_call_update', 'toolCallId': tool_id,
                         'status': status}}
    if decision is not None:
        params['permissionDecision'] = decision
    if approval is not None:
        params['approval'] = approval
    return {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': params}}


def test_review_successor_source_accepts_only_a_closed_blocked_command_observation():
    receipt = {'events': [_review_update('command-a', 'in_progress'),
        _review_permission(), _review_update('command-a', 'failed', 'cancelled')]}
    assert DeclaredWorkReportSource._review_command_failure(receipt, {'/repo/spec.md'}) is True
    # Outgoing callback responses are optional in native captures. When present,
    # they must corroborate refusal and cannot contradict a cancelled update.
    receipt['events'].append({'raw': {'id': 17, 'result': {'outcome': {'outcome': 'cancelled'}}}})
    assert DeclaredWorkReportSource._review_command_failure(receipt, {'/repo/spec.md'}) is True

    # A read of one of the pinned files may precede the refused command.
    receipt['events'].insert(1, {'raw': {'jsonrpc': '2.0', 'id': 18,
        'method': 'session/request_permission', 'params': {
            'toolCallId': 'read-a', 'approval': 'file',
            'toolCall': {'toolCallId': 'read-a', 'kind': 'read',
                         'locations': [{'path': '/repo/spec.md'}]},
            'files': ['/repo/spec.md'],
            'options': [{'optionId': 'read-once', 'kind': 'allow_once'}]}}})
    receipt['events'].append({'raw': {'jsonrpc': '2.0', 'id': 18, 'result': {'outcome': 'selected'}}})
    receipt['events'].append(_review_update('read-a', 'completed', 'approved', 'file'))
    assert DeclaredWorkReportSource._review_command_failure(receipt, {'/repo/spec.md'}) is True

    # The native Pi command gate can refuse before a permission callback.
    gate = _review_update('gate-a', 'failed', approval='command')
    gate['raw']['params']['delta'] = 'Blocked by acp-adapter approved check command gate'
    gate['raw']['params']['update']['content'] = [{'type': 'content', 'content': {
        'type': 'text', 'text': 'Blocked by acp-adapter approved check command gate'}}]
    receipt['events'].extend([_review_update('gate-a', 'in_progress', approval='command'), gate])
    assert DeclaredWorkReportSource._review_command_failure(receipt, {'/repo/spec.md'}) is True
    # The bounded recovery requires a real permission refusal, not a gate alone.
    with pytest.raises(ApplicationError, match='SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID'):
        DeclaredWorkReportSource._review_command_failure({'events': [gate]}, {'/repo/spec.md'})


@pytest.mark.parametrize('mutation', ['no_command', 'completed', 'open', 'write', 'outside_read',
    'unknown_method', 'unknown_update', 'unmatched_completed', 'unmatched_failed',
    'gate_text_only', 'late_progress', 'read_unclosed', 'ambiguous_failed', 'orphan_response',
    'approved_response_cancelled_update', 'duplicate_response', 'result_and_error'])
def test_review_successor_source_refuses_unqualified_predecessor_observations(mutation):
    events = [_review_update('command-a', 'in_progress'), _review_permission(),
              _review_update('command-a', 'failed', 'cancelled')]
    if mutation == 'no_command':
        events = [_review_update('command-a', 'failed')]
    elif mutation == 'completed':
        events[-1] = _review_update('command-a', 'completed', 'approved')
    elif mutation == 'open':
        events[-1] = _review_update('command-a', 'in_progress')
    elif mutation == 'write':
        events.append({'raw': {'jsonrpc': '2.0', 'id': 19,
            'method': 'fs/write_text_file', 'params': {'path': '/repo/spec.md'}}})
    elif mutation == 'outside_read':
        events.append({'raw': {'jsonrpc': '2.0', 'id': 20,
            'method': 'fs/read_text_file', 'params': {'path': '/private/elsewhere'}}})
    elif mutation == 'unknown_method':
        events.append({'raw': {'method': 'future/mutate', 'params': {}}})
    elif mutation == 'unknown_update':
        events.append({'raw': {'method': 'session/update', 'params': {
            'update': {'sessionUpdate': 'future_tool'}}}})
    elif mutation in {'unmatched_completed', 'unmatched_failed'}:
        events.append(_review_update('unmatched', mutation.removeprefix('unmatched_')))
    elif mutation == 'gate_text_only':
        event = _review_update('unmatched', 'failed', approval='command')
        event['raw']['params']['delta'] = 'Blocked by acp-adapter approved check command gate'
        events.append(event)
    elif mutation == 'late_progress':
        events.append(_review_update('command-a', 'in_progress'))
    elif mutation == 'read_unclosed':
        events.append({'raw': {'id': 20, 'method': 'session/request_permission', 'params': {
            'toolCallId': 'read-open', 'approval': 'file', 'files': ['/repo/spec.md'],
            'toolCall': {'toolCallId': 'read-open', 'kind': 'read',
                'locations': [{'path': '/repo/spec.md'}]},
            'options': [{'kind': 'allow_once', 'optionId': 'read-once'}]}}})
    elif mutation == 'ambiguous_failed':
        events[-1] = _review_update('command-a', 'failed')
    elif mutation == 'orphan_response':
        events.append({'raw': {'jsonrpc': '2.0', 'id': 'unmatched', 'result': {}}})
    elif mutation == 'approved_response_cancelled_update':
        events.append({'raw': {'id': 17, 'result': {'outcome': {
            'outcome': 'selected', 'optionId': 'allow-once'}}}})
    elif mutation == 'duplicate_response':
        events.extend([{'raw': {'id': 17, 'result': {'outcome': 'cancelled'}}}] * 2)
    elif mutation == 'result_and_error':
        events.append({'raw': {'id': 17, 'error': {'code': -32000},
            'result': {'outcome': {'outcome': 'selected', 'optionId': 'allow-once'}}}})
    with pytest.raises(ApplicationError, match='SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID'):
        DeclaredWorkReportSource._review_command_failure(
            {'events': events}, {'/repo/spec.md'})


# --- RC1.1 protocol: controlled journal/blobs/peers, no native call ----------
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.commands import CommandKey
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.work_context import WorkBinding
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding, package_ref_projection
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef

REPO = Path(__file__).resolve().parents[4]
SCOPE = Scope('realm-a', 'project-a')
UNIT = {'environmentNamespace': 'env-a', 'unitId': 'unit-a',
        'ownerProviderRef': {'provider': 'owner-a'}, 'sourceRevision': 'rev-1'}
UNIT_BYTES = canonical_bytes(UNIT)
LIMITATION = ('selected original Pi journal observation; '
              'not independently authenticated execution proof')


def _digest(raw):
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


class _Blobs:
    authority_id = 'authority-a'

    def __init__(self):
        self.values = {}

    def put_verified(self, raw, digest, media_type, **_kwargs):
        storage_object_id = 'blob-' + digest.hex + '-' + hashlib.sha256(
            media_type.encode('utf-8')).hexdigest()[:12]
        ref = BlobRef(digest, len(raw), media_type, storage_object_id)
        self.values[storage_object_id] = (ref, raw)
        return ref

    def read_verified(self, ref):
        stored = self.values.get(ref.storage_object_id)
        if stored is None or stored[0] != ref:
            raise AssertionError('missing blob')
        raw = stored[1]
        if len(raw) != ref.byte_length or _digest(raw) != ref.digest:
            raise AssertionError('blob metadata mismatch')
        return raw


class _Journal:
    def __init__(self):
        self.rows = {}

    def reserve(self, key, *, project_id, operation, operation_id, request_digest):
        from types import SimpleNamespace
        entry = SimpleNamespace(key=key, project_id=project_id, operation=operation,
                                operation_id=operation_id, request_digest=request_digest,
                                state='pending', version=0, result_bytes=None)
        self.rows[operation_id] = entry
        return SimpleNamespace(entry=entry, created=True)

    def find_operation(self, scope, operation_id, *, operation):
        return self.rows.get(operation_id)

    def complete(self, key, *, expected_version, result_bytes, state='completed'):
        entry = next(item for item in self.rows.values() if item.key == key)
        entry.state, entry.version, entry.result_bytes = state, expected_version + 1, result_bytes
        return entry


class _UoW:
    def __init__(self, journal, blobs, row, grant, records):
        from types import SimpleNamespace
        self.commands = journal
        self.blobs = blobs
        self.work_dispatch = SimpleNamespace(by_operation=lambda op, scope: row)
        self.authorization = SimpleNamespace(
            get_grant=lambda ref: grant,
            get_control=lambda ref: {'state': 'granted', 'version': 3, 'revoked_at': None},
            action_budget=lambda ref: {'actions': [
                {'action': 'edit_repository', 'limit': 1, 'consumed': 1},
                {'action': 'run_checks', 'limit': 1, 'consumed': 1}]})
        self.submissions = SimpleNamespace(resolve=lambda _ref: getattr(journal, 'submission', None))
        method = SimpleNamespace(method_ref=MethodRef('method-a', '1', 2, _digest(b'snapshot')))
        self.implementation = SimpleNamespace(
            resolve_package=lambda ref: SimpleNamespace(payload=method))
        self.committed = False

    def commit(self):
        self.committed = True


def _methods_peer():
    """Schema accepts the compliant report; the port is a test double only."""
    schema = {'type': 'object', 'required': ['profile_ref', 'package_digest'],
              'properties': {'profile_ref': {'type': 'object'},
                             'package_digest': {'type': 'string'}},
              'additionalProperties': True}
    factory = None

    class _MethodControl:
        def guard(self, context, method_ref):
            from contextlib import contextmanager

            @contextmanager
            def _guard():
                yield type('D', (), {'actions': [type('A', (), {
                    'action_id': 'incremental.implement-package',
                    'steps': [type('S', (), {'step_id': 'implement',
                                             'name': 'implement-approved-package',
                                             'kind': 'invoke',
                                             'outputs': ('implementation_report',)})],
                    'resources': [type('R', (), {'resource_id': 'implementation-report-schema'})]})]})()
            return _guard()

        def resource_ref(self, context, method_ref, resource_id):
            from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
            return ExactMethodResourceRef(method_ref, 'implementation-report-schema',
                                          Digest('sha256', 'b' * 64), resource_id)

        def read_resource(self, context, ref):
            return canonical_bytes(schema)

    methods = _MethodControl()
    methods.factory = factory
    return methods


def _context():
    return CommandContext(scope=SCOPE, principal_id='principal-a',
                          authenticated_actor=ActorRef('agent', 'agent', 'principal-a'),
                          request_id='req-1', received_at='2026-10-18T04:00:00.000000Z',
                          trace_id='trace-1')


def _binding(prompt_ref=None):
    package = ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-a', _digest(b'pkg'))
    return DispatchBinding(
        scope=SCOPE, run_id='w1:work-a', step_id='implement', attempt=1, fence=1,
        action_instances=(('edit_repository', 'inst-1'), ('run_checks', 'inst-2')),
        unit_ref_bytes=UNIT_BYTES, execution_operation_ref='op-biz',
        prompt_ref=prompt_ref or BlobRef(_digest(b'prompt'), 6, 'application/json', 'prompt'),
        prompt_input_digest=_digest(b'prompt-input'), expected_query_digest='sha256:' + 'q' * 64,
        required_results=('implementation_report',), package_ref=package,
        approval_ref=ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'approval-a', _digest(b'grant')),
        intent_digest=_digest(b'intent'), control_version=1, binding_version=2,
        work={'work_id': 'work-a', 'action_id': 'incremental.implement-package',
              'step_id': 'implement', 'dispatch_key': 'w1:work-a'},
        subject={'subject_kind': 'frozen_package', 'subject_ref': package_ref_projection(package)})


def _graph(tmp_path):
    from types import SimpleNamespace
    blobs = _Blobs()
    journal = _Journal()
    profile = {'environmentNamespace': 'env-a', 'profileId': 'p',
               'contentDigest': 'sha256:' + 'a' * 64}
    task_text = canonical_bytes({'profile_ref': profile, 'instruction': 'old task'}).decode()
    prompt_raw = canonical_bytes({'sessionId': 'session-a',
                                  'prompt': [{'type': 'text', 'text': task_text}],
                                  'profile_ref': profile})
    prompt_ref = blobs.put_verified(prompt_raw, _digest(prompt_raw), 'application/json')
    binding = _binding(prompt_ref)
    rejected = {'profile_ref': {'environmentNamespace': 'env-a', 'profileId': 'p',
                                'contentDigest': 'sha256:' + 'a' * 64},
                'package_digest': 'sha256:' + binding.package_ref.digest.hex,
                'type': 'json_object'}
    rejected_raw = canonical_bytes(rejected)
    command = 'check-suite --offline'
    tool_id = 'call-check'
    journal_call = {'type': 'message', 'id': 'm-call', 'parentId': None,
        'timestamp': '2026-10-18T03:00:00.000Z', 'message': {'role': 'assistant', 'content': [
            {'type': 'toolCall', 'id': tool_id, 'name': 'bash',
             'arguments': {'command': command, 'timeout': 300}}]}}
    journal_result = {'type': 'message', 'id': 'm-result', 'parentId': 'm-call',
        'timestamp': '2026-10-18T03:00:01.000Z', 'message': {'role': 'toolResult',
        'toolCallId': tool_id, 'toolName': 'bash',
        'content': [{'type': 'text', 'text': 'testsRun:64'}], 'isError': False}}
    journal_raw = canonical_bytes(journal_call) + b'\n' + canonical_bytes(journal_result) + b'\n'
    excerpt_raw = canonical_bytes(journal_result)
    request = {'jsonrpc': '2.0', 'id': 31, 'method': 'session/prompt',
               'params': decode_json(prompt_raw)}
    response = {'jsonrpc': '2.0', 'id': 31, 'result': {'content': []}}
    events = [
        {'raw': {'jsonrpc': '2.0', 'id': 17, 'method': 'session/request_permission',
                 'params': {'sessionId': 'session-a', 'toolCallId': tool_id,
                    'approval': 'command', 'toolCall': {'toolCallId': tool_id, 'kind': 'execute',
                    'rawInput': {'command': command}},
                    'options': [{'optionId': 'accept', 'kind': 'allow_once'}]}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'type': 'tool_call_update', 'toolCallId': tool_id, 'status': 'completed',
            'permissionDecision': 'approved', 'update': {'sessionUpdate': 'tool_call_update',
            'toolCallId': tool_id, 'status': 'completed'}}}},
        {'raw': response},
    ]
    receipt = {'contractVersion': 'unit-acp-turn/1', 'unitRef': UNIT, 'operationRef': 'op-biz',
               'inputDigest': 'sha256:' + binding.prompt_input_digest.hex,
               'state': 'completed', 'revision': 360,
               'request': {'raw': request}, 'response': response, 'events': events,
               'nativeBinding': {'sessionId': 'session-a'},
               'input': {'unitRef': UNIT, 'params': decode_json(prompt_raw)},
               'summary': {'text': rejected_raw.decode(), 'eventCount': len(events),
                           'successfulRpcResponse': True, 'modelQualityVerified': False}}
    receipt_raw = canonical_bytes(receipt)
    observation_ref = blobs.put_verified(receipt_raw, _digest(receipt_raw),
                                         'application/json')
    row = {'binding_bytes': encode_dispatch(binding), 'run_id': 'w1:work-a',
           'step_id': 'implement', 'attempt': 1, 'execution_operation_ref': 'op-biz',
           'dispatch_version': 2, 'dispatch_phase': 'completed',
           'result_blob_json': canonical_bytes(asdict(observation_ref)).decode(),
           'dispatch_fence': 1}
    environments = (SimpleNamespace(environment_id='env-a', profile_id='p',
                                    profile_digest=Digest('sha256', 'a' * 64)),)
    scopes = (('edit_repository', SimpleNamespace(environment_refs=environments)),
              ('run_checks', SimpleNamespace(environment_refs=environments)))
    grant = SimpleNamespace(
        ref=binding.approval_ref, intent=SimpleNamespace(
            digest=binding.intent_digest,
            not_before='2026-10-18T00:00:00.000000Z',
            expires_at='2026-10-18T23:00:00.000000Z',
            authorization=SimpleNamespace(
                work_id='work-a', work_revision=1, work_digest=_digest(b'work'),
                action_id='incremental.implement-package',
                step_id='implement', actions=('edit_repository', 'run_checks'),
                package_ref=binding.package_ref, scope=SCOPE,
                scope_by_action=scopes,
                method_ref=MethodRef('method-a', '1', 2, _digest(b'snapshot')))))
    origin = {'parent_operation_id': 'op-parent', 'execution_operation_ref': 'op-biz',
              'expected_parent_version': 0, 'expected_dispatch_version': 2,
              'expected_observation_revision': 360}
    journal.rows['op-parent'] = SimpleNamespace(
        key=CommandKey(SCOPE.realm_id, 'principal-a', 'req-1'), project_id=SCOPE.project_id,
        operation='engineering.work.invoke', operation_id='op-parent', request_digest=None,
        state='pending', version=0, result_bytes=None)
    invoke_digest = _digest(b'invoke')
    journal.rows['op-parent'].request_digest = invoke_digest
    work = WorkBinding('work-a', SCOPE, MethodRef('method-a', '1', 2, _digest(b'snapshot')),
                       revision=1)

    def read_material(context, kind, locator):
        if kind == 'repository_file':
            source = {'/repo/catalog/views.py': b'# original source\n',
                      '/repo/catalog/loader.py': b'catalog module source\n'}
            return source.get(locator, b'changed')
        if kind == 'original_journal':
            return journal_raw
        if kind == 'original_check_excerpt':
            return excerpt_raw
        raise AssertionError(kind)

    class _Records:
        def __init__(self):
            self.receipts = {'op-biz': receipt}

        def acp_turn_query_digest(self, unit_ref, operation_ref, expected_prompt_digest):
            return 'sha256:' + 'q' * 64

        def query_acp_turn(self, unit_ref, operation_ref, invocation, *,
                           input_digest, expected_prompt_input_digest):
            assert input_digest == 'sha256:' + 'q' * 64
            return self.receipts[operation_ref]

    records = _Records()
    def query(context, unit_ref, operation_ref, prompt_digest):
        return SimpleNamespace(facts={'inputDigest': 'sha256:' + 'q' * 64})

    def read_unit(context, unit):
        return {
            'unit_ref': unit,
            'profile_ref': profile,
            'stop_record': {'state': 'confirmed', 'identity': {'unitRef': unit}},
            'release_record': {'state': 'confirmed', 'identity': {'unitRef': unit}},
        }

    ports = SimpleNamespace(factory=None, blobs=blobs, records=object(), access=_Access(),
                            query=query,
                            read_unit=read_unit,
                            read_material=read_material)

    class _Factory:
        authority_id = 'authority-a'

        def __init__(self):
            self.package = None
            self.submission = None

        @contextmanager
        def begin(self, scope, mode='read'):
            uow = _UoW(journal, blobs, row, grant, object())
            if self.package is not None:
                uow.implementation.resolve_package = lambda ref: self.package
            yield uow

    factory = _Factory()
    ports.factory = factory
    ports.records = records
    ports.paths = ('/repo/catalog/views.py',)
    methods = _methods_peer()
    methods.factory = factory
    source = DeclaredWorkReportSource(factory, methods, blobs, correction_ports=ports)
    evidence = {'files': [{'path': '/repo/catalog/views.py',
                           'blob_ref': blobs.put_verified(b'# original source\n',
                                                          _digest(b'# original source\n'),
                                                          'text/plain')}],
                'check': {'origin_operation_ref': 'op-biz',
                          'journal_ref': blobs.put_verified(
                              journal_raw, _digest(journal_raw), 'application/jsonl'),
                          'excerpt_ref': blobs.put_verified(
                              excerpt_raw, _digest(excerpt_raw), 'application/json'),
                          'tool_call_id': tool_id, 'command_digest': _digest(command.encode()),
                          'limitation': LIMITATION}}
    return SimpleNamespace(source=source, blobs=blobs, journal=journal, binding=binding,
                           origin=origin, invoke_digest=invoke_digest, work=work,
                           evidence=evidence, methods=methods, factory=factory, ports=ports,
                           row=row, grant=grant)


def _prepare(graph):
    return graph.source.prepare_correction(_context(), work=graph.work,
                                           selector=graph.origin,
                                           invoke_digest=graph.invoke_digest,
                                           evidence=graph.evidence)


def _completed_correction(g):
    prepared = _prepare(g)
    plan_ref = decode_blob_ref(prepared['plan_ref'])
    plan = decode_json(g.blobs.read_verified(plan_ref))
    unit = {'environmentNamespace': 'env-a', 'unitId': 'unit-correction',
            'ownerProviderRef': {'provider': 'owner-a'}, 'sourceRevision': 'rev-2'}
    operation = prepared['operation_ref']
    params = prepared['params']
    prompt_digest = _digest(canonical_bytes(params))
    corrected = decode_json(g.blobs.read_verified(
        decode_blob_ref(plan['origin']['rejected_report_ref'])))
    corrected = dict(corrected)
    corrected.pop('type')
    output_raw = canonical_bytes(corrected)
    output_ref = g.blobs.put_verified(output_raw, _digest(output_raw), 'application/json')
    path = plan['evidence']['files'][0]['path']
    tool_id = 'read-correction-source'
    events = [
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'sessionId': 'session-c', 'update': {'sessionUpdate': 'agent_thought_chunk',
                'content': {'type': 'text', 'text': 'Check the declared report format.'}}}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'sessionId': 'session-c', 'update': {'sessionUpdate': 'tool_call_update',
                'toolCallId': tool_id, 'status': 'in_progress'}}}},
        {'raw': {'jsonrpc': '2.0', 'id': 42, 'method': 'session/request_permission',
                 'params': {'sessionId': 'session-c', 'toolCallId': tool_id,
                    'approval': 'file', 'files': [path],
                    'toolCall': {'toolCallId': tool_id, 'kind': 'read',
                                 'locations': [{'path': path}]},
                    'options': [{'optionId': 'read-once', 'kind': 'allow_once'}]}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'fs/read_text_file',
                 'params': {'sessionId': 'session-c', 'path': path}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'sessionId': 'session-c', 'update': {'sessionUpdate': 'tool_call_update',
                'toolCallId': tool_id, 'status': 'in_progress'}}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'sessionId': 'session-c', 'permissionDecision': 'approved',
            'update': {'sessionUpdate': 'tool_call_update', 'toolCallId': tool_id,
                       'status': 'completed'}}}},
    ]
    receipt = {'contractVersion': 'unit-acp-turn/1', 'unitRef': unit,
        'operationRef': operation, 'inputDigest': 'sha256:' + prompt_digest.hex,
        'state': 'completed', 'revision': 1,
        'input': {'unitRef': unit, 'params': params},
        'nativeBinding': {'sessionId': 'session-c'}, 'events': events,
        'summary': {'text': output_raw.decode('utf-8'), 'successfulRpcResponse': True}}
    observation_raw = canonical_bytes(receipt)
    observation_ref = g.blobs.put_verified(observation_raw, _digest(observation_raw),
                                            'application/json')
    g.ports.records.receipts[operation] = receipt
    # The test peer returns the same verified profile for the author and the
    # correction Unit, with independently closed identities for each.
    stop = {'state': 'confirmed', 'identity': {'unitRef': unit}}
    release = {'state': 'confirmed', 'identity': {'unitRef': unit}}
    checkpoint = {'contract': 'ordessa.declared-report-format-rework/1',
        'plan_ref': asdict(plan_ref), 'correction': {
            'unit_ref': unit, 'operation_ref': operation,
            'prompt_input_digest': asdict(prompt_digest),
            'observation_ref': asdict(observation_ref), 'observation_revision': 1,
            'output_ref': asdict(output_ref),
            'stop_record_digest': asdict(_digest(canonical_bytes(stop))),
            'release_record_digest': asdict(_digest(canonical_bytes(release))),}}
    checkpoint_raw = canonical_bytes(checkpoint)
    checkpoint_ref = g.blobs.put_verified(checkpoint_raw, _digest(checkpoint_raw),
                                           'application/json')
    return prepared, plan, checkpoint, checkpoint_ref, output_ref, output_raw


def test_prepare_qualifies_origin_and_returns_the_closed_ready_projection(tmp_path):
    g = _graph(tmp_path)
    result = _prepare(g)
    assert set(result) == {'plan_ref', 'operation_ref', 'created', 'state', 'params',
                           'submission_ref'}
    assert result['created'] is True and result['state'] == 'ready'
    plan_ref = decode_blob_ref(result['plan_ref'])
    assert result['operation_ref'] == 'report-format-rework/' + plan_ref.digest.hex
    assert result['params']['prompt'][0]['type'] == 'text'
    body = decode_json(result['params']['prompt'][0]['text'].encode())
    assert set(body) == {'instruction', 'report_correction_plan', 'plan_ref',
                         'rejected_report_utf8', 'implementation_report_schema',
                         'allowed_read_paths'}
    assert body['plan_ref'] == result['plan_ref']
    assert 'sessionId' not in result['params']
    plan = decode_json(g.blobs.read_verified(plan_ref))
    assert set(plan['origin']['parent_key']) == {'realm_id', 'principal_id', 'request_id'}
    assert plan['origin']['profile_ref']['profileId'] == 'p'
    assert plan['origin']['work_digest'] == {'algorithm': 'sha256', 'hex': _digest(b'work').hex}
    assert set(g.journal.rows) == {'op-parent', result['operation_ref']}


def test_prepare_pending_claim_is_query_only_and_idempotent(tmp_path):
    g = _graph(tmp_path)
    first = _prepare(g)
    again = _prepare(g)
    assert first['state'] == 'ready' and first['created']
    assert again['state'] == 'pending_query_only' and not again['created']
    assert again['params'] is None and again['submission_ref'] is None
    assert again['operation_ref'] == first['operation_ref']
    assert len(g.journal.rows) == 2


def test_prepare_canonicalizes_file_order_before_claim_identity(tmp_path):
    g = _graph(tmp_path)
    second_raw = b'catalog module source\n'
    second_ref = g.blobs.put_verified(second_raw, _digest(second_raw), 'text/plain')
    g.evidence['files'].append({'path': '/repo/catalog/loader.py',
                                'blob_ref': asdict(second_ref)})
    g.ports.paths = ('/repo/catalog/views.py', '/repo/catalog/loader.py')
    first = _prepare(g)
    first_plan_ref = decode_blob_ref(first['plan_ref'])
    g.evidence['files'].reverse()
    replay = _prepare(g)
    assert decode_blob_ref(replay['plan_ref']) == first_plan_ref
    plan = decode_json(g.blobs.read_verified(first_plan_ref))
    assert [item['path'] for item in plan['evidence']['files']] == [
        '/repo/catalog/loader.py', '/repo/catalog/views.py']
    assert replay['state'] == 'pending_query_only'


@pytest.mark.parametrize('violation', ['subset', 'duplicate', 'foreign'])
def test_prepare_requires_the_complete_trusted_file_set_before_reads(tmp_path, violation):
    g = _graph(tmp_path)
    g.ports.paths = ('/repo/catalog/views.py', '/repo/catalog/loader.py')
    first = dict(g.evidence['files'][0])
    if violation == 'duplicate':
        g.evidence['files'].append(first)
    elif violation == 'foreign':
        g.evidence['files'].append(dict(first, path='/repo/catalog/other.py'))
    def forbidden_read(*_args):
        pytest.fail('incomplete scope must refuse before any material read')
    g.ports.read_material = forbidden_read
    with pytest.raises(ApplicationError, match='SUBMISSION_REPORT_CORRECTION_FILE_INVALID'):
        _prepare(g)
    assert set(g.journal.rows) == {'op-parent'}


@pytest.mark.parametrize('violation', ['subset', 'duplicate', 'foreign'])
def test_checkpoint_revalidation_requires_the_complete_trusted_file_set(tmp_path, violation):
    g = _graph(tmp_path)
    second_raw = b'catalog module source\n'
    second_ref = g.blobs.put_verified(second_raw, _digest(second_raw), 'text/plain')
    g.evidence['files'].append({'path': '/repo/catalog/loader.py',
                              'blob_ref': asdict(second_ref)})
    g.ports.paths = ('/repo/catalog/views.py', '/repo/catalog/loader.py')
    _prepared, plan, checkpoint, _checkpoint_ref, _output_ref, _raw = _completed_correction(g)
    files = plan['evidence']['files']
    if violation == 'subset':
        files.pop()
    elif violation == 'duplicate':
        files[1] = dict(files[0])
    else:
        files[1] = dict(files[1], path='/repo/catalog/other.py')
    plan_raw = canonical_bytes(plan)
    checkpoint['plan_ref'] = asdict(g.blobs.put_verified(
        plan_raw, _digest(plan_raw), 'application/json'))
    checkpoint_raw = canonical_bytes(checkpoint)
    checkpoint_ref = g.blobs.put_verified(checkpoint_raw, _digest(checkpoint_raw), 'application/json')
    with pytest.raises(ApplicationError, match='SUBMISSION_REPORT_CORRECTION_FILE_INVALID'):
        g.source.validate_correction(_context(), checkpoint_ref=checkpoint_ref)


@pytest.mark.parametrize('which', ['file', 'journal', 'excerpt'])
def test_prepare_rejects_a_blob_reference_not_resolvable_in_the_same_store(tmp_path, which):
    from ordessa_engineering.domain.common.models.refs import BlobRef
    g = _graph(tmp_path)
    if which == 'file':
        item = g.evidence['files'][0]
        raw = b'# original source\n'
        item['blob_ref'] = asdict(BlobRef(_digest(raw), len(raw), 'text/plain', 'not-in-blob-store'))
    elif which == 'journal':
        raw = g.ports.read_material(_context(), 'original_journal', 'op-biz')
        g.evidence['check']['journal_ref'] = asdict(
            BlobRef(_digest(raw), len(raw), 'application/jsonl', 'not-in-blob-store'))
    else:
        raw = g.ports.read_material(_context(), 'original_check_excerpt', 'op-biz')
        g.evidence['check']['excerpt_ref'] = asdict(
            BlobRef(_digest(raw), len(raw), 'application/json', 'not-in-blob-store'))
    with pytest.raises(ApplicationError):
        _prepare(g)
    assert set(g.journal.rows) == {'op-parent'}


def test_validate_requeries_correction_and_returns_original_business_capture(tmp_path):
    g = _graph(tmp_path)
    prepared, plan, _checkpoint, checkpoint_ref, output_ref, output_raw = _completed_correction(g)
    accepted_plan, binding, original_capture = g.source.validate_correction(
        _context(), checkpoint_ref=checkpoint_ref)
    assert accepted_plan == plan
    assert binding.execution_operation_ref == 'op-biz'
    assert original_capture.operation_ref == 'op-biz'
    assert original_capture.blob_ref == decode_blob_ref(plan['origin']['observation_ref'])
    assert output_ref.digest == _digest(output_raw)
    assert g.ports.records.receipts.keys() == {'op-biz', prepared['operation_ref']}


def test_correction_record_keeps_original_execution_and_only_corrected_report_output(
        tmp_path, monkeypatch):
    from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
    from ordessa_engineering.domain.artifacts.provenance import SourceLocator, SourceRef, VersionCapture
    from ordessa_engineering.domain.changes.refs import ProposalRef
    from ordessa_engineering.domain.packages.models import (
        ImplementationPackage, PackageDocument, PreparedPackagePayload,
    )
    from ordessa_engineering.domain.reviews.refs import ReviewRef
    from ordessa_engineering.domain.changes.submission_codec import decode_submission
    import ordessa_engineering.application.usecases.changes.declared_report as declared_report

    g = _graph(tmp_path)
    method = g.work.method_ref
    locator = SourceLocator('document', provider='fixture', document_id='design')
    actor = ActorRef('fixture-author', 'human', 'controlled-source-record')
    baseline_raw, candidate_raw = b'baseline', b'candidate'
    baseline = SourceRef('baseline', 'document', locator,
        VersionCapture('v1', _digest(baseline_raw)), '2026-10-18T04:00:00.000000Z',
        actor, 'text/plain', len(baseline_raw))
    candidate = SourceRef('candidate', 'document', locator,
        VersionCapture('v2', _digest(candidate_raw)), '2026-10-18T04:00:00.000000Z',
        actor, 'text/plain', len(candidate_raw))
    change_ref = ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-a', 'proposal-a',
                             _digest(b'proposal'))
    review_ref = ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'review-a', _digest(b'review'))
    schema_ref = ExactMethodResourceRef(method, 'implementation-report-schema',
                                        _digest(b'schema'), 'implementation-report-schema')
    payload = PreparedPackagePayload(baseline, candidate, change_ref, (review_ref,), method,
        (schema_ref,), (PackageDocument('design', candidate),))
    package = ImplementationPackage(SCOPE, 'prepared-report-test',
        '2026-10-18T04:00:00.000000Z', actor, payload)
    old_receipt = dict(g.ports.records.receipts['op-biz'])
    old_summary = dict(old_receipt['summary'])
    old_report = decode_json(old_summary['text'].encode('utf-8'))
    old_report['package_digest'] = 'sha256:' + package.ref.digest.hex
    old_summary['text'] = canonical_bytes(old_report).decode('utf-8')
    old_receipt['summary'] = old_summary
    original_observation = canonical_bytes(old_receipt)
    original_ref = g.blobs.put_verified(original_observation, _digest(original_observation),
                                        'application/json')
    g.ports.records.receipts['op-biz'] = old_receipt
    g.row['result_blob_json'] = canonical_bytes(asdict(original_ref)).decode('utf-8')
    _prepared, _plan, _checkpoint, checkpoint_ref, output_ref, output_raw = _completed_correction(g)
    monkeypatch.setattr(declared_report, 'resolve_work_package_authorization',
        lambda uow, authorization: SimpleNamespace(package=SimpleNamespace(payload=payload)))
    monkeypatch.setattr(declared_report, 'resolve_declared_report_binding',
        lambda uow, submission: g.binding)
    g.factory.package = package

    raw_record = g.source.correction_record(_context(), checkpoint_ref=checkpoint_ref)
    record = decode_submission(canonical_bytes(raw_record))
    g.factory.package = SimpleNamespace(ref=record.package_ref, payload=package.payload)
    g.journal.submission = record
    check_observation = g.source.correction_review_evidence(_context(), record)
    assert check_observation['contract'] == 'ordessa.original-check-observation/1'
    assert check_observation['origin_operation_ref'] == 'op-biz'
    assert check_observation['command_utf8'] == 'check-suite --offline'
    assert check_observation['excerpt_utf8'] == g.ports.read_material(
        _context(), 'original_check_excerpt', 'op-biz').decode('utf-8')
    assert record.execution_ref.operation_ref == 'op-biz'
    assert record.output_refs == (output_ref,)
    assert record.method_content.value_bytes == output_raw
    assert record.method_content.rendered_body_ref == output_ref
    assert record.test_evidence == () and record.effect_observations == ()
    assert record.coverage == (type(record.coverage[0])(
        change_ref, (output_ref,), (), (), 'implemented'),)
    original_capture = g.source.validate_correction(
        _context(), checkpoint_ref=checkpoint_ref)[2]
    g.factory.package = package
    with g.source.guard_report(_context(), package, record, original_capture) as verified:
        assert verified.output_refs == (output_ref,)
        assert verified.execution_operation_ref == 'op-biz'
        assert verified.report_content_digest == _digest(output_raw)


def test_pi_jsonl_excerpt_is_exact_and_bound_to_the_command():
    import json
    from ordessa_engineering.application.usecases.changes.declared_report import (
        _check_journal_evidence,
    )
    command = '/usr/bin/env -i PATH=/usr/bin:/bin check-suite --offline'
    call_id = 'call-a'
    call = {'type': 'message', 'id': 'm-call', 'parentId': None,
            'timestamp': '2026-10-18T03:00:00.000Z',
            'message': {'role': 'assistant', 'content': [
                {'type': 'toolCall', 'id': call_id, 'name': 'bash',
                 'arguments': {'command': command, 'timeout': 300}}],
                'usage': {'cost': {'input': 0.000125, 'output': 0.00025}}}}
    result = {'type': 'message', 'id': 'm-result', 'parentId': 'm-call',
              'timestamp': '2026-10-18T03:00:01.000Z',
              'message': {'role': 'toolResult', 'toolCallId': call_id,
                          'toolName': 'bash', 'content': [{'type': 'text', 'text': 'testsRun:64'}],
                          'isError': False}}
    journal = json.dumps(call).encode() + b'\n' + canonical_bytes(result) + b'\n'
    excerpt = canonical_bytes(result)
    from ordessa_engineering.domain.common.models.refs import BlobRef
    journal_ref = BlobRef(_digest(journal), len(journal), 'application/jsonl', 'journal')
    excerpt_ref = BlobRef(_digest(excerpt), len(excerpt), 'application/json', 'excerpt')
    check = {'tool_call_id': call_id}
    assert _check_journal_evidence(journal, excerpt, check, journal_ref, excerpt_ref,
                                   _digest(command.encode())) == command


@pytest.mark.parametrize('raw', [b'{"cost":NaN}\n', b'{"cost":Infinity}\n',
                                  b'{"cost":-Infinity}\n', b'{"id":1,"id":2}\n'])
def test_native_journal_still_rejects_nonfinite_numbers_and_duplicate_keys(raw):
    from ordessa_engineering.application.usecases.changes.declared_report import _jsonl_records
    with pytest.raises(ApplicationError, match='SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH'):
        _jsonl_records(raw)


def test_pi_jsonl_rejects_a_repointed_excerpt_or_command_digest():
    from ordessa_engineering.application.usecases.changes.declared_report import (
        _check_journal_evidence,
    )
    command = 'check-suite --offline'
    call = {'type': 'message', 'id': 'm-call', 'parentId': None,
            'timestamp': 't1', 'message': {'role': 'assistant', 'content': [
                {'type': 'toolCall', 'id': 'call-a', 'name': 'bash',
                 'arguments': {'command': command}}]}}
    result = {'type': 'message', 'id': 'm-result', 'parentId': 'm-call',
              'timestamp': 't2', 'message': {'role': 'toolResult', 'toolCallId': 'call-a',
                  'toolName': 'bash', 'content': [{'type': 'text', 'text': 'ok'}],
                  'isError': False}}
    journal = canonical_bytes(call) + b'\n' + canonical_bytes(result) + b'\n'
    excerpt = canonical_bytes(result)
    from ordessa_engineering.domain.common.models.refs import BlobRef
    jr = BlobRef(_digest(journal), len(journal), 'application/jsonl', 'journal')
    er = BlobRef(_digest(excerpt), len(excerpt), 'application/json', 'excerpt')
    with pytest.raises(ApplicationError):
        _check_journal_evidence(journal, excerpt, {'tool_call_id': 'other'},
                                jr, er, _digest(command.encode()))
    with pytest.raises(ApplicationError):
        _check_journal_evidence(journal, excerpt, {'tool_call_id': 'call-a'},
                                jr, er, _digest(b'different'))


def test_native_permission_selects_original_call_amid_other_turn_events():
    from ordessa_engineering.application.usecases.changes.declared_report import (
        _check_native_permission,
    )
    selected = 'selected-call'
    unrelated = 'other-call'
    command = 'python -m pytest -q'
    receipt = {'events': [
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'type': 'tool_call_update', 'toolCallId': unrelated, 'status': 'completed',
            'update': {'sessionUpdate': 'tool_call_update', 'toolCallId': unrelated,
                       'status': 'completed'}}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/request_permission',
                 'params': {'toolCallId': 'edit-call', 'approval': 'file',
                    'toolCall': {'toolCallId': 'edit-call', 'kind': 'write'},
                    'options': [{'kind': 'allow_once'}]}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'sessionId': 'session-a', 'update': {'sessionUpdate': 'tool_call_update',
                'toolCallId': selected, 'status': 'in_progress'}}}},
        {'raw': {'jsonrpc': '2.0', 'id': 9, 'method': 'session/request_permission',
                 'params': {'sessionId': 'session-a', 'toolCallId': selected,
                    'approval': 'command', 'toolCall': {'toolCallId': selected,
                    'kind': 'execute', 'rawInput': {'command': command}},
                    'options': [{'optionId': 'once', 'kind': 'allow_once'}]}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'type': 'tool_call_update', 'toolCallId': selected, 'status': 'in_progress',
            'update': {'sessionUpdate': 'tool_call_update', 'toolCallId': selected,
                       'status': 'in_progress'}}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'type': 'tool_call_update', 'toolCallId': selected, 'status': 'completed',
            'permissionDecision': 'approved', 'update': {'sessionUpdate': 'tool_call_update',
            'toolCallId': selected, 'status': 'completed'}}}},
    ]}
    _check_native_permission(receipt, selected, command)
    permission_index = 3
    approval_index = 5
    variants = []
    missing_request = {'events': list(receipt['events'])}
    missing_request['events'].pop(permission_index)
    variants.append(missing_request)
    missing_approval = {'events': list(receipt['events'])}
    missing_approval['events'].pop(approval_index)
    variants.append(missing_approval)
    wrong_tool = {'events': list(receipt['events'])}
    wrong_tool['events'][approval_index] = {'raw': dict(
        wrong_tool['events'][approval_index]['raw'], params={
            **wrong_tool['events'][approval_index]['raw']['params'],
            'toolCallId': 'different-call'})}
    variants.append(wrong_tool)
    wrong_path = {'events': list(receipt['events'])}
    wrong_path['events'][permission_index] = {'raw': dict(
        wrong_path['events'][permission_index]['raw'], params={
            **wrong_path['events'][permission_index]['raw']['params'],
            'toolCall': {'toolCallId': selected, 'kind': 'execute',
                         'rawInput': {'command': 'python -m pytest --other'}}})}
    variants.append(wrong_path)
    for malformed in variants:
        with pytest.raises(ApplicationError):
            _check_native_permission(malformed, selected, command)


def test_readonly_capture_requires_matching_file_permission_and_approved_tool_update():
    from ordessa_engineering.application.usecases.changes.declared_report import (
        _check_readonly_capture,
    )
    path = '/repo/catalog/views.py'
    tool = 'read-view'
    events = [
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'update': {'sessionUpdate': 'tool_call_update', 'toolCallId': tool,
                       'status': 'in_progress'}}}},
        {'raw': {'jsonrpc': '2.0', 'id': 11, 'method': 'session/request_permission',
                 'params': {'toolCallId': tool, 'approval': 'file', 'files': [path],
                    'toolCall': {'toolCallId': tool, 'kind': 'read',
                                 'locations': [{'path': path}]},
                    'options': [{'optionId': 'read-once', 'kind': 'allow_once'}]}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'fs/read_text_file',
                 'params': {'path': path}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'permissionDecision': 'approved', 'update': {'sessionUpdate': 'tool_call_update',
            'toolCallId': tool, 'status': 'completed'}}}},
    ]
    _check_readonly_capture({'events': events}, [path])
    # Pi can perform its own native read after allow-once; ACP does not require
    # a second fs/read_text_file callback for that same approved tool.
    _check_readonly_capture({'events': events[:2] + events[3:]}, [path])
    no_request = {'events': events[:1] + events[2:]}
    no_approval = {'events': events[:3]}
    mismatched_permission_path = {'events': [dict(event) for event in events]}
    mismatched_permission_path['events'][1] = {'raw': dict(events[1]['raw'], params={
        **events[1]['raw']['params'], 'files': ['/repo/catalog/other.py'],
        'toolCall': {'toolCallId': tool, 'kind': 'read',
                     'locations': [{'path': '/repo/catalog/other.py'}]}})}
    mismatched_read_path = {'events': [dict(event) for event in events]}
    mismatched_read_path['events'][2] = {'raw': dict(events[2]['raw'], params={
        'path': '/repo/catalog/other.py'})}
    wrong_tool = {'events': [dict(event) for event in events]}
    wrong_tool['events'][3] = {'raw': dict(events[3]['raw'], params={
        **events[3]['raw']['params'], 'update': {
            **events[3]['raw']['params']['update'], 'toolCallId': 'other-tool'}})}
    for malformed in (no_request, no_approval, mismatched_permission_path,
                      mismatched_read_path, wrong_tool):
        with pytest.raises(ApplicationError):
            _check_readonly_capture(malformed, [path])


def test_readonly_capture_allows_pure_text_and_rejects_nonread_tool_activity():
    from ordessa_engineering.application.usecases.changes.declared_report import (
        _check_readonly_capture,
    )
    text_only = {'events': [
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'update': {'sessionUpdate': 'agent_message_chunk',
                       'content': {'type': 'text', 'text': '{"profile_ref":{}}'}}}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'update': {'sessionUpdate': 'agent_thought_chunk',
                       'content': {'type': 'text', 'text': 'Format-only correction.'}}}}},
        {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
            'update': {'sessionUpdate': 'usage_update', 'usage': {'inputTokens': 12}}}}},
    ]}
    _check_readonly_capture(text_only, ['/repo/catalog/views.py'])
    _check_readonly_capture({'events': []}, ['/repo/catalog/views.py'])

    tool_id = 'unauthorized-tool'
    for kind in ('execute', 'edit'):
        bad_events = [
            {'raw': {'jsonrpc': '2.0', 'method': 'session/update', 'params': {
                'update': {'sessionUpdate': 'tool_call_update', 'toolCallId': tool_id,
                           'kind': kind, 'status': 'in_progress'}}}},
        ]
        with pytest.raises(ApplicationError):
            _check_readonly_capture({'events': bad_events}, ['/repo/catalog/views.py'])


@pytest.mark.parametrize('mutate', [
    lambda g: g.origin.update(expected_dispatch_version=3),
    lambda g: g.origin.update(expected_parent_version=True),
    lambda g: g.origin.pop('expected_observation_revision'),
    lambda g: g.evidence.update(files=[]),
    lambda g: g.evidence['files'][0].update(path='catalog/views.py'),
    lambda g: g.evidence['check'].update(limitation='trusted'),
    lambda g: g.evidence['check'].update(origin_operation_ref='op-other'),
])
def test_prepare_rejects_any_selector_or_evidence_drift(tmp_path, mutate):
    g = _graph(tmp_path)
    mutate(g)
    with pytest.raises(ApplicationError) as refused:
        _prepare(g)
    assert refused.value.code in {'SUBMISSION_REPORT_CORRECTION_INVALID',
                                  'SUBMISSION_REPORT_CORRECTION_ORIGIN_MISMATCH',
                                  'SUBMISSION_REPORT_CORRECTION_FILE_INVALID',
                                  'SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH'}


def test_validate_rejects_a_non_correction_checkpoint(tmp_path):
    g = _graph(tmp_path)
    other = g.blobs.put_verified(canonical_bytes({'contract': 'other/1'}),
                                 _digest(canonical_bytes({'contract': 'other/1'})), 'application/json')
    with pytest.raises(ApplicationError) as refused:
        g.source.validate_correction(_context(), checkpoint_ref=other)
    assert refused.value.code == 'SUBMISSION_REPORT_BINDING_MISMATCH'


def test_validate_rejects_an_open_or_incomplete_checkpoint_before_unit_query(tmp_path):
    g = _graph(tmp_path)
    raw = canonical_bytes({'contract': 'ordessa.declared-report-format-rework/1',
                           'plan_ref': {}, 'correction': {}})
    checkpoint_ref = g.blobs.put_verified(raw, _digest(raw), 'application/json')
    with pytest.raises(ApplicationError) as refused:
        g.source.validate_correction(_context(), checkpoint_ref=checkpoint_ref)
    assert refused.value.code == 'SUBMISSION_REPORT_CORRECTION_INVALID'


def test_finish_refuses_a_claim_that_was_never_committed(tmp_path):
    g = _graph(tmp_path)
    raw = canonical_bytes({'contract': REWORK_PLAN_CONTRACT, 'rule': REWORK_RULE,
                           'origin': {}, 'evidence': {}})
    plan_ref = g.blobs.put_verified(raw, _digest(raw), 'application/json')
    from ordessa_engineering.domain.reviews.refs import SubmissionRef
    submission_ref = SubmissionRef(SCOPE.realm_id, SCOPE.project_id, 'work-report-x',
                                   _digest(b'submission'))
    with pytest.raises(ApplicationError):
        g.source.finish_correction_claim(_context(), plan_ref=plan_ref,
                                         submission_ref=submission_ref)
