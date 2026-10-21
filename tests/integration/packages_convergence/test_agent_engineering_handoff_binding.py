"""Original Agent origin/binding checks before ANY Engineering handoff.

Controlled real Profile/peer/Records/BlobStore; these are source-integrity
checks, NOT a full business approval/UoW positive (yaml remains absent).
"""
import asyncio,hashlib
from contextlib import contextmanager
from dataclasses import fields,replace
from pathlib import Path
import pytest
from test_agent_guarded_bootstrap import setup
from ordessa_engineering.adapters.native_records.agent_execution import AgentExecutionConsumer
from ordessa_engineering.adapters.native_records.agent_effect_write import EngineeringAgentEffectHandoff
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.changes.agent_dispatch import AgentDispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_agents.sdk.interactions import InteractionService,InteractionsRefused
from ordessa_infrastructure.encoding import canonical_bytes


@pytest.mark.parametrize('failure',['business-abort','cancel','postclaim-read-refused','normal-exit'])
def test_prepared_dispatch_end_drops_original_send_flow_before_handoff(tmp_path,failure):
    async def scenario():
        case=await setup(tmp_path)
        try:
            start=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert start.state=='running'
            source=InteractionService(case.records,case.authority,case.fixture.resolver)
            library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='abort-cut-test',schema_version=13)
            blobs=SQLiteBlobStore(library);consumer=AgentExecutionConsumer(source,blobs)
            raw=canonical_bytes({'sessionId':start.session_id,'prompt':[]})
            if failure=='postclaim-read-refused':
                reserve=source.reserve_turn
                def revoke_after_claim(*a,**k):
                    result=reserve(*a,**k);case.authority.read=False;return result
                source.reserve_turn=revoke_after_claim
            class BusinessAbort(Exception):pass
            expected={'business-abort':BusinessAbort,'cancel':asyncio.CancelledError,
                      'postclaim-read-refused':InteractionsRefused}.get(failure)
            entered=asyncio.Event()
            async def prepare_and_abort():
                with consumer.prepared_dispatch(start.instance_ref.projection(),raw,request_id='original',
                        engineering_attempt_ref='attempt',send_invocation=case.fixture.invocation,
                        read_invocation=case.fixture.invocation) as prepared:
                    assert prepared.session_id==start.session_id
                    entered.set()
                    if failure=='cancel':await asyncio.Future()
                    if expected is not None:raise expected('original business flow ended')
            if failure=='cancel':
                pending=asyncio.create_task(prepare_and_abort())
                try:
                    await asyncio.wait_for(entered.wait(),2)
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):await pending
                finally:
                    pending.cancel()
                    await asyncio.gather(pending,return_exceptions=True)
            elif expected is None:await prepare_and_abort()
            else:
                with pytest.raises(expected):await prepare_and_abort()
            if failure=='postclaim-read-refused':source.reserve_turn=reserve
            case.authority.read=True
            prompt=source.freeze_prompt(start.instance_ref,raw)
            # No fresh send can be reconstructed from the durable reservation.
            replay=source.reserve_turn(start.instance_ref,prompt,request_id='original',engineering_attempt_ref='attempt',invocation=case.fixture.invocation)
            assert replay.state=='unknown' and replay.endpoint_operation_ref is None
            class NoPhysicalWrite:
                @contextmanager
                def guard_write(self,*a,**k):raise AssertionError('aborted business flow sent bytes');yield
            result=await source.prompt_recorded(start.instance_ref,prompt,request_id='original',
                engineering_attempt_ref='attempt',invocation=case.fixture.invocation,
                write_guard=NoPhysicalWrite(),deadline=asyncio.get_running_loop().time()+2)
            assert result==replay and source._fresh=={}
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==1
            assert case.records.turn(result.turn_ref.turn_id).status=='reserved'
            assert library._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==0
            assert library._connection.execute('SELECT count(*) FROM step_log').fetchone()[0]==0
            assert case.fixture.retained_use_count==1
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())

class NoBusinessAdmission:
    """Any attempted business authority use fails: source validation only."""
    def require(self,*a,**k):raise AssertionError('not a business grant test')
    def handoff_effect_write(self,*a,**k):raise AssertionError('no handoff may be issued')
    def consume_effect_write(self,*a,**k):raise AssertionError('no handoff may be consumed')


# This fixture is the frozen V1 historical input from a23, not a current Work
# dispatch projection. Current binding_version/work/subject remain UNMAPPED;
# these tests do not qualify that newer recipe or its business write checks.
FROZEN_V1_FIELDS = frozenset((
    'scope', 'run_id', 'step_id', 'attempt', 'fence', 'package_ref', 'approval_ref',
    'intent_digest', 'control_version', 'action_instances', 'unit_ref_bytes',
    'execution_operation_ref', 'prompt_ref', 'prompt_input_digest',
    'expected_query_digest', 'required_results', 'digest',
))



def test_original_turn_query_cannot_be_retargeted_by_constructible_prepared_facts(tmp_path):
    async def scenario():
        case=await setup(tmp_path)
        try:
            start=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert start.state=='running'
            source=InteractionService(case.records,case.authority,case.fixture.resolver)
            library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='binding-cut-test',schema_version=13)
            blobs=SQLiteBlobStore(library);consumer=AgentExecutionConsumer(source,blobs)
            raw=canonical_bytes({'sessionId':start.session_id,'prompt':[]})
            prepared=consumer.claim_and_prepare(start.instance_ref.projection(),raw,request_id='original',engineering_attempt_ref='attempt',send_invocation=case.fixture.invocation,read_invocation=case.fixture.invocation)
            old=decode_dispatch((Path(__file__).parents[3]/'packages/engineering/tests/domain/fixtures/dispatch-v1-baseline.json').read_bytes())
            prompt=blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
            values={f.name:getattr(old,f.name) for f in fields(old) if f.name in FROZEN_V1_FIELDS and f.init and f.name not in ('unit_ref_bytes','execution_operation_ref')}
            binding=AgentDispatchBinding(**{**values,'agent_ref_bytes':prepared.agent_ref_bytes,'turn_ref_bytes':prepared.turn_ref_bytes,'engineering_attempt_ref':'attempt',
                'prompt_ref':prompt,'prompt_input_digest':Digest('sha256',prepared.prompt_input_digest[7:]),'expected_query_digest':prepared.query_digest})
            dispatch=ImplementationDispatch(SQLiteUoWFactory(library),NoBusinessAdmission(),blobs=blobs)
            bridge=EngineeringAgentEffectHandoff(dispatch,consumer)
            bridge._validate(binding,prepared,read_invocation=case.fixture.invocation)
            other=source.reserve_turn(start.instance_ref,source.freeze_prompt(start.instance_ref,raw),request_id='other',engineering_attempt_ref='attempt',invocation=case.fixture.invocation)
            forged=replace(prepared,turn_ref_bytes=canonical_bytes(other.turn_ref.projection()),agent_operation_ref=other.agent_operation_ref)
            with pytest.raises(ApplicationError,match='DISPATCH_EFFECT_BINDING_MISMATCH'):
                bridge._validate(binding,forged,read_invocation=case.fixture.invocation)
            with pytest.raises(ApplicationError,match='AGENT_RECEIPT_BINDING_MISMATCH'):
                bridge._validate(binding,replace(prepared,agent_operation_ref='forged-operation'),read_invocation=case.fixture.invocation)
            # Exercise the actual public handoff entrypoint: validation refuses
            # BEFORE NoBusinessAdmission is touched, and ends the fresh flow.
            with pytest.raises(ApplicationError,match='DISPATCH_EFFECT_BINDING_MISMATCH'):
                with bridge.guard_effect_handoff(None,binding,forged,send_invocation=case.fixture.invocation,
                        read_invocation=case.fixture.invocation):
                    raise AssertionError('invalid source entered business handoff')
            assert source._fresh=={}
            assert source.query_turn(source.turn_query(other.turn_ref,prepared.prompt_input_digest),
                invocation=case.fixture.invocation).state=='unknown'
            case.authority.read=False
            with pytest.raises(InteractionsRefused,match='READ_NOT_AUTHORIZED'):
                bridge._validate(binding,prepared,read_invocation=case.fixture.invocation)
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==2
            assert library._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==0
            assert library._connection.execute('SELECT count(*) FROM step_log').fetchone()[0]==0
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
