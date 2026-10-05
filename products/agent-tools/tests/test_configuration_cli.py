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
def observation_server(parts, mode='healthy', managing=False):
    services = agent_services(parts[1], invocation_issuer=parts[10] if managing else None)
    # Use the same actual published Node and admitted controlled owner. No issuer
    # is installed here: describing capabilities requires only read admission.
    assert services.configuration.capabilities()['configurationManagement'] is managing
    handlers = {method.method_id: method.handler for method in agent_core_methods(lambda: parts[1], contract_version='agent-assembly/2')}
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(request)
            assert self.headers['Authorization'] == 'Bearer ' + SECRET
            method = request['method']
            if method.endswith('.inspect') and mode == 'disconnect':
                self.close_connection = True
                self.connection.close()
                return
            try:
                if method == 'server.hello':
                    result = {'serverId': 'controlled-core', 'protocolVersion': 'wire/1',
                              'auth': {'required': True, 'schemes': ['session_token']},
                              'capabilities': [{'id': name, 'supported': True} for name in handlers]}
                else:
                    if mode == 'forbidden' and method.startswith('agents.nodes.configuration.'): parts[2].allowed = False
                    result = handlers[method](request['params'])
                    if method == 'agents.capabilities' and mode == 'missing':
                        result['supportedMethods'] = [name for name in result['supportedMethods'] if not name.startswith('agents.nodes.configuration.')]
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
                    if method.endswith('.inspect'):
                        if mode == 'unknown-outcome':
                            raise WireError('OUTCOME_UNKNOWN', SECRET, {'retryable': False})
                        if mode == 'foreign-unit': result['unitRef']['environmentNamespace'] = 'foreign'
                        if mode == 'foreign-scope': result['scopeRef']['environmentNamespace'] = 'foreign'
                        if mode == 'foreign-proof': result['confirmationEvidence']['environmentNamespace'] = 'foreign'
                        if mode == 'absent-proof': result['confirmationEvidence'] = None
                        if mode == 'unknown-revision': result['sourceRevision'] = None
                        if mode == 'bool-revision': result['sourceRevision'] = True
                        if mode == 'naive-time': result['observedAt'] = '2026-10-05T01:00:00'
                        if mode == 'bool-time': result['observedAt'] = True
                        if mode == 'overlap': result['unknownItems'] = ['model']
                        if mode == 'duplicate-unknown': result['unknownItems'] = ['tools', 'tools']
                        if mode == 'object-unknown': result['unknownItems'] = [{}]
                        if mode == 'desired': result['configuration']['desired'] = {}
                        if mode == 'plaintext': result['configuration']['nested'] = {'password': 'must-not-emit'}
                        if mode == 'secret': result['configuration']['model'] = SECRET
                        if mode == 'bad-secret-ref': result['configuration']['secretRef'] = {'ref': 'invented'}
                        if mode == 'unknown-fields':
                            result['sourceRevision'] = None
                            result['comparisonGuarantee'] = 'unavailable'
                            result['unknownItems'] = ['tools']
                        if mode == 'secret-ref':
                            result['configuration']['credentials'] = {'secretRef': {'ref': 'opaque-ref', 'revision': '1', 'owner_namespace': 'test.owner', 'access_purpose': 'test.read'}}
                    if method.endswith(('.apply', '.query')):
                        if mode == 'receipt-lost' and method.endswith('.apply'):
                            self.close_connection = True
                            self.connection.close()
                            return
                        if mode == 'operation-mismatch': result['operationRef'] = 'other-operation'
                        if mode == 'bool-operation-revision': result['revision'] = True
                        if mode == 'applied-no-proof': result['configurationResult']['itemResults'][0]['confirmation'] = None
                        if mode == 'unknown-published': result['configurationResult']['itemResults'][0]['outcome'] = 'unknown'; result['configurationResult']['overallOutcome'] = 'unknown'
                        if mode == 'wrong-overall': result['configurationResult']['overallOutcome'] = 'partial'
                        if mode == 'missing-item': result['configurationResult']['itemResults'] = []
                        if mode == 'foreign-confirmation': result['configurationResult']['itemResults'][0]['confirmation']['unitRef']['environmentNamespace'] = 'foreign'
                        if mode == 'private-result': result['configurationResult']['itemResults'][0]['confirmation']['evidenceRef']['password'] = 'must-not-emit'
                        if mode in ('bool-unit-identity', 'float-scope-identity'):
                            key = 'unitRef' if mode == 'bool-unit-identity' else 'scopeRef'
                            result['configurationResult']['itemResults'][0]['confirmation'][key]['identityNumber'] = True if mode == 'bool-unit-identity' else 1.0
                            result['configurationResult']['confirmedSnapshot'][key]['identityNumber'] = 1
                        if mode == 'published-deferred':
                            result['configurationResult']['itemResults'][0]['outcome'] = 'deferred'
                            result['configurationResult']['overallOutcome'] = 'deferred'
                        if mode == 'result-secret': result['configurationResult']['itemResults'][0]['confirmation']['evidenceRef']['ref'] = SECRET
                body = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
            except WireError as error:
                body = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': error.family, 'message': SECRET}}
            raw = json.dumps(body).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    try: yield 'http://127.0.0.1:' + str(httpd.server_port), calls
    finally: httpd.shutdown(); httpd.server_close(); thread.join()


def invoke(parts, tmp_path, monkeypatch, capsys, mode='healthy', ref=None, action='describe'):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with observation_server(parts, mode) as (endpoint, calls):
        node = encode_node_ref(parts[4]) if ref is None else ref
        code = main(['nodes', 'configuration', action, json.dumps(node), '--config', str(config(tmp_path, endpoint)), '--service', 'local', '--json'])
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


@pytest.mark.parametrize('mode', ['healthy', 'unknown-fields', 'secret-ref'])
def test_inspect_preserves_owner_snapshot_without_effect(setup, tmp_path, monkeypatch, capsys, mode):
    code, result, calls = invoke(setup, tmp_path, monkeypatch, capsys, mode, action='inspect')
    assert code == 0 and result['status'] == 'confirmed'
    assert result['data']['configuration']['model'] == 'old'
    assert result['evidence'] == {'level': 'configurationSnapshotObserved', 'runtimeVerified': False, 'configurationValuesObserved': True}
    assert result['data']['sourceRevision'] == (None if mode == 'unknown-fields' else 'native-1')
    assert result['data']['unknownItems'] == (['tools'] if mode == 'unknown-fields' else [])
    assert result['data']['comparisonGuarantee'] == ('unavailable' if mode == 'unknown-fields' else 'ownerSerialized')
    assert calls[-1]['method'] == 'agents.nodes.configuration.inspect'
    assert setup[7]['calls'] == 0 and setup[7]['queryCalls'] == 0
    assert setup[0].read_operation(setup[5]) is None


@pytest.mark.parametrize('mode', ['foreign-unit', 'foreign-scope', 'foreign-proof', 'absent-proof', 'unknown-revision',
    'bool-revision', 'naive-time', 'bool-time', 'overlap', 'duplicate-unknown', 'object-unknown', 'desired', 'plaintext', 'secret', 'bad-secret-ref'])
def test_inspect_rejects_false_facts_and_unsafe_snapshot(setup, tmp_path, monkeypatch, capsys, mode):
    code, result, calls = invoke(setup, tmp_path, monkeypatch, capsys, mode, action='inspect')
    assert code == 4 and result['error']['code'] == 'CORE_RESPONSE_INVALID' and len(calls) == 3
    assert 'configuration' not in result['data'] and 'must-not-emit' not in json.dumps(result)
    assert setup[7]['calls'] == 0 and setup[7]['queryCalls'] == 0


@pytest.mark.parametrize('mode,expected,count', [('missing', 4, 2), ('forbidden', 3, 3)])
def test_inspect_missing_method_or_permission_refused(setup, tmp_path, monkeypatch, capsys, mode, expected, count):
    code, result, calls = invoke(setup, tmp_path, monkeypatch, capsys, mode, action='inspect')
    assert code == expected and result['status'] == 'refused' and len(calls) == count
    assert setup[7]['calls'] == 0


@pytest.mark.parametrize('mode,expected,status,error', [('disconnect', 4, 'refused', 'SERVICE_UNAVAILABLE'),
    ('unknown-outcome', 6, 'unknown', 'OUTCOME_UNKNOWN')])
def test_inspect_disconnect_or_unknown_never_resends_or_invents_snapshot(setup, tmp_path, monkeypatch, capsys, mode, expected, status, error):
    code, result, calls = invoke(setup, tmp_path, monkeypatch, capsys, mode, action='inspect')
    assert code == expected and result['status'] == status and result['error']['code'] == error
    assert result['error']['retryable'] is False
    assert len(calls) == 3 and sum(call['method'].endswith('.inspect') for call in calls) == 1
    assert 'configuration' not in result['data']
    assert result['evidence']['level'] == 'coreCapabilitiesObserved'
    assert setup[7]['calls'] == 0 and setup[7]['queryCalls'] == 0


def command_change(parts, tmp_path, endpoint, action, change=None, operation=None):
    command = ['nodes', 'configuration', action, json.dumps(encode_node_ref(parts[4]))]
    if action == 'apply':
        path = tmp_path / 'change.json'
        path.write_text(json.dumps(change or parts[6].to_dict()))
        command += ['--file', str(path)]
    else: command.append(operation)
    return main(command + ['--config', str(config(tmp_path, endpoint)), '--service', 'local', '--json'])


def envelope(capsys):
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    return json.loads(output.out)


def test_apply_query_replay_use_original_core_operation_once(setup, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with observation_server(setup, managing=True) as (endpoint, calls):
        assert command_change(setup, tmp_path, endpoint, 'apply') == 0
        first = envelope(capsys)
        assert first['requestId'] == setup[6].request_id and first['status'] == 'confirmed'
        assert first['data']['status'] == 'published'
        assert first['data']['configurationResult']['overallOutcome'] == 'applied'
        assert first['operationRef'] == first['data']['operationRef']
        assert first['evidence']['allDeclarationsApplied'] is True
        assert setup[7]['calls'] == 1
        assert command_change(setup, tmp_path, endpoint, 'apply') == 0
        replay = envelope(capsys)
        assert replay['data'] == first['data'] and setup[7]['calls'] == 1
        assert command_change(setup, tmp_path, endpoint, 'query', operation=first['operationRef']) == 0
        queried = envelope(capsys)
        assert queried['data'] == first['data']
        assert setup[7]['calls'] == 1 and setup[7]['queryCalls'] == 0
        assert sum(call['method'].endswith('.apply') for call in calls) == 2
        assert sum(call['method'].endswith('.query') for call in calls) == 1


@pytest.mark.parametrize('conflict', ['version', 'request-payload'])
def test_apply_version_or_spent_request_conflict_never_repeats_effect(setup, tmp_path, monkeypatch, capsys, conflict):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with observation_server(setup, managing=True) as (endpoint, calls):
        change = setup[6].to_dict()
        expected_calls = 0
        if conflict == 'version': change['expectedConfigurationRevision'] = 'stale'
        else:
            assert command_change(setup, tmp_path, endpoint, 'apply') == 0
            envelope(capsys)
            change['declarations'][0]['payload'] = {'modelId': 'different'}
            expected_calls = 1
        assert command_change(setup, tmp_path, endpoint, 'apply', change) == 5
        result = envelope(capsys)
        assert result['error']['code'] == 'PRECONDITION_CONFLICT' and result['status'] == 'refused'
        assert setup[7]['calls'] == expected_calls


def test_unknown_same_key_and_original_query_never_resend(setup, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    setup[7]['outcome'] = 'unknown'
    with observation_server(setup, managing=True) as (endpoint, calls):
        assert command_change(setup, tmp_path, endpoint, 'apply') == 6
        first = envelope(capsys)
        assert first['status'] == 'unknown' and first['operationRef']
        assert first['error']['retryable'] is False and setup[7]['calls'] == 1
        assert command_change(setup, tmp_path, endpoint, 'apply') == 6
        replay = envelope(capsys)
        assert replay['operationRef'] == first['operationRef'] and setup[7]['calls'] == 1
        assert command_change(setup, tmp_path, endpoint, 'query', operation=first['operationRef']) == 6
        query = envelope(capsys)
        assert query['status'] == 'unknown' and query['operationRef'] == first['operationRef']
        assert setup[7]['calls'] == 1 and setup[7]['queryCalls'] == 1
        setup[7]['outcome'] = 'applied'
        assert command_change(setup, tmp_path, endpoint, 'query', operation=first['operationRef']) == 0
        recovered = envelope(capsys)
        assert recovered['operationRef'] == first['operationRef'] and recovered['status'] == 'confirmed'
        assert setup[7]['calls'] == 1 and setup[7]['queryCalls'] == 2


@pytest.mark.parametrize('failure', ['missing-authority', 'forbidden', 'malformed', 'foreign-material'])
def test_apply_missing_authority_or_invalid_request_refused(setup, tmp_path, monkeypatch, capsys, failure):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    managing = failure != 'missing-authority'
    with observation_server(setup, 'forbidden' if failure == 'forbidden' else 'healthy', managing=managing) as (endpoint, calls):
        change = setup[6].to_dict()
        if failure == 'malformed': change['applicationPolicy']['allowRestart'] = 1
        if failure == 'foreign-material': change['declarations'][0]['resourceRefs'] = [{'environmentNamespace': 'foreign', 'ref': 'material'}]
        expected = {'missing-authority': 4, 'forbidden': 3, 'malformed': 2, 'foreign-material': 2}[failure]
        assert command_change(setup, tmp_path, endpoint, 'apply', change) == expected
        result = envelope(capsys)
        assert result['status'] == 'refused' and setup[7]['calls'] == 0
        assert len(calls) == (0 if failure == 'malformed' else 2 if failure == 'foreign-material' else 3)


@pytest.mark.parametrize('outcome,allow_deferred,expected,status', [('deferred', True, 6, 'unknown'),
    ('restartRequired', False, 0, 'pending'), ('rejected', False, 4, 'refused'), ('conflict', False, 5, 'refused')])
def test_known_owner_outcomes_not_promoted_to_applied(setup, tmp_path, monkeypatch, capsys, outcome, allow_deferred, expected, status):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    setup[7]['outcome'] = outcome
    change = setup[6].to_dict()
    change['applicationPolicy']['allowDeferred'] = allow_deferred
    with observation_server(setup, managing=True) as (endpoint, calls):
        assert command_change(setup, tmp_path, endpoint, 'apply', change) == expected
        result = envelope(capsys)
        assert result['status'] == status and result['data']['configurationResult']['overallOutcome'] == outcome
        assert result['evidence']['allDeclarationsApplied'] is False
        assert setup[7]['calls'] == 1 and setup[7]['model'] == 'old'


def test_partial_applied_and_optional_rejected_retained_without_rollback(setup, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    change = setup[6].to_dict()
    change['declarations'].append({'declarationId': 'optional', 'configurationKind': 'unsupported', 'schemaVersion': '1',
        'action': 'disabled', 'requirement': 'optional'})
    with observation_server(setup, managing=True) as (endpoint, calls):
        assert command_change(setup, tmp_path, endpoint, 'apply', change) == 6
        result = envelope(capsys)
        assert result['status'] == 'partial' and result['error']['code'] == 'CONFIGURATION_PARTIAL'
        assert result['evidence']['allDeclarationsApplied'] is False
        assert result['data']['configurationResult']['overallOutcome'] == 'partial'
        assert [(item['declarationId'], item['outcome']) for item in result['data']['configurationResult']['itemResults']] == [('model', 'applied'), ('optional', 'rejected')]
        assert setup[7]['calls'] == 1 and setup[7]['model'] == 'new'
        assert command_change(setup, tmp_path, endpoint, 'query', operation=result['operationRef']) == 6
        queried = envelope(capsys)
        assert queried['data'] == result['data'] and queried['status'] == 'partial'
        assert setup[7]['calls'] == 1 and setup[7]['queryCalls'] == 0


@pytest.mark.parametrize('mode', ['operation-mismatch', 'bool-operation-revision', 'applied-no-proof', 'unknown-published',
    'wrong-overall', 'missing-item', 'foreign-confirmation', 'private-result', 'result-secret', 'bool-unit-identity', 'float-scope-identity', 'published-deferred'])
def test_invalid_apply_response_is_unknown_and_cannot_emit_result(setup, tmp_path, monkeypatch, capsys, mode):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with observation_server(setup, mode, managing=True) as (endpoint, calls):
        assert command_change(setup, tmp_path, endpoint, 'apply') == 6
        result = envelope(capsys)
        assert result['status'] == 'unknown' and result['error']['code'] == 'OUTCOME_UNKNOWN'
        assert result['operationRef'] is None and 'configurationResult' not in result['data']
        assert 'must-not-emit' not in json.dumps(result)
        assert sum(call['method'].endswith('.apply') for call in calls) == 1
        assert setup[7]['calls'] == 1


def test_committed_apply_receipt_lost_query_original_without_resubmit(setup, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with observation_server(setup, 'receipt-lost', managing=True) as (endpoint, calls):
        assert command_change(setup, tmp_path, endpoint, 'apply') == 6
        lost = envelope(capsys)
        assert lost['status'] == 'unknown' and lost['requestId'] == setup[6].request_id
        assert setup[7]['calls'] == 1 and lost['operationRef'] is None
        # The test reads the original sole Core record, not a client-derived id.
        original = setup[0].read_operation(setup[5]).intent.operation_ref
        assert command_change(setup, tmp_path, endpoint, 'query', operation=original) == 0
        queried = envelope(capsys)
        assert queried['operationRef'] == original and queried['status'] == 'confirmed'
        assert setup[7]['calls'] == 1 and setup[7]['queryCalls'] == 0
        assert sum(call['method'].endswith('.apply') for call in calls) == 1
