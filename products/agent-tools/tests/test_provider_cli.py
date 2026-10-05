"""C: CLI over temporary HTTP to actual CoreRegistry wire handlers.

This is not Server transport/product acceptance or native installation evidence.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).parent / 'integration'))
from test_runtime_admission import installed, Provider
from test_discovery import SECRET, config
from pacthold.agents.public import AGENT_MANAGEMENT_CONTRACT_VERSION, wire_contract, wire_schema_digest
from pacthold.agents.runtime import AgentContributionSet
from ordessa_server.agent_core_wire import agent_core_methods
from server_plugin_api import WireError
from ordessa_agent_tools.cli import main
from ordessa_agent_tools.client import core_schema


@contextmanager
def provider_server(mode='healthy', version=AGENT_MANAGEMENT_CONTRACT_VERSION):
    env, policy = installed()
    provider = Provider()
    stage = env.stage_activation('fixture.plugin', AgentContributionSet(agent_runtime_providers=(provider,)))
    if mode != 'staged': stage.commit()
    handlers = {item.method_id: item.handler for item in agent_core_methods(lambda: env, contract_version=version)}
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
                    result = {'serverId': 'controlled-core-wire', 'protocolVersion': 'wire/1',
                              'auth': {'required': True, 'schemes': ['session_token']},
                              'capabilities': [{'id': name, 'supported': True} for name in handlers]}
                else:
                    if mode == 'forbidden' and method.startswith('agents.providers.'): policy.allowed = False
                    result = handlers[method](request['params'])
                    if method == 'agents.capabilities':
                        if mode == 'missing': result['supportedMethods'].remove('agents.providers.list')
                        if mode == 'bad-digest': result['schemaDigest'] = 'sha256:' + '0' * 64
                        if mode == 'duplicate-method': result['supportedMethods'].append(result['supportedMethods'][0])
                        if mode == 'bool-schema': result['schema']['profileRef']['properties']['manifestRevision']['minimum'] = True
                    elif method.startswith('agents.providers.'):
                        values = result['providers'] if method.endswith('list') else [result]
                        if mode == 'duplicate-provider': values.append(values[0])
                        if mode == 'unknown-method': values[0]['descriptor']['supportedMethods'].append('fabricated_method')
                        if mode == 'secret': values[0]['descriptor']['definitionRef']['definitionId'] = SECRET
                        if mode == 'generation-bool': values[0]['providerRef']['generation'] = True
                        if mode == 'owner-mismatch': values[0]['providerRef']['ownerActivationRef']['generation'] += 1
                        if mode == 'foreign-env': values[0]['providerRef']['environmentNamespace'] = 'foreign'
                        if mode == 'wrong-definition': values[0]['descriptor']['definitionRef']['revision'] = 'different'
                body = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
            except WireError as error:
                body = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': error.family, 'message': SECRET}}
            raw = json.dumps(body).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    try:
        yield 'http://127.0.0.1:' + str(httpd.server_port), calls, provider.descriptor.definition_ref
    finally:
        httpd.shutdown(); httpd.server_close(); thread.join(); env.close()


def invoke(tmp_path, monkeypatch, capsys, action, mode='healthy', version=AGENT_MANAGEMENT_CONTRACT_VERSION):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with provider_server(mode, version) as (endpoint, calls, definition):
        command = ['providers', action]
        if action == 'describe': command.append(json.dumps(dict(definition)))
        code = main(command + ['--config', str(config(tmp_path, endpoint)), '--service', 'local', '--json'])
        output = capsys.readouterr()
        assert SECRET not in output.out + output.err
        return code, json.loads(output.out), calls


@pytest.mark.parametrize('action', ['list', 'describe'])
def test_provider_cli_uses_actual_public_registry_only(tmp_path, monkeypatch, capsys, action):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, action)
    assert code == 0 and result['status'] == 'confirmed'
    assert result['evidence'] == {'level': 'providerRegistryObserved', 'runtimeVerified': False}
    view = result['data']['providers'][0] if action == 'list' else result['data']
    assert view['descriptor']['providerId'] == 'fixture.runtime'
    assert view['providerRef']['ownerActivationRef']['pluginId'] == 'fixture.plugin'
    assert [call['method'] for call in calls] == ['server.hello', 'agents.capabilities', 'agents.providers.' + action]


def test_staged_registry_is_empty_without_claiming_ready(tmp_path, monkeypatch, capsys):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, 'list', 'staged')
    assert code == 0 and result['data'] == {'providers': []} and result['evidence']['runtimeVerified'] is False


@pytest.mark.parametrize('mode', ['missing', 'bad-digest', 'duplicate-method', 'bool-schema'])
def test_bad_or_missing_core_contract_never_calls_provider(tmp_path, monkeypatch, capsys, mode):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, 'list', mode)
    assert code == 4 and result['status'] == 'refused' and len(calls) == 2


@pytest.mark.parametrize('mode', ['duplicate-provider', 'secret', 'generation-bool', 'owner-mismatch', 'foreign-env', 'unknown-method'])
def test_invalid_public_provider_identity_never_emits_result(tmp_path, monkeypatch, capsys, mode):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, 'list', mode)
    assert code == 4 and result['error']['code'] == 'CORE_RESPONSE_INVALID' and len(calls) == 3
    assert result['evidence']['level'] == 'coreCapabilitiesObserved'


def test_describe_wrong_complete_definition_refused(tmp_path, monkeypatch, capsys):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, 'describe', 'wrong-definition')
    assert code == 4 and result['error']['code'] == 'CORE_RESPONSE_INVALID'


def test_public_registry_authorization_is_enforced(tmp_path, monkeypatch, capsys):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, 'list', 'forbidden')
    assert code == 3 and result['error']['code'] == 'AUTHORIZATION_REFUSED' and len(calls) == 3


def test_old_profile_contract_refuses_providers_without_fallback(tmp_path, monkeypatch, capsys):
    code, result, calls = invoke(tmp_path, monkeypatch, capsys, 'list', version='agent-assembly/1')
    assert code == 4 and result['error']['code'] == 'PROVIDER_DISCOVERY_UNAVAILABLE' and len(calls) == 2


def test_generated_management_schema_is_exact_public_authority():
    assert core_schema(AGENT_MANAGEMENT_CONTRACT_VERSION) == {
        'schema': wire_contract(AGENT_MANAGEMENT_CONTRACT_VERSION), 'schemaDigest': wire_schema_digest(AGENT_MANAGEMENT_CONTRACT_VERSION)}
