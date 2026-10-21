"""F2 original SQLite + Agent Records close/reopen in an independent process.

Real controlled Profile/provider/native session; original lower repositories,
not a full business approval UoW qualification. No model, fake session or app map.
"""
import asyncio,hashlib,json,subprocess,sys
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
import pytest
from test_agent_guarded_bootstrap import setup
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_agents.sdk.interactions import InteractionService
from ordessa_engineering.adapters.native_records.agent_execution import AgentExecutionConsumer
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import _RepositoryAccess
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import SQLiteDispatchRepository
from ordessa_engineering.adapters.persistence.sqlite.agent_dispatch_bindings import AgentDispatchBindings
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.domain.changes.agent_dispatch import AgentDispatchBinding
from ordessa_engineering.domain.common.models.values import Digest

ROOT=Path(__file__).parents[3]
CHILD=r'''
import asyncio,hashlib,json,sys
from dataclasses import replace
from pathlib import Path
from ordessa_infrastructure.encoding import canonical_bytes,decode_json
from ordessa_agents.public import Records
from ordessa_agents.sdk.interactions import InteractionService,InteractionsRefused,TurnRef
from ordessa_agents.sdk.instances import AgentInstanceRef
from ordessa_engineering.adapters.native_records.agent_execution import AgentExecutionConsumer
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import _RepositoryAccess
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import SQLiteDispatchRepository
from ordessa_engineering.adapters.persistence.sqlite.agent_dispatch_bindings import AgentDispatchBindings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.changes.agent_dispatch_codec import decode_agent_dispatch,encode_agent_dispatch

class ReadAuthority:
    def __init__(self):self.invocation=object();self.subject='principal:existing-test-caller'
    def principal_scope(self,value):
        if value is not self.invocation:raise InteractionsRefused('FORGED_INVOCATION')
        return self.subject
    def check_read_binding(self,value,ref):self.principal_scope(value)
    def check_read_turn(self,value,query):self.principal_scope(value)
    def check_send(self,*args):raise AssertionError('cold query checked send authority')
class NoEndpoints:
    async def resolve(self,*args):raise AssertionError('cold query resolved a physical endpoint')

library=EngineeringLibrary.open(Path(sys.argv[1]),library_id='f2-original-library')
records=Records(Path(sys.argv[2]));auth=ReadAuthority()
source=InteractionService(records,auth,NoEndpoints())
def no_reserve(*a,**k):raise AssertionError('cold query reconstructed a reservation')
source.reserve_turn=no_reserve
blobs=SQLiteBlobStore(library);consumer=AgentExecutionConsumer(source,blobs)
scope=Scope('realm','project')
with library.transaction() as connection:
    repo=SQLiteDispatchRepository(_RepositoryAccess(connection,scope,'read',library.library_id))
    row,binding=AgentDispatchBindings(repo).read('run','step',1,scope)
    original_bytes=row['binding_bytes']
ref,captured=consumer.capture_dispatch(binding,read_invocation=auth.invocation)
assert captured.state==sys.argv[3] and source._fresh=={}
assert ref.turn_ref_bytes==binding.turn_ref_bytes and ref.query_digest==binding.expected_query_digest
assert ref.operation_ref!=binding.engineering_attempt_ref
assert blobs.read_verified(ref.captured_observation_ref)==canonical_bytes(source.query_turn(
    source.turn_query(TurnRef.decode(
        decode_json(binding.turn_ref_bytes)),'sha256:'+binding.prompt_input_digest.hex),invocation=auth.invocation).projection())

def refused(value,code=None):
    try:consumer.capture_dispatch(value,read_invocation=auth.invocation)
    except (ApplicationError,InteractionsRefused) as exc:
        if code:assert str(exc)==code or getattr(exc,'code',None)==code,str(exc)
    else:raise AssertionError('foreign/missing original binding admitted')

def query_digest(turn,prompt):
    return 'sha256:'+hashlib.sha256(canonical_bytes({'schemaVersion':'agent-turn-query/1',
        'turnRef':turn,'expectedInputDigest':'sha256:'+prompt.hex})).hexdigest()
turn=decode_json(binding.turn_ref_bytes);turn['turnId']='foreign-original-turn'
refused(replace(binding,turn_ref_bytes=canonical_bytes(turn),expected_query_digest=query_digest(turn,binding.prompt_input_digest)))
turn=decode_json(binding.turn_ref_bytes);other=Digest('sha256','f'*64)
refused(replace(binding,prompt_input_digest=other,expected_query_digest=query_digest(turn,other)))
refused(replace(binding,turn_ref_bytes=None),'AGENT_DISPATCH_TURN_REFERENCE_UNAVAILABLE')
auth.subject='principal:foreign';refused(binding,'PROVENANCE_UNAVAILABLE');auth.subject='principal:existing-test-caller'
prompt=source.freeze_prompt(AgentInstanceRef.decode(decode_json(binding.agent_ref_bytes)),blobs.read_verified(binding.prompt_ref))
replay=asyncio.run(source.prompt_recorded(prompt.instance_ref,prompt,request_id='prompt',
    engineering_attempt_ref=binding.engineering_attempt_ref,invocation=auth.invocation,write_guard=None,deadline=None))
assert replay.state==sys.argv[3] and source._fresh=={}
with library.transaction() as connection:
    repo=SQLiteDispatchRepository(_RepositoryAccess(connection,scope,'read',library.library_id))
    assert repo.get('run','step',1,scope)['binding_bytes']==original_bytes
assert records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==1
print(json.dumps({'state':captured.state,'turnId':turn['turnId'],'agentOperationRef':ref.operation_ref,
    'engineeringAttemptRef':binding.engineering_attempt_ref,'freshAssociations':len(source._fresh),
    'negativeCases':['wrong-turn','wrong-input','missing-turn','foreign-principal'],'sendCount':0}))
records._db.close();library.close()
'''


@pytest.mark.parametrize('send,state',[(True,'completed'),(False,'unknown')])
def test_f2_actual_original_binding_cold_process_query_never_restores_send(tmp_path,send,state):
    async def scenario():
        case=await setup(tmp_path)
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running'
            source=InteractionService(case.records,case.authority,case.fixture.resolver)
            path=tmp_path/'engineering.sqlite'
            library=EngineeringLibrary.create(path.resolve(),library_id='f2-original-library',schema_version=13)
            blobs=SQLiteBlobStore(library);consumer=AgentExecutionConsumer(source,blobs)
            raw=canonical_bytes({'sessionId':started.session_id,'prompt':[]})
            with consumer.prepared_dispatch(started.instance_ref.projection(),raw,request_id='prompt',
                    engineering_attempt_ref='engineering-attempt',send_invocation=case.fixture.invocation,
                    read_invocation=case.fixture.invocation) as prepared:
                old=decode_dispatch((ROOT/'packages/engineering/tests/domain/fixtures/dispatch-v1-baseline.json').read_bytes())
                values={f.name:getattr(old,f.name) for f in fields(old) if f.init and f.name not in ('unit_ref_bytes','execution_operation_ref')}
                prompt=blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
                binding=AgentDispatchBinding(**{**values,'agent_ref_bytes':prepared.agent_ref_bytes,
                    'turn_ref_bytes':prepared.turn_ref_bytes,'engineering_attempt_ref':'engineering-attempt',
                    'prompt_ref':prompt,'prompt_input_digest':Digest('sha256',prepared.prompt_input_digest[7:]),
                    'expected_query_digest':prepared.query_digest})
                with library.transaction() as connection:
                    connection.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)',('run','{}','{}','{}','running',0,None,'now','now'))
                    repo=SQLiteDispatchRepository(_RepositoryAccess(connection,binding.scope,'write',library.library_id))
                    AgentDispatchBindings(repo).reserve(binding)
                if send:
                    class Cut:
                        @contextmanager
                        def guard_write(self,write,invocation):
                            assert write.turn_ref.projection()==json.loads(binding.turn_ref_bytes)
                            assert invocation is case.fixture.invocation
                            yield
                    result=await case.manager.send_prompt('prompt',started.instance_ref,case.fixture.invocation,
                        prompt=source.freeze_prompt(started.instance_ref,raw),interaction_service=source,
                        engineering_attempt_ref='engineering-attempt',write_guard=Cut(),deadline=asyncio.get_running_loop().time()+2)
                    assert result.state=='completed'
            assert source._fresh=={}
            original_rows=case.records._db.execute('SELECT count(*) FROM operations').fetchone()[0]
            library.close();case.records._db.close()
            roots=[ROOT/'packages/engineering/src',ROOT/'packages/execution/agents/src']
            done=subprocess.run([sys.executable,'-c',CHILD,str(path),str(tmp_path/'agent.sqlite'),state],
                cwd=tmp_path,env={'PYTHONPATH':':'.join(map(str,roots)),'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'},
                text=True,capture_output=True,timeout=20)
            assert done.returncode==0,done.stdout+done.stderr
            facts=json.loads(done.stdout);assert facts['state']==state and facts['sendCount']==0
            from ordessa_agents.public import Records
            reopened=Records(tmp_path/'agent.sqlite')
            assert reopened._db.execute('SELECT count(*) FROM operations').fetchone()[0]==original_rows
            reopened._db.close()
            assert case.fixture.retained_use_count==1
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
