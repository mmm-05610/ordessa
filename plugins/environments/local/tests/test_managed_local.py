"""Actual local subprocesses remain creator-owned with two independent Uses."""
import sys
import asyncio
import pytest
from ordessa_environments import (
    EnvironmentManager, SQLiteEnvironmentStore, ProcessRequest, EnvironmentRefused,
    PROCESS_CAPABILITY, TERMINAL_CAPABILITY, CapabilityReport, CapabilityStatus,
)
from ordessa_environments_local import LocalEnvironmentResourceProvider


def test_managed_local_use_reports_a_capability_report(tmp_path):
    root=tmp_path/'files'
    provider=LocalEnvironmentResourceProvider(default_root=str(root))
    manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.db'),providers={'local':provider})
    instance=manager.create('local',{'root':str(root)})
    use=instance.acquire('unit',sharing=False)
    assert isinstance(use.capabilities, CapabilityReport)
    assert use.capabilities.isolation=='none'
    assert use.capabilities.values[PROCESS_CAPABILITY] is CapabilityStatus.SUPPORTED
    assert use.capabilities.values[TERMINAL_CAPABILITY] is CapabilityStatus.UNSUPPORTED
    assert use.capabilities.provides==frozenset({'process','byte-channel','files','stderr'})
    use.release()


def test_shared_local_uses_keep_original_process_and_file_behavior(tmp_path):
    async def exercise():
        root=tmp_path/'files'
        provider=LocalEnvironmentResourceProvider(default_root=str(root))
        manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.db'),providers={'local':provider})
        instance=manager.create('local',{'root':str(root)})
        a=instance.acquire('unit-a',sharing=True);b=instance.acquire('unit-b',sharing=True)
        a.files.write_text('kept.txt','retained')
        req=ProcessRequest((sys.executable,'-u','-c','import sys;\nfor line in sys.stdin: print(line.strip(),flush=True)'),str(root),{})
        pa=a.execution.start(req);pb=b.execution.start(req)
        assert pa.generation==a.generation
        for name in ('stdin','stdout','stderr','poll','wait','kill','fileno'):
            assert not hasattr(pa,name),name
        await pa.write_stdin(b'a\n');assert await pa.read_stdout(100,timeout=2)==b'a\n'
        await pb.write_stdin(b'b\n');assert await pb.read_stdout(100,timeout=2)==b'b\n'
        with pytest.raises(EnvironmentRefused):a.release()
        old_read=pa.read_stdout
        await pa.close_stdin();assert (await pa.wait_exit(timeout=2)).exit_code==0
        facts=pa.release();assert pa.release()==facts
        with pytest.raises(EnvironmentRefused):await old_read(1)
        assert pa.observe().state=='exited'
        receipt=a.release();assert a.release()==receipt
        await pb.write_stdin(b'still-alive\n');assert await pb.read_stdout(100,timeout=2)==b'still-alive\n'
        await pb.close_stdin();assert (await pb.wait_exit(timeout=2)).state=='exited'
        pb.release();b.release()
        assert root.joinpath('kept.txt').read_text()=='retained'
        assert instance.snapshot.active_uses==0
        with pytest.raises(EnvironmentRefused):provider.delete(instance.snapshot.backend_id)
        with pytest.raises(EnvironmentRefused):instance.stop()
        assert instance.snapshot.phase=='ready' and instance.snapshot.generation==0
    asyncio.run(exercise())
