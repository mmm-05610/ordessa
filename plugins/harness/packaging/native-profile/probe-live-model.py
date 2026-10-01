"""Real enhanced native adapters + Python owner/C2/C4, without inference.

Usage: .venv/bin/python plugins/harness/packaging/native-profile/probe-live-model.py
       /absolute/candidate-assets [--brand codex|claude-code]
Pinned DEVELOPMENT artifacts and ledger fixtures, not installed/product proof.
"""
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading


def flatten(options):
    for option in options:
        if 'value' in option:
            yield option
        yield from flatten(option.get('options', []))


def probe(assets, brand):
    from ordessa_harness.server_acp.registry import _Channel, _ObservedTransport, AcpChannelRegistry
    from ordessa_harness.server_acp.profile_owner import ProfileSessionOwner
    from ordessa_harness.configuration.model.live_service import create_model_service
    from ordessa_harness.configuration.model.plugin import ModelProviderAdaptersPlugin
    from ordessa_harness_api import DesiredFragment, Installation
    from ordessa_server.bootstrap import build_runtime
    pins = {'codex': ('codex-runtime', 'codex-acp', (1, 1, 14), 'gpt-5.5',
                      'custom-gateway', 'openai', 'responses', 'openai-responses'),
            'claude-code': ('claude-runtime', 'claude-agent-acp', (0, 81, 2), 'sonnet',
                            'main', 'anthropic', 'anthropic', 'anthropic-messages')}
    artifact, package, pin, initial_model, provider_id, api_type, api, protocol = pins[brand]
    entry = assets / artifact / 'node_modules/@agentclientprotocol' / package / 'dist/ordessa-profile.mjs'
    assert entry.is_file(), 'enhanced candidate entry missing'
    counts = {'http': 0, 'inference': 0}
    class RejectInference(BaseHTTPRequestHandler):
        def do_GET(self):
            counts['http'] += 1
            if any(part in self.path for part in ('/responses', '/messages', '/chat/completions')):
                counts['inference'] += 1
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":"no-model probe rejects all requests"}')
        do_POST = do_GET
        do_PUT = do_GET
        do_DELETE = do_GET
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), RejectInference)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    endpoint = 'http://127.0.0.1:' + str(server.server_port)
    try:
        with tempfile.TemporaryDirectory(prefix='ordessa-native-c4-') as temporary:
            home = Path(temporary)
            instance = home / 'instance'; instance.mkdir(mode=0o700)
            project = home / 'project'; project.mkdir(mode=0o700)
            environment = {'PATH': os.defpath, 'HOME': str(home), 'CODEX_HOME': str(instance),
                'CLAUDE_CONFIG_DIR': str(instance), 'XDG_CONFIG_HOME': str(instance),
                'ORDESSA_NATIVE_INSTANCE_DIR': str(instance), 'NO_COLOR': '1'}
            replies = queue.Queue()
            sent = []
            with tempfile.TemporaryFile(mode='w+') as stderr:
                child = subprocess.Popen(['/usr/bin/node', str(entry)], cwd=project,
                    env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=stderr, text=True, start_new_session=True)
                carrier = None
                channel = _Channel(connection_id='probe-channel', harness_id=brand,
                    workspace_id='probe-workspace', profile_id='probe-profile', cwd=str(project))
                channel.session_id = 'probe-ledger-fixture'
                channel.execution_id = 'probe-execution-fixture'
                channel.session_scope_id = 'probe-dedicated-scope-fixture'
                class Pipe:
                    def send_line(self, line):
                        sent.append(json.loads(line))
                        child.stdin.write(line + '\n'); child.stdin.flush()
                class ImmediateLoop:
                    def call_soon_threadsafe(self, callback, item):
                        callback(item)
                channel.transport = _ObservedTransport(channel, Pipe())
                channel.attach(ImmediateLoop(), lambda line: replies.put(json.loads(line)))
                def collect():
                    for line in child.stdout:
                        try:
                            frame = json.loads(line)
                            if frame.get('method') and 'id' in frame:
                                channel.transport.send_line(json.dumps({'jsonrpc': '2.0', 'id': frame['id'],
                                    'error': {'code': -32601, 'message': 'Probe supplies no client operations'}}))
                            else:
                                channel.deliver(line)
                        except ValueError:
                            replies.put({'invalid_stdout': True})
                threading.Thread(target=collect, daemon=True).start()
                serial = 0
                def request(method, params):
                    nonlocal serial
                    serial += 1
                    channel.transport.send_line(json.dumps({'jsonrpc': '2.0', 'id': serial,
                        'method': method, 'params': params}))
                    while True:
                        frame = replies.get(timeout=25)
                        assert 'invalid_stdout' not in frame, 'non-JSON ACP stdout'
                        if frame.get('id') == serial:
                            assert 'error' not in frame, (method, frame.get('error', {}).get('code'))
                            return frame['result']
                try:
                    initialized = request('initialize', {'protocolVersion': 1, 'clientCapabilities': {},
                        'clientInfo': {'name': 'ordessa-native-c4-no-model', 'version': '1'}})
                    assert initialized['_meta']['ordessaConfiguration']['version'] == 1
                    registry = AcpChannelRegistry(session_records=None, profile_records=None,
                        launch=lambda **kwargs: (_ for _ in ()).throw(AssertionError('second launch forbidden')))
                    registry._by_id[channel.connection_id] = channel
                    registry._by_pair[channel.pair] = channel
                    prepared = registry.prepare_native_creation(channel.connection_id,
                        {'operationId': 'create:probe', 'model': initial_model,
                         'provider': {'providerId': provider_id, 'apiType': api_type, 'baseUrl': endpoint,
                                      'headers': {'authorization': 'Bearer ordessa-synthetic-no-model-key'}}})
                    assert prepared['state'] == 'prepared'
                    native = request('session/new', {'cwd': str(project), 'mcpServers': []})['sessionId']
                    startup = registry.query_native_creation(channel.connection_id, 'create:probe')
                    assert startup['state'] == 'observed'
                    assert 'ordessa-synthetic-no-model-key' not in json.dumps(startup), 'startup evidence leaked credential'
                    owners = ProfileSessionOwner(registry, server_id='probe-server-incarnation')
                    before = owners.bind(canonical_session_id='probe-canonical-fixture', harness_id=brand,
                        workspace_id='probe-workspace', connection_id=channel.connection_id,
                        native_session_id=native)
                    selector = next(item for item in before.config_options if item['id'] == 'model')
                    assert selector['currentValue'] == initial_model
                    models = list(flatten(selector['options']))
                    def exact_route(option):
                        return option.get('_meta', {}).get('ordessaModel') == {
                            'provider': provider_id, 'model': option['value'], 'api': api, 'baseUrl': endpoint}
                    selectable = [item for item in models if exact_route(item)]
                    assert selectable, 'actual catalogue lacks exact native construction route'
                    alternatives = [item for item in selectable if item['value'] != initial_model]
                    preferred = next((item for item in alternatives if item['value'] == 'haiku'), None)
                    chosen = preferred or (alternatives[0] if alternatives else next(item for item in selectable
                                                                                   if item['value'] == initial_model))
                    from pacthold_runtime_compat.storage import Database
                    from ordessa_harness.contributions import CONFIGURATION_POINT, HarnessContributionRegistry
                    carrier = build_runtime(home / 'controlled-carrier', server_plugins=(), database_factory=Database)
                    contribution_registry = HarnessContributionRegistry()
                    carrier.plugin_host.register_contribution_point(CONFIGURATION_POINT, 'v1',
                        handler=contribution_registry.configuration_handler, exclusive=False)
                    carrier.plugin_host.activate(ModelProviderAdaptersPlugin())
                    service, runtime = create_model_service(registry=registry, owners=owners,
                        target=before.target, carrier=carrier.plugin_host,
                        installation=Installation(brand, pin, (1, 0, 0), 'DEVELOPMENT-pinned:' + brand),
                        journal_path=home / 'c4.sqlite')
                    def desired(url):
                        return DesiredFragment('assets.model-provider', 'choice', '1', 'probe-provider',
                            'probe-revision', 'set', {'provider': 'synthetic-probe', 'model': chosen['value'],
                            'protocol': protocol, 'endpoint': url, 'credentialRef': None})
                    wrong = service.plan(before.target, (desired(endpoint + '/wrong'),),
                        runtime.capture(before.target).before_revision)
                    assert wrong.kind != 'plan', 'wrong endpoint accepted'
                    assert not any(frame.get('method') == '_ordessa/session/configuration/apply' for frame in sent)
                    plan = service.plan(before.target, (desired(endpoint),),
                        runtime.capture(before.target).before_revision)
                    assert plan.kind == 'plan', plan
                    confirmed = service.apply_prepared(plan.plan_id, 'probe-c4-model')
                    assert confirmed.kind == 'confirmed', confirmed
                    receipt = runtime._executor.last_receipt
                    assert receipt and receipt.operation_id == confirmed.operation_id
                    apply_count = sum(frame.get('method') == '_ordessa/session/configuration/apply' for frame in sent)
                    assert apply_count == 1
                    assert service.apply_prepared(plan.plan_id, 'probe-c4-model') == confirmed
                    assert sum(frame.get('method') == '_ordessa/session/configuration/apply' for frame in sent) == apply_count
                    owner, retained = registry.query_native_operation(channel.connection_id, native, confirmed.operation_id)
                    assert owner is before.owner and retained['state'] == 'observed'
                    assert retained['observedValue'] == chosen['value']
                    assert retained['manifestDigest'] == receipt.manifest_digest
                    after = owners.readback(before.target)
                    assert after.owner is before.owner and after.native_generation == before.native_generation
                    current = next(item for item in after.config_options if item['id'] == 'model')
                    assert current['currentValue'] == chosen['value']
                    actual = [item for item in flatten(current['options']) if item['value'] == chosen['value']]
                    assert len(actual) == 1 and exact_route(actual[0])
                    assert not runtime.private_root.exists()
                    while not replies.empty():
                        relayed = replies.get_nowait()
                        assert not str(relayed.get('id', '')).startswith('ordessa-config-'), 'owner RPC leaked into client relay'
                        assert 'invalid_stdout' not in relayed
                    assert sum(frame.get('method') == 'session/new' for frame in sent) == 1
                    assert not any(frame.get('method') in ('session/prompt', 'session/load') for frame in sent)
                    assert counts['inference'] == 0
                    request('session/close', {'sessionId': native})
                    return {'brand': brand, 'scope': 'real-adapter-owner-C2-C4-ledger-fixture',
                        'installation': 'DEVELOPMENT-pinned-not-installed-proof', 'serverLedger': 'fixture only',
                        'fullServerProfileUI': False, 'preparedBeforeCreate': True,
                        'initialModel': initial_model, 'selectedModel': chosen['value'],
                        'actualModelSwitch': chosen['value'] != initial_model,
                        'sameModelActionOnly': chosen['value'] == initial_model,
                        'actualCatalogueModels': [item['value'] for item in selectable],
                        'c4Confirmed': True, 'idempotentWithoutSecondNativeOperation': True,
                        'independentOwnerReadback': True, 'sameNativeIdentityAndGeneration': True,
                        'wrongEndpointRefused': True, 'exactRoute': actual[0]['_meta']['ordessaModel'],
                        'receipt': asdict(receipt), 'retainedOperationState': retained['state'],
                        'sessionNew': 1, 'prompt': 0, 'inferenceRequests': counts['inference'],
                        'syntheticProviderRequests': counts['http']}
                finally:
                    if carrier is not None:
                        carrier.stop()
                    # This isolated process group belongs exclusively to this probe.
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=5)
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('assets', type=Path)
    parser.add_argument('--brand', choices=('codex', 'claude-code'))
    args = parser.parse_args()
    assert args.assets.is_absolute(), 'absolute candidate assets required'
    for selected_brand in ([args.brand] if args.brand else ['codex', 'claude-code']):
        print(json.dumps(probe(args.assets, selected_brand), sort_keys=True), flush=True)
