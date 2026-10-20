"""Disposable Local resource/Use; no real credentials or model/network calls."""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore, ProcessRequest, EnvironmentRefused, EnvironmentOperationUnknown
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_units.assembly.process_input import UnitProcessInput


@pytest.fixture
def original(tmp_path):
    root = tmp_path / 'area'
    store = SQLiteEnvironmentStore(tmp_path / 'resources.sqlite')
    manager = EnvironmentManager(store=store, providers={'local': LocalEnvironmentResourceProvider(default_root=str(root))})
    instance = manager.create('local', {'root': str(root)})
    yield instance, root, store
    # SQLiteEnvironmentStore opens bounded per-operation connections; no close handle.


class Source:
    def __init__(self): self.reads, self.buffer = 0, bytearray(b'controlled-capability-value')
    def read(self):
        self.reads += 1
        return self.buffer


def bind(instance, request, source, check=lambda: None):
    return UnitProcessInput(instance=instance, agent_id='fixed-agent', sharing=False,
        source=source, admitted_launch=lambda: request, check_start=check)


def test_same_guarded_use_real_spawn_only_exact_value_and_no_ambient_inheritance(original, monkeypatch):
    instance, root, store = original
    monkeypatch.setenv('UNRELATED_AMBIENT_SECRET', 'must-not-arrive')
    import hashlib
    digest = hashlib.sha256(b'controlled-capability-value').hexdigest()
    program = f"import os, hashlib; assert hashlib.sha256(os.environ['OPENCODE_API_KEY'].encode()).hexdigest() == '{digest}'; assert 'UNRELATED_AMBIENT_SECRET' not in os.environ; print('confirmed')"
    request = ProcessRequest.build([sys.executable, '-c', program], cwd=str(root), env={})
    source = Source()
    checks = []
    cap = bind(instance, request, source, check=lambda: checks.append('original-start-authority'))
    use = cap.acquire('fixed-agent', sharing=False)
    assert use.environment_id == instance.identity
    assert 'controlled-capability-value' not in repr(cap)
    process = use.execution.start(request)
    async def finish():
        assert await process.read_stdout(100, timeout=5) == b'confirmed\n'
        assert (await process.wait_exit(timeout=5)).exit_code == 0
    asyncio.run(finish())
    process.release()
    assert source.reads == 1 and not any(source.buffer)
    assert checks == ['original-start-authority', 'original-start-authority']
    with pytest.raises(EnvironmentRefused): use.execution.start(request)
    use.release()
    assert instance.snapshot.active_uses == 0
    assert b'controlled-capability-value' not in Path(store.path).read_bytes()
    assert not root.joinpath('auth.json').exists()


def test_different_launch_owner_or_sharing_refuses_before_secret_read(original):
    instance, root, store = original
    request = ProcessRequest.build([sys.executable, '-c', 'pass'], cwd=str(root), env={})
    source = Source(); cap = bind(instance, request, source)
    with pytest.raises(EnvironmentRefused): cap.acquire('foreign', sharing=False)
    with pytest.raises(EnvironmentRefused): cap.acquire('fixed-agent', sharing=True)
    use = cap.acquire('fixed-agent', sharing=False)
    for bad in (ProcessRequest.build([sys.executable, '-c', 'print(1)'], cwd=str(root), env={}),
                ProcessRequest.build(request.argv, cwd=str(root), env={'OPENCODE_API_KEY': 'arbitrary'})):
        with pytest.raises(EnvironmentRefused): use.execution.start(bad)
    assert source.reads == 0
    use.release()


def test_revoke_between_read_and_spawn_refuses_and_wipes(original):
    instance, root, store = original
    request = ProcessRequest.build([sys.executable, '-c', 'pass'], cwd=str(root), env={})
    source = Source(); checks = []
    def check():
        checks.append(True)
        if len(checks) == 2: raise EnvironmentRefused('original authority revoked')
    cap = bind(instance, request, source, check)
    use = cap.acquire('fixed-agent', sharing=False)
    with pytest.raises(EnvironmentRefused, match='revoked'): use.execution.start(request)
    assert source.reads == 1 and not any(source.buffer)
    with pytest.raises(EnvironmentRefused): use.execution.start(request)
    use.release()


def test_capability_use_check_preserves_original_identity_and_generation_refusal(original):
    instance, root, store = original
    request = ProcessRequest.build([sys.executable, '-c', 'pass'], cwd=str(root), env={})
    use = bind(instance, request, Source()).acquire('fixed-agent', sharing=False)

    assert use.check(use.environment_id, use.generation) is True
    with pytest.raises(EnvironmentRefused):
        use.check('foreign-environment', use.generation)
    with pytest.raises(EnvironmentRefused):
        use.check(use.environment_id, use.generation + 1)
    with pytest.raises(EnvironmentRefused):
        use.check(use.environment_id, use.generation, allow_unknown=1)
    use.release()


def test_capability_use_check_rejects_released_use(original):
    instance, root, store = original
    request = ProcessRequest.build([sys.executable, '-c', 'pass'], cwd=str(root), env={})
    use = bind(instance, request, Source()).acquire('fixed-agent', sharing=False)
    environment_id, generation = use.environment_id, use.generation

    use.release()
    with pytest.raises(EnvironmentRefused):
        use.check(environment_id, generation)
    with pytest.raises(EnvironmentRefused):
        use.check(environment_id, generation, allow_unknown=True)


def test_capability_use_check_requires_explicit_unknown_permission(original):
    instance, root, store = original
    request = ProcessRequest.build([sys.executable, '-c', 'pass'], cwd=str(root), env={})
    use = bind(instance, request, Source()).acquire('fixed-agent', sharing=False)

    store.fence_use(use.identity)
    with pytest.raises(EnvironmentRefused):
        use.check(use.environment_id, use.generation)
    assert use.check(use.environment_id, use.generation, allow_unknown=True) is True
    with pytest.raises(EnvironmentRefused):
        use.check('foreign-environment', use.generation, allow_unknown=True)
    with pytest.raises(EnvironmentRefused):
        use.check(use.environment_id, use.generation + 1, allow_unknown=True)


def test_remote_instance_refuses():
    with pytest.raises(EnvironmentRefused):
        bind(SimpleNamespace(snapshot=SimpleNamespace(provider_id='openshell')), None, Source())
