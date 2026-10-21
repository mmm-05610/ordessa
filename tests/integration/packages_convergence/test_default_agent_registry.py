"""Formal current registry -> original Profile/native owners, no real brand/model."""
import asyncio,json,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_server.composition.registry_runtime import RegistryRuntime
from ordessa_server.composition.packages_convergence import build_agent_registry_host,build_agent_registry_runtime
from ordessa_server.composition.agent_bindings.profile_access import OriginalProfileAccess
from test_recorded_native_configuration import native_case,request,close

ROOT=Path(__file__).parents[3]


def test_default_registry_original_profile_native_and_cold_query_after_revoke(tmp_path):
    async def scenario():
        case=await native_case(tmp_path)
        try:
            profile_actions=('capabilities','list','readEntry','read','preview','create','edit','clone','rename','archive','restore')
            original_caps=case.caller[0].grants[0].capabilities
            caps=tuple(original_caps)+tuple('agents.profiles.'+a for a in profile_actions)
            case.issuer.replace_grants((AccessGrant(case.scope,caps),))
            case.caller[0]=case.issuer.authenticate('Bearer synthetic-native-token')
            def caller(invocation):
                assert invocation is case.fixture.invocation
                return case.caller[0]
            profile_access=OriginalProfileAccess(case.issuer,caller_resolver=caller,
                scope_for_service=lambda service:case.scope if service is case.owner.service else None,
                principal_scope_for_caller=lambda p:'principal:'+p.principal_id)
            owner=SimpleNamespace(profile_service=case.owner.service,interactions=case.native,records=case.records,manager=case.manager)
            host=build_agent_registry_host(owner,invocation_resolver=lambda context:case.fixture.invocation,
                native_write_guard=case.native_access,profile_guard=profile_access.guard)
            def context(caller,identity,deadline):
                case.issuer.verify(caller)
                case.caller[0]=caller
                return RequestContext({'principalId':caller.principal_id},identity,deadline)
            runtime=build_agent_registry_runtime(owner,case.issuer,context_factory=context,
                invocation_resolver=lambda context:case.fixture.invocation,native_write_guard=case.native_access,
                profile_guard=profile_access.guard,server_id='existing-controlled-server-id')
            hello=await runtime.wire({'jsonrpc':'2.0','id':'hello','method':'server.hello',
                'params':{'clientVersions':['wire/1'],'clientPresentationSupports':[]}},'Bearer synthetic-native-token')
            assert hello['result']['serverId']=='existing-controlled-server-id'
            assert {c['id'] for c in hello['result']['capabilities']}=={'capabilities.list','operations.describe','operations.call'}
            async def invoke(op,data,identity):
                body={'jsonrpc':'2.0','id':identity,'method':'operations.call','params':{'operationId':op,'input':data}}
                result=await runtime.wire(body,'Bearer synthetic-native-token')
                assert result['id']==identity
                return result['result']
            original=case.owner.service.select_current('peer')
            ref=__import__('ordessa_agents.profiles',fromlist=['encode_revision_ref']).encode_revision_ref(original.ref)
            listing=await invoke('agents.profiles.list',{},'list')
            assert listing['status']=='completed' and listing['data']['entries'][0]['profileId']=='peer'
            read=await invoke('agents.profiles.read',{'profileRef':ref},'exact-revision')
            assert read['data']['ref']==ref and read['data']['content']['declarations']==[]
            changed=await invoke('agents.profiles.rename',{'profileId':'peer','displayName':'Registry rename','expectedCatalogRevision':1},'rename')
            assert changed['status']=='completed' and case.owner.service.get('peer').name=='Registry rename'
            assert changed==await invoke('agents.profiles.rename',{'profileId':'peer','displayName':'Registry rename','expectedCatalogRevision':1},'rename')
            apply=request(case)
            applied=await invoke('agents.native.recorded',{'request':apply.projection()},'native-registry')
            assert applied['status']=='completed' and applied['data']['state']=='completed'
            assert case.effects.read_text()=='m2\n'
            case.issuer.replace_grants((AccessGrant(case.scope,('agents.operations.read','agents.profiles.list','agents.profiles.read')),))
            case.caller[0]=case.issuer.authenticate('Bearer synthetic-native-token')
            db=case.owner.service._profile_store._conn
            before=db.total_changes
            denied=await invoke('agents.profiles.rename',{'profileId':'peer','displayName':'Forbidden','expectedCatalogRevision':2},'revoked')
            assert denied['status']=='refused' and db.total_changes==before
            cold=await invoke('agents.native.query',{'operationRef':applied['data']['binding']['operationRef'],'expectedInputDigest':apply.input_digest},'cold')
            assert cold['data']==applied['data'] and case.effects.read_text()=='m2\n'
            before=case.records._db.total_changes
            denied=await invoke('agents.native.recorded',{'request':request(case,purpose='query').projection()},'forbidden-upstream')
            assert denied['status']=='refused' and case.records._db.total_changes==before
            with pytest.raises(Exception):await runtime.wire({'jsonrpc':'2.0','id':'bad','method':'capabilities.list','params':{}},'Bearer wrong-test-token')
        finally:await close(case)
    asyncio.run(scenario())


def test_installed_console_and_cli_module_share_registry_without_kernel(tmp_path):
    from installed_server_fixture import build_installed_server
    python, console, env, packaging = build_installed_server(
        ROOT, tmp_path, extra_projects=('ordessa-cli',))
    for index, executable in enumerate(([str(console)],[str(python),'-m','ordessa_cli'])):
        receipt = tmp_path/('entry-imports-'+str(index)+'.json')
        env['ORDESSA_IMPORT_RECEIPT'] = str(receipt)
        result=subprocess.run([*executable,'--state',str(tmp_path/'state'),'list','--json'],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=10)
        (tmp_path/('entry-result-'+str(index)+'.json')).write_text(json.dumps({'args':result.args,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr},indent=2))
        assert result.returncode==0,result.stderr
        value=json.loads(result.stdout)
        assert value['apiVersion']=='agent-tools/1' and value['status']=='completed'
        ids={op['id'] for op in value['data']['operations']}
        assert 'environments.list' in ids and 'environments.acquire' not in ids
        # One-shot metadata lists the Agent/Decision surfaces but not the
        # session-only retained-handle operations.
        assert 'agents.start' in ids and 'decisions.query' in ids
        assert 'environments.process-release' not in ids
        imports=json.loads(receipt.read_text())
        assert imports['errors']==[],imports
        assert 'ordessa_cli.cli' in imports['origins']
        assert 'ordessa_interfaces.system_access' in imports['origins']
    assert packaging['localWheels']
    # The root module is the existing long-lived HTTP entry, not the CLI.
    env['ORDESSA_IMPORT_RECEIPT'] = str(tmp_path/'http-help-imports.json')
    help_result=subprocess.run([str(python),'-m','ordessa_server','--help'],cwd=tmp_path,
        env=env,capture_output=True,text=True,timeout=10)
    (tmp_path/'http-help-result.json').write_text(json.dumps({'args':help_result.args,
        'returncode':help_result.returncode,'stdout':help_result.stdout,'stderr':help_result.stderr},indent=2))
    assert help_result.returncode==0,help_result.stderr
    assert '--data-root' in help_result.stdout and '--port' in help_result.stdout
    assert '--state' not in help_result.stdout
    assert json.loads((tmp_path/'http-help-imports.json').read_text())['errors']==[]
