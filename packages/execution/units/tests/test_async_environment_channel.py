"""Real Local IO at the framing/writer cut, without SDK or model calls."""
import asyncio
import sys

import pytest
from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore, ProcessRequest
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_execution_agents.harness.transport import ProcessChannel, ChannelClosed, RequestTimeout, WriterLeaseRefused


def owned(tmp_path, command):
    provider=LocalEnvironmentResourceProvider(default_root=str(tmp_path))
    manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.sqlite'),providers={'local':provider})
    instance=manager.create('local',{'root':str(tmp_path)})
    use=instance.acquire('channel-test',sharing=True)
    process=use.execution.start(ProcessRequest.build([sys.executable,'-u','-c',command],cwd=str(tmp_path),env={}))
    channel=ProcessChannel.attach(process,name='controlled',managed=True)
    return use,process,channel,channel.bind_writer(channel.acquire_writer())


def test_stdout_eof_fences_but_never_proves_real_process_exit(tmp_path):
    async def exercise():
        use,process,channel,view=owned(tmp_path,'import os,time;os.close(1);time.sleep(30)')
        try:
            with pytest.raises(ChannelClosed):await view.next_message_async(timeout=2)
            assert process.observe().state=='running'
            with pytest.raises(WriterLeaseRefused):channel.acquire_writer()
            code=await channel.close_async(timeout=.05)
            assert process.observe().state=='exited' and process.observe().exit_code==code
        finally:
            if process.observe().state!='exited':
                await process.cancel(force=True);await process.wait_exit(timeout=2)
            process.release();use.release()
    asyncio.run(exercise())


def test_pending_read_cancel_and_timeout_preserve_future_unknown_unicode_frames(tmp_path):
    async def exercise():
        use,process,channel,view=owned(tmp_path,
            'import sys,json,time;time.sleep(.2);print(json.dumps({"jsonrpc":"2.0","method":"unknown/雪","params":{"text":"α\\u2028β"}},ensure_ascii=False),flush=True);sys.stdin.read()')
        try:
            read=asyncio.create_task(view.next_message_async(timeout=2))
            await asyncio.sleep(.02);read.cancel()
            with pytest.raises(asyncio.CancelledError):await read
            with pytest.raises(RequestTimeout):await view.next_message_async(timeout=.01)
            message=await view.next_message_async(timeout=2)
            assert message.raw=={'jsonrpc':'2.0','method':'unknown/雪','params':{'text':'α\u2028β'}}
            assert process.observe().state=='running'
            assert await channel.close_async(timeout=2)==0
        finally:
            process.release();use.release()
    asyncio.run(exercise())


def test_guard_revocation_fences_before_any_native_write(tmp_path):
    async def exercise():
        use,process,channel,view=owned(tmp_path,'import sys;\nfor line in sys.stdin: print(line,flush=True)')
        try:
            def revoke():channel.fence_all()
            with pytest.raises(WriterLeaseRefused):
                await view.send_frame_async(b'{"jsonrpc":"2.0","id":17,"method":"effect"}\n',before_write=revoke)
            assert channel._unresolved and not channel._prepared_inflight
            with pytest.raises(RequestTimeout):await view.next_message_async(timeout=.05)
            with pytest.raises(WriterLeaseRefused):await view.send_raw_async({'method':'second'})
            assert await channel.close_async(timeout=2)==0
        finally:
            process.release();use.release()
    asyncio.run(exercise())
