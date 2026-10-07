"""D-route: CLI consumption of the frozen operation-read wire binding.

The CLI imports no core/Server/Harness package, never retries a wire request
automatically, and never promotes a query receipt to task completion. The
`operations read` command validates its plain-string ref locally (exit 2,
zero HTTP), refuses unadvertised methods with OPERATION_READ_UNAVAILABLE
(exit 4, pre-HTTP), validates the sealed six-field projection, and maps the
frozen §2 wire error families. Every service double is a local in-process
HTTP fixture; no user service, user data or real model is involved.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
import json
import re
import subprocess
import sys
import threading

import pytest

from ordessa_agent_tools.cli import main, parser as cli_parser
from ordessa_agent_tools.client import ClientError, Service, WireClient, core_schema
from ordessa_agent_tools.operations import operation_read_result_valid
from pacthold.agents.public import wire_contract, wire_schema_digest


SECRET = 'fixture-private-bearer-do-not-print'
READ_METHOD = 'agents.operations.read'
NODE_REF_JSON = json.dumps({'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 1})
FOREIGN_NODE_REF_JSON = json.dumps({'environmentNamespace': 'foreign', 'instanceId': 'node', 'generation': 1})
FOREIGN_DEFINITION_JSON = json.dumps({'environmentNamespace': 'foreign', 'definitionId': 'fixture', 'revision': '1'})
MALFORMED_DEFINITION_JSON = json.dumps({'environmentNamespace': 'env'})
DEFAULT_METHODS = ['agents.capabilities', 'agents.nodes.list', 'agents.nodes.read',
                   'agents.nodes.queryPreparation', 'agents.nodes.configuration.query',
                   'agents.nodes.configuration.describe', 'agents.nodes.configuration.apply',
                   'agents.providers.describe', 'agents.providers.list', 'agents.profiles.list']
SEALED_VIEW = {'operationRef': 'operation-x', 'kind': 'configuration-change', 'revision': 1,
               'status': 'published',
               'nodeRef': {'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 1},
               'hasResult': True}


def config(tmp_path, endpoint):
    path = tmp_path / 'services.json'
    path.write_text(json.dumps({'services': {'local': {'endpoint': endpoint, 'tokenEnv': 'TOOLS_TEST_TOKEN'}}}))
    path.chmod(0o600)
    return path


def capabilities_payload(mutate=None):
    result = {
        'contractVersion': 'agent-assembly/3',
        'schemaDigest': wire_schema_digest('agent-assembly/3'),
        'schema': wire_contract('agent-assembly/3'),
        'environmentNamespace': 'env',
        'supports': {'profileCatalog': True, 'nodes': True, 'managedInput': False,
                     'configurationManagement': False, 'nodePreparation': False,
                     'nodeLifecycle': False},
        'supportedMethods': list(DEFAULT_METHODS),
    }
    if mutate is not None:
        mutate(result)
    return result


def hello_payload():
    return {'serverId': 'controlled-fixture', 'protocolVersion': 'wire/1',
            'auth': {'required': True, 'schemes': ['session_token']},
            'capabilities': [{'id': 'agents.capabilities', 'supported': True}]}


def without(*methods):
    def mutate(result):
        result['supportedMethods'] = [name for name in result['supportedMethods']
                                      if name not in methods]
    return mutate


def set_support(key, value):
    def mutate(result):
        result['supports'][key] = value
    return mutate


def set_contract_version(value):
    def mutate(result):
        result['contractVersion'] = value
    return mutate


def set_digest(value):
    def mutate(result):
        result['schemaDigest'] = value
    return mutate


def set_protocol(value):
    def mutate(result):
        result['protocolVersion'] = value
    return mutate


def operations_read_args(path, operation='operation-x'):
    return ['operations', 'read', operation,
            '--config', str(path), '--service', 'local', '--json']


def with_methods(*names):
    def mutate(result):
        result['supportedMethods'] = list(result['supportedMethods']) + [
            name for name in names if name not in result['supportedMethods']]
    return mutate


def set_v1(result):
    # A wire/1 service: no management contract and no supportedMethods member.
    result.update({
        'contractVersion': 'agent-assembly/1',
        'schemaDigest': wire_schema_digest('agent-assembly/1'),
        'schema': wire_contract('agent-assembly/1'),
        'supports': {'profileCatalog': True, 'nodes': False, 'managedInput': False},
    })
    result.pop('supportedMethods', None)


@contextmanager
def wire_server(hello=None, capabilities=None, results=None, errors=None, drop=(), status=200):
    calls = []
    results = results or {}
    errors = errors or {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append({'path': self.path,
                          'authorization': self.headers.get('Authorization'),
                          'request': request})
            method = request['method']
            if method in drop:
                self.close_connection = True
                self.connection.close()
                return
            if status != 200:
                raw = SECRET.encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if method == 'server.hello':
                payload = hello_payload()
                if hello is not None:
                    hello(payload)
                body = {'jsonrpc': '2.0', 'id': request['id'], 'result': payload}
            elif method == 'agents.capabilities':
                body = {'jsonrpc': '2.0', 'id': request['id'],
                        'result': capabilities_payload(capabilities)}
            elif method in results:
                body = {'jsonrpc': '2.0', 'id': request['id'], 'result': results[method]}
            elif method in errors:
                body = {'jsonrpc': '2.0', 'id': request['id'],
                        'error': {'code': errors[method], 'message': SECRET}}
            else:
                raise AssertionError('unexpected wire method ' + method)
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(httpd.server_port), calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def envelope(capsys):
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    return json.loads(output.out)


def query_preparation_args(path):
    return ['nodes', 'query-preparation', 'original-preparation-request',
            '--config', str(path), '--service', 'local', '--json']


def configuration_query_args(path, node_ref=NODE_REF_JSON, operation='original-operation'):
    return ['nodes', 'configuration', 'query', node_ref, operation,
            '--config', str(path), '--service', 'local', '--json']


def configuration_describe_args(path, node_ref=NODE_REF_JSON):
    return ['nodes', 'configuration', 'describe', node_ref,
            '--config', str(path), '--service', 'local', '--json']


def configuration_inspect_args(path, node_ref=NODE_REF_JSON):
    return ['nodes', 'configuration', 'inspect', node_ref,
            '--config', str(path), '--service', 'local', '--json']


def providers_describe_args(path, definition=None):
    definition = definition or json.dumps({'environmentNamespace': 'env',
                                           'definitionId': 'fixture', 'revision': '1'})
    return ['providers', 'describe', definition,
            '--config', str(path), '--service', 'local', '--json']


def providers_list_args(path):
    return ['providers', 'list', '--config', str(path), '--service', 'local', '--json']


BUILDERS = {
    'query-preparation': (query_preparation_args, 'agents.nodes.queryPreparation'),
    'configuration-query': (configuration_query_args, 'agents.nodes.configuration.query'),
    'configuration-query-foreign-node': (
        lambda path: configuration_query_args(path, node_ref=FOREIGN_NODE_REF_JSON),
        'agents.nodes.configuration.query'),
    'configuration-describe': (configuration_describe_args, 'agents.nodes.configuration.describe'),
    'configuration-describe-foreign-node': (
        lambda path: configuration_describe_args(path, node_ref=FOREIGN_NODE_REF_JSON),
        'agents.nodes.configuration.describe'),
    'configuration-inspect': (configuration_inspect_args, 'agents.nodes.configuration.inspect'),
    'providers-describe': (providers_describe_args, 'agents.providers.describe'),
    'providers-describe-foreign-definition': (
        lambda path: providers_describe_args(path, definition=FOREIGN_DEFINITION_JSON),
        'agents.providers.describe'),
    'providers-list': (providers_list_args, 'agents.providers.list'),
    'operations-read': (operations_read_args, READ_METHOD),
}

# mode -> (server kwargs, builder key, exit code, error code, total calls, target calls)
SCENARIOS = {
    'version': (dict(hello=set_protocol('wire/2')),
                'query-preparation', 4, 'WIRE_VERSION_UNSUPPORTED', 1, 0),
    'contract': (dict(capabilities=set_contract_version('agent-assembly/9')),
                 'query-preparation', 4, 'CORE_VERSION_UNSUPPORTED', 2, 0),
    'digest': (dict(capabilities=set_digest('sha256:' + '0' * 64)),
               'query-preparation', 4, 'CORE_VERSION_UNSUPPORTED', 2, 0),
    'unadvertised-preparation': (dict(capabilities=without('agents.nodes.queryPreparation')),
                                 'query-preparation', 4, 'PREPARATION_QUERY_UNAVAILABLE', 2, 0),
    'capability-flag-down': ({}, 'query-preparation', 4, 'PREPARATION_QUERY_UNAVAILABLE', 2, 0),
    'preparation-refused': (dict(capabilities=set_support('nodePreparation', True),
                                errors={'agents.nodes.queryPreparation': 'INVALID_REQUEST'}),
                            'query-preparation', 2, 'PARAMETER_INVALID', 3, 1),
    'preparation-forbidden': (dict(capabilities=set_support('nodePreparation', True),
                                  errors={'agents.nodes.queryPreparation': 'FORBIDDEN'}),
                              'query-preparation', 3, 'AUTHORIZATION_REFUSED', 3, 1),
    'preparation-unknown': (dict(capabilities=set_support('nodePreparation', True),
                                errors={'agents.nodes.queryPreparation': 'OUTCOME_UNKNOWN'}),
                            'query-preparation', 6, 'OUTCOME_UNKNOWN', 3, 1),
    'preparation-drop': (dict(capabilities=set_support('nodePreparation', True),
                              drop={'agents.nodes.queryPreparation'}),
                         'query-preparation', 6, 'OUTCOME_UNKNOWN', 3, 1),
    'preparation-absent': (dict(capabilities=set_support('nodePreparation', True),
                                results={'agents.nodes.queryPreparation': {'operation': None}}),
                           'query-preparation', 4, 'PREPARATION_NOT_FOUND', 3, 1),
    'hello-unauthorized': (dict(status=401), 'query-preparation', 3, 'AUTHORIZATION_REFUSED', 1, 0),
    'configuration-query-unadvertised': (
        dict(capabilities=without('agents.nodes.configuration.query')),
        'configuration-query', 4, 'NODE_CONFIGURATION_UNAVAILABLE', 2, 0),
    'configuration-query-refused': (
        dict(errors={'agents.nodes.configuration.query': 'INVALID_REQUEST'}),
        'configuration-query', 2, 'PARAMETER_INVALID', 3, 1),
    'configuration-query-drop': (dict(drop={'agents.nodes.configuration.query'}),
                                 'configuration-query', 4, 'SERVICE_UNAVAILABLE', 3, 1),
    'configuration-query-foreign-node': ({}, 'configuration-query-foreign-node',
                                         2, 'PARAMETER_INVALID', 2, 0),
    'configuration-query-invalid-view': (
        dict(results={'agents.nodes.configuration.query':
                      {'operationRef': 'operation-x', 'revision': 1, 'status': 'published'}}),
        'configuration-query', 4, 'CORE_RESPONSE_INVALID', 3, 1),
    'configuration-query-refused-view': (
        dict(results={'agents.nodes.configuration.query':
                      {'operationRef': 'original-operation', 'revision': 1, 'status': 'refused',
                       'configurationResult': None}}),
        'configuration-query', 4, 'CONFIGURATION_REFUSED', 3, 1),
    'configuration-describe-unadvertised': (
        dict(capabilities=without('agents.nodes.configuration.describe')),
        'configuration-describe', 4, 'NODE_CONFIGURATION_UNAVAILABLE', 2, 0),
    'configuration-describe-foreign-node': ({}, 'configuration-describe-foreign-node',
                                            2, 'PARAMETER_INVALID', 2, 0),
    'configuration-describe-forbidden': (
        dict(errors={'agents.nodes.configuration.describe': 'FORBIDDEN'}),
        'configuration-describe', 3, 'AUTHORIZATION_REFUSED', 3, 1),
    'configuration-inspect-unadvertised': (
        dict(capabilities=without('agents.nodes.configuration.inspect')),
        'configuration-inspect', 4, 'NODE_CONFIGURATION_UNAVAILABLE', 2, 0),
    'providers-describe-unadvertised': (
        dict(capabilities=without('agents.providers.describe')),
        'providers-describe', 4, 'PROVIDER_DISCOVERY_UNAVAILABLE', 2, 0),
    'providers-describe-foreign-definition': ({}, 'providers-describe-foreign-definition',
                                              2, 'PARAMETER_INVALID', 2, 0),
    'providers-describe-forbidden': (
        dict(errors={'agents.providers.describe': 'FORBIDDEN'}),
        'providers-describe', 3, 'AUTHORIZATION_REFUSED', 3, 1),
    'providers-describe-invalid-view': (
        dict(results={'agents.providers.describe': {'descriptor': {}}}),
        'providers-describe', 4, 'CORE_RESPONSE_INVALID', 3, 1),
    'providers-list-unadvertised': (
        dict(capabilities=without('agents.providers.list')),
        'providers-list', 4, 'PROVIDER_DISCOVERY_UNAVAILABLE', 2, 0),
    # §6 gate 3: unadvertised or /1-negotiated services refuse before any
    # method HTTP with the new code; no write effect can exist.
    'operations-read-unadvertised': (
        dict(capabilities=without(READ_METHOD)),
        'operations-read', 4, 'OPERATION_READ_UNAVAILABLE', 2, 0),
    'operations-read-v1-service': (
        dict(capabilities=set_v1),
        'operations-read', 4, 'OPERATION_READ_UNAVAILABLE', 2, 0),
    # §2 frozen wire→CLI error families, each attempted exactly once.
    'operations-read-forbidden': (
        dict(capabilities=with_methods(READ_METHOD), errors={READ_METHOD: 'FORBIDDEN'}),
        'operations-read', 3, 'AUTHORIZATION_REFUSED', 3, 1),
    'operations-read-conflict': (
        dict(capabilities=with_methods(READ_METHOD), errors={READ_METHOD: 'CONFLICT_REQUEST'}),
        'operations-read', 5, 'PRECONDITION_CONFLICT', 3, 1),
    'operations-read-wire-refused': (
        dict(capabilities=with_methods(READ_METHOD), errors={READ_METHOD: 'CAPABILITY_UNSUPPORTED'}),
        'operations-read', 4, 'WIRE_REFUSED', 3, 1),
    'operations-read-unavailable': (
        dict(capabilities=with_methods(READ_METHOD), errors={READ_METHOD: 'UNAVAILABLE'}),
        'operations-read', 4, 'SERVICE_UNAVAILABLE', 3, 1),
    'operations-read-not-found': (
        dict(capabilities=with_methods(READ_METHOD), errors={READ_METHOD: 'NOT_FOUND'}),
        'operations-read', 4, 'OPERATION_NOT_FOUND', 3, 1),
    'operations-read-drop': (
        dict(capabilities=with_methods(READ_METHOD), drop={READ_METHOD}),
        'operations-read', 4, 'SERVICE_UNAVAILABLE', 3, 1),
    # Result validation: only the exact sealed projection may pass.
    'operations-read-invalid-view': (
        dict(capabilities=with_methods(READ_METHOD),
             results={READ_METHOD: {'operationRef': 'operation-x', 'status': 'published'}}),
        'operations-read', 4, 'CORE_RESPONSE_INVALID', 3, 1),
    'operations-read-ref-mismatch': (
        dict(capabilities=with_methods(READ_METHOD),
             results={READ_METHOD: dict(SEALED_VIEW, operationRef='other-operation')}),
        'operations-read', 4, 'CORE_RESPONSE_INVALID', 3, 1),
    'operations-read-bad-status': (
        dict(capabilities=with_methods(READ_METHOD),
             results={READ_METHOD: dict(SEALED_VIEW, status='completed')}),
        'operations-read', 4, 'CORE_RESPONSE_INVALID', 3, 1),
    'operations-read-bad-has-result': (
        dict(capabilities=with_methods(READ_METHOD),
             results={READ_METHOD: dict(SEALED_VIEW, hasResult='yes')}),
        'operations-read', 4, 'CORE_RESPONSE_INVALID', 3, 1),
    'operations-read-bad-node-ref': (
        dict(capabilities=with_methods(READ_METHOD),
             results={READ_METHOD: dict(SEALED_VIEW, nodeRef={'environmentNamespace': 'foreign',
                                                              'instanceId': 'node', 'generation': 1})}),
        'operations-read', 4, 'CORE_RESPONSE_INVALID', 3, 1),
    'operations-read-extra-field': (
        dict(capabilities=with_methods(READ_METHOD),
             results={READ_METHOD: dict(SEALED_VIEW, evidence={'level': 'forged'})}),
        'operations-read', 4, 'CORE_RESPONSE_INVALID', 3, 1),
    'operations-read-token-leak': (
        dict(capabilities=with_methods(READ_METHOD),
             results={READ_METHOD: dict(SEALED_VIEW, note=SECRET)}),
        'operations-read', 4, 'CORE_RESPONSE_INVALID', 3, 1),
}


def test_cli_and_client_import_no_core_or_host_packages():
    forbidden = ('ordessa_server', 'ordessa_harness', 'pacthold', 'server_plugin_api',
                 'ordessa_environment_api', 'ordessa_persistence_sqlite')
    for name in ('cli.py', 'client.py'):
        source = files('ordessa_agent_tools').joinpath(name).read_text(encoding='utf-8')
        for token in forbidden:
            assert token not in source, (name, token)


def test_cli_method_literals_stay_inside_the_frozen_contract():
    contract = set(wire_contract('agent-assembly/3')['methods'])
    source = files('ordessa_agent_tools').joinpath('cli.py').read_text(encoding='utf-8')
    source += files('ordessa_agent_tools').joinpath('client.py').read_text(encoding='utf-8')
    literals = set(re.findall(r'agents\.[A-Za-z][A-Za-z0-9.]*', source))
    assert literals
    for literal in literals:
        stem = literal.rstrip('.')
        assert stem in contract or any(name.startswith(stem) for name in contract), literal
    for uncontracted in ('agents.operations.list', 'agents.nodes.resolveMaterial',
                         'agents.nodes.compile', 'agents.materials'):
        assert uncontracted not in source


def test_cli_runtime_import_boundary_holds_in_a_fresh_interpreter():
    code = (
        "import sys\n"
        "import ordessa_agent_tools.cli, ordessa_agent_tools.client\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'ordessa_server', 'ordessa_harness', 'pacthold', 'server_plugin_api', "
        "'ordessa_environment_api', 'ordessa_persistence_sqlite'})\n"
        "sys.stdout.write(','.join(bad))\n"
        "raise SystemExit(1 if bad else 0)\n")
    completed = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout == ''


LOCAL_INVALID = [
    # §6 gate 2: illegal operationRef shapes refuse locally, exit 2, zero HTTP.
    ['operations', 'read', ''],
    ['operations', 'read', ' leading'],
    ['operations', 'read', 'trailing '],
    ['operations', 'read', 'line\nbreak'],
    ['operations', 'read', 'x' * 257],
    ['nodes', 'query-preparation', ''],
    ['nodes', 'query-preparation', 'Bad Request Id'],
    ['nodes', 'configuration', 'query', NODE_REF_JSON, ''],
    ['providers', 'describe', MALFORMED_DEFINITION_JSON],
]


@pytest.mark.parametrize('command', LOCAL_INVALID)
def test_invalid_local_parameters_exit_2_without_any_http(tmp_path, monkeypatch, capsys, command):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    # Closed loopback port: any network attempt would surface a transport
    # refusal instead of the local PARAMETER_INVALID exit.
    path = config(tmp_path, 'http://127.0.0.1:1')
    actual = main(command + ['--config', str(path), '--service', 'local', '--json'])
    body = envelope(capsys)
    assert actual == 2 and body['error']['code'] == 'PARAMETER_INVALID'
    assert body['error']['retryable'] is False
    assert body['status'] == 'refused'
    assert body['data'] is None and body['evidence'] == {'level': 'unobserved'}


@pytest.mark.parametrize('mode', sorted(SCENARIOS))
def test_operation_query_cli_refusals_are_typed_and_never_retry(tmp_path, monkeypatch, capsys, mode):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    server_kwargs, builder_key, expected_exit, expected_code, expected_calls, expected_target = SCENARIOS[mode]
    builder, target_method = BUILDERS[builder_key]
    with wire_server(**server_kwargs) as (endpoint, calls):
        actual = main(builder(config(tmp_path, endpoint)))
    body = envelope(capsys)
    assert actual == expected_exit and body['error']['code'] == expected_code
    assert body['error']['retryable'] is False
    assert body['status'] in ('refused', 'unknown')
    methods = [call['request']['method'] for call in calls]
    assert len(calls) == expected_calls, methods
    assert sum(name == target_method for name in methods) == expected_target, methods
    if expected_target:
        # Every refusal or observation is attempted exactly once: no auto retry.
        assert body['evidence']['level'] != 'unobserved'


def test_refused_query_is_attempted_exactly_once_per_invocation(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    server_kwargs = dict(capabilities=set_support('nodePreparation', True),
                         errors={'agents.nodes.queryPreparation': 'INVALID_REQUEST'})
    with wire_server(**server_kwargs) as (endpoint, calls):
        path = config(tmp_path, endpoint)
        assert main(query_preparation_args(path)) == 2
        envelope(capsys)
        assert main(query_preparation_args(path)) == 2
        envelope(capsys)
    assert sum(call['request']['method'] == 'agents.nodes.queryPreparation' for call in calls) == 2


def test_successful_query_receipt_is_not_task_completion(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with wire_server(results={'agents.nodes.list': {'nodes': []}}) as (endpoint, calls):
        actual = main(['nodes', 'list', '--config', str(config(tmp_path, endpoint)),
                       '--service', 'local', '--json'])
    body = envelope(capsys)
    assert actual == 0 and body['status'] == 'confirmed'
    assert body['operationRef'] is None
    assert body['evidence'] == {'level': 'nodePublicationObserved', 'runtimeVerified': False}
    assert body['data'] == {'nodes': []}
    rendered = json.dumps(body)
    assert 'completed' not in rendered and 'taskCompleted' not in rendered
    assert len(calls) == 3


def test_absent_original_preparation_is_refused_receipt_not_success(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    server_kwargs = dict(capabilities=set_support('nodePreparation', True),
                         results={'agents.nodes.queryPreparation': {'operation': None}})
    with wire_server(**server_kwargs) as (endpoint, calls):
        actual = main(query_preparation_args(config(tmp_path, endpoint)))
    body = envelope(capsys)
    assert actual == 4 and body['error']['code'] == 'PREPARATION_NOT_FOUND'
    assert body['status'] == 'refused' and body['error']['retryable'] is False
    assert body['data'] == {'operation': None}
    assert body['evidence'] == {'level': 'preparationOperationObserved',
                                'runtimeVerified': False, 'nodePublished': False}
    assert len(calls) == 3
    assert sum(call['request']['method'] == 'agents.nodes.queryPreparation' for call in calls) == 1


def test_configuration_query_refused_receipt_is_not_task_completion(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    results = {'agents.nodes.configuration.query':
               {'operationRef': 'original-operation', 'revision': 1, 'status': 'refused',
                'configurationResult': None}}
    with wire_server(results=results) as (endpoint, calls):
        actual = main(configuration_query_args(config(tmp_path, endpoint)))
    body = envelope(capsys)
    assert actual == 4 and body['error']['code'] == 'CONFIGURATION_REFUSED'
    assert body['status'] == 'refused' and body['operationRef'] == 'original-operation'
    assert body['evidence']['runtimeVerified'] is False
    assert sum(call['request']['method'] == 'agents.nodes.configuration.query' for call in calls) == 1


def test_operation_read_contract_capabilities_and_shipped_mirror_agree():
    # §6 gate 1: /3 wire_contract, the constant supportedMethods advertisement
    # and the generated client mirror carry one identical read method; the
    # client mirror verifies its own digest on load.
    contract = wire_contract('agent-assembly/3')
    assert READ_METHOD in contract['methods']
    definition = contract['methods'][READ_METHOD]
    assert definition['action'] == 'operationRead'
    assert definition['required'] == ['operationRef'] and definition['optional'] == []
    assert definition['effectful'] is False
    assert contract['results']['operationMetadata'] == {
        'required': ['operationRef', 'kind', 'revision', 'status', 'nodeRef', 'hasResult'],
        'additionalProperties': False,
        'statuses': ['reserved', 'running', 'unknown', 'published', 'refused', 'cancelled']}
    mirror = core_schema('agent-assembly/3')
    assert mirror['schemaDigest'] == wire_schema_digest('agent-assembly/3')
    assert mirror['schema']['methods'][READ_METHOD] == definition
    assert READ_METHOD not in core_schema('agent-assembly/1')['schema']['methods']
    assert READ_METHOD not in wire_contract('agent-assembly/1')['methods']


def test_successful_operation_read_receipt_is_metadata_not_completion(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    server_kwargs = dict(capabilities=with_methods(READ_METHOD), results={READ_METHOD: SEALED_VIEW})
    with wire_server(**server_kwargs) as (endpoint, calls):
        actual = main(operations_read_args(config(tmp_path, endpoint)))
    body = envelope(capsys)
    assert actual == 0 and body['status'] == 'confirmed' and body['error'] is None
    assert body['data'] == SEALED_VIEW
    assert body['operationRef'] == 'operation-x'
    assert body['evidence'] == {'level': 'operationMetadataObserved',
                                'runtimeVerified': False, 'hasResult': True}
    rendered = json.dumps(body)
    assert 'completed' not in rendered and 'taskCompleted' not in rendered
    methods = [call['request']['method'] for call in calls]
    assert len(calls) == 3 and sum(name == READ_METHOD for name in methods) == 1


def test_operation_read_uncertain_receipt_states_no_result_without_completion(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    view = dict(SEALED_VIEW, status='unknown', nodeRef=None, hasResult=False)
    server_kwargs = dict(capabilities=with_methods(READ_METHOD), results={READ_METHOD: view})
    with wire_server(**server_kwargs) as (endpoint, calls):
        actual = main(operations_read_args(config(tmp_path, endpoint)))
    body = envelope(capsys)
    # The read succeeded; the operation's own state is never completion.
    assert actual == 0 and body['status'] == 'confirmed'
    assert body['data'] == view
    assert body['evidence']['hasResult'] is False
    assert 'completed' not in json.dumps(body)
    assert sum(call['request']['method'] == READ_METHOD for call in calls) == 1


def test_v1_negotiated_service_refuses_operation_read_without_write_http(tmp_path, monkeypatch, capsys):
    # §6 gate 3: a wire/1 service publishes no management methods; the CLI
    # refuses before any method HTTP, so no write effect can exist.
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    with wire_server(capabilities=set_v1) as (endpoint, calls):
        actual = main(operations_read_args(config(tmp_path, endpoint)))
    body = envelope(capsys)
    assert actual == 4 and body['error']['code'] == 'OPERATION_READ_UNAVAILABLE'
    assert body['error']['retryable'] is False
    assert body['error']['recoveryAction'] == 'inspectService'
    assert body['status'] == 'refused'
    methods = [call['request']['method'] for call in calls]
    assert methods == ['server.hello', 'agents.capabilities'], methods


def test_operation_read_result_valid_rejects_every_non_sealed_shape():
    good = {'operationRef': 'operation-x', 'kind': 'configuration-change', 'revision': 1,
            'status': 'published', 'nodeRef': None, 'hasResult': True}
    assert operation_read_result_valid(good, 'env', 'operation-x') is True
    good_node = dict(good, nodeRef={'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 1})
    assert operation_read_result_valid(good_node, 'env', 'operation-x') is True
    for broken in (
            None, [], 'operation-x', 1,
            dict(good, operationRef='other-operation'),
            dict(good, status='completed'), dict(good, status=None),
            dict(good, hasResult='yes'), dict(good, hasResult=1), dict(good, hasResult=None),
            dict(good, extra=True),
            {key: value for key, value in good.items() if key != 'hasResult'},
            dict(good, nodeRef={'environmentNamespace': 'foreign', 'instanceId': 'node', 'generation': 1}),
            dict(good, nodeRef={'environmentNamespace': 'env', 'instanceId': 'node'}),
            dict(good, nodeRef={'environmentNamespace': 'env', 'instanceId': 'node', 'generation': '1'}),
            dict(good, nodeRef={'environmentNamespace': 'env', 'instanceId': '', 'generation': 1}),
            dict(good, nodeRef={'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 0}),
            dict(good, nodeRef=[]),
    ):
        assert operation_read_result_valid(broken, 'env', 'operation-x') is False, broken


def test_operations_read_help_matches_the_skill_query_lines(capsys):
    # §6 gate 4: the command help and the three Skill query lines agree.
    with pytest.raises(SystemExit) as exit_info:
        cli_parser().parse_args(['operations', 'read', '--help'])
    assert exit_info.value.code == 0
    rendered = capsys.readouterr().out
    assert 'operation_ref' in rendered
    for option in ('--config', '--service', '--json', '--timeout'):
        assert option in rendered
    skills_root = Path(__file__).resolve().parents[2] / 'skills'
    command = 'ordessa-agent operations read <operationRef> --config … --service … --json'
    gloss = '只读六字段元数据，不返回正文，不推进/恢复/重发；`hasResult` 不等于任务完成'
    for skill in ('configure-agent-profile', 'manage-external-agent', 'use-external-agent'):
        text = (skills_root / skill / 'SKILL.md').read_text(encoding='utf-8')
        assert command in text, skill
        assert gloss in text, skill


def test_init_still_observes_without_executing_binaries(tmp_path, monkeypatch, capsys):
    # §6 gate 4: the new operations command does not change init behavior.
    monkeypatch.setenv('TOOLS_TEST_TOKEN', SECRET)
    actual = main(['init', '--json', '--path', str(tmp_path)])
    body = envelope(capsys)
    assert body['evidence']['executedBinaries'] is False
    assert body['evidence']['serverHostChecked'] is False
    assert body['evidence']['runtimeVerified'] is False
    assert actual in (0, 4)
