"""Multi-level CLI metadata, help without a host, save-result and field refs."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

from ordessa_interfaces.system_access import CapabilityHost, build_registry
from ordessa_interfaces_contracts import (
    Capability, CapabilityDescriptor, OperationDescriptor, OperationResult,
    compute_descriptor_digest,
)


def _capabilities(calls):
    async def handler(request, context):
        calls.append((request, context))
        return OperationResult('completed', data={'echo': dict(request)})

    agents = (OperationDescriptor(
        'agents.start', {'type': 'object', 'properties': {
            'instanceRef': {'type': 'object'}, 'force': {'type': 'boolean'}},
            'additionalProperties': False}, {'type': 'object'},
        cli={'command': 'agents', 'operation': 'start',
             'args': ({'name': 'instanceRef', 'flags': ('--instance-ref',),
                       'type': 'json-file'},
                      {'name': 'force', 'flags': ('--force',), 'type': 'boolean'})}),)
    profiles = (OperationDescriptor(
        'profiles.list', {'type': 'object', 'properties': {
            'includeArchived': {'type': 'boolean'}},
            'additionalProperties': False}, {'type': 'object'},
        cli={'command': 'agents profiles', 'operation': 'list',
             'args': ({'name': 'includeArchived', 'flags': ('--include-archived',),
                       'type': 'boolean'},)}),)
    def build(capability_id, operations):
        base = CapabilityDescriptor(capability_id, 'test/1', operations, '')
        return Capability(
            CapabilityDescriptor(capability_id, 'test/1', operations,
                                 compute_descriptor_digest(base)),
            {operation.id: handler for operation in operations})
    return build('agents', agents), build('profiles', profiles)


def _host(calls):
    agents, profiles = _capabilities(calls)
    return CapabilityHost(build_registry([agents, profiles]), ('agents', 'profiles'))


def _metadata(calls):
    agents, profiles = _capabilities(calls)
    return (*agents.descriptor.operations, *profiles.descriptor.operations)


def _run(argv, *, host=None, metadata=(), stdin=b''):
    from ordessa_interfaces.channels import cli
    out, err = io.StringIO(), io.StringIO()
    code = cli.run(argv, host=host, authenticate=lambda command: {'id': 'test'},
                   metadata=metadata, stdin=io.BytesIO(stdin),
                   stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_longest_command_path_wins_and_reaches_the_same_handler():
    calls = []
    code, output, error = _run(['agents', 'profiles', 'list', '--json'], host=_host(calls))
    assert code == 0 and error == ''
    assert calls[0][0] == {}
    assert json.loads(output)['data'] == {'echo': {}}
    assert json.loads(output)['requestId']


def test_boolean_switch_and_field_reference_before_effect(tmp_path):
    calls = []
    source = tmp_path / 'start.json'
    source.write_text(json.dumps({'data': {'instanceRef': {'schemaVersion': 'agent-instance/1'}}}))
    code, output, _ = _run(['agents', 'start',
                            '--instance-ref', str(source) + '#/data/instanceRef',
                            '--force', '--json'], host=_host(calls))
    assert code == 0
    assert calls[0][0] == {'instanceRef': {'schemaVersion': 'agent-instance/1'}, 'force': True}

    calls.clear()
    code, output, _ = _run(['agents', 'start',
                            '--instance-ref', str(source) + '#/data/missing',
                            '--json'], host=_host(calls))
    assert code == 2 and calls == []
    assert json.loads(output)['error']['code'] == 'INVALID_INPUT'


def test_help_and_list_need_no_host_or_state():
    calls = []
    code, output, error = _run(['agents', 'profiles', '--help'], metadata=_metadata(calls))
    assert code == 0 and 'usage: ordessa agents profiles list' in output and calls == []
    code, output, _ = _run(['--help'], metadata=_metadata(calls))
    assert code == 0 and 'agents' in output and 'profiles' in output and calls == []
    code, output, _ = _run(['list', '--json'], metadata=_metadata(calls))
    assert code == 0 and {item['id'] for item in json.loads(output)['data']['operations']} == {
        'agents.start', 'profiles.list'}
    assert calls == []


def test_duplicate_command_metadata_is_refused_before_dispatch():
    calls = []
    metadata = _metadata(calls)
    duplicate = (metadata[0], metadata[1], operation_copy(metadata[1]))
    code, output, _ = _run(['agents', 'profiles', 'list', '--json'], metadata=duplicate)
    assert code == 2 and calls == []
    assert json.loads(output)['error']['code'] == 'INVALID_INPUT'


def test_save_result_is_exactly_once_and_never_overwrites(tmp_path):
    calls = []
    target = tmp_path / 'result.json'
    code, _, _ = _run(['agents', 'profiles', 'list', '--json',
                       '--save-result', str(target)], host=_host(calls))
    assert code == 0 and len(calls) == 1
    saved = json.loads(target.read_text())
    assert saved['apiVersion'] == 'agent-tools/1' and saved['status'] == 'completed'
    assert oct(target.stat().st_mode & 0o777) == '0o600'

    code, output, _ = _run(['agents', 'profiles', 'list', '--json',
                            '--save-result', str(target)], host=_host(calls))
    assert code == 5 and len(calls) == 1
    assert json.loads(output)['error']['code'] == 'CONFLICT'


def test_timeout_sets_a_bounded_monotonic_deadline():
    calls = []
    code, _, _ = _run(['agents', 'profiles', 'list', '--json', '--timeout', '5'],
                      host=_host(calls))
    assert code == 0
    deadline = calls[0][1].deadline
    assert deadline is not None and deadline > 0
    code, _, _ = _run(['agents', 'profiles', 'list', '--json', '--timeout', '0'],
                      host=_host(calls))
    assert code == 2 and len(calls) == 1


def operation_copy(descriptor):
    from ordessa_interfaces_contracts import OperationDescriptor
    return OperationDescriptor(descriptor.id, descriptor.input_schema,
                               descriptor.output_schema, descriptor.scopes,
                               descriptor.cli, descriptor.mcp)


def test_unknown_fields_and_oversized_json_are_refused_before_effect(tmp_path):
    calls = []
    code, output, _ = _run(['call', 'agents.start', '--input', '-', '--json'],
                           host=_host(calls),
                           stdin=json.dumps({'instanceRef': {}, 'force': True,
                                             'unknown': 1}).encode())
    assert code == 2 and calls == []
    assert json.loads(output)['error']['code'] == 'INVALID_INPUT'

    oversized = tmp_path / 'oversized.json'
    oversized.write_bytes(b'{"x":"' + b'a' * (1 << 20) + b'"}')
    code, output, _ = _run(['agents', 'start', '--instance-ref', str(oversized),
                            '--json'], host=_host(calls))
    assert code == 2 and calls == []
    assert json.loads(output)['error']['code'] == 'INVALID_INPUT'
