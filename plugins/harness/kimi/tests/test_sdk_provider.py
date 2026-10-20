"""Pure SDK migration tests. Native protocol L1 requirements remain separate."""
import ast
import asyncio
from dataclasses import replace
from pathlib import Path
import pytest
from ordessa_execution_agents.sdk import BoundPath,PrepareContext,SessionBootstrap,HarnessError
from ordessa_execution_agents.profiles import decode_content
from ordessa_harness_kimi import factory

PIN={'environmentNamespace':'test','definitionId':'kimi','revision':'1'}
DIGEST='sha256:'+'a'*64


def content(payload=None):
    return decode_content({'schemaVersion':'1','harnessDefinitionRef':PIN,'declarations':[] if payload is None else [
        {'declarationId':'native','configurationKind':'kimi.configuration','schemaVersion':'1','action':'value','requirement':'required','payload':payload}]},'test')


def context():
    roots={key:BoundPath(key,'.') for key in ('work','home','config','data','state','cache','tmp')}
    environment={'HOME':'/approved/home','PATH':'/approved/bin','XDG_CONFIG_HOME':'/approved/config',
        'XDG_DATA_HOME':'/approved/data','XDG_STATE_HOME':'/approved/state','XDG_CACHE_HOME':'/approved/cache',
        'TMPDIR':'/approved/tmp','KIMI_SHARE_DIR':'/approved/private-native'}
    return PrepareContext({'members':['launcher','communicate']},roots,('/approved/kimi',),environment,(),(),(),SessionBootstrap('fresh','original-bootstrap-config'))


def test_real_provider_retains_native_protocol_and_pure_immutable_plan(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('no direct spawn')))
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    profile=content({'model':'kimi-test','thinking':False});provider.validate_profile(profile)
    plan=provider.prepare(profile,context())
    assert plan.argv==('/approved/kimi','--wire','--model','kimi-test','--no-thinking')
    assert provider.descriptor.protocol_id=='kimi-wire/1.10'
    assert plan.cwd_ref==BoundPath('work','.')
    with pytest.raises(TypeError):plan.environment_values['HOME']='changed'
    with pytest.raises(HarnessError,match='PROFILE_HARNESS_PIN_MISMATCH'):
        provider.validate_profile(replace(profile,harness_definition_ref={**PIN,'revision':'2'}))


def test_native_protocol_never_uses_acp_or_legacy_client():
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    class Process:
        async def open_acp_session(self,*args):raise AssertionError('native protocol is not ACP')
    with pytest.raises(HarnessError,match='NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE'):
        asyncio.run(provider.open_session(Process(),context()))
    with pytest.raises(HarnessError,match='SESSION_CONFIGURATION_UNAVAILABLE'):provider.validate_profile(content({'replay':True}))
    with pytest.raises(HarnessError,match='SESSION_MODE_UNSUPPORTED'):
        provider.prepare(content(),replace(context(),session_bootstrap=SessionBootstrap('resume','old-session')))


def test_no_implicit_environment_credentials_or_auto_approval():
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    with pytest.raises(HarnessError,match='EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED'):
        provider.prepare(content(),replace(context(),launch_environment={}))
    with pytest.raises(HarnessError,match='CREDENTIAL_REFERENCE_REQUIRED'):
        provider.prepare(content(),replace(context(),launch_environment={**dict(context().launch_environment),'GH_TOKEN':'refuse'}))
    with pytest.raises(HarnessError,match='AUTO_APPROVAL_UNSUPPORTED'):
        provider.prepare(content(),replace(context(),command_prefix=('/approved/kimi','--yolo')))
    with pytest.raises(HarnessError,match='CONFIGURATION_UNSUPPORTED'):provider.validate_profile(content({'mcpServers':{}}))


def test_all_runtime_imports_use_sdk_only_and_old_client_is_absent():
    import ordessa_harness_kimi.client as module
    assert not hasattr(module,'KimiWireClient')
    for path in Path(module.__file__).parent.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.ImportFrom) and (node.module or '').startswith('ordessa_'):
                assert node.module=='ordessa_execution_agents.sdk'


def test_factory_bindings_and_entrypoint_are_explicit():
    import tomllib
    with pytest.raises(HarnessError,match='HARNESS_BINDINGS_INVALID'):factory.build({})
    metadata=tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text())
    assert metadata['project']['entry-points']['ordessa.harness_providers']['kimi']=='ordessa_harness_kimi.client:factory'


def test_actual_profile_owner_calls_real_kimi_validator_before_its_atomic_commit(tmp_path):
    from threading import RLock
    from ordessa_execution_agents.profiles import ProfileService,SqliteProfileStore,ProfileValidationError
    from ordessa_infrastructure.security.fingerprints import HmacKeyRing
    from ordessa_infrastructure.encoding import canonical_bytes
    class Policy:
        def admit_invoke(self,*args):return True
        def admit_object_access(self,*args):return True
    class Fingerprint:
        def __init__(self):self.ring=HmacKeyRing({'fixture':b'controlled-kimi-profile'},active_key_id='fixture')
        def describe(self):return self.ring.describe(comparison_scope='profile:test')
        def fingerprint(self,request,surface,digest):
            return self.ring.sign(canonical_bytes([request.environment_namespace,request.principal_scope,request.request_id,surface,digest]))
    class Admission:
        namespace='test';principal_scope='controlled';admission_lock=RLock();policy=Policy();fingerprint_port=Fingerprint()
        def check_open(self):pass
        def check_namespace(self,namespace):assert namespace==self.namespace
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    store=SqliteProfileStore(tmp_path/'profiles.sqlite');service=ProfileService(store,Admission(),provider)
    body={'schemaVersion':'1','harnessDefinitionRef':PIN,'declarations':[]}
    try:
        created=service.create(profile_id='kimi',name='Kimi',content=body,request=service.request_key('valid'))
        pinned=service.get_revision(created.current_revision)
        assert provider.prepare(pinned.content,context()).argv==('/approved/kimi','--wire')
        bad={'schemaVersion':'1','harnessDefinitionRef':PIN,'declarations':[{'declarationId':'native','configurationKind':'kimi.configuration','schemaVersion':'1','action':'value','requirement':'required','payload':{'oauthToken':'refused-before-commit'}}]}
        with pytest.raises(ProfileValidationError):service.create(profile_id='bad',name='Bad',content=bad,request=service.request_key('bad'))
        assert len(service.list())==1
        assert store._conn.execute('SELECT count(*) FROM profile_requests').fetchone()[0]==1
    finally:store.close()
