"""Controlled write/revoke schedules and real Local/SDK owner; zero model."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

import pytest
from ordessa_environments import ProcessHandle
from ordessa_execution_agents.harness.transport import EffectWriteGuard, EffectWriteRefused, WriterLeaseRefused, ChannelClosed
from ordessa_units.sessions.environment_channel import EnvironmentProcessChannel


UNIT = {'environmentNamespace': 'env', 'unitId': 'unit', 'ownerProviderRef': {}, 'sourceRevision': 'rev'}
PARAMS = {'sessionId': 'session', 'prompt': []}
FRAME = (json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'session/prompt', 'params': PARAMS}) + '\n').encode()
DIGEST = 'sha256:' + 'a' * 64


def channel(write):
    process = MagicMock(spec=ProcessHandle)
    process.observe.return_value = SimpleNamespace(state='running')
    process.read_stderr = AsyncMock(return_value=b'')
    process.write_stdin = write
    transport = EnvironmentProcessChannel(process, name='controlled', managed=True)
    return transport, transport.bind_writer(transport.acquire_writer())


@pytest.mark.parametrize('edge', ['success', 'partial', 'write_timeout', 'cancel', 'enter_refused', 'enter_timeout', 'release_error', 'release_timeout'])
def test_guard_covers_actual_async_write_and_releases_on_every_edge(edge):
    async def exercise():
        state = {'held': False, 'entered': 0, 'released': 0, 'writes': 0, 'before': 0}
        writing = asyncio.Event()
        @asynccontextmanager
        async def acquire(identity, deadline):
            assert identity['operationRef'] == 'operation' and identity['inputDigest'] == DIGEST
            assert identity['frameDigest'].startswith('sha256:') and deadline > asyncio.get_running_loop().time()
            if edge == 'enter_refused': raise PermissionError('controlled revoke before write cut')
            if edge == 'enter_timeout': await asyncio.Event().wait()
            state['held'] = True; state['entered'] += 1
            try: yield
            finally:
                try:
                    await asyncio.sleep(10 if edge == 'release_timeout' else 0)
                finally:
                    state['held'] = False; state['released'] += 1
                if edge == 'release_error': raise RuntimeError('controlled release error')
        async def write(data, *, timeout=None):
            assert state['held'] and data == FRAME and timeout is not None and timeout > 0
            state['writes'] += 1; writing.set()
            if edge in {'write_timeout', 'cancel'}: await asyncio.Event().wait()
            await asyncio.sleep(0)
            assert state['held']
            return len(data)-1 if edge == 'partial' else len(data)
        transport, view = channel(write)
        guard = EffectWriteGuard(UNIT, 'operation', DIGEST, PARAMS, acquire, timeout=.04, release_timeout=.04)
        def before():
            assert state['held']; state['before'] += 1
        task = asyncio.create_task(view.send_frame_async(FRAME, before_write=before, effect_write_guard=guard))
        if edge == 'cancel':
            await writing.wait(); task.cancel()
        failures = {'partial': ChannelClosed, 'write_timeout': TimeoutError, 'cancel': asyncio.CancelledError,
                    'enter_refused': PermissionError, 'enter_timeout': TimeoutError,
                    'release_error': RuntimeError, 'release_timeout': TimeoutError}
        if edge == 'success': await task
        else:
            with pytest.raises(failures[edge]): await task
            assert transport._unresolved
            with pytest.raises(WriterLeaseRefused): await view.send_raw_async({'method':'never-replay'})
        assert state['held'] is False and state['released'] == state['entered']
        assert state['writes'] == (0 if edge in {'enter_refused', 'enter_timeout'} else 1)
        if transport._stderr_task is not None: await transport._stderr_task
    asyncio.run(exercise())


def test_revoke_writer_waits_for_admitted_bytes_then_fences_next_operation():
    async def exercise():
        lock = asyncio.Lock(); entered = asyncio.Event(); complete_write = asyncio.Event(); revoked = []
        @asynccontextmanager
        async def acquire(identity, deadline):
            async with lock:
                if revoked: raise PermissionError('controlled revoked')
                yield
        async def write(data, *, timeout=None):
            assert lock.locked(); entered.set(); await complete_write.wait()
            assert not revoked
            return len(data)
        transport, view = channel(write)
        guard = EffectWriteGuard(UNIT, 'operation', DIGEST, PARAMS, acquire)
        send = asyncio.create_task(view.send_frame_async(FRAME, before_write=lambda:None, effect_write_guard=guard))
        await entered.wait()
        async def revoke():
            async with lock: revoked.append(True)
        revoke_task = asyncio.create_task(revoke()); await asyncio.sleep(0)
        assert not revoke_task.done()
        complete_write.set(); await send; await revoke_task
        second = FRAME.replace(b'"id": 1', b'"id": 2')
        with pytest.raises(PermissionError): await view.send_frame_async(second, before_write=lambda:None, effect_write_guard=guard)
        assert transport._unresolved
        await transport._stderr_task
    asyncio.run(exercise())


def test_wrong_frame_binding_never_acquires_or_writes():
    async def exercise():
        def no_acquire(*_): raise AssertionError('different input cannot acquire original guard')
        async def no_write(*_, **__): raise AssertionError('different input cannot write')
        transport, view = channel(no_write)
        guard = EffectWriteGuard(UNIT, 'operation', DIGEST, {'sessionId':'other','prompt':[]}, no_acquire)
        with pytest.raises(EffectWriteRefused): await view.send_frame_async(FRAME, before_write=lambda:None, effect_write_guard=guard)
        assert transport._unresolved
    asyncio.run(exercise())


def test_guard_cannot_suppress_partial_write_into_success():
    async def exercise():
        class Suppress:
            async def __aenter__(self): pass
            async def __aexit__(self, *_): return True
        async def write(data, *, timeout=None): return len(data)-1
        transport, view = channel(write)
        guard = EffectWriteGuard(UNIT, 'operation', DIGEST, PARAMS, lambda *_:Suppress())
        with pytest.raises(ChannelClosed): await view.send_frame_async(FRAME, before_write=lambda:None, effect_write_guard=guard)
        assert transport._unresolved
        await transport._stderr_task
    asyncio.run(exercise())


def test_original_unit_sdk_guard_release_precedes_model_wait(tmp_path, monkeypatch):
    # Shared actual owner fixture lives in Agents tests; source ownership stays
    # there, without a synthetic issuer/Unit implementation in this test.
    import sys
    from pathlib import Path
    support = Path(__file__).resolve().parents[2] / 'agents' / 'tests' / 'support'
    sys.path.insert(0, str(support))
    from agent_tools_fixtures.manager_joint import build_joint_owner
    from ordessa_infrastructure.identifiers import RequestKey
    from ordessa_units.bindings.publication import decode_node_ref
    from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import test_unit_instance
    monkeypatch.setattr(test_unit_instance, 'PEER', test_unit_instance.PEER.replace(
        "elif method=='session/prompt':", """elif method=='session/prompt':
        import time
        while not os.path.exists(os.environ['FIXTURE_CONFIG']+'.allow-result'): time.sleep(.01)"""))
    released = threading.Event()
    state = {'held': False, 'writes': 0, 'released': 0}
    @asynccontextmanager
    async def acquire(identity, deadline):
        state['held'] = True
        try: yield
        finally:
            state['held'] = False; state['released'] += 1; released.set()
    def factory(unit, operation, digest, params):
        return EffectWriteGuard(unit, operation, digest, params, acquire)
    with build_joint_owner(tmp_path, acp_turn_opt_in=True, effect_write_guard_factory=factory) as j:
        original = j.services.assembly.prepare(RequestKey('env','principal','prepare'), j.profile, {}, {})
        assert original.status == 'published'
        ref = j.services.nodes.read(decode_node_ref(original.intent.node_ref))['binding']['harnessUnitRef']
        unit = j.manager.find(ref); lease = unit.lease_port.grant(ref)
        record = unit.channel_factory.owned_record
        write = record.process.write_stdin
        async def observed_write(data, *, timeout=None):
            assert state['held']; state['writes'] += 1
            await asyncio.sleep(.01)
            assert state['held']
            return await write(data, timeout=timeout)
        record.process.write_stdin = observed_write
        marker = Path(record.prepared_agent.harness.launch_spec.env['FIXTURE_CONFIG']+'.allow-result')
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(unit.prompt, ref, lease, operation_ref='guarded-turn', timeout=5, prompt=[])
            try:
                assert released.wait(2)
                assert not pending.done()  # Peer has not returned the matching response.
            finally:
                marker.write_text('allow')
            receipt = pending.result(timeout=7)
        assert receipt['state'] == 'completed' and state == {'held':False,'writes':1,'released':1}
        connection = unit.connect(ref, lease)
        with pytest.raises(EffectWriteRefused): connection.command('session/prompt', sessionId=record.entry.session_id, prompt=[])
        forged = factory(ref, 'forged-turn', DIGEST, {'sessionId':record.entry.session_id, 'prompt':[]})
        for owner in (None, object(), 'wire-owner'):
            with pytest.raises(EffectWriteRefused):
                connection.command('session/prompt', sessionId=record.entry.session_id, prompt=[],
                    effect_write_guard=forged, _effect_write_owner=owner, before_write=lambda raw:None)
        with pytest.raises(TypeError, match='operation_ref'): unit.prompt(ref, lease, prompt=[])
        with pytest.raises(UnitLifecycleRefused, match='callbacks'): unit.prompt(ref, lease,
            operation_ref='wire-injection', prompt=[], effect_write_guard=object())
        with pytest.raises(UnitLifecycleRefused, match='callbacks'): unit.prompt(ref, lease,
            operation_ref='wire-owner', prompt=[], _effect_write_owner=object())
        assert state['writes'] == 1 and j.events.count('spawn') == 1
