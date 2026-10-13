"""Actual pipe/process cancellation, timeout, EOF, stderr and release negatives."""
import asyncio
import sys
import threading
import pytest

from ordessa_environments import (ProcessRequest,ProcessWaitTimeout,EnvironmentRefused,
    EnvironmentOperationUnknown,EnvironmentManager,SQLiteEnvironmentStore)
from ordessa_environments_local import spawn,LocalEnvironmentResourceProvider


def make_process(tmp_path,code):
    return spawn(ProcessRequest((sys.executable,'-u','-c',code),str(tmp_path),{}))


async def finish(process):
    if process.observe().state!='exited':await process.cancel(force=True)
    await process.wait_exit(timeout=3)
    process.release()


def test_cancelled_read_does_not_consume_next_bytes_or_leave_worker(tmp_path):
    async def exercise():
        process=make_process(tmp_path,'import sys;\nfor line in sys.stdin: print(line.strip(),flush=True)')
        before={thread.ident for thread in threading.enumerate()}
        try:
            read=asyncio.create_task(process.read_stdout(100))
            await asyncio.sleep(0.03)
            with pytest.raises(EnvironmentRefused):await process.read_stdout(1,timeout=0)
            read.cancel()
            with pytest.raises(asyncio.CancelledError):await read
            with pytest.raises(ProcessWaitTimeout):await process.read_stdout(1,timeout=0.01)
            assert await process.write_stdin(b'after-cancel\n',timeout=0)==13
            assert await process.read_stdout(100,timeout=2)==b'after-cancel\n'
            assert {thread.ident for thread in threading.enumerate()}==before
        finally:await finish(process)
    asyncio.run(exercise())


def test_eof_is_not_exit_and_release_is_not_kill(tmp_path):
    async def exercise():
        process=make_process(tmp_path,'import os,time;os.close(1);time.sleep(30)')
        try:
            assert await process.read_stdout(100,timeout=2)==b''
            assert process.observe().state=='running'
            with pytest.raises(ProcessWaitTimeout):await process.wait_exit(timeout=0.01)
            facts=process.release();assert process.release()==facts
            assert facts['processState']=='running' and 'exitCode' not in facts
            assert process.observe().state=='running'
            with pytest.raises(EnvironmentRefused):await process.write_stdin(b'new')
            result=await process.cancel(force=True)
            assert result.outcome=='requested'
            assert (await process.wait_exit(timeout=2)).state=='exited'
            assert process.release()==facts  # Historical release receipt, no fake new exit.
        finally:await finish(process)
    asyncio.run(exercise())


def test_stderr_is_independently_drained_before_stdout(tmp_path):
    async def exercise():
        process=make_process(tmp_path,'import sys;sys.stderr.write("x"*2097152);sys.stderr.flush();print("ready",flush=True)')
        try:
            assert await process.read_stdout(100,timeout=2)==b'ready\n'
            total=bytearray()
            while True:
                data=await process.read_stderr(65536,timeout=2)
                if not data:break
                total.extend(data)
            assert total==b'x'*2097152
            assert (await process.wait_exit(timeout=2)).exit_code==0
        finally:await finish(process)
    asyncio.run(exercise())


def test_partial_write_timeout_is_unknown_and_live_exit_can_release_own_use(tmp_path):
    async def exercise():
        root=tmp_path/'files';provider=LocalEnvironmentResourceProvider(default_root=str(root))
        manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.db'),providers={'local':provider})
        instance=manager.create('local',{});use=instance.acquire('unit',sharing=False)
        process=use.execution.start(ProcessRequest((sys.executable,'-c','import time;time.sleep(30)'),str(root),{}))
        try:
            task=asyncio.create_task(process.write_stdin(b'x'*4194304,timeout=0.04))
            await asyncio.sleep(0.02)
            with pytest.raises(EnvironmentRefused):await process.write_stdin(b'another')
            with pytest.raises(EnvironmentOperationUnknown):await task
            assert process.observe().state=='running' and process.observe().io_state=='unknown'
            with pytest.raises(EnvironmentRefused):instance.delete()
            with pytest.raises(EnvironmentRefused):await process.write_stdin(b'retry')
            assert (await process.cancel(force=True)).outcome=='requested'
            observation=await process.wait_exit(timeout=2)
            assert observation.state=='exited' and type(observation.exit_code) is int
            process.release();receipt=use.release();assert use.release()==receipt
            assert instance.snapshot.active_uses==0
        finally:
            if process._target.observe().state!='exited':
                await process._target.cancel(force=True);await process._target.wait_exit(timeout=2)
            process._target.release()
    asyncio.run(exercise())


def test_write_task_cancel_after_dispatch_is_unknown(tmp_path):
    async def exercise():
        process=make_process(tmp_path,'import time;time.sleep(30)')
        try:
            write=asyncio.create_task(process.write_stdin(b'x'*4194304))
            await asyncio.sleep(0.03);write.cancel()
            with pytest.raises(EnvironmentOperationUnknown):await write
            assert process.observe().state=='running' and process.observe().io_state=='unknown'
        finally:await finish(process)
    asyncio.run(exercise())


@pytest.mark.parametrize('timeout',[-1,float('nan'),float('inf'),True,'1'])
def test_invalid_timeouts_refuse_without_effect(tmp_path,timeout):
    async def exercise():
        process=make_process(tmp_path,'import time;time.sleep(30)')
        try:
            with pytest.raises(EnvironmentRefused):await process.read_stdout(1,timeout=timeout)
            with pytest.raises(EnvironmentRefused):await process.write_stdin(b'x',timeout=timeout)
            with pytest.raises(EnvironmentRefused):await process.wait_exit(timeout=timeout)
            assert process.observe().state=='running'
        finally:await finish(process)
    asyncio.run(exercise())
