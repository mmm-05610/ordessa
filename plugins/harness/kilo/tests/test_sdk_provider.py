"""SDK migration boundary tests; no real brand/model compatibility claim."""
import ast
import asyncio
import json
from dataclasses import replace
from pathlib import Path
import pytest
from ordessa_execution_agents.sdk import BoundPath,PrepareContext,PreparedConfigurationRef,SessionBootstrap,HarnessError
from ordessa_execution_agents.profiles import decode_content
from ordessa_harness_kilo import factory
PIN={'environmentNamespace':'test','definitionId':'kilo','revision':'1'}
DIGEST='sha256:'+'a'*64


def content(payload=None):
    return decode_content({'schemaVersion':'1','harnessDefinitionRef':PIN,'declarations':[] if payload is None else [
        {'declarationId':'native','configurationKind':'kilo.configuration','schemaVersion':'1','action':'value','requirement':'required','payload':payload}]},'test')


def context():
    roots={key:BoundPath(key,'.') for key in ('work','home','config','data','state','cache','tmp')}
    environment={'HOME':'/approved/home','PATH':'/approved/bin','XDG_CONFIG_HOME':'/approved/config',
        'XDG_DATA_HOME':'/approved/data','XDG_STATE_HOME':'/approved/state','XDG_CACHE_HOME':'/approved/cache','TMPDIR':'/approved/tmp'}
    environment['KILO_CONFIG_CONTENT']=json.dumps({'autoupdate':False,'provider':{'custom':{'options':{'apiKey':'{env:OPENAI_API_KEY}'}}}})
    prepared=()
    return PrepareContext({'members':['launcher','communicate']},roots,('/approved/kilo',),environment,(),(),prepared,SessionBootstrap('fresh','original-bootstrap'))


def test_pinned_profile_and_pure_immutable_acp_plan(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('no direct spawn')))
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    plan=provider.prepare(content(),context())
    assert provider.descriptor.protocol_id=='acp'
    assert plan.argv==('/approved/kilo','acp')
    assert plan.cwd_ref==BoundPath('work','.')
    assert plan.prepared_configuration_refs==context().prepared_configuration_refs
    with pytest.raises(TypeError):plan.environment_values['HOME']='changed'
    with pytest.raises(HarnessError,match='PROFILE_HARNESS_PIN_MISMATCH'):
        provider.validate_profile(replace(content(),harness_definition_ref={**PIN,'revision':'2'}))
    with pytest.raises(HarnessError,match='CONFIGURATION_UNSUPPORTED'):provider.validate_profile(content({'model':'unsupported-declaration'}))


def test_open_session_uses_only_original_owner_closure():
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    observed=[];session=object()
    class Process:
        async def open_acp_session(self,bootstrap):observed.append(bootstrap);return session
    assert asyncio.run(provider.open_session(Process(),context())) is session
    assert observed==[context().session_bootstrap]
    with pytest.raises(HarnessError,match='ACP_BOOTSTRAP_UNAVAILABLE'):
        asyncio.run(provider.open_session(object(),context()))
    with pytest.raises(HarnessError,match='SESSION_MODE_UNSUPPORTED'):
        provider.prepare(content(),replace(context(),session_bootstrap=SessionBootstrap('resume','native-session')))


def test_explicit_environment_and_no_credentials_or_autoapproval():
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    with pytest.raises(HarnessError,match='EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED'):
        provider.prepare(content(),replace(context(),launch_environment={}))
    with pytest.raises(HarnessError,match='CREDENTIAL_REFERENCE_REQUIRED'):
        provider.prepare(content(),replace(context(),launch_environment={**dict(context().launch_environment),'OPENAI_API_KEY':'not-materialized'}))
    with pytest.raises(HarnessError,match='AUTO_APPROVAL_UNSUPPORTED'):
        provider.prepare(content(),replace(context(),command_prefix=('/approved/kilo','--yes')))


def test_sdk_only_runtime_imports_and_entrypoint():
    import tomllib
    import ordessa_harness_kilo.provider as module
    for path in Path(module.__file__).parent.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.ImportFrom) and (node.module or '').startswith('ordessa_'):
                assert node.module=='ordessa_execution_agents.sdk'
    metadata=tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text())
    assert metadata['project']['entry-points']['ordessa.harness_providers']['kilo']=='ordessa_harness_kilo.provider:factory'
    with pytest.raises(HarnessError,match='HARNESS_BINDINGS_INVALID'):factory.build({})


def test_native_config_rejects_literal_credentials_and_auto_update():
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    for document,reason in (({'autoupdate':True},'CONFIGURATION_INVALID'),
                            ({'autoupdate':False,'provider':{'apiKey':'literal'}},'CREDENTIAL_REFERENCE_REQUIRED')):
        with pytest.raises(HarnessError,match=reason):
            provider.prepare(content(),replace(context(),launch_environment={**dict(context().launch_environment),'KILO_CONFIG_CONTENT':json.dumps(document)}))
    with pytest.raises(HarnessError,match='PREPARED_CONFIGURATION_REQUIRED'):
        provider.prepare(content(),replace(context(),launch_environment={**dict(context().launch_environment),'KILO_CONFIG_CONTENT':'{"autoupdate":true,"autoupdate":false}'}))


def test_actual_profile_owner_calls_real_kilo_validator_before_its_atomic_commit(tmp_path):
    from threading import RLock
    from ordessa_execution_agents.profiles import ProfileService,SqliteProfileStore,ProfileValidationError
    from ordessa_infrastructure.security.fingerprints import HmacKeyRing
    from ordessa_infrastructure.encoding import canonical_bytes
    class Policy:
        def admit_invoke(self,*args):return True
        def admit_object_access(self,*args):return True
    class Fingerprint:
        def __init__(self):self.ring=HmacKeyRing({'fixture':b'controlled-kilo-profile'},active_key_id='fixture')
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
        created=service.create(profile_id='kilo',name='Kilo',content=body,request=service.request_key('valid'))
        pinned=service.get_revision(created.current_revision)
        assert provider.prepare(pinned.content,context()).argv==('/approved/kilo','acp')
        bad={'schemaVersion':'1','harnessDefinitionRef':PIN,'declarations':[{'declarationId':'native','configurationKind':'kilo.configuration','schemaVersion':'1','action':'value','requirement':'required','payload':{'oauthToken':'refused-before-commit'}}]}
        with pytest.raises(ProfileValidationError):service.create(profile_id='bad',name='Bad',content=bad,request=service.request_key('bad'))
        assert len(service.list())==1
        assert store._conn.execute('SELECT count(*) FROM profile_requests').fetchone()[0]==1
    finally:store.close()
