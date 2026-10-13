"""Actual SQLite admission/commit/failure fences; no simulated storage."""
from datetime import datetime, timezone
from types import SimpleNamespace
import threading
import asyncio
import sqlite3

import pytest
from ordessa_environments import (
    EnvironmentManager, SQLiteEnvironmentStore, BackendObservation, Capabilities,
    EnvironmentRefused, EnvironmentOperationUnknown, BackendNotFound,
)


class Provider:
    identity = 'controlled'
    binding_id = 'controlled-backend-scope'
    operations = frozenset({'start','stop','delete'})

    def __init__(self):
        self.state = 'running'
        self.exists = True
        self.creates = 0
        self.delete_entered, self.delete_continue = threading.Event(), threading.Event()
        self.delete_continue.set()

    def inspect(self, backend_id):
        if not self.exists:
            raise BackendNotFound('controlled backend absent')
        return BackendObservation(backend_id, self.state, Capabilities('controlled'), datetime.now(timezone.utc).isoformat())

    def create(self, reference, *, operation_id):
        self.creates += 1
        return self.inspect('immutable-backend')

    def open_use(self, backend_id, **kwargs):
        return SimpleNamespace(files=SimpleNamespace(root=lambda:'/backend'),
            execution=SimpleNamespace(start=lambda request:None), release=lambda:{'preserved':True})

    def stop(self, backend_id):
        self.state = 'stopped'
        return self.inspect(backend_id)

    def start(self, backend_id):
        self.state = 'running'
        return self.inspect(backend_id)

    def delete(self, backend_id):
        self.delete_entered.set()
        assert self.delete_continue.wait(3)
        self.exists = False


def manager(tmp_path, provider):
    return EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'environments.db'), providers={provider.identity:provider})


def test_scoped_registration_persistence_and_immutable_mapping(tmp_path):
    provider = Provider()
    first = manager(tmp_path,provider)
    instance = first.register(provider.identity,'immutable-backend')
    second = manager(tmp_path,provider)
    assert second.get(instance.identity).inspect().backend_id == 'immutable-backend'
    assert second.list()[0].observation.observed_at
    assert second.list()[0].generation == 0
    with pytest.raises(sqlite3.IntegrityError):
        second.register(provider.identity,'immutable-backend')


def test_explicit_sharing_and_release_are_independent(tmp_path):
    provider=Provider(); instance=manager(tmp_path,provider).create(provider.identity,{})
    a=instance.acquire('unit-a',sharing=True); b=instance.acquire('unit-b',sharing=True)
    cached=a.files
    with pytest.raises(EnvironmentRefused):
        instance.acquire('unit-c',sharing=False)
    a.release()
    with pytest.raises(EnvironmentRefused):
        cached.root()
    assert b.files.root() == '/backend'
    assert instance.snapshot.active_uses == 1
    b.release(); assert provider.exists
    single=instance.acquire('unit-c',sharing=False)
    with pytest.raises(EnvironmentRefused):
        instance.acquire('unit-d',sharing=True)
    single.release()


def test_cold_manager_cannot_forget_held_use(tmp_path):
    provider=Provider(); first=manager(tmp_path,provider)
    instance=first.create(provider.identity,{})
    instance.acquire('cold-owner',sharing=True)
    cold=manager(tmp_path,provider).get(instance.identity)
    assert cold.snapshot.active_uses == 1
    with pytest.raises(EnvironmentRefused):
        cold.delete()


def test_delete_gate_is_atomic_across_managers(tmp_path):
    provider=Provider(); first=manager(tmp_path,provider)
    instance=first.create(provider.identity,{})
    second=manager(tmp_path,provider).get(instance.identity)
    provider.delete_continue.clear()
    results=[]
    thread=threading.Thread(target=lambda:results.append(instance.delete()))
    thread.start(); assert provider.delete_entered.wait(3)
    assert second.snapshot.phase == 'deleting'
    with pytest.raises(EnvironmentRefused):
        second.acquire('late-owner',sharing=True)
    provider.delete_continue.set();thread.join(3)
    assert results[0].confirmed and second.snapshot.phase == 'deleted'


def test_stop_start_invalidates_old_use_and_preserves_id(tmp_path):
    provider=Provider(); instance=manager(tmp_path,provider).create(provider.identity,{})
    use=instance.acquire('unit',sharing=True); cached=use.files
    with pytest.raises(EnvironmentRefused):
        instance.stop()
    assert instance.stop(allow_in_use=True).confirmed
    with pytest.raises(EnvironmentRefused):
        cached.root()
    assert instance.start().generation == 2
    assert instance.snapshot.backend_id == 'immutable-backend'
    with pytest.raises(EnvironmentRefused):
        use.release()
    fresh=instance.acquire('unit-new',sharing=False);fresh.release()


def test_create_effect_success_local_commit_failure_is_reconcilable_unknown(tmp_path,monkeypatch):
    provider=Provider(); mgr=manager(tmp_path,provider)
    confirm=mgr.store.confirm
    monkeypatch.setattr(mgr.store,'confirm',lambda *a,**k: (_ for _ in ()).throw(OSError('controlled commit failure')))
    with pytest.raises(EnvironmentOperationUnknown) as caught:
        mgr.create(provider.identity,{})
    error=caught.value
    assert provider.creates == 1 and error.backend_id == 'immutable-backend'
    assert mgr.get(error.identity).snapshot.phase == 'unknown'
    with pytest.raises(EnvironmentRefused):
        mgr.get(error.identity).acquire('unit',sharing=False)
    monkeypatch.setattr(mgr.store,'confirm',confirm)
    instance=mgr.reconcile_creation(error.identity,error.backend_id)
    assert provider.creates == 1 and instance.inspect().phase == 'ready'


def test_failed_initial_local_commit_never_dispatches_remote_create(tmp_path,monkeypatch):
    provider=Provider(); mgr=manager(tmp_path,provider)
    monkeypatch.setattr(mgr.store,'insert',lambda *a,**k: (_ for _ in ()).throw(OSError('full store')))
    with pytest.raises(OSError):
        mgr.create(provider.identity,{})
    assert provider.creates == 0


def test_delete_timeout_unknown_no_retry_and_actual_absence_reconciles(tmp_path,monkeypatch):
    provider=Provider(); instance=manager(tmp_path,provider).create(provider.identity,{})
    count=[]
    def timeout(backend_id):
        count.append(backend_id)
        raise TimeoutError('no receipt')
    monkeypatch.setattr(provider,'delete',timeout)
    with pytest.raises(EnvironmentOperationUnknown):instance.delete()
    assert instance.inspect().phase == 'unknown'
    with pytest.raises(EnvironmentRefused):instance.delete()
    assert len(count) == 1
    provider.exists=False
    assert instance.inspect().phase == 'deleted'


def test_inflight_use_effect_blocks_release_and_admin_transition(tmp_path):
    provider=Provider(); mgr=manager(tmp_path,provider); instance=mgr.create(provider.identity,{})
    use=instance.acquire('unit',sharing=True)
    mgr.store.begin_use_effect(use.identity)
    with pytest.raises(EnvironmentRefused):mgr.store.release_use(use.identity)
    with pytest.raises(EnvironmentRefused):instance.stop(allow_in_use=True)
    mgr.store.end_use_effect(use.identity,unknown=True)
    with pytest.raises(EnvironmentRefused):use.release()
    with pytest.raises(EnvironmentRefused):instance.delete()


def test_foreign_database_is_never_migrated(tmp_path):
    path=tmp_path/'foreign.db'
    with sqlite3.connect(path) as c:c.execute('CREATE TABLE user_data (v TEXT)')
    with pytest.raises(EnvironmentRefused):SQLiteEnvironmentStore(path)
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [('user_data',)]


def test_provider_scope_cannot_be_rebound_after_restart(tmp_path):
    provider=Provider(); first=manager(tmp_path,provider)
    first.create(provider.identity,{})
    provider.binding_id='different-backend-scope'
    with pytest.raises(EnvironmentRefused):manager(tmp_path,provider)


def test_provider_cannot_change_mapping_in_an_observation(tmp_path,monkeypatch):
    provider=Provider(); instance=manager(tmp_path,provider).create(provider.identity,{})
    old=provider.inspect
    monkeypatch.setattr(provider,'inspect',lambda backend_id:old('replacement-id'))
    with pytest.raises(EnvironmentRefused):instance.inspect()
    assert instance.snapshot.backend_id == 'immutable-backend'


def test_read_wait_is_not_a_native_effect_that_blocks_admin_stop(tmp_path):
    async def exercise():
        provider=Provider(); instance=manager(tmp_path,provider).create(provider.identity,{})
        use=instance.acquire('unit',sharing=True)
        entered,finish=asyncio.Event(),asyncio.Event()
        class Process:
            identity='controlled-process'
            async def wait_exit(self,*,timeout=None):entered.set();await finish.wait();return None
        use._backend.execution.start=lambda request:Process()
        process=use.execution.start(None)
        task=asyncio.create_task(process.wait_exit());await entered.wait()
        assert instance.stop(allow_in_use=True).confirmed
        finish.set()
        with pytest.raises(EnvironmentRefused):await task
    asyncio.run(exercise())


def test_use_release_native_gate_blocks_other_manager_stop_and_delete(tmp_path):
    provider=Provider();entered=threading.Event();proceed=threading.Event();results=[]
    def release():
        entered.set();assert proceed.wait(3);return {'preserved':True}
    provider.open_use=lambda *a,**k:SimpleNamespace(files=SimpleNamespace(),execution=SimpleNamespace(),release=release)
    first=manager(tmp_path,provider);instance=first.create(provider.identity,{})
    use=instance.acquire('owner',sharing=False);other=manager(tmp_path,provider).get(instance.identity)
    thread=threading.Thread(target=lambda:results.append(use.release()));thread.start()
    try:
        assert entered.wait(3) and other.snapshot.active_uses==1
        with pytest.raises(EnvironmentRefused):other.stop(allow_in_use=True)
        with pytest.raises(EnvironmentRefused):other.delete()
        with pytest.raises(EnvironmentRefused):other.acquire('late',sharing=True)
    finally:proceed.set();thread.join(3)
    assert results and other.snapshot.active_uses==0
    assert use.release()==results[0]
