"""Real HTTP host process with explicit controlled owner inputs; no default grants."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys

import httpx
import pytest

CHILD = r'''
import asyncio, json, sys
from pathlib import Path
from ordessa_server.entrypoints.http import main
from ordessa_server.composition.http_bindings import HttpOwnerBindings
from ordessa_server.composition.agent_owner import AgentOwnerInputs
from ordessa_server.composition.agent_bindings.profile_access import OriginalProfileAccess
from ordessa_agents.capability.profiles import build_profile_capability
from ordessa_server_product.composition import ServerProductComposition
from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority, AccessGrant
from test_agent_guarded_bootstrap import setup

case = None
runtime = None
def factory(root):
    global case, runtime
    case = asyncio.run(setup(root/'controlled-fixture'))
    scope = Scope('fixture-realm','fixture-project')
    authority = InstanceAccessAuthority(lambda:'controlled-http-launch-token',
        principal_id='existing-test-caller', legacy_principal=None,
        grants=(AccessGrant(scope,('agents.profiles.list',)),))
    selected = [None]
    access = OriginalProfileAccess(authority,
        caller_resolver=lambda invocation:selected[0] if invocation is case.fixture.invocation else None,
        scope_for_service=lambda service:scope if service is case.owner.service else None,
        principal_scope_for_caller=lambda caller:'principal:'+caller.principal_id)
    def capabilities(owner):
        return (build_profile_capability(owner.profile_service,
            invocation_resolver=lambda context:case.fixture.invocation, guard=access.guard),)
    def context(caller, identity, deadline):
        authority.verify(caller); selected[0] = caller
        return RequestContext({'id':caller.principal_id},identity,deadline)
    inputs = AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
        case.manager.preparation_resolver,case.authority,case.authority,capabilities)
    product = ServerProductComposition(agent_owner_inputs=inputs,
        http_bindings=HttpOwnerBindings(authority,context,'controlled-original-server'))
    runtime = product.prepare_http_runtime()(root)
    original_close = runtime._close
    def close():
        original_close()
        (root/'controlled-cleanup.json').write_text(json.dumps({'runtimeClosed':runtime._closed}))
    runtime._close = close
    return runtime
try:
    code = main(sys.argv[1:],runtime_factory=factory)
finally:
    if runtime is not None: runtime.close()
    if case is not None:
        case.records.close(); case.owner.close(); asyncio.run(case.fixture.cleanup())
    Path(sys.argv[sys.argv.index('--data-root')+1],'controlled-cleanup.json').write_text(
        json.dumps({'runtimeClosed':runtime is not None and runtime._closed}))
raise SystemExit(code)
'''


def child_script(tmp_path, body):
    # Preserve the test runner's explicit wheel/source selection without loading
    # unrelated first-party .pth files from the dependency interpreter.
    script=tmp_path/'controlled-child.py'
    paths=[str(p) for p in sys.path if p]
    script.write_text('import sys\nsys.path[:0]='+repr(paths)+'\n'+body)
    return script


def test_invalid_service_config_refuses_before_root_writes(tmp_path):
    """The zero-configuration default is real; an explicit-but-broken file is not.

    Absence of `--service-config` now means "derive the defaults", so the
    no-side-effect property is proved on a configuration that fails validation.
    """
    root=tmp_path/'not-created'
    broken=tmp_path/'broken.json'
    broken.write_text('{"version": 1}',encoding='utf-8')
    script=child_script(tmp_path,"from ordessa_server.__main__ import main\nraise SystemExit(main())\n")
    env=dict(os.environ);env.pop('ORDESSA_STATE',None)
    result=subprocess.run([sys.executable,'-I','-S',str(script),'--data-root',str(root),'--port','0',
                           '--service-config',str(broken)],
        env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==2, result.stderr
    assert 'AGENT_OWNER_UNAVAILABLE' in result.stderr
    assert 'service configuration' in result.stderr
    assert not result.stdout and not root.exists()


@pytest.mark.parametrize('root_source',['flag','environment'])
def test_http_entrypoint_handshake_authenticated_capabilities_and_cleanup(tmp_path,root_source):
    root=tmp_path/'product'
    script=child_script(tmp_path,CHILD)
    env=dict(os.environ);env['ORDESSA_DATA_ROOT']=str(root)
    # CHILD's cleanup locator is explicit; environment-only selection is passed
    # to the actual host while the fixture retains its own known temporary path.
    body=CHILD
    if root_source=='environment':
        body=body.replace("Path(sys.argv[sys.argv.index('--data-root')+1],'controlled-cleanup.json')",
                          "Path(__import__('os').environ['ORDESSA_DATA_ROOT'],'controlled-cleanup.json')")
        script=child_script(tmp_path,body)
    args=['--port','0']
    if root_source=='flag': args=['--data-root',str(root),*args]
    errors=tmp_path/'child.stderr'
    with errors.open('w') as stderr:
        child=subprocess.Popen([sys.executable,'-I','-S',str(script),*args],env=env,
            stdout=subprocess.PIPE,stderr=stderr,text=True,start_new_session=True)
        tail=''
        try:
            ready,_,_=select.select([child.stdout],[],[],10)
            assert ready, errors.read_text()
            line=child.stdout.readline()
            assert line, errors.read_text()
            hello=json.loads(line)
            assert set(hello)=={'event','origin','serverId','pid'}
            assert hello['event']=='listening' and hello['pid']==child.pid
            assert hello['serverId']=='controlled-original-server'
            assert hello['origin'].startswith('http://127.0.0.1:')
            assert int(hello['origin'].rsplit(':',1)[1])>0
            with httpx.Client(base_url=hello['origin'],timeout=3,trust_env=False) as client:
                assert client.get('/live').json()=={'status':'alive'}
                assert client.get('/live',headers={'Host':'foreign.invalid'}).status_code==403
                request={'jsonrpc':'2.0','id':'hello','method':'server.hello',
                    'params':{'clientVersions':['wire/1']}}
                assert client.post('/wire/v1/server.hello',json=request).status_code==401
                assert client.post('/wire/v1/server.hello',json=request,
                    headers={'Authorization':'Bearer wrong-controlled-token'}).status_code==401
                auth={'Authorization':'Bearer controlled-http-launch-token'}
                answered=client.post('/wire/v1/server.hello',json=request,headers=auth)
                assert answered.status_code==200 and answered.json()['result']['serverId']==hello['serverId']
                request={'jsonrpc':'2.0','id':'list','method':'operations.call',
                    'params':{'operationId':'agents.profiles.list','input':{}}}
                result=client.post('/wire/v1/operations.call',json=request,headers=auth).json()['result']
                assert result['status']=='completed' and result['data']['entries'][0]['profileId']=='peer',result
                request['id']='not-granted';request['params']['operationId']='agents.profiles.create'
                request['params']['input']={}
                assert client.post('/wire/v1/operations.call',json=request,headers=auth).json()['result']['status']=='refused'
            from ordessa_server.composition.root_ownership import DataRootOwner
            with pytest.raises(RuntimeError): DataRootOwner(root).acquire()
            assert not (root/'state/core.sqlite').exists()
        finally:
            if child.poll() is None: child.terminate()
            try: tail=child.communicate(timeout=8)[0]
            except subprocess.TimeoutExpired:
                child.kill();tail=child.communicate(timeout=3)[0]
    # Uvicorn replays SIGTERM after lifespan shutdown; the OS exit signal is
    # expected. Cleanup is proved by the close receipt and the real root lock.
    assert child.returncode in (0,-signal.SIGTERM),errors.read_text()
    assert not tail.strip(), 'listening handshake must be the sole stdout line'
    assert 'controlled-http-launch-token' not in errors.read_text()
    assert json.loads((root/'controlled-cleanup.json').read_text())=={'runtimeClosed':True}
    from ordessa_server.composition.root_ownership import DataRootOwner
    owner=DataRootOwner(root);owner.acquire();owner.release()
