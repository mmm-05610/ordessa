"""Original Agent + real local pipes + retained native configuration receiver.

Controlled Node peer (not a model or real brand binary). Original shared JS
receiver actually reserves, invokes a controlled setter and independently reads.
InstanceAccessAuthority issues only explicit project-scoped native/read grants.
"""
import asyncio,hashlib,json,os,shutil,subprocess,sys,threading,time
from pathlib import Path
from dataclasses import replace
import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_agents.public import Records,InteractionService
from ordessa_agents.sdk.native_contracts import METHODS,FrozenNativeRequest,NativeOperationRef,NativeOperationReceipt
from ordessa_agents.sdk.interactions import InteractionsRefused
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.agent_bindings.native_access import OriginalNativeAccess,NATIVE_READ,NATIVE_CAPABILITIES
from test_agent_guarded_bootstrap import setup

ROOT=Path(__file__).parents[3]
OPTIONS=[{'id':'model','type':'select','currentValue':'m1','options':[{'value':x} for x in ('m1','m2','m3','cancel','throw','ack')]}]
PEER=r'''import fs from 'node:fs';import readline from 'node:readline';
import {configurationOperations} from MODULE;
const session='native-session',generation='generation-1';let options=OPTIONS;
const agent={live:new Map([[session,{}]])};
const read=({sessionId})=>{if(sessionId!==session)throw Error('session');return {sessionId:session,generation,busy:false,configOptions:structuredClone(options)}};
const operations=configurationOperations({agent,read,invalidParams:m=>Error(m),configIds:['model','thinkingLevel'],
 evidencePrefix:'controlled-native-operation',assertIdle:()=>{},setOption:async p=>{
   options[0].currentValue=p.value;fs.appendFileSync('native-effects.log',p.value+'\n');
   if(p.value==='cancel')await new Promise(r=>setTimeout(r,2000));
   if(p.value==='throw')throw Error('controlled lost upstream reply');
 }});
for await (const line of readline.createInterface({input:process.stdin})){
 const q=JSON.parse(line);let result;
 try{
  if(q.method==='initialize')result={protocolVersion:1,agentCapabilities:{}};
  else if(q.method==='session/new')result={sessionId:session};
  else if(q.method==='_ordessa/session/configuration/apply')result=q.params.value==='ack'?{}:await operations.apply(q.params);
  else if(q.method==='_ordessa/session/configuration/operation')result=operations.query(q.params);
  else throw Error('unknown native method');
  console.log(JSON.stringify({jsonrpc:'2.0',id:q.id,result}));
 }catch(error){console.log(JSON.stringify({jsonrpc:'2.0',id:q.id,error:{code:-32602,message:error.message}}));}
}
'''


async def native_case(tmp_path,*,grants=True):
    module=(ROOT/'packages/execution/agents/src/ordessa_agents/harness/configuration/acp/operation.mjs').as_uri()
    peer=PEER.replace('MODULE',json.dumps(module)).replace('OPTIONS',json.dumps(OPTIONS))
    case=await setup(tmp_path,peer,runner=(shutil.which('node'),),peer_name='peer.mjs')
    started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
    assert started.state=='running'
    scope=Scope('fixture-realm','fixture-project')
    caps=(NATIVE_READ,*NATIVE_CAPABILITIES.values()) if grants else ()
    issuer=InstanceAccessAuthority(lambda:'synthetic-native-token',principal_id='existing-test-caller',
        grants=(AccessGrant(scope,caps),) if caps else (),legacy_principal=None)
    caller=[issuer.authenticate('Bearer synthetic-native-token')]
    def original(invocation):
        if invocation is not case.fixture.invocation:raise InteractionsRefused('FORGED_INVOCATION')
        return caller[0]
    def mapped(instance):
        if instance!=started.instance_ref:raise InteractionsRefused('NATIVE_PROJECT_MAPPING_UNAVAILABLE')
        return scope
    access=OriginalNativeAccess(case.authority,issuer,caller_resolver=original,scope_for_agent=mapped,
        principal_scope_for_caller=lambda p:'principal:'+p.principal_id)
    case.native=InteractionService(case.records,access,case.fixture.resolver)
    case.native_access=access;case.issuer=issuer;case.caller=caller;case.scope=scope;case.started=started
    case.effects=Path(case.prepared.native_working_directory)/'native-effects.log'
    return case


def request(case,*,value='m2',purpose='apply',native_id='native-protocol-1',before=None):
    params={'sessionId':case.started.session_id,'operationId':native_id}
    if purpose=='apply':params.update(expectedGeneration='generation-1',configId='model',value=value,
        expectedConfigDigest=before or hashlib.sha256(canonical_bytes(OPTIONS)).hexdigest())
    return case.native.freeze_native_request(case.started.instance_ref,purpose=purpose,method=METHODS[purpose],params_bytes=canonical_bytes(params))


async def close(case):
    case.records.close();case.owner.close();await case.fixture.cleanup()


def test_original_live_apply_query_finite_grants_and_native_readback(tmp_path):
    async def scenario():
        case=await native_case(tmp_path)
        try:
            assert case.native.records is case.manager.records
            assert {r[0] for r in case.records._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}=={'operations'}
            frozen=request(case)
            result=await case.native.native_recorded(frozen,request_id='apply1',invocation=case.fixture.invocation,
                write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+2)
            assert result.state=='completed',result.projection()
            assert case.effects.read_text()=='m2\n'
            assert result.endpoint_operation_ref and result.endpoint_operation_ref!=result.binding.operation_ref.agent_operation_ref
            assert NativeOperationReceipt.decode(result.projection())==result
            query=request(case,purpose='query')
            observed=await case.native.native_recorded(query,request_id='upstream-query',invocation=case.fixture.invocation,
                write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+2)
            assert observed.state=='completed' and case.effects.read_text()=='m2\n'
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='native-operation'").fetchone()==(2,)
            # Original issuer replaces actual grants; refresh same original caller.
            case.issuer.replace_grants((AccessGrant(case.scope,(NATIVE_READ,)),))
            case.caller[0]=case.issuer.authenticate('Bearer synthetic-native-token')
            before=case.records._db.total_changes
            assert case.native.native_query(result.binding.operation_ref,frozen.input_digest,invocation=case.fixture.invocation)==result
            assert await case.native.native_recorded(frozen,request_id='apply1',invocation=case.fixture.invocation,
                write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+1)==result
            assert case.records._db.total_changes==before
            with pytest.raises(InteractionsRefused,match='REQUEST_CONFLICT'):
                await case.native.native_recorded(request(case,value='m3'),request_id='apply1',invocation=case.fixture.invocation,
                    write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+1)
            with pytest.raises(InteractionsRefused,match='ACCESS_DENIED'):
                await case.native.native_recorded(request(case,purpose='query'),request_id='new-query-with-cold-read-only',invocation=case.fixture.invocation,
                    write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+1)
            assert case.effects.read_text()=='m2\n' and case.fixture.retained_use_count==1
        finally:await close(case)
    asyncio.run(scenario())


def test_no_default_grants_refuses_before_parent_or_child_write(tmp_path):
    async def scenario():
        case=await native_case(tmp_path,grants=False)
        try:
            before=case.fixture._manager.store._connection.total_changes if hasattr(case.fixture._manager.store,'_connection') else None
            with pytest.raises(InteractionsRefused,match='ACCESS_DENIED'):
                await case.native.native_recorded(request(case),request_id='denied',invocation=case.fixture.invocation,
                    write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+1)
            assert not case.effects.exists()
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='native-operation'").fetchone()==(0,)
        finally:await close(case)
    asyncio.run(scenario())


@pytest.mark.parametrize('value,state',[('m2','failed'),('ack','unknown'),('throw','unknown')])
def test_native_refusal_missing_receipt_and_throw_never_fake_success(tmp_path,value,state):
    async def scenario():
        case=await native_case(tmp_path)
        try:
            frozen=request(case,value=value,before='0'*64 if state=='failed' else None)
            result=await case.native.native_recorded(frozen,request_id='native-outcome',invocation=case.fixture.invocation,
                write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+2)
            assert result.state==state,result.projection()
            assert case.effects.exists() is (value=='throw')
            assert await case.native.native_recorded(frozen,request_id='native-outcome',invocation=case.fixture.invocation,
                write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+1)==result
        finally:await close(case)
    asyncio.run(scenario())


def test_cancel_after_actual_write_keeps_unknown_replay_and_no_lock_across_wait(tmp_path):
    from test_original_access_handoff import other_thread
    async def scenario():
        case=await native_case(tmp_path)
        try:
            frozen=request(case,value='cancel')
            task=asyncio.create_task(case.native.native_recorded(frozen,request_id='cancel-after-write',
                invocation=case.fixture.invocation,write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+5))
            deadline=asyncio.get_running_loop().time()+2
            while not case.effects.exists() and asyncio.get_running_loop().time()<deadline:await asyncio.sleep(.005)
            assert case.effects.read_text()=='cancel\n'
            await other_thread(lambda:case.issuer.verify(case.caller[0]))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            row=case.records._db.execute("SELECT request_id FROM operations WHERE operation='native-operation'").fetchone()
            stored=case.records.operation(row[0],'native-operation')
            ref=NativeOperationReceipt.decode(stored.payload['nativeReceipt']).binding.operation_ref
            before=case.records._db.total_changes
            assert case.native.native_query(ref,frozen.input_digest,invocation=case.fixture.invocation).state=='unknown'
            assert (await case.native.native_recorded(frozen,request_id='cancel-after-write',invocation=case.fixture.invocation,
                write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+1)).state=='unknown'
            assert case.records._db.total_changes==before and case.effects.read_text()=='cancel\n'
            assert case.issuer._guard_depth==0
        finally:await close(case)
    asyncio.run(scenario())


CRASH_CHILD=r'''
import asyncio,os,json,sys
from pathlib import Path
from contextlib import contextmanager
from test_recorded_native_configuration import native_case,request
async def go():
 case=await native_case(Path(sys.argv[1]));frozen=request(case)
 class Crash:
  @contextmanager
  def guard_write(self,binding,invocation):
   with case.native_access.guard_write(binding,invocation):
    Path(sys.argv[2]).write_text(json.dumps({'ref':binding.operation_ref.projection(),'digest':frozen.input_digest,
      'database':case.records.path,'effects':str(case.effects)}))
    yield
   os._exit(23)
 await case.native.native_recorded(frozen,request_id='crash-after-write',invocation=case.fixture.invocation,
   write_guard=Crash(),deadline=asyncio.get_running_loop().time()+3)
 raise AssertionError('physical cut did not exit')
asyncio.run(go())
'''
READ_CHILD=r'''
import asyncio,json,sys
from pathlib import Path
from ordessa_agents.public import Records,InteractionService
from ordessa_agents.sdk.native_contracts import NativeOperationRef,NativeOperationReceipt
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.agent_bindings.native_access import OriginalNativeAccess,NATIVE_READ
p=json.loads(Path(sys.argv[1]).read_text());ref=NativeOperationRef.decode(p['ref']);invocation=object();scope=Scope('fixture-realm','fixture-project')
authority=InstanceAccessAuthority(lambda:'synthetic-read-token',principal_id='existing-test-caller',grants=(AccessGrant(scope,(NATIVE_READ,)),),legacy_principal=None)
caller=authority.authenticate('Bearer synthetic-read-token')
class Base:
 def principal_scope(self,actual):
  assert actual is invocation
  authority.verify(caller);return 'principal:existing-test-caller'
 def check_send(self,*args):raise AssertionError('send permission queried by cold read')
 def check_read_turn(self,*args):raise AssertionError('wrong turn API')
 def check_read_binding(self,*args):raise AssertionError('cold query tried rebinding')
access=OriginalNativeAccess(Base(),authority,caller_resolver=lambda i:caller if i is invocation else None,
 scope_for_agent=lambda r:scope if r==ref.instance_ref else None,principal_scope_for_caller=lambda c:'principal:'+c.principal_id)
records=Records(p['database']);source=InteractionService(records,access,None)
before=records._db.total_changes;count=records._db.execute('SELECT count(*) FROM operations').fetchone()[0]
result=source.native_query(ref,p['digest'],invocation=invocation)
assert result.state=='unknown' and records._db.total_changes==before
assert records._db.execute('SELECT count(*) FROM operations').fetchone()[0]==count
assert records.operation(ref.request_key,'native-operation').status=='possibly-written'
async def replay():
 r=await source.native_recorded(result.binding.request,request_id='crash-after-write',invocation=invocation,write_guard=access,deadline=asyncio.get_running_loop().time()+1)
 assert r==result
asyncio.run(replay())
assert records._db.total_changes==before
print(json.dumps({'state':result.state,'rows':count,'writes':records._db.total_changes-before}))
records.close()
'''


def test_actual_agent_process_exit_after_writer_cut_and_independent_process_read_only_replay(tmp_path):
    metadata=tmp_path/'original-ref.json'
    child_env=dict(os.environ)
    child_env['PYTHONPATH']=os.pathsep.join(filter(None,(str(Path(__file__).parent),child_env.get('PYTHONPATH',''))))
    crashed=subprocess.run([sys.executable,'-c',CRASH_CHILD,str(tmp_path/'crashed'),str(metadata)],capture_output=True,text=True,timeout=10,env=child_env)
    assert crashed.returncode==23,crashed.stderr
    saved=json.loads(metadata.read_text());effects=Path(saved['effects'])
    deadline=time.monotonic()+2
    while not effects.exists() and time.monotonic()<deadline:time.sleep(.01)
    assert effects.read_text()=='m2\n'
    cold=subprocess.run([sys.executable,'-c',READ_CHILD,str(metadata)],capture_output=True,text=True,timeout=10,env=child_env)
    assert cold.returncode==0,cold.stderr
    assert json.loads(cold.stdout)['writes']==0 and effects.read_text()=='m2\n'


def test_closed_native_schema_and_full_binding_digest_negatives(tmp_path):
    from jsonschema import Draft202012Validator
    from ordessa_agents.sdk.native_schemas import native_contract_schema
    async def scenario():
        case=await native_case(tmp_path)
        try:
            frozen=request(case);validator=Draft202012Validator(native_contract_schema('FrozenNativeRequest'))
            validator.validate(frozen.projection())
            for change in ({'purpose':'arbitrary'},{'method':'session/prompt'},{'inputDigest':'sha256:'+'0'*64},
                    {'sessionId':'foreign'},{'endpointRef':{**frozen.endpoint_ref.projection(),'revision':'foreign'}},
                    {'extra':'not-permitted'}):
                altered={**frozen.projection(),**change}
                with pytest.raises((InteractionsRefused,ValueError)):FrozenNativeRequest.decode(altered)
            for params in ({**json.loads(frozen.params_bytes),'callback':'not allowed'},
                    {**json.loads(frozen.params_bytes),'configId':'arbitrary'},
                    {**json.loads(frozen.params_bytes),'actionManifest':{'extra':'not a manifest'}}):
                with pytest.raises(InteractionsRefused):case.native.freeze_native_request(case.started.instance_ref,
                    purpose='apply',method=METHODS['apply'],params_bytes=canonical_bytes(params))
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='native-operation'").fetchone()==(0,)
        finally:await close(case)
    asyncio.run(scenario())


def test_revocation_between_reservation_and_actual_writer_refuses_bytes(tmp_path):
    from contextlib import contextmanager
    async def scenario():
        case=await native_case(tmp_path)
        try:
            original=case.fixture.resolver
            class RevokeBeforePhysicalGuard:
                async def resolve(self,ref,invocation):
                    bound=await original.resolve(ref,invocation)
                    communicate=bound.communicate
                    class Proxy:
                        async def send_guarded(self,*args,**kwargs):
                            case.issuer.replace_grants((AccessGrant(case.scope,(NATIVE_READ,)),))
                            case.caller[0]=case.issuer.authenticate('Bearer synthetic-native-token')
                            return await communicate.send_guarded(*args,**kwargs)
                        async def receive(self,*args,**kwargs):return await communicate.receive(*args,**kwargs)
                    return replace(bound,communicate=Proxy())
            case.native.endpoint_resolver=RevokeBeforePhysicalGuard()
            frozen=request(case)
            result=await case.native.native_recorded(frozen,request_id='revoked-at-cut',invocation=case.fixture.invocation,
                write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+2)
            assert result.state=='failed' and json.loads(result.observation_bytes)['delivery']=='not_sent'
            assert not case.effects.exists() and case.issuer._guard_depth==0
            stored=case.records.operation(result.binding.operation_ref.request_key,'native-operation')
            assert stored.status=='failed' and stored.payload['nativeReceipt']['revision']==2
        finally:await close(case)
    asyncio.run(scenario())


def test_missing_physical_observation_after_real_write_is_unknown_never_retried(tmp_path):
    async def scenario():
        case=await native_case(tmp_path)
        try:
            resolver=case.fixture.resolver;writes=[]
            class MissingObservation:
                async def resolve(self,ref,invocation):
                    bound=await resolver.resolve(ref,invocation);communicate=bound.communicate
                    class Proxy:
                        async def send_guarded(self,*args,**kwargs):
                            result=await communicate.send_guarded(*args,**kwargs)
                            writes.append(result);return None
                        async def receive(self,*args,**kwargs):raise AssertionError('no physical receipt: cannot claim observed success')
                    return replace(bound,communicate=Proxy())
            case.native.endpoint_resolver=MissingObservation();frozen=request(case)
            observed=await case.native.native_recorded(frozen,request_id='lost-physical-receipt',invocation=case.fixture.invocation,
                write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+2)
            assert observed.state=='unknown' and len(writes)==1
            deadline=asyncio.get_running_loop().time()+2
            while not case.effects.exists() and asyncio.get_running_loop().time()<deadline:await asyncio.sleep(.005)
            assert case.effects.read_text()=='m2\n'
            assert (await case.native.native_recorded(frozen,request_id='lost-physical-receipt',invocation=case.fixture.invocation,
                write_guard=case.native_access,deadline=asyncio.get_running_loop().time()+1)).state=='unknown'
            assert len(writes)==1
        finally:await close(case)
    asyncio.run(scenario())
