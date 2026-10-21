"""Actual Gemini provider consumes only SDK data and performs no native effects."""
import ast
from dataclasses import replace
from pathlib import Path
import pytest
from ordessa_agents.sdk import PrepareContext,BoundPath,SessionBootstrap,HarnessError
from ordessa_agents.profiles import decode_content
from ordessa_harness_gemini_cli import factory

PIN={'environmentNamespace':'test','definitionId':'gemini','revision':'1'}
DIGEST='sha256:'+'a'*64


def content(payload=None):
    return decode_content({'schemaVersion':'1','harnessDefinitionRef':PIN,'declarations':[] if payload is None else [
        {'declarationId':'native','configurationKind':'gemini.configuration','schemaVersion':'1','action':'value','requirement':'required','payload':payload}]},'test')


def context():
    roots={key:BoundPath(key,'.') for key in ('work','home','config','data','state','cache','tmp')}
    environment={'HOME':'/approved/home','PATH':'/approved/bin','XDG_CONFIG_HOME':'/approved/config',
        'XDG_DATA_HOME':'/approved/data','XDG_STATE_HOME':'/approved/state','XDG_CACHE_HOME':'/approved/cache','TMPDIR':'/approved/tmp'}
    return PrepareContext({'members':['launcher','communicate']},roots,('/approved/bin/gemini',),environment,(),(),(),SessionBootstrap('fresh','original-bootstrap-config'))


def test_real_provider_validates_pin_and_compiles_immutable_native_launch_without_effects(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('provider may not spawn')))
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    profile=content({'debug':True});provider.validate_profile(profile)
    plan=provider.prepare(profile,context())
    assert plan.argv==('/approved/bin/gemini','--acp','--debug')
    assert plan.environment_values['GEMINI_TELEMETRY_ENABLED']=='false'
    assert plan.cwd_ref==BoundPath('work','.') and plan.required_capabilities==('launcher','communicate')
    assert dict(profile.harness_definition_ref)==PIN
    with pytest.raises(TypeError):plan.environment_values['HOME']='mutate'
    with pytest.raises(HarnessError,match='PROFILE_HARNESS_PIN_MISMATCH'):
        provider.validate_profile(replace(profile,harness_definition_ref={**PIN,'revision':'2'}))


def test_unimplemented_session_configuration_and_bootstrap_refuse_without_legacy_client():
    provider=factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})
    with pytest.raises(HarnessError,match='SESSION_CONFIGURATION_UNAVAILABLE'):provider.prepare(content({'model':'gemini'}),context())
    with pytest.raises(HarnessError,match='ACP_BOOTSTRAP_UNAVAILABLE'):__import__('asyncio').run(provider.open_session(object(),context()))
    with pytest.raises(HarnessError,match='CONFIGURATION_UNSUPPORTED'):provider.validate_profile(content({'oauthToken':'not-a-credential'}))
    with pytest.raises(HarnessError,match='SESSION_MODE_UNSUPPORTED'):provider.prepare(content(),replace(context(),session_bootstrap=SessionBootstrap('resume','old-session')))


def test_all_gemini_runtime_imports_use_only_sdk_and_no_retired_client_name():
    import ordessa_harness_gemini_cli.client as module
    assert not hasattr(module,'GeminiCliClient')
    for path in Path(module.__file__).parent.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.ImportFrom) and (node.module or '').startswith('ordessa_'):
                assert node.module=='ordessa_agents.sdk'


def test_actual_profile_owner_calls_real_gemini_validator_before_its_atomic_commit(tmp_path):
    from threading import RLock
    from ordessa_agents.profiles import ProfileService,SqliteProfileStore,ProfileValidationError
    from ordessa_infrastructure.security.fingerprints import HmacKeyRing
    from ordessa_infrastructure.encoding import canonical_bytes
    class Policy:
        def admit_invoke(self,*args):return True
        def admit_object_access(self,*args):return True
    class Fingerprint:
        def __init__(self):self.ring=HmacKeyRing({'fixture':b'controlled-gemini-profile'},active_key_id='fixture')
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
        created=service.create(profile_id='gemini',name='Gemini',content=body,request=service.request_key('valid'))
        pinned=service.get_revision(created.current_revision)
        assert provider.prepare(pinned.content,context()).argv==('/approved/bin/gemini','--acp')
        bad={'schemaVersion':'1','harnessDefinitionRef':PIN,'declarations':[{'declarationId':'native','configurationKind':'gemini.configuration','schemaVersion':'1','action':'value','requirement':'required','payload':{'oauthToken':'refused-before-commit'}}]}
        with pytest.raises(ProfileValidationError):service.create(profile_id='bad',name='Bad',content=bad,request=service.request_key('bad'))
        assert len(service.list())==1
        assert store._conn.execute('SELECT count(*) FROM profile_requests').fetchone()[0]==1
    finally:store.close()
