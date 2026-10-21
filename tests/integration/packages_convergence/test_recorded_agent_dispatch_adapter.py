"""Actual source/preclaim/capability refusal of the replacement adapter.

Does not replace original business grant tests, which still require yaml.
"""
import asyncio
from types import SimpleNamespace
import pytest
from test_agent_guarded_bootstrap import setup
from ordessa_agents.sdk.interactions import InteractionService,InteractionsRefused
from ordessa_agents.sdk.endpoint import BoundEndpoint
from ordessa_engineering.adapters.native_records.agent_recorded_dispatch import RecordedDispatchExecution
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError


@pytest.mark.parametrize('port_missing',[False,True])
def test_replacement_adapter_preclaim_abort_and_missing_guard_refuse_before_business_debit(tmp_path,port_missing):
    async def scenario():
        case=await setup(tmp_path)
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running'
            resolver=case.fixture.resolver
            if port_missing:
                original=resolver
                class NoGuardPort:
                    async def resolve(self,ref,invocation):
                        bound=await original.resolve(ref,invocation)
                        return BoundEndpoint(bound.ref,bound.descriptor,communicate=SimpleNamespace(receive=bound.communicate.receive))
                resolver=NoGuardPort()
            source=InteractionService(case.records,case.authority,resolver)
            library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='adapter-original',schema_version=13)
            blobs=SQLiteBlobStore(library);context=object()
            def invocation(actual,agent):
                assert actual is context and agent==started.instance_ref.projection()
                return case.fixture.invocation
            execution=RecordedDispatchExecution(source,blobs,send_invocation_resolver=invocation,
                read_invocation_resolver=invocation,query_factory=lambda binding:case.fixture.invocation,endpoint_resolver=resolver)
            params={'sessionId':started.session_id,'prompt':[]}
            class BusinessAbort(Exception):pass
            async def prepare():
                async with execution.prepared_dispatch(context,started.instance_ref.projection(),params,
                        request_id='original-request',engineering_attempt_ref='attempt') as flow:
                    assert not port_missing and flow.context is context
                    assert flow.prepared.agent_ref_bytes
                    raise BusinessAbort()
            with pytest.raises(ApplicationError if port_missing else BusinessAbort):await prepare()
            assert source._fresh=={}
            # Source-owned reservation remains cold history and cannot resend.
            raw,digest=execution.freeze_input(started.instance_ref.projection(),params)
            replay=source.reserve_turn(started.instance_ref,source.freeze_prompt(started.instance_ref,raw),
                request_id='original-request',engineering_attempt_ref='attempt',invocation=case.fixture.invocation)
            assert replay.state=='unknown' and replay.endpoint_operation_ref is None
            assert library._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==0
            assert library._connection.execute('SELECT count(*) FROM step_log').fetchone()[0]==0
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==1
            assert case.fixture.retained_use_count==1
        finally:case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
