"""SDK-only provider contracts; no native/model process and no L1 substitution."""
import ast
import asyncio
from dataclasses import replace
from pathlib import Path
import pytest
from ordessa_agents.sdk import PrepareContext, BoundPath, SessionBootstrap, HarnessError
from ordessa_agents.profiles import decode_content
from ordessa_harness_goose import factory

PIN={'environmentNamespace':'test','definitionId':'goose','revision':'1'}
DIGEST='sha256:'+'a'*64


def content(payload=None):
    declarations=[] if payload is None else [{'declarationId':'native',
        'configurationKind':'goose.configuration','schemaVersion':'1','action':'value',
        'requirement':'required','payload':payload}]
    return decode_content({'schemaVersion':'1','harnessDefinitionRef':PIN,'declarations':declarations},'test')


def context():
    roots={key:BoundPath(key,'.') for key in ('work','home','config','data','state','cache','tmp')}
    environment={'HOME':'/approved/home','PATH':'/approved/bin','XDG_CONFIG_HOME':'/approved/config',
        'XDG_DATA_HOME':'/approved/data','XDG_STATE_HOME':'/approved/state','XDG_CACHE_HOME':'/approved/cache',
        'TMPDIR':'/approved/tmp','VIBE_HOME':'/approved/home/vibe'}
    return PrepareContext({'members':['launcher','communicate']},roots,('/approved/bin/goose',),
        environment,(),(),(),SessionBootstrap('fresh','approved-bootstrap'))


def provider():
    return factory.build({'definition_ref':PIN,'implementation_digest':DIGEST})


def test_provider_compiles_native_immutable_plan_without_spawning(monkeypatch):
    monkeypatch.setattr('subprocess.Popen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('no plugin spawn')))
    p=provider();p.validate_profile(content());plan=p.prepare(content(),context())
    assert p.descriptor.provider_id=='goose' and p.descriptor.protocol_id=='acp'
    assert plan.argv==('/approved/bin/goose','acp')
    assert plan.cwd_ref==BoundPath('work','.')
    assert plan.required_capabilities==('launcher','communicate')
    assert plan.environment_values['HOME']=='/approved/home'
    with pytest.raises(TypeError):plan.environment_values['HOME']='mutate'
    with pytest.raises(HarnessError,match='PROFILE_HARNESS_PIN_MISMATCH'):
        p.validate_profile(replace(content(),harness_definition_ref={**PIN,'revision':'2'}))


def test_no_silent_session_configuration_resume_or_secret_fallback():
    p=provider()
    with pytest.raises(HarnessError,match='SESSION_CONFIGURATION_UNAVAILABLE'):
        p.prepare(content({'model':'native-model'}),context())
    with pytest.raises(HarnessError,match='CONFIGURATION_UNSUPPORTED'):
        p.validate_profile(content({'mystery':'refused'}))
    with pytest.raises(HarnessError,match='CREDENTIAL_REFERENCE_REQUIRED'):
        p.prepare(content(),replace(context(),launch_environment={**dict(context().launch_environment),'API_KEY':'refused'}))
    with pytest.raises(HarnessError,match='SESSION_MODE_UNSUPPORTED'):
        p.prepare(content(),replace(context(),session_bootstrap=SessionBootstrap('resume','old')))
    with pytest.raises(HarnessError,match='ACP_BOOTSTRAP_UNAVAILABLE'):
        asyncio.run(p.open_session(object(),context()))


def test_open_session_delegates_exact_bootstrap_to_restricted_original_owner():
    observed=[];session=object();ctx=context()
    class Process:
        async def open_acp_session(self,bootstrap):
            observed.append(bootstrap);return session
    assert asyncio.run(provider().open_session(Process(),ctx)) is session
    assert observed==[ctx.session_bootstrap]


def test_runtime_imports_only_public_sdk_and_no_retired_client():
    import ordessa_harness_goose.client as module
    assert not hasattr(module,'GooseClient')
    for path in Path(module.__file__).parent.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.ImportFrom) and (node.module or '').startswith('ordessa_'):
                assert node.module=='ordessa_agents.sdk'


def test_missing_approved_roots_or_endpoint_fails_before_effect():
    with pytest.raises(HarnessError,match='APPROVED_ROOTS_UNAVAILABLE'):
        provider().prepare(content(),replace(context(),private_dirs={}))
    with pytest.raises(HarnessError,match='ENDPOINT_CAPABILITY_UNAVAILABLE'):
        provider().prepare(content(),replace(context(),endpoint_facts={'members':['launcher']}))


@pytest.mark.parametrize('token',['--dangerously-unauthenticated','--dangerously-unauthenticated=true'])
def test_launch_prefix_cannot_bypass_original_unauthenticated_fence(token):
    with pytest.raises(HarnessError,match='UNAUTHENTICATED_MODE_REFUSED'):
        provider().prepare(content(),replace(context(),command_prefix=context().command_prefix+(token,)))
    with pytest.raises(HarnessError,match='CONFIGURATION_UNSUPPORTED'):
        provider().validate_profile(content({'approval_mode':'yolo'}))
