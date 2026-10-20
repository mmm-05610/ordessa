"""Generic CLI channel: metadata mapping, --json, --, stdin, exit codes."""
from __future__ import annotations

import io
import json

from ordessa_interfaces.system_access.assembly import build_host

from host_fakes import FakeEntryPoint, FakeFactory, make_capability


CLI = {'command': 'demo', 'operation': 'run',
       'args': ({'name': 'value', 'flags': ('--value',), 'type': 'integer', 'required': True},
                {'name': 'note', 'flags': ('--note',), 'type': 'string'},
                {'name': 'payload', 'flags': ('--payload',), 'type': 'json-file',
                 'jsonPath': 'body'})}


def _host(schema=None):
    capability = make_capability('demo', operation_ids=('demo.run',), cli=CLI,
                                 mcp={'tool': 'demo_run'}, input_schema=schema)
    return build_host(('demo',), {'services': object(), 'invocation_resolver': object()},
                      entry_points=(FakeEntryPoint('demo', FakeFactory(capability)),))


def _run(argv, stdin=b''):
    from ordessa_interfaces.channels import cli
    out, err = io.StringIO(), io.StringIO()
    code = cli.run(argv, host=_host(),
                           authenticate=lambda command: {'principalId': 'test'},
                           stdin=io.BytesIO(stdin), stdout=out, stderr=err)
    return code, out.getvalue()


def test_metadata_command_builds_the_request_and_prints_one_envelope():
    code, output = _run(['demo', 'run', '--value', '3', '--json'])
    assert code == 0
    envelope = json.loads(output)
    assert envelope['apiVersion'] == 'agent-tools/1'
    assert envelope['status'] == 'completed'
    assert envelope['data'] == {'value': 3}


def test_json_file_argument_and_nested_json_path(tmp_path):
    payload = tmp_path / 'payload.json'
    payload.write_text(json.dumps({'nested': True}))
    from ordessa_interfaces.channels import cli
    import io
    out = io.StringIO()
    code = cli.run(['demo', 'run', '--value', '1', '--payload', str(payload), '--json'],
                           host=_host(schema={'type': 'object'}),
                           authenticate=lambda command: {'principalId': 'test'},
                           stdin=io.BytesIO(b''), stdout=out, stderr=io.StringIO())
    assert code == 0
    assert json.loads(out.getvalue())['data'] == {'value': 1, 'body': {'nested': True}}


def test_call_with_input_file_stdin_and_json_mode(tmp_path):
    source = tmp_path / 'request.json'
    source.write_text(json.dumps({'value': 2}))
    code, output = _run(['call', 'demo.run', '--input', str(source), '--json'])
    assert code == 0 and json.loads(output)['data'] == {'value': 2}

    code, output = _run(['call', 'demo.run', '--input', '-', '--json'], stdin=b'{"value":4}')
    assert code == 0 and json.loads(output)['data'] == {'value': 4}


def test_invalid_input_refuses_with_exit_two_and_no_effect():
    code, output = _run(['demo', 'run', '--value', 'NaN', '--json'])
    assert code == 2
    envelope = json.loads(output)
    assert envelope['status'] == 'refused' and envelope['error']['code'] == 'INVALID_INPUT'


def test_unknown_command_is_unsupported_exit_four():
    code, output = _run(['unknown', 'thing', '--json'])
    assert code == 4
    assert json.loads(output)['error']['code'] == 'CAPABILITY_UNSUPPORTED'


MULTI = {'command': 'multi', 'operation': 'run',
         'args': ({'name': 'root', 'flags': ('--root',), 'type': 'string', 'required': True},
                  {'name': 'files', 'flags': ('--file',), 'type': 'string', 'nargs': '+'},
                  {'name': 'note', 'flags': ('--note',), 'type': 'string', 'nargs': '?'},
                  {'name': 'rest', 'flags': ('--rest',), 'type': 'string', 'nargs': 'REMAINDER'})}


def _multi_host():
    capability = make_capability('multi', operation_ids=('multi.run',), cli=MULTI,
                                 input_schema={'type': 'object'})
    return build_host(('multi',), {'services': object(), 'invocation_resolver': object()},
                      entry_points=(FakeEntryPoint('multi', FakeFactory(capability)),))


def test_nargs_plus_remainder_and_operand_separator():
    from ordessa_interfaces.channels import cli
    import io
    out = io.StringIO()
    code = cli.run(['multi', 'run', '--root', '/w', '--file', 'a', 'b',
                            '--rest', '--', 'p1', 'p2', '--json'],
                           host=_multi_host(),
                           authenticate=lambda command: {'principalId': 'test'},
                           stdin=io.BytesIO(b''), stdout=out, stderr=io.StringIO())
    assert code == 0
    data = json.loads(out.getvalue())['data']
    assert data == {'root': '/w', 'files': ['a', 'b'], 'rest': ['p1', 'p2']}


def test_optional_nargs_question_omits_missing_value():
    from ordessa_interfaces.channels import cli
    import io
    out = io.StringIO()
    code = cli.run(['multi', 'run', '--root', '/w', '--json'],
                           host=_multi_host(),
                           authenticate=lambda command: {'principalId': 'test'},
                           stdin=io.BytesIO(b''), stdout=out, stderr=io.StringIO())
    assert code == 0
    assert json.loads(out.getvalue())['data'] == {'root': '/w'}


def test_list_describe_and_dashdash_separator():
    code, output = _run(['list', '--json'])
    assert code == 0 and json.loads(output)['data']['operations'][0]['id'] == 'demo.run'
    code, output = _run(['describe', 'demo.run', '--json'])
    assert code == 0 and json.loads(output)['data']['operation']['inputSchema']['type'] == 'object'
    # '--' ends option parsing; metadata args after it are still arguments.
    code, output = _run(['demo', 'run', '--', '--value', '5', '--json'])
    assert code == 2  # after -- the tokens are operands, not the --value flag


def test_declarative_and_call_forms_share_the_same_envelope(tmp_path):
    source = tmp_path / 'request.json'
    source.write_text(json.dumps({'value': 3}))
    declarative_code, declarative_out = _run(['demo', 'run', '--value', '3',
                                              '--json', '--request-id', 'fixed'])
    call_code, call_out = _run(['call', 'demo.run', '--input', str(source),
                                '--json', '--request-id', 'fixed'])
    assert (declarative_code, call_code) == (0, 0)
    declarative = json.loads(declarative_out)
    called = json.loads(call_out)
    for key in ('apiVersion', 'requestId', 'status', 'data', 'error',
                'operationRef', 'evidenceRefs'):
        assert declarative[key] == called[key]
