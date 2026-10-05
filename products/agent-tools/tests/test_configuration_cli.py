"""C: actual published SQLite Node + Core handler; controlled owner, no native task."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'docs/implementation/agent-tools/evidence/agent-unit-model'))
from test_management import setup, node_fixture, explicit_capabilities
from test_discovery import SECRET, config
from pacthold.agents.public import agent_services, encode_node_ref
from ordessa_server.agent_core_wire import agent_core_methods
from server_plugin_api import WireError
from ordessa_agent_tools.cli import main


@contextmanager
def observation_server(parts, mode='healthy'):
    services = agent_services(parts[1])
    # Use the same actual published Node and admitted controlled owner. No issuer
    # is installed here: describing capabilities requires only read admission.
    assert services.configuration.capabilities()['configurationManagement'] is False
    handlers = {method.method_id: method.handler for method in agent_core_methods(lambda: parts[1], contract_version='agent-assembly/2')}
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
                    if mode == 'forbidden' and method.endswith('.describe'): parts[2].allowed = False
                    result = handlers[method](request['params'])
                    if method == 'agents.capabilities' and mode == 'missing':
                        result['supportedMethods'].remove('agents.nodes.configuration.describe')
                    if method.endswith('.describe'):
                        item = result['descriptions'][0]
                        if mode == 'duplicate': result['descriptions'].append(dict(item))
                        if mode == 'actions': item['supportedActions'] = ['fabricated']
                        if mode == 'scope': item['scope'] = None
                        if mode == 'status': item['supportStatus'] = 'ready'
                        if mode == 'secret': item['inputSchema'] = {'private': SECRET}
                        if mode == 'descriptions-object': result['descriptions'] = {}
                        if mode == 'element-bool': result['descriptions'] = [True]
                        if mode == 'actions-object': item['supportedActions'] = [{}]
                        if mode == 'modes-list': item['applicationModes'] = [[]]
                        if mode == 'actions-bool': item['supportedActions'] = [True]
                        if mode == 'scope-object': item['scope'] = {}
                        if mode == 'confirmation-list': item['confirmation'] = []
                        if mode == 'schema-list': item['inputSchema'] = []
                body = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
            except WireError as error:
                body = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': error.family, 'message': SECRET}}
            raw = json.dumps(body).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    try: yield 'http://127.0.0.1:' + str(httpd.server_port), calls
    finally: httpd.shutdown(); httpd.server_close(); thread.join()


def invoke(parts, tmp_path, monkeypatch, capsys, mode='healthy', ref=None):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with observation_server(parts, mode) as (endpoint, calls):
        node = encode_node_ref(parts[4]) if ref is None else ref
        code = main(['nodes', 'configuration', 'describe', json.dumps(node), '--config', str(config(tmp_path, endpoint)), '--service', 'local', '--json'])
        output = capsys.readouterr()
        assert SECRET not in output.out + output.err
        return code, json.loads(output.out), calls


def test_description_with_no_issuer_reads_owner_without_effect(setup, tmp_path, monkeypatch, capsys):
    code, result, calls = invoke(setup, tmp_path, monkeypatch, capsys)
    assert code == 0 and result['status'] == 'confirmed'
    assert result['data']['descriptions'][0]['configurationKind'] == 'model'
    assert result['evidence'] == {'level': 'configurationDescriptionObserved', 'runtimeVerified': False, 'configurationValuesObserved': False}
    assert [call['method'] for call in calls] == ['server.hello', 'agents.capabilities', 'agents.nodes.configuration.describe']
    assert setup[7]['calls'] == 0 and setup[7]['queryCalls'] == 0
    assert setup[0].read_operation(setup[5]) is None


@pytest.mark.parametrize('mode', ['duplicate', 'actions', 'scope', 'status', 'secret', 'descriptions-object', 'element-bool', 'actions-object', 'modes-list', 'actions-bool', 'scope-object', 'confirmation-list', 'schema-list'])
def test_description_invalid_results_refused_without_effect(setup, tmp_path, monkeypatch, capsys, mode):
    code, result, calls = invoke(setup, tmp_path, monkeypatch, capsys, mode)
    assert code == 4 and result['error']['code'] == 'CORE_RESPONSE_INVALID'
    assert 'descriptions' not in result['data'] and len(calls) == 3
    assert setup[7]['calls'] == 0


@pytest.mark.parametrize('mode,expected,count', [('missing', 4, 2), ('forbidden', 3, 3)])
def test_missing_method_or_authority_never_claims_success(setup, tmp_path, monkeypatch, capsys, mode, expected, count):
    code, result, calls = invoke(setup, tmp_path, monkeypatch, capsys, mode)
    assert code == expected and result['status'] == 'refused' and len(calls) == count
    assert setup[7]['calls'] == 0


@pytest.mark.parametrize('ref,count', [({'environmentNamespace':'env','instanceId':'node','generation':True},0),
    ({'environmentNamespace':'foreign','instanceId':'node','generation':1},2),
    ({'environmentNamespace':'env','instanceId':'node','generation':1,'principal':'forged'},0)])
def test_complete_node_identity_checked_before_observation(setup, tmp_path, monkeypatch, capsys, ref, count):
    code, result, calls = invoke(setup, tmp_path, monkeypatch, capsys, ref=ref)
    assert code == 2 and result['error']['code'] == 'PARAMETER_INVALID' and len(calls) == count
    assert setup[7]['calls'] == 0


@pytest.mark.parametrize('resource', ['node', 'owner'])
def test_absent_published_node_or_retired_owner_refused(setup, tmp_path, monkeypatch, capsys, resource):
    ref = encode_node_ref(setup[4])
    if resource == 'node': ref['instanceId'] = 'absent'
    else:
        activation = setup[1].agent_runtime_contribution(setup[3]._nodes.read(setup[4])['binding']['harnessDefinitionRef']).provider_ref
        from ordessa_environment_api.identity import ActivationRef
        owner = activation['ownerActivationRef']
        setup[1].retire_activation(ActivationRef(owner['environmentNamespace'], owner['pluginId'], owner['generation']))
    code, result, calls = invoke(setup, tmp_path, monkeypatch, capsys, ref=ref)
    assert code == (4 if resource == 'node' else 3)
    assert result['status'] == 'refused' and len(calls) == 3
    assert setup[7]['calls'] == 0 and setup[7]['queryCalls'] == 0
