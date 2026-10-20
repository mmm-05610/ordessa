"""T018 physical lifecycle cuts on the original local Use/process owner."""
import asyncio
from contextlib import contextmanager
import sys
import threading

import pytest

from ordessa_environments import EnvironmentRefused
from test_guarded_endpoint_send import LocalChild


def test_terminate_signal_is_inside_cut_and_exit_wait_is_outside(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path)
        try:
            raw=child.native._target
            original=raw.popen.terminate
            task,thread=asyncio.current_task(),threading.get_ident()
            effects=[]
            def terminate():
                assert child.active
                assert asyncio.current_task() is task and threading.get_ident()==thread
                effects.append('signal')
                return original()
            raw.popen.terminate=terminate
            result=await child.process.terminate_guarded(request_id='stop',guard_effect=child.guard)
            assert result['status']=='completed'
            assert effects==['signal'] and child.guard_calls==1 and not child.active
            # Signal receipt is not substituted for independent exit evidence.
            assert (await child.process.wait_exit(timeout=3)).state=='exited'
            assert await child.process.terminate_guarded(request_id='stop',guard_effect=child.guard)==result
            assert effects==['signal'] and child.guard_calls==1
        finally:await child.cleanup()
    asyncio.run(scenario())


def test_detach_closes_only_association_inside_cut_keeps_process_and_use(tmp_path,monkeypatch):
    async def scenario():
        child=LocalChild(tmp_path,[sys.executable,'-c','import time; time.sleep(30)'])
        try:
            raw=child.native._target;original=type(raw).release;effects=[]
            def release(handle):
                assert handle is raw and child.active
                effects.append('detach')
                return original(handle)
            monkeypatch.setattr(type(raw),'release',release)
            result=child.process.detach_guarded(request_id='detach',guard_effect=child.guard)
            assert result['status']=='completed' and result['exitClaimed'] is False
            assert raw.observe().state=='running' and child.instance.snapshot.active_uses==1
            assert effects==['detach'] and child.guard_calls==1 and not child.active
            assert child.process.detach_guarded(request_id='detach',guard_effect=child.guard)==result
            assert effects==['detach'] and child.guard_calls==1
        finally:
            monkeypatch.undo()
            await child.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('action',['terminate','detach'])
def test_guard_refusal_before_effect_preserves_live_process_and_use(tmp_path,action):
    async def scenario():
        child=LocalChild(tmp_path)
        @contextmanager
        def refuse():
            raise EnvironmentRefused('revoked at physical cut')
            yield
        try:
            if action=='terminate':
                result=await child.process.terminate_guarded(request_id='deny',guard_effect=refuse)
            else:
                result=child.process.detach_guarded(request_id='deny',guard_effect=refuse)
            assert result['status']=='refused'
            assert child.native.observe().state=='running' and not child.native._released
            assert child.instance.snapshot.active_uses==1
        finally:await child.cleanup()
    asyncio.run(scenario())


def test_guard_exception_after_signal_is_unknown_and_replay_does_not_signal(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path)
        effects=[];raw=child.native._target;original=raw.popen.terminate
        def terminate():
            effects.append('signal');return original()
        raw.popen.terminate=terminate
        @contextmanager
        def uncertain():
            yield
            raise RuntimeError('lost outcome after effect')
        try:
            result=await child.process.terminate_guarded(request_id='uncertain',guard_effect=uncertain)
            assert result['status']=='unknown' and effects==['signal']
            assert await child.process.terminate_guarded(request_id='uncertain',guard_effect=uncertain)==result
            assert effects==['signal']
        finally:await child.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('action',['terminate','detach'])
def test_missing_guard_refuses_before_reservation(tmp_path,action):
    async def scenario():
        child=LocalChild(tmp_path)
        try:
            with pytest.raises(EnvironmentRefused,match='mandatory synchronous'):
                if action=='terminate':
                    await child.process.terminate_guarded(request_id='same',guard_effect=None)
                else:child.process.detach_guarded(request_id='same',guard_effect=None)
            # Same request remains available for a real authorized effect.
            if action=='terminate':
                result=await child.process.terminate_guarded(request_id='same',guard_effect=child.guard)
            else:result=child.process.detach_guarded(request_id='same',guard_effect=child.guard)
            assert result['status']=='completed' and child.guard_calls==1
        finally:await child.cleanup()
    asyncio.run(scenario())
