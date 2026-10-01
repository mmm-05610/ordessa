"""Explicitly authorized, bounded real-chat acceptance; never prints credentials.

Uses real installed assets, product wire/Profile/C4 and the system keyring.
This is backend product acceptance, not Desktop UI acceptance. Each selected
brand receives exactly two short prompts in its own disposable project.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread, Lock, Event
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from time import monotonic
from uuid import uuid4

from ordessa_server_product.composition import create_composition

ROOT = Path(__file__).resolve().parents[3]


class ImmediateLoop:
    def call_soon_threadsafe(self, callback, argument):
        callback(argument)


def bounded_key(lines, line):
    key = lines[line - 1].strip() if type(line) is int and 1 <= line <= len(lines) else ''
    if not key or len(key) > 8000 or any(ord(c) < 32 or ord(c) == 127 for c in key):
        raise ValueError('Invalid bounded key file')
    return key


def relay_upstreams(switch_go=False):
    return {'/pi/': 'https://api.deepseek.com/',
            '/pi-next/': 'https://opencode.ai/zen/go/v1/' if switch_go else 'https://api.deepseek.com/',
            '/claude/': 'https://api.deepseek.com/anthropic/',
            '/claude-next/': 'https://opencode.ai/zen/go/' if switch_go
                else 'https://api.deepseek.com/anthropic/'}


def run(args):
    if not args.allow_model_calls:
        raise ValueError('Explicit model-call opt-in required')
    lines = args.key_file.read_text().splitlines()
    key = bounded_key(lines, args.key_line)
    switch_go = getattr(args, 'switch_go', False)
    direct_provider = getattr(args, 'direct_provider', False)
    brands = args.brand or ['pi', 'claude-code']
    if direct_provider and (brands != ['pi'] or not switch_go or not args.switch_provider
                           or args.local_relay or not args.fixed_assets):
        raise ValueError('Direct provider acceptance requires Pi/fixed-assets/switch-provider/switch-go without relay')
    if switch_go and not args.switch_provider:
        raise ValueError('Go destination requires explicit provider restoration mode')
    if args.switch_provider and (len(brands) != 1 or brands[0] not in ('pi', 'claude-code')
            or (not args.local_relay and not direct_provider) or not args.fixed_assets):
        raise ValueError('Provider transition probe requires one supported brand, fixed assets and isolated local relay')
    destination_key = bounded_key(lines, args.destination_key_line) if switch_go else key
    native_brands = [brand for brand in brands if brand != 'pi']
    pi_bridge = 'pi' in brands
    environment = dict(os.environ)
    relay = None
    relay_worker = None
    relay_counts = {'requests': 0, 'inference': 0}
    relay_lock = Lock()
    relay_rejected = Event()
    if args.local_relay:
        class Relay(BaseHTTPRequestHandler):
            def do_POST(self):
                mapping = relay_upstreams(switch_go)
                prefix = next((p for p in mapping if self.path.startswith(p)), None)
                length = int(self.headers.get('Content-Length', '0'))
                if prefix is None or not 0 <= length <= 1024 * 1024 or '..' in self.path:
                    self.send_error(400); return
                with relay_lock:
                    relay_counts['requests'] += 1
                    inference = any(part in self.path for part in ('/messages', '/chat/completions'))
                    relay_counts['inference'] += inference
                    exhausted = relay_counts['requests'] > 16 or relay_counts['inference'] > 8
                if exhausted:
                    self.send_error(429); return
                headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in ('host', 'connection', 'content-length', 'accept-encoding')}
                auth = self.headers.get('Authorization', '')
                destination = prefix in ('/claude-next/', '/pi-next/')
                expected_key = destination_key if destination else key
                if auth != 'Bearer ' + expected_key or (switch_go and prefix == '/claude-next/'
                        and self.headers.get('x-api-key') != expected_key):
                    relay_rejected.set(); self.send_error(401); return
                print(json.dumps(dict(stage='relay-request', inference=inference, counts=dict(relay_counts),
                    credentialMatches=True, upstream='go' if switch_go and destination else 'deepseek',
                    nativeSessionHeaderPresent=bool(self.headers.get('x-opencode-session')),
                    placeholderAuth=(auth == 'Bearer acp-proxy'))), flush=True)
                request = Request(mapping[prefix] + self.path[len(prefix):],
                    data=self.rfile.read(length), headers=headers, method='POST')
                try:
                    response = urlopen(request, timeout=90)
                except HTTPError as error:
                    response = error
                except Exception:
                    self.send_error(502); return
                with response:
                    if response.status in (401, 403):
                        relay_rejected.set()
                    print(json.dumps(dict(stage='relay-response', httpStatus=response.status)), flush=True)
                    self.send_response(response.status)
                    self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    try:
                        while chunk := response.read1(4096):
                            self.wfile.write(chunk); self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            def log_message(self, *_):
                pass
        relay = ThreadingHTTPServer(('127.0.0.1', 0), Relay)
        relay_worker = Thread(target=relay.serve_forever, daemon=True)
        relay_worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix='ordessa-authorized-chat-') as folder:
            private = Path(folder)
            for name in ('home', 'project', 'config'):
                (private / name).mkdir(mode=0o700)
            os.environ.update(HOME=str(private / 'home'), XDG_CONFIG_HOME=str(private / 'config'),
                CODEX_HOME=str(private / 'config/codex'), CLAUDE_CONFIG_DIR=str(private / 'config/claude'))
            module = (ROOT / 'plugins/harness/packaging/native-server-plan.mjs').as_uri()
            roots = {'pi': '/opt/ordessa/harnesses/profile-pi-provider/artifacts',
                     'claude-code': '/opt/ordessa/harnesses/profile-native/artifacts'}
            if args.fixed_assets:
                roots = {brand: '/opt/ordessa/harnesses/profile-chat-fixes/artifacts' for brand in brands}
            if switch_go:
                roots[brands[0]] = ('/opt/ordessa/harnesses/profile-pi-registration-owner-bound/artifacts' if brands[0] == 'pi'
                    else '/opt/ordessa/harnesses/profile-claude-provider-restoration/artifacts')
            elif args.switch_provider and brands == ['pi']:
                roots['pi'] = '/opt/ordessa/harnesses/profile-pi-registration-owner-bound/artifacts'
            plan = json.loads(subprocess.check_output(['node', '--input-type=module', '-e',
                f"import {{nativeServerPlan}} from {json.dumps(module)}; console.log(JSON.stringify(nativeServerPlan({{harnessIds:{json.dumps(brands)},nativeProfileHarnesses:{json.dumps(native_brands)},piProfileBridge:{json.dumps(pi_bridge)},artifactRoots:{json.dumps({brand: roots[brand] for brand in brands})},pluginRoot:{json.dumps(str(ROOT / 'plugins/harness'))},artifactRoot:'/opt/ordessa/harnesses/artifacts'}}).args))"], text=True))
            value = lambda flag: plan[plan.index(flag) + 1]
            runtime = create_composition().native_runtime(private / 'data', plugin_root=ROOT / 'plugins/harness',
                harness_id=value('--native-harness'), adapter_command=value('--native-adapter-command'),
                adapter_args=tuple(arg.split('=', 1)[1] for arg in plan if arg.startswith('--native-adapter-arg=')),
                installed_artifact_root=value('--native-installed-artifact-root'), native_profile_harnesses=tuple(native_brands),
                pi_profile_bridge=pi_bridge,
                additional_adapters=tuple(json.loads(value('--native-additional-adapters'))) if '--native-additional-adapters' in plan else ())
            opened, locators, evidence = [], [], []
            wire = runtime.wire.dispatch
            profile = lambda name, **params: wire('profiles.v2.' + name, params)['data']
            try:
                runtime.start()
                workspace = wire('workspaces.open', dict(requestId='live-project-' + uuid4().hex,
                    environment=dict(kind='local', host=None, user=None), path=str(private / 'project')))['workspace']
                registry = runtime.plugin_host.provided_port('acp.channels')
                for brand in brands:
                    protocol, endpoint, models = (
                        ('openai-chat', 'https://api.deepseek.com', ('deepseek-flash', 'deepseek-v4-pro')) if brand == 'pi'
                        else ('anthropic-messages', 'https://api.deepseek.com/anthropic', ('haiku', 'sonnet')))
                    if relay is not None:
                        endpoint = f'http://127.0.0.1:{relay.server_port}/' + ('pi' if brand == 'pi' else 'claude')
                    imported = wire('modelProvider.importApiKey', dict(requestId='live-key-' + uuid4().hex,
                        harnessId=brand, apiKey=key))
                    if imported['state'] != 'imported':
                        raise RuntimeError('Key import refused')
                    from ordessa_server.credentials import CredentialRecords
                    locators.append(CredentialRecords(runtime.database).get(imported['credentialId'], kind='api-key')['secret_locator'])
                    provider = wire('providerModels.create', dict(requestId='live-provider-' + uuid4().hex,
                        harness=brand, provider='deepseek', displayName='Authorized DeepSeek probe',
                        credentialId=imported['credentialId'], configuration=[], protocols=[protocol], endpoints={protocol: endpoint},
                        models=[dict(modelId=m, displayName=m, availability='available', unavailableReason=None) for m in models]))['providerModel']
                    preset = profile('createProfile', operationKey='live-profile-' + uuid4().hex,
                        realm='local', harnessId=brand, displayName='Authorized real-chat probe')
                    def save(model, version):
                        return profile('saveProfile', operationKey='live-save-' + uuid4().hex,
                            profileId=preset['profileId'], expectedVersion=version, patches=[dict(facetId='assets.model-provider',
                            itemId='choice', op='set', value=dict(harnessId=brand, providerConfigId=provider['id'], modelId=model))])
                    save(models[0], 1)
                    scope = 'live-' + uuid4().hex
                    connection = wire('acp.channel.open', dict(harnessId=brand, projectId=workspace['id'], sessionScopeId=scope))
                    opened.append(connection['connectionId'])
                    channel = registry.get(connection['connectionId'])
                    configuration_calls = []
                    original_configuration_rpc = channel._configuration_rpc
                    def counted_configuration_rpc(*args, **kwargs):
                        configuration_calls.append(args[1])  # method only; never retain secret-bearing params
                        result = original_configuration_rpc(*args, **kwargs)
                        if args[1] in ('_ordessa/session/configuration/restore', '_ordessa/session/configuration/operation',
                                       '_ordessa/session/configuration/provider-register'):
                            record = result[1]
                            print(json.dumps(dict(stage='native-operation-evidence',
                                state=record.get('state'), phase=record.get('phase'),
                                failureStep=record.get('failureStep'), failureReason=record.get('failureReason'))), flush=True)
                        return result
                    channel._configuration_rpc = counted_configuration_rpc
                    inbox = queue.Queue()
                    channel.attach(ImmediateLoop(), inbox.put)
                    def request(method, params):
                        rid = 'live-' + uuid4().hex
                        channel.transport.send_line(json.dumps(dict(jsonrpc='2.0', id=rid, method=method, params=params)))
                        deadline = monotonic() + 120
                        output = []
                        while True:
                            try:
                                line = inbox.get(timeout=min(1, max(0, deadline - monotonic())))
                            except queue.Empty:
                                if relay_rejected.is_set():
                                    raise RuntimeError('Upstream rejected authentication; no automatic replay') from None
                                if monotonic() < deadline:
                                    continue
                                print(json.dumps(dict(harness=brand, failedMethod=method,
                                    failure='deadline', relayCounts=dict(relay_counts))), flush=True)
                                raise RuntimeError('Native reply deadline exceeded') from None
                            if line is None:
                                raise RuntimeError('Native adapter closed before reply')
                            answer = json.loads(line)
                            if answer.get('method') and 'id' in answer:
                                # No tools, filesystem or permission grants in this probe.
                                channel.transport.send_line(json.dumps(dict(jsonrpc='2.0', id=answer['id'],
                                    error=dict(code=-32601, message='Acceptance probe provides no client tools'))))
                            if answer.get('method') == 'session/update':
                                update = answer.get('params', {}).get('update', {})
                                if update.get('sessionUpdate') == 'agent_message_chunk':
                                    content = update.get('content', {})
                                    if content.get('type') == 'text':
                                        output.append(content.get('text', ''))
                            if answer.get('id') == rid:
                                if 'error' in answer:
                                    error = answer['error']
                                    detail = str(error.get('message', '')) + ' ' + str(error.get('data', {}))
                                    # Closed diagnostic categories, never arbitrary upstream text.
                                    markers = ['authentication', 'api key', '401', '403', '404', '429',
                                        'model', 'fetch', 'connect', 'timeout', 'undefined', 'not found', 'provider',
                                        'unknown provider', 'provider is not configured', 'no api provider registered']
                                    print(json.dumps(dict(harness=brand, failedMethod=method,
                                        errorCode=error.get('code'), markers=[m for m in markers if m in detail.lower()],
                                        relayCounts=relay_counts)), flush=True)
                                    raise RuntimeError(f"Native {method} refused, code={error.get('code')}")
                                return answer['result'], ''.join(output)
                    request('initialize', dict(protocolVersion=1, clientCapabilities={}, clientInfo=dict(name='ordessa-authorized-chat', version='1')))
                    prepared = profile('prepareNativeCreation', connectionId=channel.connection_id,
                        profileId=preset['profileId'], operationId='create:' + scope)
                    if prepared['state'] != 'prepared':
                        raise RuntimeError('Initial Profile preparation not confirmed')
                    native = request('session/new', dict(cwd=str(private / 'project'), mcpServers=[]))[0]['sessionId']
                    ref = profile('registerNativeSession', connectionId=channel.connection_id,
                        nativeSessionId=native, profileId=preset['profileId'])['sessionRef']
                    first = profile('beginTurnApplication', operationKey='live-first-' + uuid4().hex, sessionRef=ref)
                    if 'receipt' not in first:
                        raise RuntimeError('Initial Profile application not confirmed')
                    token = 'ORDESSA_' + uuid4().hex[:12]
                    reply, text = request('session/prompt', dict(sessionId=native, prompt=[dict(type='text',
                        text=f'Remember this token for the next message: {token}. Reply only ACK. Do not use tools or read files.')]))
                    if reply.get('stopReason') != 'end_turn' or not text.strip():
                        raise RuntimeError('First real turn did not complete with text')
                    print(json.dumps(dict(harness=brand, stage='first-real-turn', completed=True, replyChars=len(text))), flush=True)
                    before_owner = registry.native_session_observation(channel.connection_id, native)
                    _, before_config = channel._configuration_rpc(native, '_ordessa/session/configuration', dict(sessionId=native))
                    if args.switch_provider:
                        destination_credential = imported['credentialId']
                        if switch_go:
                            destination_import = wire('modelProvider.importApiKey', dict(requestId='live-go-key-' + uuid4().hex,
                                harnessId=brand, apiKey=destination_key))
                            if destination_import['state'] != 'imported':
                                raise RuntimeError('Destination key import refused')
                            destination_credential = destination_import['credentialId']
                            locators.append(CredentialRecords(runtime.database).get(destination_credential, kind='api-key')['secret_locator'])
                            models = (models[0], 'glm-5.3-flash' if brand == 'pi' else 'minimax-m2.7')
                        provider = wire('providerModels.create', dict(requestId='live-destination-' + uuid4().hex,
                            harness=brand, provider=('opencode-go' if brand == 'pi' else 'go-destination')
                                if switch_go else 'deepseek-destination', displayName='Authorized restoration destination',
                            credentialId=destination_credential, configuration=[], protocols=[protocol],
                            endpoints={protocol: ('https://opencode.ai/zen/go/v1' if direct_provider else
                                f'http://127.0.0.1:{relay.server_port}/' + ('pi-next' if brand == 'pi' else 'claude-next'))},
                            models=[dict(modelId=m, displayName=m, availability='available', unavailableReason=None)
                                    for m in models]))['providerModel']
                    save(models[1], 2)
                    second = profile('beginTurnApplication', operationKey='live-next-' + uuid4().hex, sessionRef=ref)
                    if 'receipt' not in second:
                        raise RuntimeError('Next Profile model application not confirmed')
                    _, after_config = channel._configuration_rpc(native, '_ordessa/session/configuration', dict(sessionId=native))
                    if args.switch_provider:
                        if brand == 'pi' and before_config['generation'] != after_config['generation']:
                            raise RuntimeError('Pi live registration unexpectedly renewed native generation')
                        if brand != 'pi' and before_config['generation'] == after_config['generation']:
                            raise RuntimeError('Provider restoration did not renew native generation')
                        if registry.native_session_observation(channel.connection_id, native) is not before_owner:
                            raise RuntimeError('Provider restoration changed native conversation owner')
                        effects = ('_ordessa/session/configuration/provider-register' if brand == 'pi'
                                   else '_ordessa/session/configuration/restore')
                        if configuration_calls.count(effects) != 1:
                            raise RuntimeError('Provider transition was not effect-once')
                        if brand == 'pi' and configuration_calls.count('_ordessa/session/configuration/restore') != 0:
                            raise RuntimeError('Pi live transition issued restoration')
                        if first['receipt']['sessionRef'] != second['receipt']['sessionRef']:
                            raise RuntimeError('Provider restoration changed canonical conversation')
                    reply, text = request('session/prompt', dict(sessionId=native, prompt=[dict(type='text',
                        text='What token did I ask you to remember? Reply only that token. Do not use tools or read files.')]))
                    if reply.get('stopReason') != 'end_turn' or token not in text:
                        raise RuntimeError('History was not preserved across the actual model switch')
                    evidence.append(dict(harness=brand, actualTurns=2, initialProfileConfirmed=True,
                        nextProfileConfirmed=True, historyPreserved=True, models=list(models),
                        providerRouteRestoration=args.switch_provider and brand != 'pi',
                        providerTransitionStrategy=('live-registration' if brand == 'pi' else 'restart-resume') if args.switch_provider else None,
                        providerRegistrationEffects=configuration_calls.count('_ordessa/session/configuration/provider-register'),
                        restorationEffects=configuration_calls.count('_ordessa/session/configuration/restore'),
                        nativeGenerationRenewed=before_config['generation'] != after_config['generation'],
                        distinctUpstreamVendors=switch_go if args.switch_provider else None))
                    print(json.dumps(evidence[-1]), flush=True)
                print(json.dumps(dict(scope='real-product-profile-chat-not-desktop-ui', evidence=evidence,
                    viaLocalRelay=relay is not None,
                    relayCounts=relay_counts if relay is not None else None,
                    directEndpointAcceptance=direct_provider)), flush=True)
            finally:
                primary = sys.exc_info()[1]
                failures = []
                for cid in opened:
                    try: wire('acp.channel.release', dict(connectionId=cid))
                    except Exception: failures.append('channel')
                for locator in locators:
                    try: runtime.secret_store.delete(locator)
                    except Exception: failures.append('imported-key')
                try: runtime.stop()
                except Exception: failures.append('runtime')
                if failures:
                    if primary is not None:
                        primary.add_note('Owned cleanup failed: ' + ','.join(failures))
                    else:
                        raise RuntimeError('Owned cleanup failed: ' + ','.join(failures))
                print('Owned channels, imported keyring entries and product cleaned', flush=True)
    finally:
        os.environ.clear(); os.environ.update(environment)
        if relay is not None:
            relay.shutdown(); relay.server_close(); relay_worker.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-model-calls', action='store_true')
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--key-line', type=int, default=1)
    parser.add_argument('--fixed-assets', action='store_true', help='Use separately installed chat-fix assets')
    parser.add_argument('--switch-provider', action='store_true',
                        help='Pi/Claude: two distinct provider configurations/endpoints; explicit transition acceptance')
    parser.add_argument('--switch-go', action='store_true',
                        help='Explicit Pi/Claude DeepSeek-to-Go transition; requires switch-provider/local-relay/fixed-assets')
    parser.add_argument('--destination-key-line', type=int, default=2)
    parser.add_argument('--direct-provider', action='store_true',
                        help='Pi only: preserve real provider hostname for native compatibility/session attribution; no relay')
    parser.add_argument('--brand', choices=['pi', 'claude-code'], action='append')
    parser.add_argument('--local-relay', action='store_true', help='Explicit isolated TLS forwarding, not direct endpoint acceptance')
    run(parser.parse_args())
