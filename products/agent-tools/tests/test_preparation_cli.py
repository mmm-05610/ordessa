"""C: actual preparation Core/SQLite/issuer plus controlled HTTP and owner."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'docs/implementation/agent-tools/evidence/agent-unit-model'))
from test_assembly import assembly
from pacthold.agents.public import agent_services, AGENT_MANAGEMENT_CONTRACT_VERSION, ProfileRef
from ordessa_environment_api.operations import safe_json
from ordessa_server.agent_core_wire import agent_core_methods
from server_plugin_api import WireError
from ordessa_agent_tools.cli import main
from test_discovery import SECRET, config


@contextmanager
def server(parts, mode='healthy'):
    services = agent_services(parts[10], invocation_issuer=parts[3].issuer, node_evidence_port=parts[9],
        preparation_context_port=parts[8], preparation_observation_port=parts[9])
    handlers = {item.method_id: item.handler for item in agent_core_methods(lambda: parts[10], contract_version=AGENT_MANAGEMENT_CONTRACT_VERSION)}
    if mode == 'absent-port': services.assembly._context_port = None
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(request)
            assert self.headers['Authorization'] == 'Bearer ' + SECRET
            method = request['method']
            try:
                if method == 'server.hello':
                    result = {'serverId': 'controlled-core', 'protocolVersion': 'wire/1',
                        'auth': {'required': True, 'schemes': ['session_token']},
                        'capabilities': [{'id': name, 'supported': True} for name in handlers]}
                else:
                    if method == 'agents.nodes.prepare' and mode == 'forbidden': parts[10]._policy.allowed = False
                    if method == 'agents.nodes.prepare' and mode == 'reserved':
                        params = request['params']
                        op = services.assembly.reserve(services.profiles.request_key(params['requestId']),
                            ProfileRef.from_dict(params['profileRef']), params['context'], params['options'])
                        result = json.loads(safe_json(services.assembly.operation_view(op)))
                    else:
                        result = handlers[method](request['params'])
                    if method == 'agents.capabilities' and mode == 'missing':
                        result['supportedMethods'].remove('agents.nodes.prepare')
                    if method == 'agents.nodes.prepare':
                        if mode == 'receipt-lost':
                            self.close_connection = True; self.connection.close(); return
                        if mode == 'bool-revision': result['revision'] = True
                        if mode == 'wrong-profile': result['node']['lineage']['profileSnapshotRef']['manifestRevision'] += 1
                        if mode == 'wrong-operation': result['operationRef'] = 'other-operation'
                        if mode == 'wrong-context': result['node']['lineage']['preparationContextRef']['preparationRequest']['options']['other'] = True
                        if mode == 'ready': result['node']['ready'] = True
                        if mode == 'private': result['node']['binding']['harnessUnitRef']['stdout'] = 'must-not-emit'
                        if mode == 'token': result['operationRef'] = SECRET
                        if mode == 'malformed': result = []
                body = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
            except WireError as error:
                body = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': error.family, 'message': SECRET}}
            raw = json.dumps(body).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    try: yield 'http://127.0.0.1:' + str(httpd.server_port), calls
    finally: httpd.shutdown(); httpd.server_close(); thread.join()


def fixed(parts):
    return {'requestId': parts[1].request_id, 'profileRef': parts[2].to_dict(), 'context': {}, 'options': {}}


def invoke(parts, tmp_path, monkeypatch, capsys, mode='healthy', request=None, twice=False):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    path = tmp_path / 'preparation.json'; path.write_text(json.dumps(fixed(parts) if request is None else request))
    with server(parts, mode) as (endpoint, calls):
        args = ['nodes', 'prepare', '--file', str(path), '--config', str(config(tmp_path, endpoint)), '--service', 'local', '--json']
        results = []
        for _ in range(2 if twice else 1):
            code = main(args); out = capsys.readouterr()
            assert SECRET not in out.out + out.err and 'must-not-emit' not in out.out
            results.append((code, json.loads(out.out)))
        return results, calls


def test_fixed_prepare_publishes_and_replays_without_another_dispatch(assembly, tmp_path, monkeypatch, capsys):
    results, calls = invoke(assembly, tmp_path, monkeypatch, capsys, twice=True)
    assert all(code == 0 and item['status'] == 'confirmed' for code, item in results)
    assert results[0][1]['data'] == results[1][1]['data']
    item = results[0][1]
    assert item['requestId'] == assembly[1].request_id
    assert item['operationRef'] == item['data']['node']['binding']['operationRef']
    assert item['evidence'] == {'level': 'preparationOperationObserved', 'runtimeVerified': False, 'nodePublished': True}
    assert assembly[3].calls == ['prepare', 'start']
    dispatched = [call for call in calls if call['method'] == 'agents.nodes.prepare']
    assert len(dispatched) == 2 and all(call['id'] == call['params']['requestId'] == assembly[1].request_id for call in dispatched)


@pytest.mark.parametrize('action', ['prepare', 'start'])
def test_native_unknown_keeps_original_key_no_automatic_resend(assembly, tmp_path, monkeypatch, capsys, action):
    assembly[3].fail = action
    results, calls = invoke(assembly, tmp_path, monkeypatch, capsys)
    code, item = results[0]
    assert code == 6 and item['status'] == 'unknown' and item['data']['node'] is None
    assert item['operationRef'] == assembly[4].read_operation(assembly[1]).intent.operation_ref
    assert item['requestId'] == assembly[1].request_id and item['error']['retryable'] is False
    assert len([call for call in calls if call['method'] == 'agents.nodes.prepare']) == 1
    assert assembly[5].list() == ()
    assert assembly[3].calls == (['prepare'] if action == 'prepare' else ['prepare', 'start'])


@pytest.mark.parametrize('mode', ['receipt-lost', 'bool-revision', 'wrong-profile', 'wrong-operation', 'wrong-context', 'ready', 'private', 'token', 'malformed'])
def test_committed_bad_or_missing_receipt_is_unknown_not_no_effect(assembly, tmp_path, monkeypatch, capsys, mode):
    results, calls = invoke(assembly, tmp_path, monkeypatch, capsys, mode=mode)
    code, item = results[0]
    assert code == 6 and item['status'] == 'unknown' and item['operationRef'] is None
    assert item['requestId'] == assembly[1].request_id and item['error']['retryable'] is False
    assert assembly[4].read_operation(assembly[1]).status == 'published'
    assert assembly[3].calls == ['prepare', 'start'] and len(calls) == 3


@pytest.mark.parametrize('mutation,count', [('extra',0), ('context-list',0), ('options-list',0), ('bool-profile',0), ('float-profile',0), ('foreign',2), ('path',0), ('credential',0), ('request-id',0), ('nested-foreign',2)])
def test_invalid_request_refused_before_effect(assembly, tmp_path, monkeypatch, capsys, mutation, count):
    request = fixed(assembly)
    if mutation == 'extra': request['native'] = True
    elif mutation == 'context-list': request['context'] = []
    elif mutation == 'options-list': request['options'] = []
    elif mutation in ('bool-profile', 'float-profile'): request['profileRef']['manifestRevision'] = True if mutation == 'bool-profile' else 1.0
    elif mutation == 'foreign': request['profileRef']['environmentNamespace'] = 'foreign'
    elif mutation == 'path': request['context'] = {'nested': {'cwd': '/caller/private'}}
    elif mutation == 'credential': request['options'] = {'password': 'must-not-emit'}
    elif mutation == 'request-id': request['requestId'] = 'Bad:request'
    else: request['context'] = {'binding': {'environmentNamespace': 'foreign', 'ref': 'other'}}
    results, calls = invoke(assembly, tmp_path, monkeypatch, capsys, request=request)
    code, item = results[0]
    assert code == 2 and item['error']['code'] == 'PARAMETER_INVALID' and len(calls) == count
    assert assembly[4].read_operation(assembly[1]) is None and assembly[3].calls == []


@pytest.mark.parametrize('mode,expected,count', [('missing',4,2), ('forbidden',3,3)])
def test_missing_method_and_permission_do_not_prepare(assembly, tmp_path, monkeypatch, capsys, mode, expected, count):
    results, calls = invoke(assembly, tmp_path, monkeypatch, capsys, mode=mode)
    assert results[0][0] == expected and len(calls) == count
    assert assembly[4].read_operation(assembly[1]) is None and assembly[3].calls == []


@pytest.mark.parametrize('field', ['context', 'options'])
def test_spent_request_changed_parameters_conflict_without_effect(assembly, tmp_path, monkeypatch, capsys, field):
    first, _ = invoke(assembly, tmp_path, monkeypatch, capsys)
    assert first[0][0] == 0
    request = fixed(assembly); request[field] = {'different': True}
    second, calls = invoke(assembly, tmp_path, monkeypatch, capsys, request=request)
    assert second[0][0] == 5 and second[0][1]['error']['retryable'] is False
    assert assembly[3].calls == ['prepare', 'start'] and len(calls) == 3


def test_absent_deployment_port_refuses_before_spending_key(assembly, tmp_path, monkeypatch, capsys):
    results, calls = invoke(assembly, tmp_path, monkeypatch, capsys, mode='absent-port')
    assert results[0][0] == 4 and results[0][1]['error']['code'] == 'NODE_PREPARATION_UNAVAILABLE'
    assert len(calls) == 2 and assembly[4].read_operation(assembly[1]) is None
    assert assembly[3].calls == []



def test_reserved_operation_is_unknown_to_cli_and_does_not_dispatch(assembly, tmp_path, monkeypatch, capsys):
    results, calls = invoke(assembly, tmp_path, monkeypatch, capsys, mode='reserved')
    code, item = results[0]
    assert code == 6 and item['status'] == 'unknown'
    assert item['data']['status'] == 'reserved' and item['data']['node'] is None
    assert item['operationRef'] == assembly[4].read_operation(assembly[1]).intent.operation_ref
    assert item['evidence']['nodePublished'] is False and assembly[3].calls == []
    assert len(calls) == 3 and assembly[5].list() == ()


@pytest.mark.parametrize('status', ['running', 'unknown', 'refused', 'cancelled'])
def test_original_nonpublished_dto_requires_null_node(assembly, status):
    from ordessa_agent_tools.preparation import result_valid
    from pacthold.agents.public import wire_contract
    op = assembly[0].reserve(assembly[1], assembly[2], {}, {})
    value = assembly[0].operation_view(op); value['status'] = status
    assert result_valid(value, fixed(assembly), 'env', wire_contract(AGENT_MANAGEMENT_CONTRACT_VERSION))
    value['node'] = {'ready': True}
    assert not result_valid(value, fixed(assembly), 'env', wire_contract(AGENT_MANAGEMENT_CONTRACT_VERSION))
