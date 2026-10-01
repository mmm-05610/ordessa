"""Actual installed product/Profile/C4 official + API isolation.

Uses Ordessa's existing native login only. No credential export or global
configuration changes. Default mode has no inference; opt-in allows exactly two
short prompts (official then Go when explicitly selected). Creates three own native threads and releases
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
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from ordessa_server_product.composition import create_composition

ROOT = Path(__file__).resolve().parents[3]
ASSET_DEFAULT = '/opt/ordessa/harnesses/profile-codex-managed/artifacts'


def trusted_asset_root(value):
    """Explicit asset selection. Harness still applies full installed
    verification (root-owned, non-writable tree digest); this never relaxes it."""
    root = Path(value)
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError('Asset root must be an existing canonical directory')
    return str(root)


class ImmediateLoop:
    def call_soon_threadsafe(self, callback, argument):
        callback(argument)


def validate_transition_scope(allow_model_calls, switch_go, key_file, key_line):
    if switch_go and (not allow_model_calls or key_file is None or type(key_line) is not int or key_line < 1):
        raise ValueError('Provider history acceptance requires model opt-in and an explicit key file/line')


def run(*, allow_model_calls=False, switch_go=False, key_file=None, key_line=2,
        observe_go_relay=False, asset_root=None):
    validate_transition_scope(allow_model_calls, switch_go, key_file, key_line)
    asset = trusted_asset_root(asset_root or ASSET_DEFAULT)
    if observe_go_relay and not switch_go:
        raise ValueError('Go observation requires explicit provider transition')
    api_key = None
    if switch_go:
        lines = Path(key_file).read_text().splitlines()
        if key_line > len(lines) or not lines[key_line - 1].strip():
            raise ValueError('Destination key is absent')
        api_key = lines[key_line - 1].strip()
    counts = dict(new=0, prompt=0, http=0)
    token = 'ORDESSA_' + uuid4().hex[:12]
    upstream_counts = dict(requests=0, historyRequests=0)
    class RejectProvider(BaseHTTPRequestHandler):
        def do_POST(self):
            if observe_go_relay and self.path.startswith('/go/v1/'):
                upstream_counts['requests'] += 1
                length = int(self.headers.get('Content-Length', '0'))
                if (upstream_counts['requests'] > 8 or not 0 < length <= 2 * 1024 * 1024
                        or self.headers.get('Authorization') != 'Bearer ' + api_key):
                    self.send_error(403); return
                body = self.rfile.read(length)
                data = json.loads(body)
                has_history = token in body.decode()
                upstream_counts['historyRequests'] += has_history
                print(json.dumps(dict(stage='go-outbound-history', containsFirstToken=has_history,
                    previousResponsePresent=bool(data.get('previous_response_id')),
                    inputItems=len(data.get('input', [])), requestCount=upstream_counts['requests'])), flush=True)
                headers = {key: value for key, value in self.headers.items()
                           if key.lower() not in {'host', 'content-length', 'connection'}}
                request = Request('https://opencode.ai/zen/go/v1/' + self.path[len('/go/v1/'):],
                                  data=body, headers=headers, method='POST')
                try:
                    with urlopen(request, timeout=180) as response:
                        self.send_response(response.status)
                        self.send_header('Content-Type', response.headers.get('Content-Type', 'text/event-stream'))
                        self.end_headers()
                        while chunk := response.read(8192):
                            self.wfile.write(chunk); self.wfile.flush()
                except HTTPError as error:
                    self.send_error(error.code)
                return
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
                           pluginRoot=str(ROOT / 'plugins/harness'), artifactRoot=asset)
            plan = json.loads(subprocess.check_output(['node', '--input-type=module', '-e',
                f'import {{nativeServerPlan}} from {json.dumps(module)}; console.log(JSON.stringify(nativeServerPlan({json.dumps(options)}).args))'], text=True))
            flag = lambda name: plan[plan.index(name) + 1]
            runtime = create_composition().native_runtime(private / 'data', plugin_root=ROOT / 'plugins/harness',
                harness_id='codex', adapter_command=flag('--native-adapter-command'),
                adapter_args=tuple(arg.split('=', 1)[1] for arg in plan if arg.startswith('--native-adapter-arg=')),
                installed_artifact_root=asset, native_profile_harnesses=('codex',))
            opened, locators = [], []
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
                operations = []
                for slot, route in enumerate(('managed', 'managed', 'api')):
                    scope = 'probe-codex-' + uuid4().hex
                    cid = wire('acp.channel.open', dict(harnessId='codex', projectId=workspace['id'],
                        sessionScopeId=scope, configurationProfileId=presets[route]))['connectionId']
                    opened.append(cid)
                    channel = registry.get(cid)
                    if slot == 0:
                        configuration_rpc = channel._configuration_rpc
                        def counted_rpc(*args, **kwargs):
                            operations.append(args[1])  # Method only, never secret-bearing parameters.
                            return configuration_rpc(*args, **kwargs)
                        channel._configuration_rpc = counted_rpc
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
                            if answer.get('method') and 'id' in answer:
                                channel.transport.send_line(json.dumps(dict(jsonrpc='2.0', id=answer['id'],
                                    error=dict(code=-32601, message='Acceptance provides no client tools'))))
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
                                return (answer['result'], output) if method == 'session/prompt' else answer['result']
                    request('initialize', dict(protocolVersion=1, clientCapabilities={}, clientInfo=dict(name='ordessa-no-model',version='1')))
                    assert request('authentication/status', {})['type'] == ('chat-gpt' if route == 'managed' else 'unauthenticated')
                    prepared = profile('prepareNativeCreation', connectionId=cid, profileId=presets[route], operationId='create:' + scope)
                    assert prepared['state'] == 'prepared', 'Initial preparation not confirmed'
                    native = request('session/new', dict(cwd=str(project), mcpServers=[]))['sessionId']
                    ref = profile('registerNativeSession', connectionId=cid, nativeSessionId=native, profileId=presets[route])['sessionRef']
                    assert 'receipt' in profile('beginTurnApplication', operationKey='probe-first-' + uuid4().hex, sessionRef=ref), 'Initial C4 missing'
                    sessions.append((cid, native, ref, request))
                    if slot == 0 and allow_model_calls:
                        request('session/prompt', dict(sessionId=native, prompt=[dict(type='text', text=(
                            f'Remember this token for the next message: {token}. Reply only ACK. Do not use tools or access files.'
                            if switch_go else 'Reply exactly OK. Do not use tools or access files.'))]))
                        print(json.dumps(dict(stage='first-real-turn', completed=True)), flush=True)
                before_a = registry.query_native_configuration(sessions[0][0], sessions[0][1])
                before_b = registry.query_native_configuration(sessions[1][0], sessions[1][1])
                owner = registry.native_session_observation(sessions[0][0], sessions[0][1])
                if switch_go:
                    imported = wire('modelProvider.importApiKey', dict(requestId='probe-key-' + uuid4().hex,
                        harnessId='codex', apiKey=api_key))
                    assert imported['state'] == 'imported', 'Destination key import refused'
                    from ordessa_server.credentials import CredentialRecords
                    locators.append(CredentialRecords(runtime.database).get(imported['credentialId'], kind='api-key')['secret_locator'])
                    destination = wire('providerModels.create', dict(requestId='probe-go-' + uuid4().hex,
                        harness='codex', provider='opencode-go', displayName='Authorized Go destination',
                        credentialId=imported['credentialId'], configuration=[], protocols=['openai-responses'],
                        endpoints={'openai-responses': (f'http://127.0.0.1:{server.server_port}/go/v1'
                            if observe_go_relay else 'https://opencode.ai/zen/go/v1')},
                        models=[dict(modelId='gpt-5.6-luna', displayName='gpt-5.6-luna',
                                     availability='available', unavailableReason=None)]))['providerModel']
                    save(presets['managed'], destination, 'gpt-5.6-luna', 2)
                else:
                    save(presets['managed'], providers['managed'], models[1], 2)
                next_apply = profile('beginTurnApplication', operationKey='probe-next-' + uuid4().hex,
                                     sessionRef=sessions[0][2])
                assert 'receipt' in next_apply, 'Next C4 missing'
                if switch_go:
                    after_a = registry.query_native_configuration(sessions[0][0], sessions[0][1])
                    after_b = registry.query_native_configuration(sessions[1][0], sessions[1][1])
                    assert after_a.native_generation != before_a.native_generation, 'Native generation did not renew'
                    assert after_b == before_b, 'Other official session changed'
                    assert registry.native_session_observation(sessions[0][0], sessions[0][1]) is owner, 'Native owner changed'
                    assert next_apply['receipt']['sessionRef'] == sessions[0][2], 'Canonical conversation changed'
                    assert operations.count('_ordessa/session/configuration/restore') == 1, 'Restoration was not effect-once'
                    print(json.dumps(dict(stage='restoration-confirmed-before-next-prompt',
                        generationRenewed=True, otherOfficialUnchanged=True, canonicalUnchanged=True,
                        restorationEffects=1)), flush=True)
                selected = []
                if allow_model_calls:
                    _, text = sessions[0][3]('session/prompt', dict(sessionId=sessions[0][1],
                        prompt=[dict(type='text', text=(
                            'What token did I ask you to remember? Reply only that token. Do not use tools or access files.'
                            if switch_go else 'Reply exactly OK again. Do not use tools or access files.'))]))
                    if switch_go:
                        print(json.dumps(dict(stage='second-real-turn', replyChars=len(text),
                            historyTokenPresent=token in text, observedGoRequests=upstream_counts['requests']
                                if observe_go_relay else None)), flush=True)
                        assert token in text, 'History was not preserved across provider restoration'
                        if observe_go_relay:
                            assert upstream_counts['requests'] > 0, 'No request reached the declared Go upstream'
                            assert upstream_counts['historyRequests'] > 0, 'Go request did not carry the first-turn token'
                for cid, native, _, _ in sessions:
                    observed = registry.query_native_configuration(cid, native)
                    selected.append(next(option['currentValue'] for option in observed.config_options if option['id'] == 'model'))
                assert selected == ['gpt-5.6-luna' if switch_go else models[1], models[0], models[0]], 'Independent configurations diverged'
                assert len({native for _, native, _, _ in sessions}) == 3, 'Native identities not distinct'
                assert counts == dict(new=3, prompt=2 if allow_model_calls else 0, http=0), 'Probe exceeded authorized effects'
                print(json.dumps(dict(scope='installed-product-managed-profile-canonical-c4',
                    officialAndApiIndependent=True, initialC4Confirmed=True, nextC4Confirmed=True,
                    nativeIdsDistinct=True, selectedModels=selected, counts=counts,
                    realChatConfirmed=allow_model_calls, officialToApiHistoryPreserved=switch_go,
                    providerRestorationEffects=operations.count('_ordessa/session/configuration/restore'),
                    directApiEndpoint=switch_go and not observe_go_relay,
                    upstreamRequestCount=upstream_counts['requests'] if observe_go_relay else None if switch_go else 0)), flush=True)
            finally:
                primary = sys.exc_info()[1]
                failed = []
                for cid in opened:
                    try: wire('acp.channel.release', dict(connectionId=cid))
                    except Exception: failed.append('channel')
                for locator in locators:
                    try: runtime.secret_store.delete(locator)
                    except Exception: failed.append('imported-key')
                try: runtime.stop()
                except Exception: failed.append('runtime')
                if failed:
                    if primary is not None: primary.add_note('Own cleanup failed: ' + ','.join(failed))
                    else: raise RuntimeError('Own cleanup failed')
                print(json.dumps(dict(stage='probe-cleaned', counts=counts,
                    observedGoRequests=upstream_counts['requests'] if observe_go_relay else None,
                    importedKeyEntriesRemoved=len(locators))), flush=True)
                print('Own channels released and isolated product stopped', flush=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-model-calls', action='store_true')
    parser.add_argument('--switch-go', action='store_true')
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--key-line', type=int, default=2)
    parser.add_argument('--observe-go-relay', action='store_true')
    parser.add_argument('--asset-root', default=ASSET_DEFAULT,
                        help='Explicit verified asset root; Harness re-verifies it in full.')
    run(**vars(parser.parse_args()))
