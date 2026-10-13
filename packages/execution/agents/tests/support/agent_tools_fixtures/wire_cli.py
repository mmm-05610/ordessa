"""Canonical loopback HTTP and CLI argument fixtures; no test collection."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from ordessa_units.public import wire_contract, wire_schema_digest

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
