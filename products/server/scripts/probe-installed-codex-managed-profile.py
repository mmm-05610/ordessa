"""Actual installed product/Profile/C4 official + API isolation.

Uses Ordessa's existing native login only. No credential export or global
configuration changes. Default mode has no inference; opt-in allows exactly two
short official-account prompts. Creates three own native threads and releases
their channels; canonical ledger is in a temporary product data root.
"""
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
from time import monotonic
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from ordessa_server_product.composition import create_composition

ROOT = Path(__file__).resolve().parents[3]
ASSET = '/opt/ordessa/harnesses/profile-codex-managed/artifacts'


class ImmediateLoop:
    def call_soon_threadsafe(self, callback, argument):
        callback(argument)


def run(*, allow_model_calls=False):
    counts = dict(new=0, prompt=0, http=0)
    class RejectProvider(BaseHTTPRequestHandler):
        def do_POST(self):
            counts['http'] += 1
            self.send_response(403)
            self.end_headers()
        do_GET = do_POST
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), RejectProvider)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix='ordessa-codex-managed-product-') as directory:
            private = Path(directory)
            project = private / 'project'
            project.mkdir(mode=0o700)
            module = (ROOT / 'plugins/harness/packaging/native-server-plan.mjs').as_uri()
            options = dict(harnessId='codex', nativeProfileHarnesses=['codex'],
                           pluginRoot=str(ROOT / 'plugins/harness'), artifactRoot=ASSET)
            plan = json.loads(subprocess.check_output(['node', '--input-type=module', '-e',
                f'import {{nativeServerPlan}} from {json.dumps(module)}; console.log(JSON.stringify(nativeServerPlan({json.dumps(options)}).args))'], text=True))
            flag = lambda name: plan[plan.index(name) + 1]
            runtime = create_composition().native_runtime(private / 'data', plugin_root=ROOT / 'plugins/harness',
                harness_id='codex', adapter_command=flag('--native-adapter-command'),
                adapter_args=tuple(arg.split('=', 1)[1] for arg in plan if arg.startswith('--native-adapter-arg=')),
                installed_artifact_root=ASSET, native_profile_harnesses=('codex',))
            opened = []
            wire = runtime.wire.dispatch
            def profile(method, **params):
                return wire('profiles.v2.' + method, params)['data']
            try:
                runtime.start()
                workspace = wire('workspaces.open', dict(requestId='probe-project-' + uuid4().hex,
                    environment=dict(kind='local', host=None, user=None), path=str(project)))['workspace']
                registry = runtime.plugin_host.provided_port('acp.channels')
                models = ['gpt-5.5', 'gpt-5.6-sol']
                providers = {}
                for route in ('managed', 'api'):
                    providers[route] = wire('providerModels.create', dict(requestId='probe-provider-' + uuid4().hex,
                        harness='codex', provider='openai' if route == 'managed' else 'synthetic-provider',
                        displayName='Probe ' + route, credentialId=None,
                        configuration=[dict(controlId='authentication', value='managed-account')] if route == 'managed' else [],
                        protocols=['openai-responses'], endpoints={} if route == 'managed' else {
                            'openai-responses': 'http://127.0.0.1:' + str(server.server_port)},
                        models=[dict(modelId=model, displayName=model, availability='available', unavailableReason=None)
                                for model in models]))['providerModel']
                presets = {}
                def save(pid, provider, model, version):
                    return profile('saveProfile', operationKey='probe-save-' + uuid4().hex,
                        profileId=pid, expectedVersion=version, patches=[dict(facetId='assets.model-provider', itemId='choice',
                        op='set', value=dict(harnessId='codex', providerConfigId=provider['id'], modelId=model))])
                for route in providers:
                    pid = profile('createProfile', operationKey='probe-profile-' + uuid4().hex,
                                  realm='local', harnessId='codex', displayName='Probe ' + route)['profileId']
                    save(pid, providers[route], models[0], 1)
                    presets[route] = pid
                sessions = []
                for slot, route in enumerate(('managed', 'managed', 'api')):
                    scope = 'probe-codex-' + uuid4().hex
                    cid = wire('acp.channel.open', dict(harnessId='codex', projectId=workspace['id'],
                        sessionScopeId=scope, configurationProfileId=presets[route]))['connectionId']
                    opened.append(cid)
                    channel = registry.get(cid)
                    inbox = queue.Queue()
                    channel.attach(ImmediateLoop(), inbox.put)
                    def request(method, params, *, channel=channel, inbox=inbox):
                        rid = 'probe-' + uuid4().hex
                        output = ''
                        if method == 'session/prompt' and (not allow_model_calls or counts['prompt'] >= 2):
                            raise ValueError('Bounded inference opt-in required')
                        counts['new'] += method == 'session/new'
                        counts['prompt'] += method == 'session/prompt'
                        channel.transport.send_line(json.dumps(dict(jsonrpc='2.0', id=rid, method=method, params=params)))
                        deadline = monotonic() + (180 if method == 'session/prompt' else 60)
                        while True:
                            line = inbox.get(timeout=max(0, deadline - monotonic()))
                            assert line is not None, 'Own adapter exited'
                            answer = json.loads(line)
                            if method == 'session/prompt' and answer.get('method') == 'session/update':
                                event = answer.get('params', {})
                                update = event.get('update', {})
                                if event.get('sessionId') == params['sessionId'] and update.get('sessionUpdate') == 'agent_message_chunk':
                                    content = update.get('content', {})
                                    if content.get('type') == 'text':
                                        output += content.get('text', '')
                                        assert len(output) <= 4096, 'Bounded output exceeded'
                            if answer.get('id') == rid:
                                assert 'error' not in answer, 'Native request refused: ' + method
                                if method == 'session/prompt':
                                    assert answer['result'].get('stopReason') == 'end_turn' and output.strip(), 'Real turn did not complete with text'
                                return answer['result']
                    request('initialize', dict(protocolVersion=1, clientCapabilities={}, clientInfo=dict(name='ordessa-no-model',version='1')))
                    assert request('authentication/status', {})['type'] == ('chat-gpt' if route == 'managed' else 'unauthenticated')
                    prepared = profile('prepareNativeCreation', connectionId=cid, profileId=presets[route], operationId='create:' + scope)
                    assert prepared['state'] == 'prepared', 'Initial preparation not confirmed'
                    native = request('session/new', dict(cwd=str(project), mcpServers=[]))['sessionId']
                    ref = profile('registerNativeSession', connectionId=cid, nativeSessionId=native, profileId=presets[route])['sessionRef']
                    assert 'receipt' in profile('beginTurnApplication', operationKey='probe-first-' + uuid4().hex, sessionRef=ref), 'Initial C4 missing'
                    sessions.append((cid, native, ref, request))
                    if slot == 0 and allow_model_calls:
                        request('session/prompt', dict(sessionId=native, prompt=[dict(type='text', text='Reply exactly OK. Do not use tools or access files.')]))
                save(presets['managed'], providers['managed'], models[1], 2)
                assert 'receipt' in profile('beginTurnApplication', operationKey='probe-next-' + uuid4().hex,
                                           sessionRef=sessions[0][2]), 'Next C4 missing'
                selected = []
                if allow_model_calls:
                    sessions[0][3]('session/prompt', dict(sessionId=sessions[0][1],
                        prompt=[dict(type='text', text='Reply exactly OK again. Do not use tools or access files.')]))
                for cid, native, _, _ in sessions:
                    observed = registry.query_native_configuration(cid, native)
                    selected.append(next(option['currentValue'] for option in observed.config_options if option['id'] == 'model'))
                assert selected == [models[1], models[0], models[0]], 'Independent configurations diverged'
                assert len({native for _, native, _, _ in sessions}) == 3, 'Native identities not distinct'
                assert counts == dict(new=3, prompt=2 if allow_model_calls else 0, http=0), 'Probe exceeded authorized effects'
                print(json.dumps(dict(scope='installed-product-managed-profile-canonical-c4',
                    officialAndApiIndependent=True, initialC4Confirmed=True, nextC4Confirmed=True,
                    nativeIdsDistinct=True, selectedModels=selected, counts=counts,
                    realChatConfirmed=allow_model_calls)), flush=True)
            finally:
                primary = sys.exc_info()[1]
                failed = []
                for cid in opened:
                    try: wire('acp.channel.release', dict(connectionId=cid))
                    except Exception: failed.append('channel')
                try: runtime.stop()
                except Exception: failed.append('runtime')
                if failed:
                    if primary is not None: primary.add_note('Own cleanup failed: ' + ','.join(failed))
                    else: raise RuntimeError('Own cleanup failed')
                print('Own channels released and isolated product stopped', flush=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-model-calls', action='store_true')
    run(allow_model_calls=parser.parse_args().allow_model_calls)
