"""Real env capability descriptor through the generic CLI host.

The env factory/descriptor comes from ``ordessa_environments.capability``; only
the owner service is a controlled stub so the test stays offline. No env or
server source is modified.
"""
from __future__ import annotations

import io
import json

from ordessa_environments import capability as envcap
from ordessa_interfaces.system_access.assembly import build_host
from ordessa_interfaces_contracts import CapabilityError, OperationResult


def _entry(factory):
    return type('Entry', (), {'name': 'environments',
                              'load': staticmethod(lambda: {'factory': factory})})()


def _host(replies=None):
    replies = replies or {}
    service = object.__new__(envcap.EnvironmentCapabilityService)
    calls = []

    async def invoke(action, request, invocation, request_id):
        calls.append((action, dict(request)))
        if action in replies:
            return replies[action]
        if action == 'exec':
            return OperationResult('completed', data={'exitCode': 3, 'stdout': 'o', 'stderr': 'e'})
        return OperationResult('completed', data={})

    service.invoke = invoke
    host = build_host(('environments',),
                      {'services': service,
                       'invocation_resolver': lambda context: {'stub': True}},
                      entry_points=(_entry(envcap.EnvironmentsCapabilityFactory()),))
    return host, calls


def _run(argv, *, replies=None, stdin=b''):
    from ordessa_interfaces.channels import cli
    host, calls = _host(replies)
    out = io.StringIO()
    code = cli.run(argv, host=host,
                           authenticate=lambda command: {'principalId': 'test'},
                           stdin=io.BytesIO(stdin), stdout=out, stderr=io.StringIO())
    return code, out.getvalue(), calls


def test_providers_without_arguments_still_passes():
    code, output, calls = _run(['environments', 'providers', '--json'])
    assert code == 0
    assert json.loads(output)['status'] == 'completed'
    assert calls == [('providers', {})]


def test_create_maps_positional_provider_and_alias_flag():
    code, output, calls = _run(['environments', 'create', 'local',
                                '--root', '/tmp/x', '--alias', 'demo', '--json'])
    assert code == 0, output
    assert calls == [('create', {'provider': 'local', 'root': '/tmp/x', 'alias': 'demo'})]


def test_inspect_positional_reference_and_files_defaults():
    code, _, calls = _run(['environments', 'inspect', 'demo', '--json'])
    assert code == 0
    assert calls == [('inspect', {'reference': 'demo'})]

    code, _, calls = _run(['environments', 'files', 'demo', 'ls', 'out.txt', '--json'])
    assert code == 0
    assert calls == [('files', {'reference': 'demo', 'verb': 'ls',
                                'path': 'out.txt', 'content': ''})]


def test_exec_remainder_operands_after_dashdash_and_process_output():
    code, output, calls = _run(['environments', 'exec', 'demo', '--', 'echo', 'hi'])
    assert code == 3
    assert calls == [('exec', {'reference': 'demo', 'argv': ['echo', 'hi']})]
    assert output == 'o'


def test_exit_codes_for_refused_conflict_unsupported_and_completed():
    conflict = OperationResult('refused', error=CapabilityError('CONFLICT', 'busy'))
    code, _, _ = _run(['environments', 'delete', 'demo', '--json'], replies={'delete': conflict})
    assert code == 5
    code, output, _ = _run(['environments', 'nope', '--json'])
    assert code == 4 and json.loads(output)['error']['code'] == 'CAPABILITY_UNSUPPORTED'
    code, _, _ = _run(['environments', 'list', '--json'])
    assert code == 0


def test_stdin_pipe_reaches_the_operation_via_call():
    code, output, calls = _run(['call', 'environments.exec', '--input', '-', '--json'],
                               stdin=b'{"reference": "demo", "argv": ["echo"]}')
    assert code == 3
    assert calls == [('exec', {'reference': 'demo', 'argv': ['echo']})]
    assert json.loads(output)['status'] == 'completed'


def _run_full(argv, *, replies=None, stdin=b''):
    from ordessa_interfaces.channels import cli
    host, calls = _host(replies)
    out, err = io.StringIO(), io.StringIO()
    code = cli.run(argv, host=host,
                           authenticate=lambda command: {'principalId': 'test'},
                           stdin=io.BytesIO(stdin), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue(), calls


def test_process_output_is_raw_and_child_exit_is_propagated():
    replies = {'exec': OperationResult('completed', data={
        'exitCode': 1, 'stdout': 'out\n', 'stderr': 'err\n'})}
    code, out, err, calls = _run_full(['environments', 'exec', 'demo', '--', '/bin/false'],
                                      replies=replies)
    assert code == 1
    assert out == 'out\n' and err == 'err\n'
    assert calls == [('exec', {'reference': 'demo', 'argv': ['/bin/false']})]


def test_json_mode_keeps_one_envelope_and_still_propagates_child_exit():
    replies = {'exec': OperationResult('completed', data={
        'exitCode': 3, 'stdout': 'ignored', 'stderr': ''})}
    code, out, err, _ = _run_full(['environments', 'exec', 'demo', '--', '/bin/sh', '--json'],
                                  replies=replies)
    assert code == 3
    lines = out.splitlines()
    assert len(lines) == 1
    envelope = json.loads(lines[0])
    assert envelope['status'] == 'completed'
    assert envelope['data']['exitCode'] == 3
    assert out.count('ignored') == 1  # only inside the envelope, never raw


def test_piped_stdin_reaches_the_declared_stdin_property():
    code, out, err, calls = _run_full(['environments', 'exec', 'demo', '--', '/bin/cat'],
                                      replies={'exec': OperationResult('completed', data={
                                          'exitCode': 0, 'stdout': 'pipe-positive\n', 'stderr': ''})},
                                      stdin=b'pipe-positive\n')
    assert code == 0
    assert calls == [('exec', {'reference': 'demo', 'argv': ['/bin/cat'],
                               'stdin': 'pipe-positive\n'})]
    assert out == 'pipe-positive\n'


def test_refused_process_operation_uses_envelope_exit_code():
    replies = {'exec': OperationResult('refused', error=CapabilityError('CONFLICT', 'busy'))}
    code, out, err, _ = _run_full(['environments', 'exec', 'demo', '--', '/bin/echo'],
                                  replies=replies)
    assert code == 5
    assert 'busy' in out + err
