"""Original SQLite revoke/debit + original async writer; package/source admissions are explicit fixtures."""
import asyncio
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

import pytest
from test_implementation_dispatch import _setup, _context, UNIT, NOW
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_infrastructure.encoding import canonical_bytes

# Original public Execution owner; qualification selects its frozen dependency site.
from ordessa_environments import ProcessHandle
from ordessa_execution_agents.harness.transport import EffectWriteGuard, ChannelClosed, WriterLeaseRefused
from ordessa_execution_agents.harness.transport.environment_channel import EnvironmentProcessChannel


def prepared(tmp_path,monkeypatch):
    library,factory,service,_,_,grant,package,_=_setup(tmp_path,monkeypatch)
    monkeypatch.setattr('ordessa_engineering.application.usecases.support.clock.utc_now',lambda:NOW)
    params={'sessionId':'fixed-session','prompt':[]};raw=canonical_bytes(params)
    prompt=service.blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
    binding=DispatchBinding(package.scope,'run-1','source_review',1,1,package.ref,grant.ref,grant.intent.digest,
        0,(('edit_repository','effect-action'),),canonical_bytes(UNIT),'effect-operation',prompt,
        Digest('sha256','a'*64),'synthetic-query-digest',('submission',))
    encoded=encode_dispatch(binding)
    with factory.begin(package.scope) as uow:
        uow.authorization.consume_action(grant.ref,action='edit_repository',action_instance_id='effect-action',
            target_digest=binding.digest,now=NOW)
        uow.dispatch.reserve('run-1','source_review',1,package.scope,encoded,
            Digest('sha256',hashlib.sha256(encoded).hexdigest()),'effect-operation')
        uow.dispatch.transition('run-1','source_review',1,package.scope,expected_version=0,fence=1,phase='possibly_written')
        uow.commit()
    return library,factory,service,grant,package,binding,params,_context(package.scope,package.created_by)


def native(binding,params,service,ctx,write):
    process=MagicMock(spec=ProcessHandle)
    process.observe.return_value=SimpleNamespace(state='running')
    process.read_stderr=AsyncMock(return_value=b'')
    process.close_stdin=AsyncMock(return_value=None)
    process.wait_exit=AsyncMock(return_value=SimpleNamespace(state='exited',exit_code=0))
    process.write_stdin=write
    channel=EnvironmentProcessChannel(process,name='engineering-cut',managed=True)
    view=channel.bind_writer(channel.acquire_writer())
    frame=(json.dumps({'jsonrpc':'2.0','id':1,'method':'session/prompt','params':params})+'\n').encode()
    guard=EffectWriteGuard(UNIT,binding.execution_operation_ref,'sha256:'+binding.prompt_input_digest.hex,params,
        lambda identity,deadline:service.acquire_effect_write(ctx,binding,identity,deadline),timeout=.3)
    return channel,view,frame,guard


def revoke(factory,grant,event):
    with factory.begin(grant.intent.scope) as uow:
        uow.authorization.revoke(grant.ref,0,NOW,'controlled actual revoke',event)
        uow.commit()


async def entered_or_failed(event, task):
    """Keep the native-write checkpoint bounded and expose early owner refusal."""
    waiter = asyncio.create_task(event.wait())
    try:
        done, _ = await asyncio.wait((waiter, task), timeout=2,
                                    return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        assert waiter in done, 'native write did not reach its controlled checkpoint'
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


def test_completed_revoke_before_actual_cut_never_writes(tmp_path,monkeypatch):
    lib,factory,service,grant,package,binding,params,ctx=prepared(tmp_path,monkeypatch)
    try:
        revoke(factory,grant,'before-cut')
        async def exercise():
            write=AsyncMock(return_value=1)
            ch,view,frame,guard=native(binding,params,service,ctx,write)
            with pytest.raises(ApplicationError,match='APPROVAL_CONTROL_CHANGED'):
                await view.send_frame_async(frame,before_write=lambda:None,effect_write_guard=guard)
            assert write.await_count==0 and ch._unresolved
        asyncio.run(exercise())
        assert lib._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==1
        assert not lib._connection.in_transaction
    finally:lib.close()


def test_different_connection_revoke_commits_after_admitted_bytes_before_model_wait(tmp_path,monkeypatch):
    lib,factory,service,grant,package,binding,params,ctx=prepared(tmp_path,monkeypatch)
    other=EngineeringLibrary.open(lib.path,library_id=lib.library_id);otherfactory=SQLiteUoWFactory(other)
    try:
        async def exercise():
            entered=asyncio.Event();allowed=asyncio.Event();writes=[]
            async def write(data,*,timeout=None):
                assert lib._connection.in_transaction;entered.set();await allowed.wait();writes.append(data);return len(data)
            ch,view,frame,guard=native(binding,params,service,ctx,write)
            task=asyncio.create_task(view.send_frame_async(frame,before_write=lambda:None,effect_write_guard=guard))
            await entered_or_failed(entered,task)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(revoke,otherfactory,grant,'after-cut')
                await asyncio.sleep(.02);assert not future.done()  # Same DB BEGIN IMMEDIATE holds original revoke writer.
                allowed.set();await task
                await asyncio.to_thread(future.result,2)
            assert writes==[frame] and not lib._connection.in_transaction
            # The caller may now wait arbitrarily for RPC/model without a DB lock.
            await asyncio.sleep(0)
            with factory.begin(package.scope,'read') as uow:
                assert uow.authorization.get_control(grant.ref)['state']=='revoked'
            assert await ch.close_async(timeout=.3)==0
            assert ch._stderr_task.done()
        asyncio.run(exercise())
        assert lib._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==1
    finally:other.close();lib.close()


@pytest.mark.parametrize('edge',['partial','timeout','cancel'])
def test_partial_timeout_cancel_release_original_tx_and_keep_native_unknown(tmp_path,monkeypatch,edge):
    lib,factory,service,grant,package,binding,params,ctx=prepared(tmp_path,monkeypatch)
    try:
        async def exercise():
            entered=asyncio.Event()
            async def write(data,*,timeout=None):
                assert lib._connection.in_transaction;entered.set()
                if edge!='partial':await asyncio.Event().wait()
                return len(data)-1
            ch,view,frame,guard=native(binding,params,service,ctx,write)
            task=asyncio.create_task(view.send_frame_async(frame,before_write=lambda:None,effect_write_guard=guard))
            if edge=='cancel':await entered_or_failed(entered,task);task.cancel()
            expected={'partial':ChannelClosed,'timeout':TimeoutError,'cancel':asyncio.CancelledError}[edge]
            with pytest.raises(expected):await task
            assert not lib._connection.in_transaction and ch._unresolved
            with pytest.raises(WriterLeaseRefused):await view.send_raw_async({'method':'never-retry'})
            assert await ch.close_async(timeout=.3)==0
            assert ch._stderr_task.done()
        asyncio.run(exercise())
        assert lib._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==1
    finally:lib.close()


def test_effect_uow_failfast_on_other_writer_and_preserves_original_timeout(tmp_path,monkeypatch):
    lib,factory,service,grant,package,binding,params,ctx=prepared(tmp_path,monkeypatch)
    other=EngineeringLibrary.open(lib.path,library_id=lib.library_id)
    try:
        old=lib._connection.execute('PRAGMA busy_timeout').fetchone()[0]
        with other.transaction():
            with pytest.raises(ApplicationError,match='EFFECT_WRITE_BUSY'):
                with factory.begin_effect_cut(package.scope):pass
        assert lib._connection.execute('PRAGMA busy_timeout').fetchone()[0]==old
        with factory.begin_effect_cut(package.scope) as uow:
            with pytest.raises(ApplicationError,match='EFFECT_WRITE_BUSY'):
                with factory.begin_effect_cut(package.scope):pass
            uow.commit()
    finally:other.close();lib.close()


@pytest.mark.parametrize('revoked',[False,True])
def test_actual_unit_sdk_factory_and_original_approval_control_cut(tmp_path,monkeypatch,revoked):
    """Actual Local/SDK/durable Unit; package/Grant source admission remains explicit fixture."""
    from test_implementation_dispatch import _fixture_records
    from ordessa_engineering.adapters.native_records.recorded_dispatch import (
        RecordedDispatchExecution,engineering_effect_write_guard_factory,NativeDispatchSources)
    from ordessa_engineering.domain.approvals.scope import EnvironmentRef
    from dataclasses import replace
    from ordessa_infrastructure.identifiers import RequestKey
    from ordessa_units.bindings.publication import decode_node_ref
    from ordessa_units.bindings.contracts import DirectoryBindingRef
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'execution/agents/tests/support'))
    from agent_tools_fixtures.manager_joint import build_joint_owner
    holder={}
    def configured_factory(*args):return holder['factory'](*args)
    with build_joint_owner(tmp_path/'native',acp_turn_opt_in=True,effect_write_guard_factory=configured_factory) as j:
        original=j.services.assembly.prepare(RequestKey('env','principal','prepare'),j.profile,{},{});
        assert original.status=='published'
        ref=json.loads(json.dumps({'value':j.services.nodes.read(decode_node_ref(original.intent.node_ref))['binding']['harnessUnitRef']},default=dict))['value']
        unit=j.manager.find(ref);lease=unit.lease_port.grant(ref);unit.connect(ref,lease)
        lib,factory,service,_,_,grant,package,_=_setup(tmp_path/'engineering',monkeypatch)
        try:
            monkeypatch.setattr('ordessa_engineering.application.usecases.support.clock.utc_now',lambda:NOW)
            package=replace(package,payload=replace(package.payload,execution_profile_ref=EnvironmentRef(
                j.profile.environment_namespace,j.profile.profile_id,Digest('sha256',j.profile.digest[7:]))))
            service._work_package=lambda *_,**kwargs:package
            ctx=_context(package.scope,package.created_by)
            holder['factory']=engineering_effect_write_guard_factory(service,ctx,unit.records,service.blobs)
            port=RecordedDispatchExecution(unit.records,unit,lease,service.blobs,
                effect_write_guard_factory=configured_factory)
            raw,prompt_digest=port.freeze_input(ref,{'prompt':[]})
            prompt=service.blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
            op='original-sdk-cut'
            binding=DispatchBinding(package.scope,'run-1','source_review',1,1,package.ref,grant.ref,grant.intent.digest,
                0,(('edit_repository','sdk-cut-action'),),canonical_bytes(ref),op,prompt,prompt_digest,
                port.query_digest(ref,op,prompt_digest),('submission',))
            encoded=encode_dispatch(binding)
            with factory.begin(package.scope) as uow:
                uow.authorization.consume_action(grant.ref,action='edit_repository',action_instance_id='sdk-cut-action',
                    target_digest=binding.digest,now=NOW)
                uow.dispatch.reserve('run-1','source_review',1,package.scope,encoded,
                    Digest('sha256',hashlib.sha256(encoded).hexdigest()),op)
                uow.dispatch.transition('run-1','source_review',1,package.scope,expected_version=0,fence=1,phase='possibly_written')
                uow.commit()
            j.current.acquired=dict(original.intent.node_ref);j.current.evidence=dict(ref)
            invocation=j.services.authorize_acp_turn_query(RequestKey('env','principal','engine-query'),ref,op,
                expected_prompt_input_digest='sha256:'+prompt_digest.hex)
            directory=DirectoryBindingRef.from_dict(json.loads(json.dumps({'value':original.intent.context_ref['directoryBindingRef']},default=dict))['value'])
            sources=NativeDispatchSources(j.services,lambda *_:(j.profile,directory,invocation,invocation.facts['inputDigest']))
            with sources.guard_commit_snapshot(ctx,package,ref) as snap:
                assert snap['contract']=='unit-live-source-snapshot/1'
                assert snap['currentThroughCommit'] is snap['liveDispatchAuthorized'] is snap['checkoutBaselineVerified'] is False
            record=unit.channel_factory.owned_record;write=record.process.write_stdin;writes=[]
            async def observed(data,*,timeout=None):
                assert lib._connection.in_transaction
                writes.append(data)
                return await write(data,timeout=timeout)
            record.process.write_stdin=observed
            if revoked:revoke(factory,grant,'sdk-before-cut')
            if revoked:
                with pytest.raises(ApplicationError,match='APPROVAL_CONTROL_CHANGED'):port.send(binding,timeout=3)
                assert writes==[]
            else:
                receipt=port.send(binding,timeout=3)
                assert receipt['state']=='completed' and len(writes)==1
                assert b'session/prompt' in writes[0]
            assert not lib._connection.in_transaction
            # This read is actual original authorization/cold recipe, independent of the action Grant.
            receipt=unit.records.query_acp_turn(ref,op,invocation,input_digest=invocation.facts['inputDigest'],
                expected_prompt_input_digest='sha256:'+prompt_digest.hex)
            assert receipt['state']==('unknown' if revoked else 'completed')
            with sources.guard_history_read(ctx,package,ref) as read:
                assert read['contract']=='unit-selection-read-cut/1' and read['currentThroughCommit'] is False
            assert lib._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==1
            assert j.events.count('spawn')==1
        finally:lib.close()


def test_effect_cut_rechecks_actual_time_instead_of_original_command_time(tmp_path,monkeypatch):
    lib,factory,service,grant,package,binding,params,ctx=prepared(tmp_path,monkeypatch)
    try:
        monkeypatch.setattr('ordessa_engineering.application.usecases.support.clock.utc_now',lambda:grant.intent.expires_at)
        async def exercise():
            write=AsyncMock(return_value=1)
            ch,view,frame,guard=native(binding,params,service,ctx,write)
            with pytest.raises(ApplicationError,match='AUTHORIZATION_EXPIRED'):
                await view.send_frame_async(frame,before_write=lambda:None,effect_write_guard=guard)
            assert write.await_count==0 and not lib._connection.in_transaction and ch._unresolved
        asyncio.run(exercise())
    finally:lib.close()


def test_wrong_original_effect_operation_identity_cannot_acquire_tx(tmp_path,monkeypatch):
    lib,factory,service,grant,package,binding,params,ctx=prepared(tmp_path,monkeypatch)
    try:
        async def exercise():
            identity={'unitRef':UNIT,'operationRef':'other-operation','inputDigest':'sha256:'+binding.prompt_input_digest.hex,
                'requestId':1,'frameDigest':'sha256:'+'b'*64}
            with pytest.raises(ApplicationError,match='DISPATCH_EFFECT_BINDING_MISMATCH'):
                async with service.acquire_effect_write(ctx,binding,identity,asyncio.get_running_loop().time()+.1):
                    raise AssertionError('other operation must not enter')
            assert not lib._connection.in_transaction
        asyncio.run(exercise())
    finally:lib.close()


def test_original_dispatch_detaches_sealed_unit_without_changing_binding(tmp_path,monkeypatch):
    from types import MappingProxyType
    lib,factory,service,execution,calls,grant,package,_=_setup(tmp_path,monkeypatch,guard_mode='second_guard_fails')
    ref=MappingProxyType({**UNIT,'ownerProviderRef':MappingProxyType(UNIT['ownerProviderRef'])})
    # Old synthetic execution fixture only accepts mutable JSON; actual native adapter was checked above.
    original_freeze=execution.freeze_input
    def fixture_freeze(unit,params):
        assert unit is ref
        return original_freeze(UNIT,params)
    execution.freeze_input=fixture_freeze
    try:
        with pytest.raises(ApplicationError,match='SECOND_GUARD_REFUSED'):
            service.dispatch('run-1','source_review',1,ref,{'prompt':'synthetic prompt'},
                ('edit_repository',),_context(package.scope,package.created_by))
        assert execution.send_calls==[] and calls['guards']==2
        with factory.begin(package.scope,'read') as uow:
            row=uow.dispatch.get('run-1','source_review',1,package.scope)
            from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
            assert decode_dispatch(row['binding_bytes']).unit_ref_bytes==canonical_bytes(UNIT)
        assert lib._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==1
    finally:lib.close()
