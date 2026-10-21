"""The local instruction case builds a continuation selector and no authority."""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CASE = REPO / 'tooling/checks/server_product/local_library_instruction_case.py'


def _load():
    import sys
    spec = importlib.util.spec_from_file_location('local_instruction_case', CASE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CASE_MODULE = _load()
SELECTOR = {'execution_operation_ref': 'op-a', 'attempt': 1,
            'expected_dispatch_version': 2, 'expected_acp_revision': 1}
PUBLIC_SELECTOR = {key: value for key, value in SELECTOR.items() if key != 'attempt'}


def test_v2_selector_carries_only_the_origin_identities():
    parameters = CASE_MODULE.continuation_parameters(
        SELECTOR, work_id='work-a', action_id='incremental.implement-package',
        expected_revision=1, inputs={'profile': {}})
    assert parameters['invocation_version'] == 2
    assert parameters['continuation_of'] == PUBLIC_SELECTOR
    assert set(parameters) == {'invocation_version', 'work_id', 'action_id',
                               'expected_revision', 'inputs', 'continuation_of'}
    # It creates no Work/Grant/authorization surface of its own.
    assert 'grant' not in parameters and 'authorization' not in parameters


def test_continuation_path_executes_v2_and_creates_no_authority(tmp_path):
    """Consumer path: registration and Unit creation are structurally absent."""
    calls = {}
    saved = {}

    def execute_case(**values):
        calls['execute'] = values
        return {'stage': 'EXECUTED_DECLARED_WORK', 'read_back': {'state': 'unknown'}}

    def save(path, value):
        saved[str(path)] = value

    case = {'grant': {'grant_digest': 'd' * 64}, 'grant_ref': {'approval_id': 'a'},
            'expectations': {'work_id': 'work-a'}, 'pins': {}, 'clone': {'clone_root': '/tmp/x'}}
    answer, parameters = CASE_MODULE.run_continuation(
        entry=None, continuation=SELECTOR, work_id='work-a',
        action_id='incremental.implement-package', expected_revision=1,
        inputs={'profile': {}}, case=case, invoke_parameters={'work_id': 'work-a'},
        execute_case=execute_case, save=save, output=tmp_path,
        request_id='req-1', receipt_path=tmp_path / 'receipt.json')

    assert answer['stage'] == 'EXECUTED_DECLARED_WORK'
    assert parameters['invocation_version'] == 2
    assert calls['execute']['mode'] == 'continuation'
    assert calls['execute']['origin'] == SELECTOR
    assert calls['execute']['parameters']['continuation_of'] == PUBLIC_SELECTOR
    assert calls['execute']['parameters']['inputs'] == {'profile': {}}
    # The continuation path has no hook that could register Work/Grant or
    # pre-create a Unit: execute_case is the only sink, and it was called once.
    assert set(calls['execute']) == {'parameters', 'case', 'mode', 'origin',
                                     'request_id', 'receipt_path'}
    assert saved[str(tmp_path / 'continuation-invoke.json')]['origin'] == SELECTOR


def _fake_uow(rows, latest):
    class _WorkDispatch:
        def latest_attempt(self, key, step, scope):
            return latest

        def get(self, key, step, attempt, scope):
            return rows[attempt]
    class _UoW:
        work_dispatch = _WorkDispatch()
    return _UoW()


def test_callback_looks_up_the_chain_verified_tip_not_attempt_one(monkeypatch):
    from types import SimpleNamespace
    from ordessa_engineering.domain.changes.dispatch import DispatchBinding, package_ref_projection
    from ordessa_engineering.domain.approvals.refs import ApprovalRef
    from ordessa_engineering.domain.common.models.identity import Scope
    from ordessa_engineering.domain.common.models.refs import BlobRef
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
    from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
    from ordessa_infrastructure.encoding import canonical_bytes
    import ordessa_engineering.application.usecases.changes.dispatch_continuation as continuation

    scope = Scope('realm-a', 'project-a')
    unit1 = canonical_bytes({'environmentNamespace': 'e', 'unitId': 'unit-1',
                             'ownerProviderRef': {}, 'sourceRevision': 'rev-1'})
    unit2 = canonical_bytes({'environmentNamespace': 'e', 'unitId': 'unit-2',
                             'ownerProviderRef': {}, 'sourceRevision': 'rev-2'})
    digest = Digest('sha256', 'a' * 64)

    def binding(attempt, unit_bytes):
        package = ImplementationPackageRef(scope.realm_id, scope.project_id, 'p', digest)
        return DispatchBinding(
            scope=scope, run_id='w1:work-a', step_id='implement', attempt=attempt, fence=1,
            action_instances=(('edit_repository', 'inst-1'),), unit_ref_bytes=unit_bytes,
            execution_operation_ref='op-%d' % attempt,
            prompt_ref=BlobRef(digest, 1, 'application/json', 'p-%d' % attempt),
            prompt_input_digest=digest, expected_query_digest='sha256:' + 'q' * 64,
            required_results=('implementation_report',), package_ref=package,
            approval_ref=ApprovalRef(scope.realm_id, scope.project_id, 'a', digest),
            intent_digest=digest, control_version=1, binding_version=2,
            work={'work_id': 'work-a', 'action_id': 'incremental.implement-package',
                  'step_id': 'implement', 'dispatch_key': 'w1:work-a'},
            subject={'subject_kind': 'frozen_package',
                     'subject_ref': package_ref_projection(package)})

    row1 = {'binding_bytes': encode_dispatch(binding(1, unit1)), 'continuation': None}
    row2 = {'binding_bytes': encode_dispatch(binding(2, unit2)),
            'continuation': SimpleNamespace(origin=SimpleNamespace(attempt=1))}
    seen = []
    monkeypatch.setattr(continuation, 'resolve_continuation_root',
                        lambda uow, value: seen.append(value.digest.hex))
    monkeypatch.setattr(CASE_MODULE, 'WORK', 'work-a')
    scope_owner = object.__new__(CASE_MODULE.FrozenScope)
    row, value = CASE_MODULE.FrozenScope.tip_binding(
        scope_owner, _fake_uow({1: row1, 2: row2}, 2), scope)
    assert row is row2 and value.attempt == 2      # no attempt-1 fixation
    assert seen == [value.digest.hex]              # the chain is proved, never blind latest

    def _break(uow, value):
        raise RuntimeError('CONTINUATION_RELATION_INVALID')
    monkeypatch.setattr(continuation, 'resolve_continuation_root', _break)
    with pytest.raises(RuntimeError):
        CASE_MODULE.FrozenScope.tip_binding(
            scope_owner, _fake_uow({1: row1, 2: row2}, 2), scope)


def test_case_compose_hands_the_cli_switch_to_the_binder():
    """The real compose call path (assemble_with_mode) receives the switch."""
    seen = {}

    class _Entry:
        def assemble_declared_work_case(self, **values):
            seen.update(values)
            return 'assembly'

    kwargs = dict(runtime='rt', holder={'h': 1}, scope='scope', caller='caller',
                  frozen_scope='policy', expected_selection=('a', ('reviewer',), 1),
                  prompt_parameters={}, review_paths=('p',), deliver='d',
                  implementation_timeout=1800)
    assert CASE_MODULE.assemble_with_mode(_Entry(), continuation=SELECTOR, **kwargs) == 'assembly'
    assert seen['continuation'] is True
    seen.clear()
    assert CASE_MODULE.assemble_with_mode(_Entry(), continuation=None, **kwargs) == 'assembly'
    assert seen['continuation'] is False


@pytest.mark.parametrize('selector', [
    None, {}, dict(SELECTOR, attempt=0), dict(SELECTOR, attempt=True),
    dict(SELECTOR, expected_dispatch_version=-1),
    dict(SELECTOR, expected_acp_revision=0),
    dict(SELECTOR, execution_operation_ref=''),
    dict(SELECTOR, extra='x'),
])
def test_selector_shape_is_strict(selector):
    with pytest.raises(RuntimeError):
        CASE_MODULE.continuation_parameters(
            selector, work_id='work-a', action_id='a', expected_revision=1, inputs={})


def test_cli_continuation_reopens_only_the_registered_graph(tmp_path, monkeypatch):
    """CLI graph routing only; stop at compose, before any permission/Unit."""
    import hashlib
    import json
    from types import SimpleNamespace
    module = _load()
    root = tmp_path / 'repo'
    cache = root / '.nightly-cache'
    graph = cache / 'already-executed' / 'runtime'
    (graph / 'product').mkdir(parents=True)
    (graph / 'engineering.sqlite').write_bytes(b'controlled graph locator')
    (graph.parent / 'native-setup-before-product.json').write_text(json.dumps(
        {'environment_identity': 'original-environment'}))
    registration = cache / 'registration.json'
    registration.write_text(json.dumps({'work_id': 'work-a', 'graph': str(graph),
                                         'state': 'registered'}))
    candidate = tmp_path / 'candidate.json'
    candidate.write_text(json.dumps({'authorization': {'work_id': 'work-a'},
        'intent': {'digest': {'hex': 'a' * 64}}, 'new_question_or_answer_presented': False,
        'invoke_parameters': {'inputs': {}}}))
    monkeypatch.setattr(module, 'ROOT', root)
    monkeypatch.setattr(module, 'FIXED_WORK', 'work-a')
    monkeypatch.setattr(module, 'REGISTERED_RUNTIME', registration)
    monkeypatch.setattr(module, 'PINNED', {})
    monkeypatch.setattr(module, 'target_hashes', lambda: module.BEFORE)
    monkeypatch.setattr(module, 'protected_original', lambda: {})
    monkeypatch.setattr(module, 'FrozenScope', lambda: SimpleNamespace(check_verify=lambda: None))
    driver = SimpleNamespace(CAPABILITIES=(), safe_error=lambda e: {'type': type(e).__name__})
    entry = object()
    monkeypatch.setattr(module, 'load_module', lambda _name, path: entry if path == module.M2 else driver)
    def refuse_snapshot(*args):
        raise AssertionError('continuation must never clone a new graph')
    monkeypatch.setattr(module, 'prepare_snapshot', refuse_snapshot)
    seen = {}
    def stop_at_compose(output, selected_graph, selected_candidate, policy, selected_entry,
                        selected_driver, **options):
        seen.update(graph=selected_graph, entry=selected_entry, **options)
        raise RuntimeError('controlled stop before composition effects')
    monkeypatch.setattr(module, 'compose', stop_at_compose)
    before = registration.read_bytes()
    output = cache / 'continuation-output'
    assert module.main(['--candidate', str(candidate), '--candidate-sha256',
        hashlib.sha256(candidate.read_bytes()).hexdigest(), '--output', str(output),
        '--run-real', '--continuation-operation-ref', 'op-a', '--continuation-attempt', '1',
        '--continuation-dispatch-version', '2', '--continuation-acp-revision', '1']) == 1
    assert seen == {'graph': graph, 'entry': entry, 'real': True,
                    'environment_identity': 'original-environment', 'continuation': SELECTOR}
    assert registration.read_bytes() == before
    assert not (output / 'runtime').exists()
    completion = json.loads((output / 'completion.json').read_text())
    assert completion['unit_started'] is False and completion['grant_registered'] is False


def test_reviewed_entry_pin_matches_the_source_consumed_by_compose():
    import hashlib
    assert CASE_MODULE.PINNED[str(CASE_MODULE.M2)] == hashlib.sha256(
        CASE_MODULE.M2.read_bytes()).hexdigest()


def _native_cli_materials(root, case_id):
    """Synthetic input bytes in the existing case manifest format."""
    import hashlib
    import json
    directory = root / '.nightly-cache' / case_id / 'inputs/citation-r5'
    directory.mkdir(parents=True)
    srs = ('### 1.1 Identity', '### LL-REQ-041 Search', '#### 3.2.1 Search',
           '#### 3.3.2 Detail', '### 3.8 Limits', '### 3.4 Ownership',
           '### 3.5 Records', '## 4. Verification', '## 5. Acceptance',
           '### LL-REQ-028 Limitations', '## Appendix D. Synthetic amendment',
           *(f'### D.{n} Fixture clause' for n in range(1, 9)))
    sdd = ('### 1.1 Identity', '### 3.1 Entry', '### 4.3 View', '### B.1 Public port',
           '### 4.2 Call chain', '### 4.1 State', '### A.1 Owner', '### A.3 Store',
           '## Appendix C. Fixture mapping', '### B.2 Assembly',
           '## Appendix E. Synthetic amendment',
           *(f'### E.{n} Fixture clause' for n in range(1, 9)))
    def did(version):
        result = f'# Synthetic {version} evidence\nExplicit synthetic integration data.\n'
        for name, headings in (('SRS.md', srs), ('SDD.md', sdd)):
            result += f'# BEGIN MEMBER {name}\n'
            result += ''.join(heading + '\nSynthetic bounded local search behavior.\n' for heading in headings)
            result += f'# END MEMBER {name}\n'
        return result.encode()
    raw = {'baseline': did('baseline'), 'candidate': did('candidate'),
           'project_facts': b'# Synthetic spec\nOnly the temporary catalog fixture is editable.\n',
           'capture_adapter': b'# Synthetic plan\nEdit one fixture file and run the exact prepared check.\n',
           'independent_review': b'# Synthetic tasks\nRead the fixture independently and report a synthetic judgment.\n'}
    checks = ('source-version-preservation', 'scoped-read-boundary', 'evidence-support',
              'unique-record-authority', 'public-call-chain', 'changed-source-refusal',
              'acceptance-coverage', 'declared-limitations')
    claims = [{'check_id': key, 'claim': 'Synthetic test claim for ' + key,
               'evidence': [{'source': role, 'excerpt': f'Synthetic {role} evidence'}
                            for role in ('baseline', 'candidate')]} for key in checks]
    def member(name, body):
        path = directory / name
        path.write_bytes(body)
        return {'path': name, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
    manifest = {'contract': 'ordessa.validation.review-materials/1',
        'revision_id': 'local-library-search-citation-r5',
        # This is protocol fixture data, not a capture of the user's repository.
        'source_commit': '342d4e9a590caa50bb0749b48cee80b5a3146439',
        'sources': {key: member(key + '.txt', value) for key, value in raw.items()},
        'source_versions': {key: 'synthetic-' + key + '-v1' for key in raw},
        'claims': member('claims.json', json.dumps({'checks': claims}).encode()),
        'excerpt_bindings': [{'check_id': item['check_id'],
            'sources': [e['source'] for e in item['evidence']],
            'excerpt_sha256': [hashlib.sha256(e['excerpt'].encode()).hexdigest()
                               for e in item['evidence']]} for item in claims]}
    path = directory / 'INPUT-MANIFEST.json'
    path.write_text(json.dumps(manifest))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), raw, claims, manifest['source_versions']


def _native_cli_peer(python):
    """An actual local ACP process; all model output is visibly synthetic."""
    return '#!' + str(python) + '\n' + r'''
import json, os, shlex, subprocess, sys, traceback
def failed(kind, error, tb):
    with open('synthetic-peer-error.json','w') as handle:
        json.dump({'type':kind.__name__,'message':str(error),
                   'frames':[(f.lineno,f.name) for f in traceback.extract_tb(tb)]},handle)
sys.excepthook=failed
session = 'synthetic-' + os.path.basename(os.path.dirname(os.getcwd()))
options = [{'id':'thinkingLevel','type':'select','name':'Thinking','currentValue':'low',
            'options':[{'value':'low','name':'Low'},{'value':'high','name':'High'}]}]
def emit(value):
    print(json.dumps(value), flush=True)
def read_update(status, decision=None):
    params={'sessionId':session,'type':'tool_call','approval':'file',
            'toolCallId':'fixture-read','status':status,
            'update':{'sessionUpdate':'tool_call','toolCallId':'fixture-read',
                      'kind':'read','status':status,'title':'Read catalog/views.py'}}
    if decision is not None:
        params['permissionDecision']=decision
    emit({'jsonrpc':'2.0','method':'session/update','params':params})
def callback(ident, method, params):
    emit({'jsonrpc':'2.0','id':ident,'method':method,'params':dict(params,sessionId=session)})
    while True:
        value = json.loads(sys.stdin.readline())
        if value.get('id') == ident and ('result' in value or 'error' in value):
            if 'error' in value:
                raise RuntimeError('synthetic callback refused: ' + str(value['error'].get('code')))
            return value['result']
for line in sys.stdin:
    q=json.loads(line); method=q.get('method'); p=q.get('params',{})
    if method == 'initialize':
        answer={'protocolVersion':1,'agentCapabilities':{'loadSession':True}}
    elif method == 'session/new':
        answer={'sessionId':session,'configOptions':options}
    elif method in ('session/load','session/set_config_option','session/set_model'):
        answer={'configOptions':options}
    elif method == '_ordessa/session/configuration':
        answer={'sessionId':session,'configOptions':options}
    elif method == 'session/cancel':
        continue
    elif method == 'session/prompt':
        bodies=[json.loads(item['text']) for item in p['prompt'] if item.get('type')=='text']
        review=next((v for v in bodies if 'transport_response' in v),None)
        options=[{'optionId':'accept','name':'Allow once','kind':'allow_once'},
                 {'optionId':'acceptForSession','name':'Allow for session','kind':'allow_always'},
                 {'optionId':'decline','name':'Reject','kind':'reject_once'}]
        if review is not None:
            # Pi reads through its native tool after the original permission
            # gate, rather than a second ACP filesystem request.
            command=shlex.split(os.environ['ORDESSA_APPROVED_CHECK_COMMAND'])
            target=command[command.index('--project-root')+1]
            path=target+'/catalog/views.py'
            read_update('in_progress')
            decision=callback('fixture-read','session/request_permission',
                {'approval':'file','toolCallId':'fixture-read','files':[path],
                 'toolCall':{'toolCallId':'fixture-read','title':'Read catalog/views.py',
                             'kind':'read','status':'pending','locations':[{'path':path}]},
                 'options':options})
            if (decision.get('outcome') or {}).get('optionId') != 'accept':
                raise RuntimeError('synthetic review read was not authorized once')
            # Only after the original policy selected allow_once does the
            # synthetic harness actually read the fixture.
            with open(path,'r') as handle:
                if handle.read() != '# synthetic successor edit\n':
                    raise RuntimeError('synthetic review did not read the author edit')
            read_update('completed','approved')
            result={'verdict':'passed','rationale':'Synthetic fixture judgment; real owner/read/assignment paths were exercised.',
                    'findings':[]}
        else:
            body=next(v for v in bodies if 'authorization' in v)
            target=json.loads(body['authorization']['request_summary'])['root']
            path=target+'/catalog/views.py'
            # A repository-relative path would resolve beneath the Unit cwd;
            # neither that path nor another absolute file inherits approval.
            for name, refused in [('relative','catalog/views.py'),
                                  ('outside',target+'/unapproved.py')]:
                decision=callback('fixture-denied-'+name,'session/request_permission',
                    {'approval':'file','toolCallId':'fixture-denied-'+name,'files':[refused],
                     'toolCall':{'toolCallId':'fixture-denied-'+name,'kind':'edit',
                                 'locations':[{'path':refused}]},'options':options})
                if (decision.get('outcome') or {}).get('outcome') != 'cancelled':
                    raise RuntimeError('synthetic unapproved path was authorized')
            decision=callback('fixture-write','session/request_permission',
                {'approval':'file','toolCallId':'fixture-write','files':[path],
                 'toolCall':{'toolCallId':'fixture-write','title':'Edit catalog/views.py',
                             'kind':'edit','status':'pending','locations':[{'path':path}],
                             'rawInput':{'path':path,'edits':[{'oldText':'# synthetic catalog baseline\n',
                                                               'newText':'# synthetic successor edit\n'}]}},
                 'options':options})
            if (decision.get('outcome') or {}).get('optionId') != 'accept':
                raise RuntimeError('synthetic fixture edit was not authorized once')
            # Only after the original policy selected allow_once does the
            # synthetic harness actually write the temporary fixture.
            with open(path,'w') as handle:
                handle.write('# synthetic successor edit\n')
            command=os.environ['ORDESSA_APPROVED_CHECK_COMMAND']
            decision=callback('fixture-check','session/request_permission',
                {'approval':'command','toolCallId':'fixture-check','command':command,
                 'toolCall':{'toolCallId':'fixture-check','kind':'execute','rawInput':{'command':command}},
                 'options':options})
            if (decision.get('outcome') or {}).get('optionId') != 'accept':
                raise RuntimeError('synthetic exact check was not authorized once')
            check=subprocess.run(shlex.split(command),capture_output=True,text=True,check=False)
            if check.returncode:
                raise RuntimeError('synthetic prepared check failed')
            result={'package_digest':'sha256:'+body['package_ref']['digest']['hex'],
                    'profile_ref':body['profile_ref'],'changed_paths':['catalog/views.py'],
                    'verification':[{'check':'synthetic prepared fixture check','result':'passed'}],
                    'status':'completed'}
        emit({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':session,
            'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':json.dumps(result)}}}})
        answer={'stopReason':'end_turn'}
    else:
        answer={}
    if 'id' in q:
        emit({'jsonrpc':'2.0','id':q['id'],'result':answer})
'''


def _native_cli_source_graph(module, seed, material, raw, claims, versions, monkeypatch):
    """Original source/review/package owners, with a synthetic Decision peer."""
    import asyncio
    from dataclasses import asdict, replace
    import json
    import sys
    from types import SimpleNamespace
    repo = REPO
    sys.path.insert(0, str(repo / 'packages/engineering/tests/application'))
    import test_real_source_chain as chain
    from test_itemized_source_chain import ItemizedControlledProvider
    from ordessa_agents.profiles import ProfileService
    from ordessa_units.bindings.profile_admission import UnitProfileAdmission
    from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
    from ordessa_server.composition.configuration.product_selection import create_host_product_composition
    from ordessa_server.composition.product_native_configuration import construct_pi_harness_declaration
    from ordessa_server.composition.product_runtime import build_product_runtime
    from ordessa_server.composition.pi_selection import PiExecutionSelection, PiExecutionPorts
    from ordessa_units.assembly import UnitRunPermission
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
    from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
    from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
    from ordessa_environments_local import LocalEnvironmentResourceProvider
    from ordessa_engineering.domain.common.models.identity import Scope, ActorRef
    from ordessa_engineering.domain.artifacts.provenance import SourceRef, SourceLocator, VersionCapture
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.adapters.filesystem.project_sources import ProjectSourceMaterials
    from ordessa_engineering.adapters.decision.source_bindings import DeclaredSourceReviewBindings
    from ordessa_engineering.adapters.decision.source_reviewer import DecisionReviewerSource
    from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
    from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service
    from ordessa_engineering.adapters.persistence.sqlite import migrations
    from ordessa_decision_jev import JevProviderSettings
    from ordessa_decision import PolicyRef
    import hashlib
    fingerprint = ProtectedFingerprintHmac({'synthetic': b'synthetic-fixture-fingerprint-32!'}, active_key_id='synthetic')
    # A synthetic, freshly written executable stands in for the external Pi
    # binary: only its file metadata is pinned; nothing is installed or called
    # outside this temporary tree.
    pi_tool = module.BRIDGE.parent / 'synthetic-pi-tool'
    pi_tool.write_text('#!/bin/sh\nexit 0\n')
    pi_tool.chmod(0o700)
    # The pinned Pi identity is a preflight metadata check, not an execution
    # dependency. Substitute the synthetic executable's own metadata for this
    # test only; the real validator (path/target/digest) still runs.
    import ordessa_server.composition.product_native_configuration as native_config
    monkeypatch.setattr(native_config, '_PI_EXECUTABLE_LINK', pi_tool)
    monkeypatch.setattr(native_config, '_PI_EXECUTABLE_TARGET', pi_tool.resolve())
    monkeypatch.setattr(native_config, '_PI_EXECUTABLE_SHA256',
                        hashlib.sha256(pi_tool.read_bytes()).hexdigest())
    setup = create_host_product_composition(fingerprint_port=fingerprint).default_runtime(seed / 'product')
    try:
        namespace = setup.unit_runtime.context.environment_namespace
        declaration = construct_pi_harness_declaration(setup, bridge_executable=module.BRIDGE,
            pi_executable=pi_tool, reviewed_bridge_sha256=module.BRIDGE_SHA)
        profiles = ProfileService(UnitProfileAdmission(setup.unit_runtime.context))
        profile = profiles.create(profile_id='synthetic-cli-profile', name='Synthetic local ACP fixture',
            content={'schemaVersion': '1', 'harnessDefinitionRef': dict(declaration.descriptor.definition_ref),
                'declarations': [{'declarationId': 'selected-model', 'configurationKind': 'assets.model-provider',
                    'schemaVersion': '1', 'action': 'value', 'requirement': 'required',
                    'payload': {'provider': 'deepseek', 'model': 'deepseek-flash', 'protocol': 'openai-chat',
                                'endpoint': 'https://api.deepseek.com'}}]},
            request=profiles.request_key('synthetic-cli-profile'))
        profile_ref = profile.current_revision
        setup.start()
    finally:
        setup.stop()
    env_root = seed / 'local-environment'
    env_root.mkdir()
    store = SQLiteEnvironmentStore(seed / 'environments.sqlite')
    environments = EnvironmentManager(store=store, providers={
        'local': LocalEnvironmentResourceProvider(default_root=str(env_root))})
    environment = environments.register('local', str(env_root))
    # Provision the same original ACP journal through the real selected Unit
    # owner. No Unit is created by this metadata-only composition.
    driver = module.load_module('synthetic_seed_model_data', repo / 'tooling/checks/server_product/probe-work-package-generation.py')
    driver.BRIDGE, driver.BRIDGE_SHA = module.BRIDGE, module.BRIDGE_SHA
    actions = frozenset({'prepare', 'start', 'interaction', 'stop', 'release'})
    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        authority = runtime.wire.identity_authority
        selected_scope = WireScope(namespace, 'local-source-chain')
        authority.replace_grants((AccessGrant(selected_scope,
            tuple('execution.units.' + action for action in sorted(actions))),))
        return UnitRunPermission(access_authority=authority,
            principal=authority.authenticate('Bearer ' + runtime.token), scope=selected_scope,
            agent_id=selection.agent_id, profile_revision=profile_ref,
            environment_identity=environment_instance.identity, root_directory=str(env_root),
            actions=actions, expires_at=__import__('time').time() + 3600)
    selection = PiExecutionSelection('local-library-generation-agent', profile_ref, environment.identity,
        'local', 'none', True, 'selected-model', 'deepseek', 'deepseek-flash',
        str(module.BRIDGE), module.BRIDGE_SHA, str(pi_tool), str(module.BRIDGE.parent / 'synthetic-model.env'))
    ports = PiExecutionPorts(environments, declaration, fingerprint, permission_factory,
        ('deepseek-flash',), driver.selected_model(), acp_turn_opt_in=True,
        defer_effect_write_guard_factory=True, credential_environment_variable='DEEPSEEK_API_KEY')
    selected = build_product_runtime(seed / 'product', pi_selection=selection, pi_ports=ports)
    selected.stop()
    scope = Scope(namespace, 'local-source-chain')
    reviewer = ActorRef('jev-real-source-reviewer', 'service', 'explicit-host-selection')
    monkeypatch.setattr(chain, 'SCOPE', scope)
    monkeypatch.setattr(chain, 'PRINCIPAL', 'local')
    monkeypatch.setattr(chain, 'REVIEWER', reviewer)
    def source(logical, version, body):
        return SourceRef(logical, 'document', SourceLocator('document', provider='project-files', document_id=logical),
            VersionCapture(version, Digest('sha256', hashlib.sha256(body).hexdigest())),
            chain.NOW, chain.AUTHOR, 'text/markdown' if logical == 'local-library-DID' else 'text/plain', len(body))
    monkeypatch.setattr(chain, 'source', source)
    refs = {name: source('local-library-DID' if name in ('baseline', 'candidate') else name,
                        versions[name], body) for name, body in raw.items()}
    caller = {'scope': asdict(scope), 'baseline': asdict(refs['baseline']), 'candidate': asdict(refs['candidate']),
        'checks': [{'check_id': c['check_id'], 'claim': c['claim'],
                    'evidence': [{'source_ref': asdict(refs[e['source']]), 'excerpt': e['excerpt']}
                                 for e in c['evidence']]} for c in claims]}
    entries = tuple(('local-library-DID' if name in ('baseline', 'candidate') else name,
                     versions[name], name + '.txt', body) for name, body in raw.items())
    entries += (('caller_review_input', 'local-library-claims-r5', 'caller_review_input.txt',
                 json.dumps(caller, indent=2).encode()),)
    provider = ItemizedControlledProvider()
    provider.binding_ref = 'opencode-zen-jev/1'
    provider.settings_digest = JevProviderSettings(binding_ref=provider.binding_ref,
        secret_ref='selected-jev-credential', base_url='https://opencode.ai/inference/systemone',
        model='jev-1.13-free', accepted_response_models=('jev-1.13.0',), timeout_seconds=20,
        long_context=True).settings_digest
    env = chain.build_local_chain(seed, provider, method_directory=repo / 'methods/incremental-engineering/candidates/2.7.2',
                                  material_entries=entries, caller_material_index=5)
    # Compose the same complete-sections binding the actual case will reopen.
    driver = module.load_module('synthetic_section_data', repo / 'tooling/checks/server_product/probe-work-package-generation.py')
    sections_raw = json.dumps(driver.review_section_manifest(scope, env.method, refs, raw, claims),
                              ensure_ascii=False, indent=2).encode()
    section_ref = source('question_sections', 'local-library-review-sections-r2', sections_raw)
    (env.project / 'question_sections.txt').write_bytes(sections_raw)
    env.reviewer.close()
    env.materials.close()
    mappings = tuple(env.mappings) + ((section_ref, 'question_sections.txt'),)
    materials = ProjectSourceMaterials(env.factory, scope=scope, root=env.project, source_mappings=mappings)
    bindings = DeclaredSourceReviewBindings(env.factory, env.controls, scope=scope, method_ref=env.method,
        baseline=env.baseline, candidate=env.candidate, action_id='incremental.review-change',
        binding_resource_id='source-review-binding', criteria_resource_id='change-review-criteria',
        prompt_resource_id='change-review-prompt', result_schema_resource_id='review-result-schema',
        reviewer_roles=('reviewer',), caller_input_schema_resource_id='caller-review-input-schema',
        caller_materials_ref=entries and mappings[5][0], question_materials_ref=section_ref)
    bound = next(ref for ref in env.resources if ref.resource_id == 'source-review-binding')
    services = replace(env.services, policy_refs=(PolicyRef('source-review-binding', '2',
                                                          'sha256:' + bound.resource_digest.hex),))
    source_reviewer = DecisionReviewerSource(env.factory, env.blobs, env.controls, materials, bindings,
        scope=scope, principal_id='local', reviewer=reviewer, roles=('reviewer',), services=services)
    admission = EngineeringReviewAdmission(env.factory, env.controls, None, source_reviewer,
        source_materials=materials, method_guard=env.controls, source_review_bindings=bindings)
    env.materials, env.bindings, env.services, env.reviewer, env.admission = materials, bindings, services, source_reviewer, admission
    env.plan = bindings.plan(chain.context('synthetic-sections-plan'), 'local-source-review')
    env.service = build_engineering_service(env.factory, EngineeringPorts(chain.ControlledLocalAccess(),
        review_admission=admission, source_materials=materials, method_guard=env.controls,
        source_review_bindings=bindings, blobs=env.blobs))
    try:
        package = chain.run_full_chain(env)
        migrations.migrate_schema16(env.library, backup_path=(seed / 'schema16-backup.sqlite').resolve())
        return SimpleNamespace(scope=scope, profile_ref=profile_ref, package=package.package,
                               package_ref=package.package_ref, method=env.method)
    finally:
        chain.close_chain(env)


def test_full_cli_native_continuation_keeps_original_authority(tmp_path, monkeypatch):
    """Actual CLI/compose/ACL/claim/Unit/callback/report/review, synthetic ACP peer.

    Only frozen test data and the external ACP process/model are controlled.
    No production Grant or user data is read.
    """
    import asyncio
    from contextlib import contextmanager
    from dataclasses import asdict
    from datetime import datetime, timedelta, timezone
    import hashlib
    import json
    import os
    import shutil
    import sqlite3
    import sys
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.artifacts.library_material_codec import content_digest
    from ordessa_engineering.application.contracts.work_context import WorkBinding, WorkAssociation, work_binding_projection
    from ordessa_engineering.domain.approvals.scope import ActionScope, EnvironmentRef, PathRule, RepositoryScope
    from ordessa_engineering.domain.approvals.implementation import (
        ActionBudgetSlot, WorkPackageAuthorization, WorkPackageAuthorizationIntent)
    from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef, ConversationSource, WorkPackageNotice
    from ordessa_server.composition.engineering_human_source import SOURCE_LIMITATION
    from ordessa_server.composition.engineering_chat_confirmation import INSTRUCTION_BINDING_LIMITATION
    from ordessa_server.composition.unit_file_callback_approval import UnitFileCallbackApproval
    from ordessa_units.api.manager import UnitManager
    from ordessa_units.api import UnitApiRefused
    from ordessa_agents.harness.transport.environment_channel import EnvironmentProcessChannel
    from ordessa_engineering.application.contracts.dispatch_identity import unit_bootstrap_request_key
    from ordessa_engineering.application.usecases.changes.dispatch_continuation import CONTINUATION_OPERATION
    import ordessa_engineering.application.usecases.support.clock as engineering_clock

    # The ambient no_proxy carries a bracketed IPv6 literal that the JEV HTTP
    # client rejects at construction; this case performs no network call.
    monkeypatch.setenv('no_proxy', 'localhost,127.0.0.1')
    monkeypatch.setenv('NO_PROXY', 'localhost,127.0.0.1')
    module = _load()
    repo = tmp_path / 'public-case'
    repo.mkdir(mode=0o700)
    # Public source copies only: this gives the unmodified case its exact
    # policy/material/source-pin files, never a historical runtime or .env.
    for relative in ('methods/incremental-engineering', 'packages/engineering/src'):
        shutil.copytree(REPO / relative, repo / relative)
    for relative in ('tooling/checks/server_product/probe-work-package-generation.py',
                     'tooling/checks/server_product/local_library_check_runtime.py',
                     'apps/server/src/ordessa_server/composition/engineering_chat_confirmation.py'):
        dest = repo / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, dest)
    cache = repo / '.nightly-cache'
    cache.mkdir(mode=0o700)
    target = tmp_path / 'synthetic-catalog'
    before = {}
    for relative in module.BEFORE:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith('test_search.py'):
            before[relative] = None
        else:
            path.write_text('# synthetic catalog baseline\n')
            before[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    bridge = tmp_path / 'synthetic-acp-peer'
    bridge.write_text(_native_cli_peer(Path(sys.executable)))
    bridge.chmod(0o700)
    bridge_digest = hashlib.sha256(bridge.read_bytes()).hexdigest()
    credential = tmp_path / 'synthetic-model.env'
    credential.write_text('DEEPSEEK_API_KEY=synthetic-fixture-no-network\nOPEN_CODE_GO_API_KEY=synthetic-fixture-no-network\n')
    credential.chmod(0o600)
    import ordessa_server.composition.temporary_process_capability as model_input
    # Explicit fixture selection at the external model-input boundary. Keep
    # the real parser and finite allowlist check; no production .env is read.
    monkeypatch.setattr(model_input, 'APPROVED_OPENCODE_SOURCES', frozenset({str(credential)}))
    for key, value in {'ROOT': repo, 'TARGET': target, 'BEFORE': before,
                       'BRIDGE': bridge, 'BRIDGE_SHA': bridge_digest}.items():
        monkeypatch.setattr(module, key, value)
    case_id = 'local-source-chain'
    manifest, manifest_digest, raw, claims, versions = _native_cli_materials(repo, case_id)
    monkeypatch.setattr(module, 'MATERIAL_MANIFEST', manifest)
    monkeypatch.setattr(module, 'MATERIAL_MANIFEST_SHA256', manifest_digest)
    seed = tmp_path / 'synthetic-source-graph'
    seed.mkdir(mode=0o700)
    source = _native_cli_source_graph(module, seed, manifest, raw, claims, versions, monkeypatch)
    pi_tool = bridge.parent / 'synthetic-pi-tool'
    monkeypatch.setattr(module, 'ORIGINAL', seed)
    monkeypatch.setattr(module, 'FROZEN_PACKAGE_DIGEST', source.package_ref.digest.hex)
    work_id = 'synthetic-cli-native-continuation'
    monkeypatch.setattr(module, 'FIXED_WORK', work_id)
    registration = cache / work_id / 'registered-runtime.json'
    registration.parent.mkdir(mode=0o700)
    monkeypatch.setattr(module, 'REGISTERED_RUNTIME', registration)
    pins = tmp_path / 'public-source-pins.json'
    pins.write_text(json.dumps({str(module.M1): module.sha(module.M1),
                               str(module.M2): module.sha(module.M2)}))
    monkeypatch.setattr(module, 'PREVIOUS_SOURCE_PINS', pins)
    monkeypatch.setattr(module, 'PINNED', {str(module.M1): module.sha(module.M1),
        str(module.M2): module.sha(module.M2), str(bridge): bridge_digest,
        str(repo / 'tooling/checks/server_product/probe-work-package-generation.py'):
            module.sha(repo / 'tooling/checks/server_product/probe-work-package-generation.py')})

    # A fresh, tiny prepared Python runtime is hashed by the real check owner.
    check_root = tmp_path / 'prepared-check'
    (check_root / 'bin').mkdir(parents=True, mode=0o700)
    check_python = check_root / 'bin/python'
    shutil.copy2(Path(sys.executable).resolve(), check_python)
    check_python.chmod(0o700)
    cfg = check_root / 'pyvenv.cfg'
    cfg.write_text('home = ' + str(Path(sys.base_prefix) / 'bin') + '\ninclude-system-site-packages = false\n')
    runner = tmp_path / 'synthetic-catalog-check.py'
    runner.write_text("import argparse,pathlib\np=argparse.ArgumentParser();p.add_argument('--project-root');a=p.parse_args()\nassert pathlib.Path(a.project_root,'catalog/views.py').read_text() == '# synthetic successor edit\\n'\nprint('synthetic fixture check passed')\n")
    producer = module.load_module('synthetic_check_data', repo / 'tooling/checks/server_product/local_library_check_runtime.py')
    pinned = {str(p): module.sha(p) for p in (check_python, cfg, runner, Path('/usr/bin/env').resolve())}
    from contextlib import nullcontext
    command, _, _ = producer.fixed_catalog_check(python_executable=check_python,
        runner=runner, project_root=target, pinned_files=pinned,
        runtime_tree_digest=producer.catalog_runtime_digest(check_root),
        allowed_paths=tuple(str(target / name) for name in before),
        scope_guard=lambda **_: nullcontext())
    config = tmp_path / 'prepared-check.json'
    config.write_text(json.dumps({'python_executable': str(check_python), 'runner': str(runner),
        'pinned_files': pinned, 'runtime_tree_digest': producer.catalog_runtime_digest(check_root),
        'approved_check_command': command}))
    monkeypatch.setattr(module, 'CHECK_CONFIGURATION', config)
    monkeypatch.setattr(module, 'CHECK_CONFIGURATION_SHA256', module.sha(config))

    binding = WorkBinding(work_id, source.scope, source.method, 1,
                          (WorkAssociation('package', source.package_ref),))
    work_digest = Digest('sha256', content_digest(work_binding_projection(binding)).removeprefix('sha256:'))
    from ordessa_agents.profiles import encode_revision_ref
    profile = encode_revision_ref(source.profile_ref)
    environment_ref = EnvironmentRef(source.scope.realm_id, source.profile_ref.profile_id,
        Digest('sha256', profile['contentDigest'].removeprefix('sha256:')))
    intent_id = 'synthetic-cli-native-intent'
    action_scope = ActionScope(source.scope.project_id,
        (RepositoryScope('synthetic-catalog', (PathRule('catalog', 'subtree', ('modify',)),)),),
        (environment_ref,), (), (), intent_id)
    now = datetime.now(timezone.utc)
    stamp = lambda value: value.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    authorization = WorkPackageAuthorization(scope=source.scope, intent_id=intent_id,
        work_id=work_id, work_revision=1, work_digest=work_digest,
        action_id=module.ACTION, step_id=module.STEP, package_ref=source.package_ref,
        method_ref=source.method, actions=('edit_repository', 'run_checks'),
        scope_by_action=(('edit_repository', action_scope), ('run_checks', action_scope)),
        action_budgets=(ActionBudgetSlot('edit_repository', 1), ActionBudgetSlot('run_checks', 1)),
        request_summary=json.dumps({'root': str(target), 'before_sha256': before,
                                   'allowed_operations': list(before)}),
        not_before=stamp(now - timedelta(seconds=1)), expires_at=stamp(now - timedelta(seconds=1) + timedelta(hours=4)))
    policy_raw = (repo / 'methods/incremental-engineering/policies/product-chat-confirmation.v2.yaml').read_bytes()
    policy = ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 2,
                             Digest('sha256', hashlib.sha256(policy_raw).hexdigest()))
    instruction = 'Synthetic test instruction: edit only the temporary catalog fixture and run its exact prepared check.'
    chat_source = ConversationSource('synthetic-fixture/explicit-instruction', (),
        SOURCE_LIMITATION + '; ' + INSTRUCTION_BINDING_LIMITATION
        + '; message references unavailable; synthetic test data, not a real user reply',
        'local', stamp(now - timedelta(seconds=2)))
    notice = WorkPackageNotice('synthetic-cli-native-notice', authorization, instruction, chat_source, policy)
    intent = WorkPackageAuthorizationIntent(authorization, notice.ref, policy)
    candidate = tmp_path / 'synthetic-candidate.json'
    invoke = {'work_id': work_id, 'action_id': module.ACTION, 'expected_revision': 1,
        'inputs': {'package': asdict(source.package_ref), 'profile': profile,
                   'reviewer_profile': profile, 'method': asdict(source.method)}}
    candidate.write_text(json.dumps({'authorization': asdict(authorization), 'intent': asdict(intent),
        'notice': asdict(notice), 'fixed_profile_ref': profile, 'actual_instruction': instruction,
        'original_business_context': 'Explicit synthetic local integration test; no production repository.',
        'new_question_or_answer_presented': False,
        'start_parameters': {'work_id': work_id, 'revision': 1, 'method_ref': asdict(source.method),
                             'associations': [{'kind': 'package', 'ref': asdict(source.package_ref)}]},
        'invoke_parameters': invoke}))

    observed = {'phase': 'origin', 'created': [], 'callbacks': [], 'permissions': [], 'replays': 0, 'fault': False,
                'file_area_failures': []}
    from ordessa_environments_local.files import LocalFileArea
    original_path = LocalFileArea.path
    def record_file_area(self, relative):
        try:
            return original_path(self, relative)
        except Exception as error:
            if observed['phase'] == 'continuation':
                observed['file_area_failures'].append({'type': type(error).__name__,
                    'reason': str(error), 'root': self.root(), 'relative': relative})
            raise
    monkeypatch.setattr(LocalFileArea, 'path', record_file_area)
    policies = []
    original_init = module.FrozenScope.__init__
    def record_policy(self):
        original_init(self)
        policies.append(self)
    monkeypatch.setattr(module.FrozenScope, '__init__', record_policy)
    original_load = module.load_module
    def load_exact(name, path):
        result = original_load(name, path)
        if Path(path).name == 'probe-work-package-generation.py':
            result.PI = pi_tool
            result.CASE_ID, result.ROOT = case_id, repo
            result.BRIDGE, result.BRIDGE_SHA, result.ENV_SOURCE = bridge, bridge_digest, credential
            def refuse_retained_owner(observation):
                pytest.fail('Original native owner did not close: ' + json.dumps(observation))
            result.wait_generation_owner_resume = refuse_retained_owner
        elif Path(path) == module.M2:
            result.NIGHTLY = cache
            execute = result.execute_case
            def observe_execute(**values):
                answer = execute(**values)
                if values.get('mode') == 'continuation':
                    replay = result.invoke_formal_work_action(values['runtime'], caller=values['caller'],
                        scope=values['scope'], parameters=values['parameters'], request_id=values['request_id'])
                    assert replay == answer['result']
                    observed['replays'] += 1
                return answer
            result.execute_case = observe_execute
        return result
    monkeypatch.setattr(module, 'load_module', load_exact)
    original_create = UnitManager.create
    def record_create(self, spec, authority):
        selected = policies[-1]
        holder = selected.holder
        assert observed['phase'] != 'expired', 'expired authorization must refuse before a Unit'
        if observed['phase'] == 'continuation':
            # The original bootstrap bridge deliberately suspends the active
            # Engineering lease while Unit's own real permissions run.
            active = holder['access']._active.get()
            assert active is not None and active.suspended
            context = active.context
            with holder['factory'].begin(holder['scope'], 'read') as uow:
                if holder.get('report_delivered'):
                    assert selected.review_id is not None
                    role = 'reviewer'
                else:
                    causal = uow.commands.find_operation(context.scope, context.request_id,
                                                         operation=CONTINUATION_OPERATION)
                    assert causal is not None and causal.state == 'pending'
                    bootstrap = uow.commands.get(unit_bootstrap_request_key(context))
                    assert bootstrap.state == 'pending'
                    role = 'successor'
        else:
            role = 'origin'
        unit = original_create(self, spec, authority)
        observed['created'].append((role, module.plain(unit.identity)))
        return unit
    monkeypatch.setattr(UnitManager, 'create', record_create)
    original_callback = UnitFileCallbackApproval.authorize
    def record_callback(self, **request):
        try:
            value = original_callback(self, **request)
        except Exception as error:
            import traceback
            print('NATIVE_CALLBACK_FAILURE', type(error).__name__, getattr(error, 'code', None),
                [(Path(f.filename).name,f.lineno,f.name) for f in traceback.extract_tb(error.__traceback__)],
                file=sys.stderr)
            raise
        observed['callbacks'].append((request['method'], module.plain(request['unit_ref']), value))
        if request['method'] == 'session/request_permission':
            observed['permissions'].append((module.plain(request['unit_ref']),
                request['params']['toolCall']['kind'], value))
        return value
    monkeypatch.setattr(UnitFileCallbackApproval, 'authorize', record_callback)
    first = cache / 'origin-attempt'
    original_write = EnvironmentProcessChannel._write_async
    async def prewrite_peer_exit(self, data, lease, **controls):
        if controls.get('effect_write_guard') is not None and not observed['fault']:
            observed['fault'] = True
            # An actual owned external harness exits after preparation, before
            # this prompt's guard. Original liveness admission, diagnostic,
            # UNKNOWN recording and stop/release evidence remain unchanged.
            await self._process.cancel(force=True)
            await self._process.wait_exit(timeout=2)
        return await original_write(self, data, lease, **controls)
    monkeypatch.setattr(EnvironmentProcessChannel, '_write_async', prewrite_peer_exit)
    base_args = ['--candidate', str(candidate), '--candidate-sha256', module.sha(candidate), '--run-real']
    assert module.main([*base_args, '--output', str(first)]) == 1
    completion = json.loads((first / 'completion.json').read_text())
    assert completion['historical_files_unchanged'] and completion['runtime_stopped']
    assert module.target_hashes() == before
    assert [role for role, _ in observed['created']] == ['origin']
    assert observed['callbacks'] == []
    graph = Path(json.loads(registration.read_text())['graph'])
    with sqlite3.connect(graph / 'engineering.sqlite') as db:
        db.row_factory = sqlite3.Row
        origin = dict(db.execute('SELECT * FROM work_step_log WHERE attempt=1').fetchone())
        protected = {table: tuple(tuple(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid'))
                     for table in ('eng_approval_grants', 'eng_action_consumptions')}
        work_rows = tuple(tuple(row) for row in db.execute("SELECT * FROM materials WHERE kind='work-context'"))
    assert origin['dispatch_phase'] == 'unknown' and origin['dispatch_version'] == 2
    selector_args = ['--continuation-operation-ref', origin['execution_operation_ref'],
        '--continuation-attempt', '1', '--continuation-dispatch-version', '2',
        '--continuation-acp-revision', '2']
    observed['phase'] = 'expired'
    actual_clock = engineering_clock.utc_now
    monkeypatch.setattr(engineering_clock, 'utc_now', lambda: stamp(now + timedelta(hours=5)))
    expired = cache / 'expired-attempt'
    assert module.main([*base_args, '--output', str(expired), *selector_args]) == 1
    expired_result = json.loads((expired / 'completion.json').read_text())
    assert expired_result['stage'] == 'BLOCKED' and expired_result['unit_started'] is False
    assert [role for role, _ in observed['created']] == ['origin']
    monkeypatch.setattr(engineering_clock, 'utc_now', actual_clock)
    observed['phase'] = 'continuation'
    continuation = cache / 'continuation-attempt'
    status = module.main([*base_args, '--output', str(continuation), *selector_args])
    if status != 0:
        blocked = json.loads((continuation / 'completion.json').read_text())
        with sqlite3.connect(graph / 'engineering.sqlite') as db:
            db.row_factory = sqlite3.Row
            preserved = dict(db.execute('SELECT * FROM work_step_log WHERE attempt=1').fetchone()) == origin
            debit_preserved = all(tuple(tuple(row) for row in db.execute(
                'SELECT * FROM ' + table + ' ORDER BY rowid')) == rows for table, rows in protected.items())
        (tmp_path / 'NATIVE-CLI-BLOCKER.json').write_text(json.dumps({'synthetic': True,
            'external_model_calls': 0, 'created': observed['created'],
            'callbacks': observed['callbacks'], 'file_area_failures': observed['file_area_failures'],
            'old_unknown_unchanged': preserved, 'grant_and_debits_unchanged': debit_preserved,
            'expired_refused_before_unit': True, 'runtime_stopped': blocked['runtime_stopped'],
            'close_states': blocked.get('unit_close'), 'error': blocked.get('error')}, indent=2))
    assert status == 0
    receipt = json.loads((continuation / 'continuation-receipt.json').read_text())
    assert receipt['read_back']['data']['state'] == 'completed'
    assert receipt['result']['result']['method_result']['disposition'] == 'accepted'
    assert observed['replays'] == 1
    assert [role for role, _ in observed['created']] == ['origin', 'successor', 'reviewer']
    origin_ref, successor_ref, reviewer_ref = [ref for _, ref in observed['created']]
    assert len({ref['unitId'] for ref in (origin_ref, successor_ref, reviewer_ref)}) == 3
    assert {method for method, _, _ in observed['callbacks']} == {'session/request_permission'}
    writes = [ref for ref, kind, value in observed['permissions'] if kind == 'edit' and value == 'accept']
    reads = [ref for ref, kind, value in observed['permissions'] if kind == 'read' and value == 'accept']
    assert writes == [successor_ref] and reads == [reviewer_ref]
    assert [(ref, kind) for ref, kind, value in observed['permissions'] if value is None
            ] == [(successor_ref, 'edit'), (successor_ref, 'edit')]
    assert [ref for ref, kind, value in observed['permissions']
            if kind == 'execute' and value == 'accept'] == [successor_ref]
    assert (target / 'catalog/views.py').read_text() == '# synthetic successor edit\n'
    with sqlite3.connect(graph / 'engineering.sqlite') as db:
        db.row_factory = sqlite3.Row
        assert dict(db.execute('SELECT * FROM work_step_log WHERE attempt=1').fetchone()) == origin
        for table, rows in protected.items():
            assert tuple(tuple(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')) == rows
        assert tuple(tuple(row) for row in db.execute("SELECT * FROM materials WHERE kind='work-context'")) == work_rows
        successor = dict(db.execute('SELECT * FROM work_step_log WHERE attempt=2').fetchone())
        assert successor['dispatch_phase'] == 'completed'
        assert db.execute('SELECT COUNT(*) FROM eng_acceptance_receipts').fetchone()[0] == 0
    final = json.loads((continuation / 'completion.json').read_text())
    assert final['runtime_stopped'] and final['historical_files_unchanged']
    (tmp_path / 'NATIVE-CLI-EVIDENCE.json').write_text(json.dumps({'synthetic': True,
        'external_models': 0, 'created': observed['created'], 'callbacks': observed['callbacks'],
        'replays': observed['replays'], 'first_unknown_preserved': True, 'grant_and_debits_unchanged': True,
        'expired_refused_before_unit': True, 'runtime_stopped': final['runtime_stopped']}, indent=2))
