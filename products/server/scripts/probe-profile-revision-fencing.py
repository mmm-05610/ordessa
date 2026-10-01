"""Global Profile revision fencing (C08) and failed first prepare (C10), real chain, no prompts.

Providers are credential-less by construction: the user keyring collection is
LOCKED, and ``server_provider_models.credential_id`` is nullable, so a
credential-less provider is a real supported shape. No keyring entry is created,
read or deleted, and no inference is attempted.
"""
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


def log(event):
    print(json.dumps(event), file=sys.stderr, flush=True)


class RejectProvider(BaseHTTPRequestHandler):
    def do_GET(self):
        COUNTS['http'] += 1
        self.send_response(403); self.end_headers()
        self.wfile.write(b'{"error":"synthetic probe denies inference"}')
    do_POST = do_GET
    def log_message(self, *_): pass


class ImmediateLoop:
    def call_soon_threadsafe(self, callback, argument): callback(argument)


def refused(call):
    """A typed refusal is evidence, not a crash: return its exact projection."""
    try:
        return {'refused': False, 'value': call()}
    except Exception as error:
        return {'refused': True, 'family': getattr(error, 'family', type(error).__name__),
                'message': str(getattr(error, 'message', error)),
                'internalCode': (getattr(error, 'details', None) or {}).get('internalCode')}


def run():
    COUNTS.update(http=0, prompt=0, new=0)
    server = ThreadingHTTPServer(('127.0.0.1', 0), RejectProvider)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    previous_environment = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix='ordessa-profile-fencing-') as folder:
            private = Path(folder)
            for name in ('home', 'project', 'config'): (private / name).mkdir(mode=0o700)
            os.environ.update(HOME=str(private / 'home'), XDG_CONFIG_HOME=str(private / 'config'),
                CODEX_HOME=str(private / 'config/codex'), CLAUDE_CONFIG_DIR=str(private / 'config/claude'))
            brands = ['codex', 'claude-code']
            module = (ROOT / 'plugins/harness/packaging/native-server-plan.mjs').as_uri()
            plan = json.loads(subprocess.check_output(['node', '--input-type=module', '-e',
                f"import {{nativeServerPlan}} from {json.dumps(module)}; console.log(JSON.stringify(nativeServerPlan({{harnessIds:{json.dumps(brands)},nativeProfileHarnesses:{json.dumps(brands)},piProfileBridge:false,artifactRoots:{{}},pluginRoot:{json.dumps(str(ROOT / 'plugins/harness'))},artifactRoot:'/opt/ordessa/harnesses/profile-native/artifacts'}}).args))"], text=True))
            value = lambda flag: plan[plan.index(flag) + 1]
            runtime = create_composition().native_runtime(private / 'data', plugin_root=ROOT / 'plugins/harness',
                harness_id=value('--native-harness'), adapter_command=value('--native-adapter-command'),
                adapter_args=tuple(arg.split('=', 1)[1] for arg in plan if arg.startswith('--native-adapter-arg=')),
                installed_artifact_root=value('--native-installed-artifact-root'), native_profile_harnesses=tuple(brands),
                pi_profile_bridge=False,
                additional_adapters=tuple(json.loads(value('--native-additional-adapters'))) if '--native-additional-adapters' in plan else ())
            opened, native_ids, cases, not_covered = [], [], {}, []
            wire = runtime.wire.dispatch
            def profile(name, **params): return wire('profiles.v2.' + name, params)['data']
            try:
                runtime.start()
                workspace = wire('workspaces.open', dict(requestId='probe-project-' + uuid4().hex,
                    environment=dict(kind='local', host=None, user=None), path=str(private / 'project')))['workspace']
                registry = runtime.plugin_host.provided_port('acp.channels')
                endpoint = 'http://127.0.0.1:' + str(server.server_port)
                store = runtime.plugin_host.provided_port('profile.core').db

                def sessions_of(profile_id):
                    with store.read() as conn:
                        return [dict(row) for row in conn.execute(
                            'SELECT session_id,session_uid,native_session_key,current_profile_id,'
                            'current_revision,switch_state FROM profile_sessions WHERE current_profile_id=?',
                            (profile_id,))]

                def open_channel(brand, scope):
                    opened_channel = wire('acp.channel.open', dict(harnessId=brand,
                        projectId=workspace['id'], sessionScopeId=scope))
                    opened.append(opened_channel['connectionId'])
                    channel = registry.get(opened_channel['connectionId'])
                    inbox = queue.Queue(); channel.attach(ImmediateLoop(), inbox.put)
                    calls = []
                    native_rpc = channel._configuration_rpc
                    def counted_rpc(*arguments, **keywords):
                        calls.append(arguments[1])  # method only; params may carry secrets
                        return native_rpc(*arguments, **keywords)
                    channel._configuration_rpc = counted_rpc
                    def request(method, params):
                        rid = 'probe-' + uuid4().hex
                        COUNTS['new'] += method == 'session/new'; COUNTS['prompt'] += method == 'session/prompt'
                        channel.transport.send_line(json.dumps(dict(jsonrpc='2.0', id=rid, method=method, params=params)))
                        deadline = monotonic() + 120
                        while True:
                            line = inbox.get(timeout=max(0, deadline - monotonic()))
                            assert line is not None, 'Native adapter exited before reply'
                            answer = json.loads(line)
                            if answer.get('id') == rid: return answer
                    def drain():
                        seen = list(calls); calls.clear(); return seen
                    initialized = request('initialize', dict(protocolVersion=1, clientCapabilities={},
                        clientInfo=dict(name='ordessa-no-model', version='1')))
                    assert 'error' not in initialized, initialized
                    assert not drain(), 'Channel initialize performed a native effect'
                    return channel, request, drain

                def create_profile(brand, name, model, provider_id=None, version=1):
                    preset = profile('createProfile', operationKey='probe-profile-' + uuid4().hex,
                        realm='local', harnessId=brand, displayName=name)
                    saved = profile('saveProfile', operationKey='probe-save-' + uuid4().hex,
                        profileId=preset['profileId'], expectedVersion=version, patches=[dict(
                        facetId='assets.model-provider', itemId='choice', op='set',
                        value=dict(harnessId=brand, providerConfigId=provider_id, modelId=model))])['profile']
                    return preset['profileId'], saved

                def execute(request, brand, profile_id, connection_id):
                    """session/new -> canonical registration -> C4. Returns the whole chain."""
                    before = COUNTS['new']
                    answer = request('session/new', dict(cwd=str(private / 'project'), mcpServers=[]))
                    assert 'error' not in answer, ('Native session/new refused: ' + json.dumps(answer['error']))
                    native = answer['result']['sessionId']
                    native_ids.append(native)
                    binding = profile('registerNativeSession', connectionId=connection_id,
                        nativeSessionId=native, profileId=profile_id)
                    applied = profile('beginTurnApplication', operationKey='probe-turn-' + uuid4().hex,
                        sessionRef=binding['sessionRef'])
                    assert 'receipt' in applied, 'Profile application not confirmed'
                    snapshot = registry.query_native_configuration(connection_id, native)
                    return {'sessionNewCalls': COUNTS['new'] - before,
                        'nativeSessionId': native, 'sessionUid': binding['sessionRef']['sessionUid'],
                        'receiptProfileRevision': applied['receipt']['profileRevision'],
                        'receiptEvidenceKind': applied['receipt']['evidenceKind'],
                        'nativeModel': next(option['currentValue'] for option in snapshot.config_options
                            if option['id'] == 'model')}

                for brand, protocol, models in [('codex', 'openai-responses', ('gpt-5.5', 'gpt-5.6-sol')),
                                                ('claude-code', 'anthropic-messages', ('sonnet', 'haiku'))]:
                    provider = wire('providerModels.create', dict(requestId='probe-provider-' + uuid4().hex,
                        harness=brand, provider='synthetic-provider', displayName='Probe provider',
                        credentialId=None, configuration=[], protocols=[protocol], endpoints={protocol: endpoint},
                        models=[dict(modelId=model, displayName=model, availability='available',
                            unavailableReason=None) for model in models]))['providerModel']
                    assert provider['credentialId'] is None, 'Probe provider must carry no credential'

                    # -- C08: the global revision moves between prepare and execute.
                    profile_id, first = create_profile(brand, 'C08 probe', models[0], provider['id'])
                    scope = 'probe-c08-' + uuid4().hex
                    channel, request, drain = open_channel(brand, scope)
                    operation = 'create:' + channel.session_scope_id
                    prepared = profile('prepareNativeCreation', connectionId=channel.connection_id,
                        profileId=profile_id, operationId=operation)
                    assert prepared['state'] == 'prepared', prepared
                    assert drain() == ['_ordessa/channel/configuration/prepare'], 'Preparation did not prepare once'
                    # A repeated identical prepare is answered by the retained
                    # operation query, never by resending the preparation effect.
                    repeated = profile('prepareNativeCreation', connectionId=channel.connection_id,
                        profileId=profile_id, operationId=operation)
                    assert repeated['state'] == 'prepared', repeated
                    assert drain() == ['_ordessa/channel/configuration/operation'], 'Repeat prepare replayed an effect'
                    moved = profile('saveProfile', operationKey='probe-save-' + uuid4().hex, profileId=profile_id,
                        expectedVersion=first['version'], patches=[dict(facetId='assets.model-provider',
                        itemId='choice', op='set', value=dict(harnessId=brand, providerConfigId=provider['id'],
                        modelId=models[1]))])['profile']
                    assert moved['currentRevision'] > prepared['profileRevision'], (first, moved)
                    assert moved['version'] == first['version'] + 1, (first, moved)
                    before = dict(COUNTS)
                    stale = refused(lambda: profile('prepareNativeCreation', connectionId=channel.connection_id,
                        profileId=profile_id, operationId=operation))
                    assert stale['refused'], 'Stale preparation plan was accepted after the revision moved'
                    assert stale['family'] == 'CONFLICT_REQUEST' and stale['internalCode'] == 'SWITCH_BLOCKED', stale
                    assert drain() == [], 'Stale plan reached the native adapter'
                    assert dict(COUNTS) == before, 'Stale plan produced a native effect'
                    assert not sessions_of(profile_id), 'Stale plan created a session record'
                    outcome = execute(request, brand, profile_id, channel.connection_id)
                    # The explicit execute re-read the moved revision; the
                    # superseded plan's model was never applied.
                    assert outcome['sessionNewCalls'] == 1, outcome
                    assert outcome['receiptProfileRevision'] == moved['currentRevision'], outcome
                    assert outcome['nativeModel'] == models[1], outcome
                    cases.setdefault('C08', {})[brand] = {
                        'preparedRevision': prepared['profileRevision'], 'movedRevision': moved['currentRevision'],
                        'repeatPrepareNativeCalls': ['_ordessa/channel/configuration/operation'],
                        'stalePlanRefusal': stale, 'stalePlanNativeCalls': [], 'countersAtRefusal': before,
                        'execute': outcome}

                    # -- C10: a first preparation that cannot resolve creates nothing.
                    broken_id, broken = create_profile(brand, 'C10 probe', models[0],
                        'provider_absent_' + uuid4().hex)
                    broken_scope = 'probe-c10-' + uuid4().hex
                    broken_channel, broken_request, broken_drain = open_channel(brand, broken_scope)
                    broken_operation = 'create:' + broken_channel.session_scope_id
                    before = dict(COUNTS)
                    failure = refused(lambda: profile('prepareNativeCreation',
                        connectionId=broken_channel.connection_id, profileId=broken_id,
                        operationId=broken_operation))
                    assert failure['refused'], 'Unresolvable Profile choice was prepared'
                    assert failure['family'] == 'CONFLICT_REQUEST' and failure['internalCode'] == 'PROVIDER_NOT_FOUND', failure
                    assert dict(COUNTS) == before, 'Failed preparation produced a native effect'
                    assert broken_drain() == [], 'Failed preparation reached the native adapter'
                    assert not sessions_of(broken_id), 'Failed preparation created a session record'
                    fixed = profile('saveProfile', operationKey='probe-save-' + uuid4().hex, profileId=broken_id,
                        expectedVersion=broken['version'], patches=[dict(facetId='assets.model-provider',
                        itemId='choice', op='set', value=dict(harnessId=brand, providerConfigId=provider['id'],
                        modelId=models[1]))])['profile']
                    retry = profile('prepareNativeCreation', connectionId=broken_channel.connection_id,
                        profileId=broken_id, operationId=broken_operation)
                    assert retry['state'] == 'prepared', retry
                    assert retry['profileRevision'] == fixed['currentRevision'], retry
                    retried = execute(broken_request, brand, broken_id, broken_channel.connection_id)
                    assert retried['sessionNewCalls'] == 1, retried
                    assert retried['receiptProfileRevision'] == fixed['currentRevision'], retried
                    cases.setdefault('C10', {})[brand] = {
                        'firstPrepareRefusal': failure, 'countersAtRefusal': before,
                        'sessionRowsAfterFailure': 0, 'fixedRevision': fixed['currentRevision'],
                        'retry': retried}
                    log({'stage': 'brand-complete', 'brand': brand, 'counts': dict(COUNTS)})

                assert COUNTS['prompt'] == 0 and COUNTS['http'] == 0, COUNTS
                assert COUNTS['new'] == 2 * len(brands), COUNTS
                assert len(set(native_ids)) == len(native_ids), native_ids
                not_covered.append('C08: an effect already Unknown was not reachable at L3 - the credential-less '
                    'native route never enters the Unknown state without fault injection; the query-only leg is '
                    'covered as the retained preparation operation query above')
                not_covered.append('C10: draft preservation verbatim is a UI property and is not observable at L3; '
                    'this probe covers the backend half only')
                print(json.dumps(dict(scope='product-chain-profile-revision-fencing-c08-c10', cases=cases,
                    nativeSessionIds=native_ids, counts=dict(COUNTS), notCovered=not_covered)))
            finally:
                primary = sys.exc_info()[1]
                failed = []
                for cid in opened:
                    try: wire('acp.channel.release', dict(connectionId=cid))
                    except Exception: failed.append('channel')
                try: runtime.stop()
                except Exception: failed.append('runtime')
                if failed:
                    if primary is not None: primary.add_note('Own cleanup failures: ' + ','.join(failed))
                    else: raise RuntimeError('Own cleanup failures: ' + ','.join(failed)) from None
                log('Released own channels, created no keyring entry, stopped isolated product')
    finally:
        os.environ.clear(); os.environ.update(previous_environment)
        server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__': run()
