"""S02 first leg: does a real enabled Skill reach the real Harness native home?

The previous probe (probe-profile-session-isolation.py) proved the SECOND half
of S02 (两session隔离) at L3 and measured ``skillsItemReachesNativeConfig:
False`` through the Profile-facet route only. This probe closes the open
question on the real product chain, with no test double and no simulation:

* one real minimal Skill enters through the product's own
  ``skills.importBegin/importChunk/importPreview/importCommit`` chain;
* BOTH candidate enabling surfaces are exercised and reported separately —
  (a) the Profile facet item ``assets.skills/<itemId>`` and (b) the Skills
  assignment surfaces (``skills.assignmentsUpsert`` + the approval gate);
* real sessions are created, registered and applied through
  ``profiles.v2.beginTurnApplication``;
* then the REAL native state is inspected: the private per-channel instance
  directories the product itself allocates
  (``plugins/harness/src/ordessa_harness/server_acp/instance_directory.py``),
  the ``CODEX_HOME`` / ``CLAUDE_CONFIG_DIR`` / ``HOME`` the probe pointed into
  its own tempdir, and the installed artifact roots the running bridge was
  given. Absence of a materialized skill is reported AS OBSERVED — never
  simulated by a hand-written file.

Providers are credential-less by construction: the user keyring collection is
LOCKED, so ``credentialId=None`` is the real supported shape. No keyring entry
is created, read or deleted; ``session/prompt`` and the reject-server ``http``
counter stay at 0, so no inference is attempted.
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

#: The one minimal Skill installed through the real ``skills.import*`` wire.
#: Frontmatter is fixed so the import digest is reproducible.
SKILL_ID = 'probe-harness-skill'
SKILL_MD = (b'---\nname: ' + SKILL_ID.encode() + b'\ndescription: Imported only to '
           b'observe whether an enabled skill is materialized into the real '
           b'harness native home.\n---\n\nProbe body.\n')
SKILL_ENABLE = {'decision': 'enable', 'revision': 1}

#: harness, protocol and a real installed-asset model id the brand adapter
#: itself offers (invented ids make the adapters refuse session/new).
BRANDS = (
    ('codex', 'openai-responses', 'gpt-5.5'),
    ('claude-code', 'anthropic-messages', 'sonnet'),
)

#: Bounded read of a directory tree: relative file paths, capped.
TREE_CAP = 600


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


# ---------------------------------------------------------------------------
# filesystem observation — read-only, never a write that simulates projection
# ---------------------------------------------------------------------------

def files_under(root):
    """Relative file paths under ``root`` (or ``None`` when it does not exist)."""
    root = Path(root)
    if not root.exists():
        return None
    found = []
    for item in root.rglob('*'):
        if item.is_file():
            found.append(str(item.relative_to(root)))
    found.sort()
    return {'totalFiles': len(found), 'files': found[:TREE_CAP],
            'truncated': len(found) > TREE_CAP}


def materialization_scan(root):
    """Paths under ``root`` that could be a mounted skill tree.

    Two independent, purely observational signals: a path whose components
    mention a skill (``skills`` directory, ``SKILL.md``) and a file whose
    bytes mention the imported asset id. Nothing is created or read as a
    substitute for a real projection.
    """
    root = Path(root)
    if not root.exists():
        return None
    by_path, by_content = [], []
    for item in sorted(root.rglob('*')):
        relative = str(item.relative_to(root))
        if 'skill' in relative.lower():
            by_path.append(relative)
            if len(by_path) >= 200:
                break
    for item in sorted(root.rglob('*')):
        if not item.is_file() or item.stat().st_size > 262144:
            continue
        try:
            if SKILL_ID in item.read_text(encoding='utf-8', errors='ignore'):
                by_content.append(str(item.relative_to(root)))
        except OSError:
            continue
        if len(by_content) >= 200:
            break
    return {'skillNamedPaths': by_path, 'filesMentioningAssetId': by_content}


def instance_scan(instance_root, known):
    """One row per private instance directory the product itself allocated.

    ``known`` is the set of instance directory names that already existed
    before this brand's sessions ran, so a row added during the sessions is
    attributable to one of its two channels.
    """
    root = Path(instance_root)
    if not root.exists():
        return []
    rows = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        files = [item for item in directory.rglob('*') if item.is_file()]
        mentions = []
        for item in files:
            if item.stat().st_size > 262144:
                continue
            try:
                if SKILL_ID in item.read_text(encoding='utf-8', errors='ignore'):
                    mentions.append(str(item.relative_to(directory)))
            except OSError:
                continue
        skills_directory = directory / 'skills'
        # Two levels, because a brand may nest its OWN bundled skills under
        # skills/.system - those are the brand's, never the imported asset.
        brand_own = []
        if skills_directory.is_dir():
            for level in (skills_directory, skills_directory / '.system'):
                brand_own.extend(
                    (str(level.relative_to(directory)) + '/' + item.name)
                    for item in sorted(level.iterdir()) if item.is_dir())
        rows.append({
            'instanceDir': directory.name,
            'existedBeforeThisBrand': directory.name in known,
            'fileCount': len(files),
            'brandOwnSkillDirectories': brand_own,
            'pathsMentioningImportedAssetId': mentions,
        })
    return rows


def delta(before, after):
    """The paths that appeared between two file listings."""
    if before is None or after is None:
        return None
    was = set(before['files'])
    return sorted(set(after['files']) - was)


def run():
    COUNTS.update(http=0, prompt=0, new=0)
    server = ThreadingHTTPServer(('127.0.0.1', 0), RejectProvider)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    previous_environment = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix='ordessa-skill-projection-') as folder:
            private = Path(folder)
            for name in ('home', 'project', 'config'):
                (private / name).mkdir(mode=0o700)
            os.environ.update(
                HOME=str(private / 'home'),
                XDG_CONFIG_HOME=str(private / 'config'),
                CODEX_HOME=str(private / 'config/codex'),
                CLAUDE_CONFIG_DIR=str(private / 'config/claude'))
            brands = [entry[0] for entry in BRANDS]
            module = (ROOT / 'plugins/harness/packaging/native-server-plan.mjs').as_uri()
            plan = json.loads(subprocess.check_output(['node', '--input-type=module', '-e',
                f"import {{nativeServerPlan}} from {json.dumps(module)}; console.log(JSON.stringify(nativeServerPlan({{harnessIds:{json.dumps(brands)},nativeProfileHarnesses:{json.dumps(brands)},piProfileBridge:false,artifactRoots:{{}},pluginRoot:{json.dumps(str(ROOT / 'plugins/harness'))},artifactRoot:'/opt/ordessa/harnesses/profile-native/artifacts'}}).args))"], text=True))
            value = lambda flag: plan[plan.index(flag) + 1]
            artifact_root = value('--native-installed-artifact-root')
            runtime = create_composition().native_runtime(
                private / 'data', plugin_root=ROOT / 'plugins/harness',
                harness_id=value('--native-harness'),
                adapter_command=value('--native-adapter-command'),
                adapter_args=tuple(arg.split('=', 1)[1] for arg in plan
                                   if arg.startswith('--native-adapter-arg=')),
                installed_artifact_root=artifact_root,
                native_profile_harnesses=tuple(brands),
                pi_profile_bridge=False,
                additional_adapters=tuple(
                    json.loads(value('--native-additional-adapters')))
                if '--native-additional-adapters' in plan else ())
            opened, native_ids, cases, not_covered = [], [], {}, []
            catalogue = {}
            wire = runtime.wire.dispatch
            data_root = private / 'data'
            instance_root = data_root / 'harness-instances'
            try:
                runtime.start()
                workspace = wire('workspaces.open', dict(
                    requestId='probe-project-' + uuid4().hex,
                    environment=dict(kind='local', host=None, user=None),
                    path=str(private / 'project')))['workspace']
                registry = runtime.plugin_host.provided_port('acp.channels')
                endpoint = 'http://127.0.0.1:' + str(server.server_port)

                def profile(name, **params):
                    return wire('profiles.v2.' + name, params)['data']

                def open_channel(brand, scope):
                    opened_channel = wire('acp.channel.open', dict(
                        harnessId=brand, projectId=workspace['id'],
                        sessionScopeId=scope))
                    opened.append(opened_channel['connectionId'])
                    channel = registry.get(opened_channel['connectionId'])
                    inbox = queue.Queue()
                    channel.attach(ImmediateLoop(), inbox.put)
                    calls = []
                    native_rpc = channel._configuration_rpc

                    def counted_rpc(*arguments, **keywords):
                        calls.append(arguments[1])  # method only; params may carry secrets
                        return native_rpc(*arguments, **keywords)
                    channel._configuration_rpc = counted_rpc

                    def request(method, params):
                        rid = 'probe-' + uuid4().hex
                        COUNTS['new'] += method == 'session/new'
                        COUNTS['prompt'] += method == 'session/prompt'
                        channel.transport.send_line(json.dumps(dict(
                            jsonrpc='2.0', id=rid, method=method, params=params)))
                        deadline = monotonic() + 120
                        while True:
                            line = inbox.get(timeout=max(0, deadline - monotonic()))
                            assert line is not None, 'Native adapter exited before reply'
                            answer = json.loads(line)
                            if answer.get('id') == rid:
                                return answer

                    def drain():
                        seen = list(calls); calls.clear(); return seen
                    initialized = request('initialize', dict(
                        protocolVersion=1, clientCapabilities={},
                        clientInfo=dict(name='ordessa-no-model', version='1')))
                    assert 'error' not in initialized, initialized
                    assert not drain(), 'Channel initialize performed a native effect'
                    return channel, request, drain

                # -- 1. the real Skill enters through the product's own import chain
                imported = refused(lambda: install_probe_skill(wire, private))
                assert not imported['refused'], imported
                assert imported['value']['assetId'] == SKILL_ID, imported
                assert imported['value']['revision'] == 1, imported
                catalogue['import'] = imported['value']

                # -- 2. the facet catalogue publishes the imported asset
                facets = profile('describeFacets', harnessId='codex')
                skill_facet = [facet for facet in facets
                               if facet['facetId'] == 'assets.skills'][0]
                catalogue['skillsFacet'] = {
                    'items': [{'itemId': item['itemId'],
                               'overrideSupported': item['overrideSupported'],
                               'effect': item['effect']}
                              for item in skill_facet['items']]}
                assert [item['itemId'] for item in skill_facet['items']] == [SKILL_ID], skill_facet

                # -- 3. the approval gate the resolver enforces on every enable
                approval = refused(lambda: wire('skills.approveRevision', dict(
                    requestId='probe-' + uuid4().hex,
                    assetId=SKILL_ID, revision=1, approvedBy='s02-probe')))
                catalogue['approval'] = approval
                log({'stage': 'import', 'imported': imported['value'],
                     'approval': approval})

                def resolve(**params):
                    return refused(lambda: wire(
                        'skills.resolve', dict(
                            requestId='probe-' + uuid4().hex,
                            projectId=workspace['id'], **params)))

                def resolution_summary(result):
                    if result['refused']:
                        return result
                    value = result['value']
                    included = [dict(assetId=row['assetId'], revision=row['revision'],
                                     selectedByLayer=(row['selectedBy'] or {}).get('layer'))
                                for row in value['resolvedSkills']]
                    excluded = [dict(assetId=row['assetId'],
                                     excludedByLayer=(row['excludedBy'] or {}).get('layer'))
                                for row in value['excludedSkills']]
                    return {'refused': False, 'includedSkills': included,
                            'excludedSkills': excluded}

                # Baseline: nothing enabled anywhere yet.
                baseline = resolution_summary(resolve(harnessId='codex'))
                log({'stage': 'resolve-baseline', 'baseline': baseline})

                for brand, protocol, model in BRANDS:
                    provider = wire('providerModels.create', dict(
                        requestId='probe-provider-' + uuid4().hex, harness=brand,
                        provider='synthetic-provider', displayName='Probe provider',
                        credentialId=None, configuration=[], protocols=[protocol],
                        endpoints={protocol: endpoint},
                        models=[dict(modelId=model, displayName=model,
                                     availability='available',
                                     unavailableReason=None)]))['providerModel']
                    assert provider['credentialId'] is None, 'Probe provider must carry no credential'

                    # -- candidate (a) step 0: a Profile carrying ONLY the model,
                    # so each enabling surface is observed before the next lands.
                    preset = profile('createProfile',
                                     operationKey='probe-profile-' + uuid4().hex,
                                     realm='local', harnessId=brand,
                                     displayName='S02 skill projection probe')
                    profile_id = preset['profileId']
                    saved = profile('saveProfile',
                                    operationKey='probe-save-' + uuid4().hex,
                                    profileId=profile_id, expectedVersion=1,
                                    patches=[dict(facetId='assets.model-provider',
                                                  itemId='choice', op='set',
                                                  value=dict(harnessId=brand,
                                                             providerConfigId=provider['id'],
                                                             modelId=model))])['profile']

                    # -- candidate (b): the Skills assignment surface, the one the
                    # resolver actually reads as a layer. Observed on its own.
                    upsert = refused(lambda: wire('skills.assignmentsUpsert', dict(
                        requestId='probe-' + uuid4().hex, scopeKind='project',
                        scopeId=workspace['id'], harnessId=brand, assetId=SKILL_ID,
                        decision='enable', revision=1, expectedVersion=0,
                        operationKey='probe-assign-' + uuid4().hex)))
                    after_assignment = resolution_summary(resolve(
                        harnessId=brand, profileId=profile_id))
                    listed = refused(lambda: wire('skills.assignmentsList', dict(
                        requestId='probe-' + uuid4().hex, scopeKind='project',
                        scopeId=workspace['id'], harnessId=brand, assetId=SKILL_ID)))
                    log({'stage': 'assignment-surface', 'brand': brand,
                         'upsert': upsert, 'resolved': after_assignment})

                    # -- candidate (a): the Profile facet item.
                    saved = profile('saveProfile',
                                    operationKey='probe-save-' + uuid4().hex,
                                    profileId=profile_id,
                                    expectedVersion=saved['version'],
                                    patches=[dict(facetId='assets.skills',
                                                  itemId=SKILL_ID, op='set',
                                                  value=SKILL_ENABLE)])['profile']
                    after_profile = resolution_summary(resolve(
                        harnessId=brand, profileId=profile_id))
                    log({'stage': 'profile-surface', 'brand': brand,
                         'resolved': after_profile})
                    native_surface = {
                        'discoverNative': refused(lambda: wire(
                            'skills.discoverNative',
                            dict(requestId='probe-' + uuid4().hex, harnessId=brand))),
                        'invokeDescriptor': refused(lambda: wire(
                            'skills.invokeDescriptor',
                            dict(requestId='probe-' + uuid4().hex, harnessId=brand)))}

                    # -- 4. two real sessions, applied through the real boundary
                    known_instances = {row['instanceDir'] for row
                                       in instance_scan(instance_root, set())}
                    before_instance_files = files_under(instance_root)
                    before_codex = files_under(Path(os.environ['CODEX_HOME']))
                    before_claude = files_under(Path(os.environ['CLAUDE_CONFIG_DIR']))
                    before_home = files_under(private / 'home')

                    channels = {}
                    for tag in ('A', 'B'):
                        channel, request, drain = open_channel(
                            brand, 'probe-skill-' + tag + '-' + uuid4().hex)
                        prepared = profile('prepareNativeCreation',
                                           connectionId=channel.connection_id,
                                           profileId=profile_id,
                                           operationId='create:' + channel.session_scope_id)
                        assert prepared['state'] == 'prepared', prepared
                        assert drain() == ['_ordessa/channel/configuration/prepare'], \
                            'Preparation did not prepare once'
                        channels[tag] = (channel, request, drain)

                    def execute(tag):
                        channel, request, drain = channels[tag]
                        before_new = COUNTS['new']
                        answer = request('session/new', dict(
                            cwd=str(private / 'project'), mcpServers=[]))
                        assert 'error' not in answer, ('Native session/new refused: '
                                                       + json.dumps(answer['error']))
                        native = answer['result']['sessionId']
                        native_ids.append(native)
                        binding = profile('registerNativeSession',
                                          connectionId=channel.connection_id,
                                          nativeSessionId=native,
                                          profileId=profile_id)
                        applied = profile('beginTurnApplication',
                                          operationKey='probe-turn-' + uuid4().hex,
                                          sessionRef=binding['sessionRef'])
                        assert 'receipt' in applied, 'Profile application not confirmed'
                        return {'tag': tag, 'channel': channel, 'drain': drain,
                                'native': native, 'binding': binding,
                                'applied': applied['receipt'],
                                'sessionNewCalls': COUNTS['new'] - before_new}

                    session_a = execute('A')
                    after_a_instances = instance_scan(instance_root, known_instances)
                    session_b = execute('B')
                    after_b_instances = instance_scan(instance_root, known_instances)
                    final_instances = instance_scan(instance_root, known_instances)

                    assert session_a['native'] != session_b['native'], \
                        'A and B are the same native session'
                    assert session_a['sessionNewCalls'] == 1, COUNTS
                    assert session_b['sessionNewCalls'] == 1, COUNTS

                    # The two channels of this brand each got their OWN private
                    # instance directory from the product's own allocator.
                    fresh = [row['instanceDir'] for row in final_instances
                             if not row['existedBeforeThisBrand']]
                    assert len(fresh) == 2, fresh

                    # -- 5. the real native state, read after the apply
                    after_codex = files_under(Path(os.environ['CODEX_HOME']))
                    after_claude = files_under(Path(os.environ['CLAUDE_CONFIG_DIR']))
                    after_home = files_under(private / 'home')
                    scan_temp = materialization_scan(private)
                    scan_artifacts = materialization_scan(artifact_root)
                    brand_instances = [row for row in final_instances
                                       if not row['existedBeforeThisBrand']]
                    materialized = [path for row in brand_instances
                                    for path in row['pathsMentioningImportedAssetId']]

                    cases[brand] = {
                        'harnessId': brand,
                        'protocol': protocol,
                        'modelId': model,
                        'skillIdImported': imported['value']['assetId'],
                        'enablingSurfaces': {
                            'profileFacetItem': {
                                'surface': 'profiles.v2.saveProfile patch '
                                           'facetId=assets.skills itemId=' + SKILL_ID,
                                'value': SKILL_ENABLE,
                                'facetItem': next(item for item in
                                                  catalogue['skillsFacet']['items']
                                                  if item['itemId'] == SKILL_ID),
                                'resolverAfter': after_profile,
                            },
                            'skillsAssignment': {
                                'surface': 'skills.assignmentsUpsert '
                                           'scopeKind=project + skills.approveRevision',
                                'upsert': upsert, 'approval': catalogue['approval'],
                                'assignmentsList': listed,
                                'resolverAfter': after_assignment,
                            },
                            'resolverBaseline': baseline,
                            'nativeDiscovery': native_surface,
                        },
                        'sessions': {
                            'A': {'nativeSessionId': session_a['native'],
                                  'connectionId': session_a['channel'].connection_id,
                                  'sessionRef': session_a['binding']['sessionRef'],
                                  'applyReceipt': session_a['applied'],
                                  'configurationRpcAfterApply': session_a['drain']()},
                            'B': {'nativeSessionId': session_b['native'],
                                  'connectionId': session_b['channel'].connection_id,
                                  'sessionRef': session_b['binding']['sessionRef'],
                                  'applyReceipt': session_b['applied'],
                                  'configurationRpcAfterApply': session_b['drain']()},
                        },
                        'nativeHome': {
                            'codexHomeEnv': os.environ['CODEX_HOME'],
                            'claudeConfigDirEnv': os.environ['CLAUDE_CONFIG_DIR'],
                            'homeEnv': os.environ['HOME'],
                            'installedArtifactRoot': artifact_root,
                            'codexHome': after_codex,
                            'claudeConfigDir': after_claude,
                            'home': after_home,
                            'brandNativeHome': after_codex if brand == 'codex' else after_claude,
                            'brandNativeHomeNewPaths': (
                                delta(before_codex, after_codex) if brand == 'codex'
                                else delta(before_claude, after_claude)),
                            'homeNewPaths': delta(before_home, after_home),
                        },
                        'skillMaterialization': {
                            'importedSkillReachesNativeHome': bool(materialized),
                            'importedSkillPathsInNativeHome': materialized,
                            'privateInstanceDirectories': brand_instances,
                            'scanRoot': str(private),
                            'scanSkillNamedPaths': None if scan_temp is None
                                else scan_temp['skillNamedPaths'],
                            'scanFilesMentioningAssetId': None if scan_temp is None
                                else scan_temp['filesMentioningAssetId'],
                            'artifactRoot': artifact_root,
                            'artifactScanFilesMentioningAssetId':
                                None if scan_artifacts is None
                                else scan_artifacts['filesMentioningAssetId'],
                            'note': 'a skills/ directory inside a private instance '
                                    'directory is written by the BRAND itself; only '
                                    'the imported asset id appearing there (or '
                                    'anywhere under the installed artifact root) '
                                    'would count as this Skill reaching the Harness '
                                    'native home',
                        },
                        'isolation': {
                            'distinctNativeSessionIds': session_a['native'] != session_b['native'],
                            'distinctConnectionIds':
                                session_a['channel'].connection_id != session_b['channel'].connection_id,
                            'distinctSessionUids':
                                session_a['binding']['sessionRef']['sessionUid']
                                != session_b['binding']['sessionRef']['sessionUid'],
                            'instanceRoot': str(instance_root),
                            'privateInstanceDirsAllocatedByThisBrand': fresh,
                            'afterSessionA': after_a_instances,
                            'afterSessionB': after_b_instances,
                            'instanceDirNewPaths':
                                delta(before_instance_files, files_under(instance_root)),
                        },
                    }
                    log({'stage': 'brand-complete', 'brand': brand,
                         'counts': dict(COUNTS),
                         'importedSkillReachesNativeHome':
                             cases[brand]['skillMaterialization'][
                                 'importedSkillReachesNativeHome'],
                         'privateInstanceDirectories': fresh})

                assert COUNTS['prompt'] == 0 and COUNTS['http'] == 0, COUNTS
                assert COUNTS['new'] == 2 * len(BRANDS), COUNTS
                assert len(set(native_ids)) == len(native_ids), native_ids
                not_covered.append(
                    'pi: no pi artifact root exists at '
                    '/opt/ordessa/harnesses/profile-native/artifacts/pi-runtime and '
                    'nativeServerPlan produces no pi binding, so the pi brand '
                    'adapters are contributed but not exercisable on this baseline')
                not_covered.append(
                    'S02: the Skills assignment surface was exercised at the '
                    'project scope for each brand (the two scope kinds '
                    'user_global/project), never at a session scope — '
                    'skills.assignmentsUpsert declares no session scope kind')
                not_covered.append(
                    'S02: the harness.configuration-adapters contribution '
                    '(harness_adapters/contribution.py) was observed only through '
                    'the product wire this probe can reach; no published '
                    'ConfigurationService.plan/apply surface is composed by the '
                    'native_runtime selection, so the adapter compile/apply path '
                    'was not driven directly')
                print(json.dumps(dict(
                    scope='product-chain-skill-harness-projection',
                    skillIdImported=imported['value']['assetId'],
                    skillImport=imported['value'],
                    importedSkillReachesNativeHome={
                        brand: cases[brand]['skillMaterialization'][
                            'importedSkillReachesNativeHome'] for brand in cases},
                    facetCatalogue=catalogue,
                    brands=cases,
                    nativeSessionIds=native_ids,
                    counts=dict(COUNTS),
                    notCovered=not_covered)))
            finally:
                primary = sys.exc_info()[1]
                failed = []
                for cid in opened:
                    try: wire('acp.channel.release', dict(connectionId=cid))
                    except Exception: failed.append('channel')
                try: runtime.stop()
                except Exception: failed.append('runtime')
                if failed:
                    if primary is not None:
                        primary.add_note('Own cleanup failures: ' + ','.join(failed))
                    else:
                        raise RuntimeError('Own cleanup failures: ' + ','.join(failed)) from None
                log('Released own channels, created no keyring entry, stopped isolated product')
    finally:
        os.environ.clear(); os.environ.update(previous_environment)
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def install_probe_skill(wire, private):
    """Publish one real skill through the product's own import wire, so the
    ``assets.skills`` facet's live asset listing has something to publish."""
    digest = 'sha256:' + hashlib.sha256(SKILL_MD).hexdigest()
    started = wire('skills.importBegin', dict(
        requestId='probe-import-' + uuid4().hex,
        files=[dict(path='SKILL.md', bytes=len(SKILL_MD), sha256=digest)],
        totalBytes=len(SKILL_MD)))
    import_id = started['importId']
    wire('skills.importChunk', dict(
        requestId='probe-import-' + uuid4().hex, importId=import_id,
        chunkIndex=0, payloadBase64=base64.b64encode(SKILL_MD).decode('ascii'),
        sha256=digest))
    preview = wire('skills.importPreview', dict(
        requestId='probe-import-' + uuid4().hex, importId=import_id,
        source=dict(kind='local', path=str(private / 'project'))))
    committed = wire('skills.importCommit', dict(
        requestId='probe-import-' + uuid4().hex, importId=import_id,
        assetId=SKILL_ID, revision=1))
    return {'assetId': committed['asset']['assetId'],
            'revision': committed['asset']['latestRevision'],
            'treeDigest': preview['treeDigest'], 'effect': committed['effect']}


if __name__ == '__main__':
    run()