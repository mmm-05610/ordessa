"""Per-session Profile isolation (C02, C03), real product chain, no prompts.

Providers are credential-less by construction: the user keyring collection is
LOCKED, and ``server_provider_models.credential_id`` is nullable, so a
credential-less provider is a real supported shape. No keyring entry is created,
read or deleted, and no inference is attempted.

C02 asks that a session-local model switch leaves the Profile global value-by-
value intact and leaves the other session alone; C03 asks that a session that
already overrode the model keeps its temporary model while a global edit of the
model *and* of a second, not-overridden preference applies. Both are observed
only through real product wires and the real native apply boundary; anything
the running product cannot express is recorded as not covered, never simulated.
"""
import base64
import hashlib
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

#: The one Probe skill installed through the real ``skills.import*`` wire so
#: ``assets.skills`` publishes a real item instead of an empty catalogue. Its
#: frontmatter is fixed so the import digest is reproducible.
SKILL_ID = 'probe-isolation-skill'
SKILL_MD = (b'---\nname: ' + SKILL_ID.encode() + b'\ndescription: Installed only to '
           b'observe whether assets.skills publishes an overridable item.\n---\n\nProbe body.\n')
SKILL_ENABLE = {'decision': 'enable', 'revision': 1}
SKILL_DISABLE = {'decision': 'disable'}

#: harness, protocol, the contract's two models (global then session override)
#: and the third installed-asset model id a C03 global edit moves to. All four
#: are real ids the brand adapter itself offers in ``config_options``; the third
#: exists because with only two model values an override and a *subsequent*
#: global edit can never disagree, which would make C03 unfalsifiable.
BRANDS = (
    ('codex', 'openai-responses', ('gpt-5.5', 'gpt-5.6-sol', 'gpt-5.2')),
    ('claude-code', 'anthropic-messages', ('haiku', 'sonnet', 'opus[1m]')),
)


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
        with tempfile.TemporaryDirectory(prefix='ordessa-session-isolation-') as folder:
            private = Path(folder)
            for name in ('home', 'project', 'config'): (private / name).mkdir(mode=0o700)
            os.environ.update(HOME=str(private / 'home'), XDG_CONFIG_HOME=str(private / 'config'),
                CODEX_HOME=str(private / 'config/codex'), CLAUDE_CONFIG_DIR=str(private / 'config/claude'))
            brands = [entry[0] for entry in BRANDS]
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
            catalogue = {}
            wire = runtime.wire.dispatch
            def profile(name, **params): return wire('profiles.v2.' + name, params)['data']
            try:
                runtime.start()
                workspace = wire('workspaces.open', dict(requestId='probe-project-' + uuid4().hex,
                    environment=dict(kind='local', host=None, user=None), path=str(private / 'project')))['workspace']
                registry = runtime.plugin_host.provided_port('acp.channels')
                store = runtime.plugin_host.provided_port('profile.core').db
                endpoint = 'http://127.0.0.1:' + str(server.server_port)

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

                def create_profile(brand, model, provider_id, version=1):
                    """A Profile whose globals carry the model choice AND the one
                    not-overridden preference C03 needs (a real skills binding)."""
                    preset = profile('createProfile', operationKey='probe-profile-' + uuid4().hex,
                        realm='local', harnessId=brand, displayName='C02/C03 probe')
                    saved = profile('saveProfile', operationKey='probe-save-' + uuid4().hex,
                        profileId=preset['profileId'], expectedVersion=version, patches=[
                        dict(facetId='assets.model-provider', itemId='choice', op='set',
                            value=dict(harnessId=brand, providerConfigId=provider_id, modelId=model)),
                        dict(facetId='assets.skills', itemId=SKILL_ID, op='set',
                            value=SKILL_ENABLE)])['profile']
                    return preset['profileId'], saved

                def turn(session_ref, key='probe-turn-'):
                    applied = profile('beginTurnApplication', operationKey=key + uuid4().hex,
                        sessionRef=session_ref)
                    assert 'receipt' in applied, 'Profile application not confirmed'
                    return applied['receipt']

                def native_model(channel, native):
                    snapshot = registry.query_native_configuration(channel.connection_id, native)
                    return next(option['currentValue'] for option in snapshot.config_options
                        if option['id'] == 'model')

                def option_ids(channel, native):
                    snapshot = registry.query_native_configuration(channel.connection_id, native)
                    return [option['id'] for option in snapshot.config_options]

                def globals_of(profile_id):
                    """Two independent reads of the Profile's global values: the
                    resolved record and the raw facet-value rows at its current
                    revision. The version rides along for the revision fence."""
                    record = profile('getProfile', profileId=profile_id)
                    preview = profile('resolvePreview', profileId=profile_id)
                    with store.read() as conn:
                        rows = [dict(row) for row in conn.execute(
                            'SELECT facet_id,item_id,value_json FROM profile_facet_values '
                            'WHERE profile_id=? AND config_revision=? ORDER BY facet_id,item_id',
                            (profile_id, record['currentRevision']))]
                    return {'version': record['version'], 'currentRevision': record['currentRevision'],
                        'previewItems': {f"{item['facetId']}/{item['itemId']}": item['value']
                            for item in preview['items']},
                        'rows': {f"{row['facet_id']}/{row['item_id']}": json.loads(row['value_json'])
                            for row in rows}}

                def session_view(session_ref):
                    view = profile('inspectSessionConfig', sessionRef=session_ref)
                    return {f"{item['facetId']}/{item['itemId']}":
                        {'value': item['value'], 'source': item['source']['kind']}
                        for item in view['items']}

                # -- the second overridable item, sought on the real product ---
                before = profile('describeFacets', harnessId='codex')
                catalogue['beforeInstall'] = {facet['facetId']: [item['itemId'] for item in facet['items']]
                    for facet in before}
                installed = refused(lambda: install_probe_skill(wire, private))
                assert not installed['refused'], installed
                after = profile('describeFacets', harnessId='codex')
                catalogue['afterInstall'] = {facet['facetId']: [
                    {'itemId': item['itemId'], 'overrideSupported': item['overrideSupported'],
                     'effect': item['effect']} for item in facet['items']]
                    for facet in after}
                skill_items = [facet for facet in after if facet['facetId'] == 'assets.skills'][0]['items']
                assert [item['itemId'] for item in skill_items] == [SKILL_ID], skill_items
                catalogue['secondItemSource'] = 'skills.importBegin/importChunk/importPreview/' \
                    'importCommit against the running product; the catalogue item is the facet provider\'s ' \
                    'live listing of installed skill assets, never a fabricated item'
                catalogue['skillsResolveAbsentProfile'] = refused(lambda: wire('skills.resolve',
                    dict(requestId='probe-' + uuid4().hex, harnessId='codex', profileId='profile_absent_probe')))
                log({'stage': 'catalogue', 'catalogue': catalogue})

                for brand, protocol, (first, second, third) in BRANDS:
                    provider = wire('providerModels.create', dict(requestId='probe-provider-' + uuid4().hex,
                        harness=brand, provider='synthetic-provider', displayName='Probe provider',
                        credentialId=None, configuration=[], protocols=[protocol], endpoints={protocol: endpoint},
                        models=[dict(modelId=model, displayName=model, availability='available',
                            unavailableReason=None) for model in (first, second, third)]))['providerModel']
                    assert provider['credentialId'] is None, 'Probe provider must carry no credential'

                    profile_id, saved = create_profile(brand, first, provider['id'])
                    channels = {}
                    for tag in ('A', 'B'):
                        channel, request, drain = open_channel(brand, 'probe-iso-' + tag + '-' + uuid4().hex)
                        prepared = profile('prepareNativeCreation', connectionId=channel.connection_id,
                            profileId=profile_id, operationId='create:' + channel.session_scope_id)
                        assert prepared['state'] == 'prepared', prepared
                        assert drain() == ['_ordessa/channel/configuration/prepare'], 'Preparation did not prepare once'
                        channels[tag] = (channel, request, drain)

                    def execute(tag):
                        """session/new -> canonical registration -> first real apply."""
                        channel, request, drain = channels[tag]
                        before_new = COUNTS['new']
                        answer = request('session/new', dict(cwd=str(private / 'project'), mcpServers=[]))
                        assert 'error' not in answer, ('Native session/new refused: ' + json.dumps(answer['error']))
                        native = answer['result']['sessionId']
                        native_ids.append(native)
                        binding = profile('registerNativeSession', connectionId=channel.connection_id,
                            nativeSessionId=native, profileId=profile_id)
                        receipt = turn(binding['sessionRef'])
                        return {'tag': tag, 'channel': channel, 'drain': drain, 'native': native,
                                'binding': binding, 'receipt': receipt, 'sessionNewCalls': COUNTS['new'] - before_new,
                                'targetServerId': binding['target']['serverId']}

                    session_a, session_b = execute('A'), execute('B')
                    assert session_a['native'] != session_b['native'], 'A and B are the same native session'
                    assert session_a['sessionNewCalls'] == 1 and session_b['sessionNewCalls'] == 1, COUNTS
                    # Both sessions read the Profile's model from two independent
                    # sources: the native effective configuration and Profile's own
                    # resolved session view.
                    assert native_model(session_a['channel'], session_a['native']) == first, first
                    assert native_model(session_b['channel'], session_b['native']) == first, first
                    initial_a = session_view(session_a['binding']['sessionRef'])
                    initial_b = session_view(session_b['binding']['sessionRef'])
                    model_key = 'assets.model-provider/choice'
                    assert initial_a[model_key]['value']['modelId'] == first, initial_a
                    assert initial_b[model_key]['value']['modelId'] == first, initial_b
                    assert initial_a[model_key]['source'] == 'profile' and initial_b[model_key]['source'] == 'profile', (initial_a, initial_b)
                    globals_before = globals_of(profile_id)
                    assert globals_before['previewItems'][model_key]['modelId'] == first, globals_before
                    assert globals_before['previewItems']['assets.skills/' + SKILL_ID] == SKILL_ENABLE, globals_before
                    # The catalogue is not a promise: a name the facet does not
                    # publish is refused with a type, never silently accepted.
                    catalogue.setdefault('unknownItemRefusal', refused(lambda: profile('saveProfile',
                        operationKey='probe-save-' + uuid4().hex, profileId=profile_id,
                        expectedVersion=globals_before['version'],
                        patches=[dict(facetId='assets.skills', itemId='no-such-item', op='set', value={})])))
                    native_option_ids = option_ids(session_a['channel'], session_a['native'])

                    # -- the named per-session model API, answered by the product ---
                    # ``serverInstanceId`` is resolved from the live runtime, never
                    # invented: the Profile session owner publishes it, and
                    # registerNativeSession echoes the same identity back.
                    owners = runtime.plugin_host.provided_port('profile.native-sessions').owners
                    server_instance_id = owners._server_id
                    assert session_a['targetServerId'] == server_instance_id, (session_a['targetServerId'], server_instance_id)
                    target_a = dict(serverInstanceId=server_instance_id, harnessId=brand, acpSessionId=session_a['native'])
                    target_b = dict(serverInstanceId=server_instance_id, harnessId=brand, acpSessionId=session_b['native'])
                    inspect = refused(lambda: wire('modelProvider.inspectChoice', dict(target=target_a,
                        choice=dict(providerConfigId=provider['id'], modelId=second))))
                    choose = refused(lambda: wire('modelProvider.chooseForSession', dict(target=target_a,
                        choice=dict(providerConfigId=provider['id'], modelId=second), operationKey='probe-choose-' + uuid4().hex)))
                    queued_after = refused(lambda: wire('modelProvider.queryChoice', dict(target=target_a)))
                    queued_after_b = refused(lambda: wire('modelProvider.queryChoice', dict(target=target_b)))

                    # -- the per-session override the running product accepts -----
                    overridden = profile('setSessionOverride', operationKey='probe-override-' + uuid4().hex,
                        sessionRef=session_a['binding']['sessionRef'], facetId='assets.model-provider',
                        itemId='choice', value=dict(harnessId=brand, providerConfigId=provider['id'], modelId=second))
                    override_items = {f"{item['facetId']}/{item['itemId']}":
                        {'value': item['value'], 'source': item['source']['kind']} for item in overridden['items']}
                    assert override_items[model_key]['source'] == 'session-overlay', override_items
                    assert override_items[model_key]['value']['modelId'] == second, override_items
                    assert override_items['assets.skills/' + SKILL_ID]['source'] == 'profile', override_items
                    assert session_view(session_b['binding']['sessionRef'])[model_key]['source'] == 'profile', 'B followed A'
                    # Queuing applies nothing: both sessions still read the global.
                    assert native_model(session_a['channel'], session_a['native']) == first, 'Queueing applied a turn'
                    assert native_model(session_b['channel'], session_b['native']) == first, 'Queueing applied a turn'

                    turn_a = turn(session_a['binding']['sessionRef'])
                    model_after_a = native_model(session_a['channel'], session_a['native'])
                    turn_b = turn(session_b['binding']['sessionRef'])
                    model_after_b = native_model(session_b['channel'], session_b['native'])
                    globals_after = globals_of(profile_id)
                    assert model_after_a == second, (model_after_a, second)
                    assert model_after_b == first, (model_after_b, first)
                    # The global must be unchanged value by value, not merely unrevisioned.
                    for field in ('harnessId', 'providerConfigId', 'modelId'):
                        assert (globals_before['previewItems'][model_key][field]
                            == globals_after['previewItems'][model_key][field]), (field, globals_before, globals_after)
                        assert (globals_before['rows'][model_key][field]
                            == globals_after['rows'][model_key][field]), (field, globals_before, globals_after)
                    assert globals_before['rows'] == globals_after['rows'], (globals_before, globals_after)
                    assert globals_before['version'] == globals_after['version'], (globals_before, globals_after)
                    assert globals_after['version'] == saved['version'], (saved, globals_after)
                    # Recorded, not asserted: the receipt's overlay_revision tracks a
                    # pending Profile *selection* sequence, not the session overlay
                    # layer, so it stays null for an ordinary every-submit re-apply.
                    assert turn_a['profileRevision'] == globals_after['currentRevision'], (turn_a, globals_after)
                    assert turn_b['profileRevision'] == globals_after['currentRevision'], (turn_b, globals_after)
                    cases.setdefault('C02', {})[brand] = {
                        'initialModelA': first, 'initialModelB': first,
                        'initialSources': {'nativeConfigOptions': native_option_ids,
                            'profileSessionViewA': initial_a[model_key],
                            'profileSessionViewB': initial_b[model_key]},
                        'sessionIds': {'A': session_a['native'], 'B': session_b['native']},
                        'serverInstanceId': {'resolvedFrom': 'profile.native-sessions ProfileSessionOwner',
                            'value': server_instance_id, 'echoedByRegisterNativeSession': session_a['targetServerId']},
                        'modelProviderInspectChoice': inspect,
                        'modelProviderChooseForSession': choose,
                        'modelProviderQueryChoiceAfterChoose': {'A': queued_after, 'B': queued_after_b},
                        'sessionOverrideAccepted': override_items,
                        'afterOverride': {'modelA': model_after_a, 'modelB': model_after_b,
                            'overlayRevisionA': turn_a['overlayRevision'], 'overlayRevisionB': turn_b['overlayRevision']},
                        'globalBefore': globals_before, 'globalAfter': globals_after,
                        'globalVersionBefore': globals_before['version'],
                        'globalVersionAfter': globals_after['version']}

                    # -- C03: the global moves the model and the other preference --
                    moved = profile('saveProfile', operationKey='probe-save-' + uuid4().hex,
                        profileId=profile_id, expectedVersion=globals_after['version'], patches=[
                        dict(facetId='assets.model-provider', itemId='choice', op='set',
                            value=dict(harnessId=brand, providerConfigId=provider['id'], modelId=third)),
                        dict(facetId='assets.skills', itemId=SKILL_ID, op='set', value=SKILL_DISABLE)])['profile']
                    globals_moved = globals_of(profile_id)
                    assert globals_moved['version'] == globals_after['version'] + 1, (globals_after, globals_moved)
                    assert globals_moved['previewItems'][model_key]['modelId'] == third, globals_moved
                    assert globals_moved['previewItems']['assets.skills/' + SKILL_ID] == SKILL_DISABLE, globals_moved
                    turn_a2 = turn(session_a['binding']['sessionRef'])
                    model_after_a2 = native_model(session_a['channel'], session_a['native'])
                    turn_b2 = turn(session_b['binding']['sessionRef'])
                    model_after_b2 = native_model(session_b['channel'], session_b['native'])
                    final_a = session_view(session_a['binding']['sessionRef'])
                    final_b = session_view(session_b['binding']['sessionRef'])
                    skill_key = 'assets.skills/' + SKILL_ID
                    # A keeps its temporary model while the global moved elsewhere.
                    assert model_after_a2 == second, (model_after_a2, second, third)
                    assert final_a[model_key]['source'] == 'session-overlay', final_a
                    assert final_a[model_key]['value']['modelId'] == second, final_a
                    # The preference A never overrode follows the global.
                    assert final_a[skill_key]['source'] == 'profile', final_a
                    assert final_a[skill_key]['value'] == SKILL_DISABLE, final_a
                    # B overrode nothing, so both of its values follow the global.
                    assert model_after_b2 == third, (model_after_b2, third)
                    assert final_b[model_key]['source'] == 'profile', final_b
                    assert final_b[skill_key]['value'] == SKILL_DISABLE, final_b
                    # A's applied facts still carry its own choice, never the moved global.
                    assert turn_a2['executionId'] == session_a['native'], (turn_a2, session_a['native'])
                    assert turn_b2['executionId'] == session_b['native'], (turn_b2, session_b['native'])
                    skills_view_a = refused(lambda: wire('skills.resolve', dict(requestId='probe-' + uuid4().hex,
                        projectId=workspace['id'], harnessId=brand, profileId=profile_id)))
                    skills_view_session_a = refused(lambda: wire('skills.resolve', dict(requestId='probe-' + uuid4().hex,
                        projectId=workspace['id'], harnessId=brand, profileId=profile_id,
                        sessionRef=session_a['binding']['sessionRef']['sessionUid'])))
                    # Third source: the Skills resolver's own layer ladder for A's
                    # session must name the profile layer as the decider.
                    assert not skills_view_session_a['refused'], skills_view_session_a
                    excluded_row = skills_view_session_a['value']['excludedSkills'][0]
                    assert excluded_row['excludedBy']['layer'] == 'profile', excluded_row
                    decisions = {row['layer']: row['decision'] for row in excluded_row['layerDecisions']}
                    assert decisions['profile'] == 'disable', decisions
                    assert decisions['session_override'] == 'inherit', decisions
                    cases.setdefault('C03', {})[brand] = {
                        'overrideKeptModel': model_after_a2, 'globalModelNow': third,
                        'finalSourcesA': final_a, 'finalSourcesB': final_b,
                        'globalBeforeEdit': globals_after, 'globalAfterEdit': globals_moved,
                        'overlayRevisionObserved': {'before': turn_a['overlayRevision'],
                            'after': turn_a2['overlayRevision'],
                            'note': 'tracks a pending Profile selection sequence, not the session overlay layer'},
                        'skillsResolveForProfile': skills_view_a,
                        'skillsResolveForSessionA': skills_view_session_a,
                        'skillsItemReachesNativeConfig': False,
                        'skillsItemReason': 'assets.skills items declare effect=capability-selection and its '
                            'v2 provider compiles to zero ConfigIntents, so the not-overridden preference is '
                            'observable in Profile\'s own resolved session view and in skills.resolve, never as a '
                            'native configuration key'}
                    log({'stage': 'brand-complete', 'brand': brand, 'counts': dict(COUNTS)})

                assert COUNTS['prompt'] == 0 and COUNTS['http'] == 0, COUNTS
                assert COUNTS['new'] == 2 * len(BRANDS), COUNTS
                assert len(set(native_ids)) == len(native_ids), native_ids
                not_covered.append('C02: the session-local switch was driven through profiles.v2.setSessionOverride, '
                    'not modelProvider.chooseForSession - the native_runtime composition never injects a '
                    'harness_config_port into ModelProviderPlugin, so that method refuses SELECTION_UNSUPPORTED on '
                    'this baseline (family/internalCode recorded per brand above) and its queue is never consumed '
                    'by any production caller')
                not_covered.append('C02: two sessions need two ACP channels - one channel admits exactly one '
                    'session/new ("Initial creation already attempted"), so session-to-session isolation is '
                    'observed across channels of the same workspace, not within one')
                not_covered.append('C03: the not-overridden preference cannot be observed in the native effective '
                    'configuration - assets.skills publishes a real overridable item only after a real skill is '
                    'imported, and that item emits zero ConfigIntents by design, so it never becomes a native key')
                not_covered.append('C03: the global model edit moves to a third installed-asset model id per brand '
                    '(codex gpt-5.2, claude-code opus[1m]), because with only the contract\'s two ids an override '
                    'and a later global edit can never disagree and the clause would be unfalsifiable')
                print(json.dumps(dict(scope='product-chain-profile-session-isolation-c02-c03',
                    cases=cases, facetCatalogue=catalogue, nativeSessionIds=native_ids,
                    counts=dict(COUNTS), notCovered=not_covered)))
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


def install_probe_skill(wire, private):
    """Publish one real skill through the product's own import wire, so the
    ``assets.skills`` facet's live asset listing has something to publish."""
    digest = 'sha256:' + hashlib.sha256(SKILL_MD).hexdigest()
    started = wire('skills.importBegin', dict(requestId='probe-import-' + uuid4().hex,
        files=[dict(path='SKILL.md', bytes=len(SKILL_MD), sha256=digest)], totalBytes=len(SKILL_MD)))
    import_id = started['importId']
    wire('skills.importChunk', dict(requestId='probe-import-' + uuid4().hex, importId=import_id,
        chunkIndex=0, payloadBase64=base64.b64encode(SKILL_MD).decode('ascii'), sha256=digest))
    preview = wire('skills.importPreview', dict(requestId='probe-import-' + uuid4().hex, importId=import_id,
        source=dict(kind='local', path=str(private / 'project'))))
    committed = wire('skills.importCommit', dict(requestId='probe-import-' + uuid4().hex,
        importId=import_id, assetId=SKILL_ID, revision=1))
    return {'assetId': committed['asset']['assetId'], 'revision': committed['asset']['latestRevision'],
        'treeDigest': preview['treeDigest'], 'effect': committed['effect']}


if __name__ == '__main__': run()