"""Real Profile -> SDK provider -> guarded bootstrap -> original BlobStore.

Local peer only, no native Gemini/model claim; external caller owns preparation
and Use. No manually published instance/session/provenance facts are used.
"""
import asyncio
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,sys,threading
import pytest

from endpoint_fixture import LocalEndpointFixture
from apps.cli.tests.integration.profile_test_owner import profile_owner
from ordessa_agents.sdk import PrepareContext,BoundPath,SessionBootstrap,ConfigurationArtifact
from ordessa_agents.public import AgentManager,Records,ManagerRefused,AgentStartRequest,PreparedAgentContext
from ordessa_agents.sdk.interactions import InteractionService,InteractionsRefused
from ordessa_agents.sdk.prepare import canonical_digest
from ordessa_harness_gemini_cli import factory
from ordessa_infrastructure.encoding import canonical_bytes

PIN={'environmentNamespace':'test','definitionId':'gemini','revision':'1'}
PEER='''import sys,json,os,uuid,hashlib
session=uuid.uuid4().hex
for line in sys.stdin:
    request=json.loads(line)
    method=request['method'];params=request['params']
    if method=='initialize':
        assert params['protocolVersion']==1
        result={'protocolVersion':1,'agentCapabilities':{}}
    elif method=='session/new':
        assert params['cwd']==os.getcwd()
        result={'sessionId':session,'_meta':{'cwd':os.getcwd()}}
    else:
        assert method=='session/prompt' and params['sessionId']==session
        print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':session,'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'original-bootstrap-peer'}}}}),flush=True)
        result={'stopReason':'end_turn','_meta':{'paramsDigest':hashlib.sha256(json.dumps(params,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
'''

class Policy:
    def admit_invoke(self,*args):return True
    def admit_object_access(self,*args):return True

class Authority:
    def guard_instance_lifecycle(self, invocation, control, *, action):
        from contextlib import nullcontext
        return nullcontext()  # explicit controlled authority fixture only

    def __init__(self,invocation,prepared,request):
        self.invocation=invocation;self.prepared=prepared;self.request=request
        self.pin=dict(prepared.context.endpoint_facts['harnessPin']);self.read=True;self.send=True;self.writes=[];self.task=asyncio.current_task();self.thread=threading.get_ident()
    def principal_scope(self,invocation):
        if invocation is not self.invocation:raise ManagerRefused('FORGED_INVOCATION')
        return 'principal:existing-test-caller'
    def check_start(self,invocation,request,descriptor):
        self.principal_scope(invocation)
        assert request==self.request and dict(descriptor.definition_ref)==self.pin
        if not self.send:raise ManagerRefused('START_NOT_AUTHORIZED')
    def check_lifecycle_write(self,invocation,binding):
        self.principal_scope(invocation)
        if not self.send:raise ManagerRefused('WRITE_NOT_AUTHORIZED')
        assert asyncio.current_task() is self.task and threading.get_ident()==self.thread
        assert binding.profile_ref==self.request.profile_revision_ref
        assert binding.directory_binding_digest==self.prepared.directory_binding_digest
        self.writes.append(binding.phase)
    def check_read_instance(self,invocation,instance):
        self.principal_scope(invocation)
        if not self.read:raise ManagerRefused('READ_NOT_AUTHORIZED')
    def check_read_turn(self,invocation,query):self.check_read_instance(invocation,None)
    def check_read_binding(self,invocation,instance):self.check_read_instance(invocation,instance)
    def check_send(self,invocation,binding):
        self.principal_scope(invocation)
        if not self.send:raise InteractionsRefused('SEND_NOT_AUTHORIZED')

async def setup(tmp_path,peer=PEER,*,brand="gemini",runner=None,peer_name="peer.py"):
    if brand == 'gemini':
        provider_factory = factory
    elif brand == 'goose':
        from ordessa_harness_goose import factory as provider_factory
    elif brand == 'vibe':
        from ordessa_harness_vibe import factory as provider_factory
    else:
        raise KeyError(brand)
    pin={**PIN,"definitionId":brand}
    fixture=LocalEndpointFixture(tmp_path/'environment')
    from importlib.metadata import EntryPoint
    from ordessa_server.composition.packages_convergence import build_harness_catalog
    module=provider_factory.__class__.__module__.rsplit('.',1)[0]
    name={'gemini':'gemini-cli','goose':'goose','vibe':'vibe'}[brand]
    bindings={'definition_ref':pin,'implementation_digest':'sha256:'+hashlib.sha256(Path(sys.modules[provider_factory.__class__.__module__].__file__).read_bytes()).hexdigest()}
    catalog=build_harness_catalog(allowlist=(name,),bindings_by_provider={name:bindings},entry_points=(EntryPoint(name=name,value=module+':factory',group='ordessa.harness_providers'),))
    provider=catalog.resolve(pin)
    owner=profile_owner(tmp_path/'profiles.sqlite','test','principal:existing-test-caller',Policy(),pin,validator=catalog)
    try:
        profile=owner.service.create(profile_id='peer',name='Controlled peer',content={'schemaVersion':'1','harnessDefinitionRef':pin,'declarations':[]},request=owner.service.request_key('create'))
        endpoint=await fixture.endpoint()
        work=(tmp_path/'environment/work').resolve()
        roots={name:BoundPath('work','.' if name=='work' else name) for name in provider.descriptor.required_roots}
        for name in provider.descriptor.required_roots:
            if name!='work':(work/name).mkdir(exist_ok=True)
        artifact=ConfigurationArtifact(BoundPath('work',peer_name),'text/javascript' if peer_name.endswith('.mjs') else 'text/x-python',peer,'sha256:'+hashlib.sha256(peer.encode()).hexdigest())
        receipt=await endpoint.files.materialize(artifact,'peer-materialize',fixture.invocation)
        assert receipt['status']=='completed' and (work/peer_name).read_bytes()==peer.encode()
        # These facts originate in actual caller-owned files/directories, not
        # claimed Agent provenance or a fabricated fixed session.
        directory_digest=canonical_digest({name:{'path':str(work if name=='work' else work/name),'inode':(work if name=='work' else work/name).stat().st_ino} for name in roots})
        environment={'HOME':str(work/'home'),'PATH':str(Path(sys.executable).parent),'TMPDIR':str(work/'tmp'),
            **{'XDG_'+name.upper()+'_HOME':str(work/name) for name in ('config','data','state','cache')}}
        environment['VIBE_HOME']=str(work/'home')
        context=PrepareContext({'members':['launcher','communicate','files'],'harnessPin':pin},roots,tuple(runner or (sys.executable,'-u'))+(str(work/peer_name),),environment,(),(),(),SessionBootstrap('fresh',artifact.digest))
        prepared=PreparedAgentContext(context,artifact.digest,directory_digest,datetime.now(timezone.utc).isoformat(),str(work))
        request=AgentStartRequest('start',profile.current_revision,endpoint.ref,limits={'timeoutSeconds':2})
        authority=Authority(fixture.invocation,prepared,request)
        class PreparationResolver:
            def resolve(self,actual,bound,invocation):
                authority.check_start(invocation,actual,provider.descriptor)
                assert bound.ref==endpoint.ref and artifact.digest=='sha256:'+hashlib.sha256((work/peer_name).read_bytes()).hexdigest()
                assert prepared.directory_binding_digest==directory_digest
                return prepared
        records=Records(tmp_path/'agent.sqlite')
        manager=AgentManager(fixture.resolver,records,profile_service=owner.service,harness_resolver=catalog,preparation_resolver=PreparationResolver(),lifecycle_authority=authority)
        return SimpleNamespace(fixture=fixture,owner=owner,records=records,manager=manager,authority=authority,endpoint=endpoint,request=request,prepared=prepared)
    except BaseException:
        owner.close();await fixture.cleanup();raise


@pytest.mark.parametrize("brand",["gemini","goose","vibe"])
def test_public_start_original_native_session_prompt_and_engineering_capture(tmp_path,brand):
    from ordessa_engineering.adapters.native_records.agent_execution import AgentExecutionConsumer
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    async def scenario():
        case=await setup(tmp_path,brand=brand)
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running',started.projection()
            assert started.instance_ref and started.session_id
            phases=case.records._db.execute("SELECT status,payload FROM operations WHERE operation='bootstrap-frame' ORDER BY request_id").fetchall()
            assert len(phases)==2 and all(row[0]=='completed' for row in phases)
            assert set(case.authority.writes)=={'initialize','session/new'}
            source=InteractionService(case.records,case.authority,case.fixture.resolver)
            provenance=source.read_binding(started.instance_ref,invocation=case.fixture.invocation)
            assert provenance.source_revision==case.prepared.source_revision
            assert provenance.directory_binding_digest==case.prepared.directory_binding_digest
            library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='bootstrap-original-library',schema_version=13)
            blobs=SQLiteBlobStore(library);consumer=AgentExecutionConsumer(source,blobs)
            raw=canonical_bytes({'sessionId':started.session_id,'prompt':[]})
            class Cut:
                calls=0
                @contextmanager
                def guard_write(self,binding,invocation):
                    assert invocation is case.fixture.invocation and binding.agent_operation_ref==prepared.agent_operation_ref
                    self.calls+=1;yield
            cut=Cut()
            with consumer.prepared_dispatch(started.instance_ref.projection(),raw,request_id='prompt',
                    engineering_attempt_ref='external-attempt',send_invocation=case.fixture.invocation,
                    read_invocation=case.fixture.invocation) as prepared:
                result=await case.manager.send_prompt('prompt',started.instance_ref,case.fixture.invocation,prompt=source.freeze_prompt(started.instance_ref,raw),interaction_service=source,engineering_attempt_ref='external-attempt',write_guard=cut,deadline=asyncio.get_running_loop().time()+2)
                assert result.state=='completed' and cut.calls==1
                captured=consumer.capture(prepared,read_invocation=case.fixture.invocation)
                assert blobs.read_verified(captured.blob_ref)==canonical_bytes(result.projection())
            assert source._fresh=={}
            case.authority.send=False
            assert await case.manager.start(case.request,case.endpoint,case.fixture.invocation)==started
            assert case.manager.get('start',case.fixture.invocation)==started
            assert case.fixture.retained_use_count==1
            case.authority.read=False
            with pytest.raises(ManagerRefused,match='READ_NOT_AUTHORIZED'):case.manager.get('start',case.fixture.invocation)
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


def test_invalid_bootstrap_native_version_is_unknown_and_never_relaunched(tmp_path):
    async def scenario():
        case=await setup(tmp_path,PEER.replace("result={'protocolVersion':1,","result={'protocolVersion':True,"))
        try:
            first=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert first.state=='unknown' and first.instance_ref is None and first.session_id is None
            assert await case.manager.start(case.request,case.endpoint,case.fixture.invocation)==first
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='bootstrap-frame'").fetchone()[0]==1
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='instance-binding'").fetchone()[0]==0
            assert case.records._db.execute("SELECT status FROM operations WHERE operation='protocol-session'").fetchone()[0]=='unknown'
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('change',[
    ("result={'protocolVersion':1,","result={'protocolVersion':'1',"),
    ("result={'sessionId':session,","result={'sessionId':'',"),
    ("'id':request['id'],'result':result","'id':'wrong-response','result':result"),
    ("'id':request['id'],'result':result","'id':request['id'],'error':{'code':-32001,'message':'controlled refusal'}"),
])
def test_bad_bootstrap_original_response_never_publishes_or_resends(tmp_path,change):
    async def scenario():
        case=await setup(tmp_path,PEER.replace(*change))
        try:
            first=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert first.state=='unknown' and first.instance_ref is None
            count=case.records._db.execute("SELECT count(*) FROM operations WHERE operation='bootstrap-frame'").fetchone()[0]
            assert await case.manager.start(case.request,case.endpoint,case.fixture.invocation)==first
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='bootstrap-frame'").fetchone()[0]==count
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='instance-binding'").fetchone()[0]==0
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


def test_lifecycle_write_revoked_at_actual_second_phase_cut_sends_no_second_frame(tmp_path):
    async def scenario():
        case=await setup(tmp_path)
        try:
            checked=case.authority.check_lifecycle_write
            def revoke_at_writer(invocation,binding):
                if binding.phase=='session/new' and case.authority.writes.count('session/new')==1:
                    case.authority.send=False
                checked(invocation,binding)
            case.authority.check_lifecycle_write=revoke_at_writer
            first=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert first.state=='unknown' and first.instance_ref is None
            rows=case.records._db.execute("SELECT payload FROM operations WHERE operation='bootstrap-frame'").fetchall()
            assert len(rows)==2
            new=[json.loads(row[0]) for row in rows if json.loads(row[0])['binding']['phase']=='session/new'][0]
            assert 'observation' not in new
            # Original environment physical effect child confirms the second
            # frame never passed its synchronous writer guard.
            with case.fixture._manager.store.transaction() as db:
                child=db.execute("SELECT result FROM environment_use_requests WHERE request_id=? AND action='send-frame'",(new['binding']['endpointRequestId'],)).fetchone()
            physical=json.loads(child[0])
            assert physical['delivery']=='not_sent' and physical['bytesObserved']==0
            assert case.authority.writes.count('session/new')==1
            assert await case.manager.start(case.request,case.endpoint,case.fixture.invocation)==first
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


def test_cancel_during_session_new_stays_unknown_on_original_cold_replay(tmp_path):
    async def scenario():
        # Real child remains alive on input but deliberately provides no phase2
        # reply. Test cancellation never terminates someone else's process.
        peer=PEER.replace("result={'sessionId':session,'_meta':{'cwd':os.getcwd()}}","continue")
        case=await setup(tmp_path,peer)
        task=None
        try:
            async def start():
                case.authority.task=asyncio.current_task()
                return await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            task=asyncio.create_task(start())
            async def await_phase():
                while True:
                    rows=case.records._db.execute("SELECT status,payload FROM operations WHERE operation='bootstrap-frame'").fetchall()
                    if any(row[0]=='possibly-written' and json.loads(row[1])['binding']['phase']=='session/new' for row in rows):return
                    await asyncio.sleep(0)
            await asyncio.wait_for(await_phase(),2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            case.authority.task=asyncio.current_task()
            cold=Records(tmp_path/'agent.sqlite')
            case.manager.records=cold
            receipt=case.manager.get('start',case.fixture.invocation)
            assert receipt.state=='unknown' and receipt.instance_ref is None
            assert await case.manager.start(case.request,case.endpoint,case.fixture.invocation)==receipt
            assert cold._db.execute("SELECT count(*) FROM operations WHERE operation='bootstrap-frame'").fetchone()[0]==2
            assert cold._db.execute("SELECT status FROM operations WHERE operation='protocol-session'").fetchone()[0]=='unknown'
            assert case.fixture.retained_use_count==1
        finally:
            if task is not None and not task.done():
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
            case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('field,value',[
    ('sessionId','foreign-nonempty-session'),('protocolId',None),('sourceStartRequestKey','foreign-start'),
    ('removeSource',None),('originalReply','foreign-native-session'),('startState','unknown'),('startInstance','foreign-instance'),
])
def test_cold_original_binding_session_origin_tamper_refuses(tmp_path,field,value):
    async def scenario():
        case=await setup(tmp_path)
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running'
            row=case.records._db.execute("SELECT request_id,payload FROM operations WHERE operation='instance-binding'").fetchone()
            payload=json.loads(row[1])
            if field in ('startState','startInstance'):
                start=case.records._db.execute("SELECT request_id,payload FROM operations WHERE operation='agent-start'").fetchone()
                changed=json.loads(start[1])
                changed['agentStartReceipt']['state' if field=='startState' else 'instanceId']=value
                case.records._db.execute("UPDATE operations SET payload=? WHERE operation='agent-start' AND request_id=?",(json.dumps(changed),start[0]))
            elif field=='originalReply':
                phase=case.records._db.execute("SELECT request_id,payload FROM operations WHERE operation='bootstrap-frame' AND request_id=?",(started.operation_ref+'/session/new',)).fetchone()
                changed=json.loads(phase[1])
                for frame in changed['observation']['protocol']['frames']:
                    if 'result' in frame:frame['result']['sessionId']=value
                case.records._db.execute('UPDATE operations SET payload=? WHERE request_id=? AND operation=?',(json.dumps(changed),phase[0],'bootstrap-frame'))
            else:
                if field=='removeSource':payload.pop('sourceStartRequestKey')
                else:payload[field]=value
                case.records._db.execute('UPDATE operations SET payload=? WHERE request_id=? AND operation=?',(json.dumps(payload),row[0],'instance-binding'))
            case.manager.records=Records(tmp_path/'agent.sqlite')
            source=InteractionService(case.manager.records,case.authority,case.fixture.resolver)
            with pytest.raises(InteractionsRefused,match='PROVENANCE_UNAVAILABLE'):
                source.read_binding(started.instance_ref,invocation=case.fixture.invocation)
            with pytest.raises(ManagerRefused,match='INSTANCE_ORIGIN_CORRUPT|RECORD_CORRUPT'):
                case.manager.get('start',case.fixture.invocation)
            assert case.manager.records._db.execute("SELECT count(*) FROM operations WHERE operation='bootstrap-frame'").fetchone()[0]==2
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol',['copilot-cli-jsonrpc/3',None])
def test_unsupported_protocol_or_none_mode_mismatch_refuses_before_any_launch(tmp_path,protocol):
    from dataclasses import replace
    async def scenario():
        case=await setup(tmp_path)
        try:
            actual=case.manager.harness_resolver.resolve(PIN)
            unsupported=SimpleNamespace(descriptor=replace(actual.descriptor,protocol_id=protocol))
            case.manager.harness_resolver=SimpleNamespace(resolve=lambda _:unsupported)
            with pytest.raises(ManagerRefused,match='PROTOCOL_UNSUPPORTED|SESSION_MODE_UNSUPPORTED'):
                await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='agent-start'").fetchone()[0]==0
            assert case.fixture._manager._owned_process_handles=={}
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
