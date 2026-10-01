"""Installed native adapters + real product ledger/Profile/wire/keyring, no prompts."""
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import sys
from time import monotonic
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from ordessa_server_product.composition import create_composition

ROOT = Path(__file__).resolve().parents[3]
COUNTS = {'http': 0, 'prompt': 0, 'new': 0}
class RejectProvider(BaseHTTPRequestHandler):
    def do_GET(self):
        COUNTS['http'] += 1
        self.send_response(403); self.end_headers()
        self.wfile.write(b'{"error":"synthetic probe denies inference"}')
    do_POST = do_GET
    def log_message(self, *_): pass
class ImmediateLoop:
    def call_soon_threadsafe(self, callback, argument): callback(argument)

def run():
    COUNTS.update(http=0, prompt=0, new=0)
    pi_root = os.environ.get('ORDESSA_PROBE_PI_ARTIFACT_ROOT')
    brands = ['codex', 'claude-code'] + (['pi'] if pi_root else [])
    server = ThreadingHTTPServer(('127.0.0.1', 0), RejectProvider)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    previous_environment = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix='ordessa-installed-profile-product-') as folder:
            private = Path(folder)
            for name in ('home', 'project', 'config'): (private / name).mkdir(mode=0o700)
            os.environ.update(HOME=str(private / 'home'), XDG_CONFIG_HOME=str(private / 'config'),
                CODEX_HOME=str(private / 'config/codex'), CLAUDE_CONFIG_DIR=str(private / 'config/claude'))
            module = (ROOT / 'plugins/harness/packaging/native-server-plan.mjs').as_uri()
            plan = json.loads(subprocess.check_output(['node', '--input-type=module', '-e',
                f"import {{nativeServerPlan}} from {json.dumps(module)}; console.log(JSON.stringify(nativeServerPlan({{harnessIds:{json.dumps(brands)},nativeProfileHarnesses:['codex','claude-code'],piProfileBridge:{json.dumps(bool(pi_root))},artifactRoots:{json.dumps({'pi': pi_root} if pi_root else {})},pluginRoot:{json.dumps(str(ROOT / 'plugins/harness'))},artifactRoot:'/opt/ordessa/harnesses/profile-native/artifacts'}}).args))"], text=True))
            value = lambda flag: plan[plan.index(flag) + 1]
            runtime = create_composition().native_runtime(private / 'data', plugin_root=ROOT / 'plugins/harness',
                harness_id=value('--native-harness'), adapter_command=value('--native-adapter-command'),
                adapter_args=tuple(arg.split('=', 1)[1] for arg in plan if arg.startswith('--native-adapter-arg=')),
                installed_artifact_root=value('--native-installed-artifact-root'), native_profile_harnesses=('codex','claude-code'),
                pi_profile_bridge=bool(pi_root),
                additional_adapters=tuple(json.loads(value('--native-additional-adapters'))))
            opened, locators, evidence = [], [], []
            wire = runtime.wire.dispatch
            def profile(name, **params): return wire('profiles.v2.' + name, params)['data']
            try:
                runtime.start()
                workspace = wire('workspaces.open', dict(requestId='probe-project-' + uuid4().hex,
                    environment=dict(kind='local', host=None, user=None), path=str(private / 'project')))['workspace']
                registry = runtime.plugin_host.provided_port('acp.channels')
                endpoint = 'http://127.0.0.1:' + str(server.server_port)
                cases = [('codex', 'openai-responses', ('gpt-5.5', 'gpt-5.6-sol')),
                         ('claude-code', 'anthropic-messages', ('sonnet', 'haiku'))]
                if pi_root: cases.append(('pi', 'openai-chat', ('first', 'second')))
                for brand, protocol, models in cases:
                    imported = wire('modelProvider.importApiKey', dict(requestId='probe-key-' + uuid4().hex,
                        harnessId=brand, apiKey='synthetic-no-model-' + uuid4().hex))
                    assert imported['state'] == 'imported'
                    from ordessa_server.credentials import CredentialRecords
                    locators.append(CredentialRecords(runtime.database).get(imported['credentialId'], kind='api-key')['secret_locator'])
                    provider = wire('providerModels.create', dict(requestId='probe-provider-' + uuid4().hex,
                        harness=brand, provider='synthetic-provider', displayName='Probe provider',
                        credentialId=imported['credentialId'], configuration=[], protocols=[protocol], endpoints={protocol:endpoint},
                        models=[dict(modelId=m, displayName=m, availability='available', unavailableReason=None) for m in models]))['providerModel']
                    preset = profile('createProfile', operationKey='probe-profile-' + uuid4().hex,
                        realm='local', harnessId=brand, displayName='Probe')
                    pid = preset['profileId']
                    def save(model, version):
                        return profile('saveProfile', operationKey='probe-save-' + uuid4().hex,
                            profileId=pid, expectedVersion=version, patches=[dict(facetId='assets.model-provider', itemId='choice',
                            op='set', value=dict(harnessId=brand, providerConfigId=provider['id'], modelId=model))])
                    save(models[0], 1)
                    sessions = []
                    for slot in (1, 2):
                        scope = f'probe-{brand}-{slot}'
                        opened_channel = wire('acp.channel.open', dict(harnessId=brand, projectId=workspace['id'], sessionScopeId=scope))
                        opened.append(opened_channel['connectionId'])
                        channel = registry.get(opened_channel['connectionId'])
                        inbox = queue.Queue(); channel.attach(ImmediateLoop(), inbox.put)
                        def request(method, params):
                            rid = 'probe-' + uuid4().hex
                            COUNTS['new'] += method == 'session/new'; COUNTS['prompt'] += method == 'session/prompt'
                            channel.transport.send_line(json.dumps(dict(jsonrpc='2.0', id=rid, method=method, params=params)))
                            deadline = monotonic() + 60
                            while True:
                                line = inbox.get(timeout=max(0, deadline - monotonic()))
                                assert line is not None, 'Native adapter exited before reply'
                                answer = json.loads(line)
                                if answer.get('id') == rid:
                                    assert 'error' not in answer, 'Native request refused: ' + method
                                    return answer['result']
                        request('initialize', dict(protocolVersion=1, clientCapabilities={}, clientInfo=dict(name='ordessa-no-model',version='1')))
                        prepared = profile('prepareNativeCreation', connectionId=channel.connection_id, profileId=pid, operationId='create:' + scope)
                        assert prepared['state'] == 'prepared'
                        native = request('session/new', dict(cwd=str(private / 'project'), mcpServers=[]))['sessionId']
                        ref = profile('registerNativeSession', connectionId=channel.connection_id, nativeSessionId=native, profileId=pid)['sessionRef']
                        applied = profile('beginTurnApplication', operationKey='probe-first-' + uuid4().hex, sessionRef=ref)
                        assert 'receipt' in applied, 'Initial Profile application not confirmed'
                        sessions.append((channel, native, ref))
                    save(models[1], 2)
                    changed = profile('beginTurnApplication', operationKey='probe-next-' + uuid4().hex, sessionRef=sessions[0][2])
                    assert 'receipt' in changed, 'Next model application not confirmed'
                    selected = []
                    for channel, native, _ in sessions:
                        snapshot = registry.query_native_configuration(channel.connection_id, native)
                        options = snapshot.config_options
                        selected.append(next(option['currentValue'] for option in options if option['id'] == 'model'))
                    expected = ['synthetic-provider/' + m for m in (models[1], models[0])] if brand == 'pi' else [models[1], models[0]]
                    assert selected == expected, (brand, selected)
                    assert sessions[0][1] != sessions[1][1]
                    evidence.append(dict(harness=brand, installed=True, initialConfirmed=True, nextConfirmed=True,
                        independentSessions=True, models=selected, nativeIdsDistinct=sessions[0][1] != sessions[1][1]))
                assert COUNTS['new'] == 2 * len(brands) and COUNTS['prompt'] == COUNTS['http'] == 0, COUNTS
                print(json.dumps(dict(scope='installed-product-wire-profile-c4-real-ledger-keyring', evidence=evidence, counts=COUNTS)))
            finally:
                primary = sys.exc_info()[1]
                failed = []
                for cid in opened:
                    try: wire('acp.channel.release', dict(connectionId=cid))
                    except Exception: failed.append('channel')
                for locator in locators:
                    try: runtime.secret_store.delete(locator)
                    except Exception: failed.append('synthetic-key')
                try: runtime.stop()
                except Exception: failed.append('runtime')
                if failed:
                    if primary is not None: primary.add_note('Own cleanup failures: ' + ','.join(failed))
                    else: raise RuntimeError('Own cleanup failures: ' + ','.join(failed)) from None
                print('Released own channels, deleted exact synthetic keyring entries, stopped isolated product')
    finally:
        os.environ.clear(); os.environ.update(previous_environment)
        server.shutdown(); server.server_close(); thread.join(timeout=5)

if __name__ == '__main__': run()
