"""Controlled failure-injection controls for construction cleanup recovery.

These tests use real temporary data roots, SQLite StorePorts, product factories,
and Host cleanup owners. Faults are injected only at close boundaries; no
provider implementation or external service is substituted.
"""
from ordessa_server.composition.agent_tools.owner_ports import OwnerAssemblyRefused
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock

import pytest

from ordessa_server.composition.runtime import DataRootOwner


def _raise(message):
    raise RuntimeError(message)


def _fingerprint_port():
    from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac

    return ProtectedFingerprintHmac(
        {"fixture": b"construction-fault-controlled-key"}, active_key_id="fixture"
    )


def _retry_pending(root):
    """Best-effort fixture cleanup, preserving the candidate's retry contract."""
    try:
        DataRootOwner.retry_pending_build(root)
    except BaseException:
        # A close fault may intentionally keep the original owner. Tests below
        # assert that state before this final deterministic retry.
        DataRootOwner.retry_pending_build(root)


def test_product_factory_retains_original_environment_and_store_for_host_retry(
    tmp_path, monkeypatch
):
    """A factory close failure must hand Host the same still-live objects."""
    from pacthold.adapters.sqlite.environment.store import SqliteStorePort
    from pacthold.environment import Environment
    from ordessa_server.composition.native_channels import contributions
    from ordessa_server.composition.product_unit_admission import create_product_unit_admission
    from ordessa_server.composition.runtime import _FailedBuildCleanup

    root = tmp_path / "product-root"
    store_path = root / "state" / "core.sqlite"
    owner = DataRootOwner(root)
    owner.acquire()
    original_environment_close = Environment.close
    original_store_close = SqliteStorePort.close
    close_events = []
    base_close_attempts = 0
    store_close_attempts = 0

    def fail_native_contributions():
        _raise("controlled post-Environment construction failure")

    def fail_first_environment_retirement(environment):
        nonlocal base_close_attempts
        base_close_attempts += 1
        close_events.append(("environment", base_close_attempts))
        if base_close_attempts == 1:
            _raise("controlled Environment close refusal")
        return original_environment_close(environment)

    def fail_first_store_close(store):
        nonlocal store_close_attempts
        store_close_attempts += 1
        close_events.append(("store", store_close_attempts))
        if store_close_attempts == 1:
            _raise("controlled Store close refusal")
        return original_store_close(store)

    monkeypatch.setattr(contributions, "native_transport_contributions", fail_native_contributions)
    monkeypatch.setattr(Environment, "close", fail_first_environment_retirement)
    monkeypatch.setattr(SqliteStorePort, "close", fail_first_store_close)

    try:
        with pytest.raises(RuntimeError, match="post-Environment") as failed:
            create_product_unit_admission(
                store_path,
                fingerprint_port=None,
                agent_owner_inputs=None,
                native_channels_selected=True,
                _exclusive_owner=lambda: owner.acquired,
            )

        construction_failure = failed.value
        original_environment = construction_failure.pending_environment_close
        original_store = construction_failure.pending_store_close
        assert original_environment is not None
        assert original_store is original_environment.store_port
        assert not original_environment._closed
        assert owner.acquired

        # This is the Host's exact recovery owner, initialized from the factory's
        # attached original objects. The first Host retry retires Environment,
        # then fails closing Store; it must retain both that Store and the OS
        # owner for another explicit retry.
        pending = _FailedBuildCleanup(
            owner, plugin_host=None, core_binding=None,
            store=original_store, environment=original_environment,
        )
        DataRootOwner._retain_failed_build(pending)
        with pytest.raises(RuntimeError, match="Store close refusal"):
            DataRootOwner.retry_pending_build(root)
        # ProductEnvironment.close did not return: it had retired the base
        # Environment but its Store close raised. The cleanup owner must keep
        # the exact Environment as well as its Store until close returns.
        assert pending.environment is original_environment
        assert pending.store is original_store
        assert owner.acquired
        with pytest.raises(RuntimeError, match="DATA_ROOT_IN_USE"):
            DataRootOwner(root).acquire()

        DataRootOwner.retry_pending_build(root)
        assert close_events == [
            ("environment", 1),  # factory cleanup refusal
            ("environment", 2),  # Host retry: base close succeeds, Store close refuses
            ("store", 1),
            ("environment", 3),  # retry same Env; Store close now succeeds
            ("store", 2),        # cleanup owner then idempotently closes same Store
            ("store", 3),
        ]
        assert original_store._connection_closed
        assert not owner.acquired
        assert root not in DataRootOwner._pending_builds
    finally:
        if root in DataRootOwner._pending_builds:
            _retry_pending(root)
        else:
            environment = locals().get("original_environment")
            store = locals().get("original_store")
            if environment is not None:
                try:
                    environment.close()
                except BaseException:
                    pass
            if store is not None:
                try:
                    store.close()
                except BaseException:
                    pass
            if owner.acquired:
                owner.release()


def test_agent_tools_factory_retains_original_environment_and_store_for_host_retry(
    tmp_path, monkeypatch
):
    """AgentTools factory hands Host its exact allocated Env/Store after close failure."""
    from pacthold.adapters.sqlite.environment.store import SqliteStorePort
    from pacthold.environment import Environment
    from ordessa_server.composition.agent_tools import AgentToolsDeployment
    from ordessa_server.composition.runtime import _FailedBuildCleanup

    root = tmp_path / "agent-tools-factory-root"
    owner = DataRootOwner(root)
    owner.acquire()
    original_environment_close = Environment.close
    original_inspect_and_close = SqliteStorePort.inspect_and_close
    environment_attempts = 0
    store_attempts = 0

    def fail_after_environment_allocation(*_args):
        _raise("controlled AgentTools owner-wiring failure")

    def fail_first_environment_retirement(environment):
        nonlocal environment_attempts
        environment_attempts += 1
        if environment_attempts == 1:
            _raise("controlled AgentTools Environment close refusal")
        return original_environment_close(environment)

    def fail_first_store_retirement(store, inspector):
        nonlocal store_attempts
        store_attempts += 1
        if store_attempts == 1:
            _raise("controlled AgentTools Store close refusal")
        return original_inspect_and_close(store, inspector)

    deployment = AgentToolsDeployment(
        fingerprint_port=_fingerprint_port(),
        agent_contract_version="agent-assembly/3",
        policy_factory=lambda _identity: type("Policy", (), {
            "admit_invoke": staticmethod(lambda *_args: True),
            "admit_object_access": staticmethod(lambda *_args: True),
        })(),
        owner_ports_factory=lambda _environment: object(),
    )
    deployment._wire_owner = fail_after_environment_allocation
    monkeypatch.setattr(Environment, "close", fail_first_environment_retirement)
    monkeypatch.setattr(SqliteStorePort, "inspect_and_close", fail_first_store_retirement)

    try:
        with pytest.raises(RuntimeError, match="owner-wiring failure") as failed:
            deployment.owned_environment_factory(root / "state" / "core.sqlite", owner)
        construction_failure = failed.value
        original_environment = construction_failure.pending_environment_close
        original_store = construction_failure.pending_store_close
        assert original_environment is not None
        assert original_store is original_environment.store_port
        assert original_environment._store_released is False
        assert owner.acquired

        pending = _FailedBuildCleanup(
            owner, plugin_host=None, core_binding=None,
            store=original_store, environment=original_environment,
        )
        DataRootOwner._retain_failed_build(pending)
        with pytest.raises(RuntimeError, match="Store close refusal"):
            DataRootOwner.retry_pending_build(root)
        assert environment_attempts == 2
        assert store_attempts == 1
        # OwnedEnvironment.close raised from Store shutdown, so the pending
        # cleanup retains that same Environment until a later close returns.
        assert pending.environment is original_environment
        assert pending.store is original_store
        assert original_environment._store_released is False
        assert owner.acquired
        with pytest.raises(RuntimeError, match="DATA_ROOT_IN_USE"):
            DataRootOwner(root).acquire()

        DataRootOwner.retry_pending_build(root)
        assert store_attempts == 2
        assert original_environment._store_released is True
        assert not owner.acquired
        assert root not in DataRootOwner._pending_builds
    finally:
        if root in DataRootOwner._pending_builds:
            _retry_pending(root)
        elif owner.acquired:
            owner.release()


def test_agent_tools_store_close_failure_is_retryable_and_not_marked_released(tmp_path):
    """A failed real Store shutdown must not cache a released state/report."""
    from ordessa_server.composition.agent_tools import AgentServiceConfiguration, build_agent_runtime

    runtime = build_agent_runtime(
        AgentServiceConfiguration(Path(tmp_path / "agent-tools-root")),
        fingerprint_port=_fingerprint_port(),
    )
    environment = runtime.core_binding.environment
    store = environment.store_port
    original_inspect_and_close = store.inspect_and_close
    attempts = 0

    def fail_once(snapshot):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("controlled Store close refusal")
        return original_inspect_and_close(snapshot)

    store.inspect_and_close = fail_once
    try:
        with pytest.raises(RuntimeError, match="Store close refusal"):
            environment.close()
        assert attempts == 1
        assert environment._store_released is False
        assert environment._unit_shutdown_report is None
        assert runtime.owner.acquired

        report = environment.close()
        assert attempts == 2
        assert environment._store_released is True
        assert environment._unit_shutdown_report is report
        assert runtime.owner.acquired
    finally:
        # The runtime still owns the process lock; close its original round
        # after the behavior under test has established a successful Store close.
        if not environment._store_released:
            environment.close()
        runtime.stop()


class _CloseFailOnceStream:
    """Transparent stream proxy that refuses close once without closing its fd."""

    def __init__(self, stream):
        self.stream = stream
        self.close_attempts = 0

    def fileno(self):
        return self.stream.fileno()

    @property
    def closed(self):
        return self.stream.closed

    def close(self):
        self.close_attempts += 1
        if self.close_attempts == 1:
            raise OSError("controlled owner stream close refusal")
        return self.stream.close()


def test_data_root_owner_refuses_replacement_until_original_fd_really_closes(tmp_path):
    root = tmp_path / "owner-root"
    owner = DataRootOwner(root)
    owner.acquire()
    original_stream = owner._stream
    stream = _CloseFailOnceStream(original_stream)
    owner._stream = stream
    try:
        with pytest.raises(OSError, match="stream close refusal"):
            owner.release()
        assert owner._stream is stream
        assert not original_stream.closed
        assert owner.acquired is True
        with pytest.raises(RuntimeError, match="DATA_ROOT_IN_USE"):
            DataRootOwner(root).acquire()

        owner.release()
        assert stream.close_attempts == 2
        assert original_stream.closed
        assert owner.acquired is False

        replacement = DataRootOwner(root)
        replacement.acquire()
        assert replacement.acquired is True
        replacement.release()
    finally:
        if owner._stream is not None and not original_stream.closed:
            try:
                owner.release()
            except OSError:
                owner.release()


class _CountingStream:
    """Count actual original-owner descriptor close calls."""

    def __init__(self, stream):
        self.stream = stream
        self.close_attempts = 0

    def fileno(self):
        return self.stream.fileno()

    @property
    def closed(self):
        return self.stream.closed

    def close(self):
        self.close_attempts += 1
        return self.stream.close()


def test_concurrent_pending_retry_serializes_real_plugin_host_shutdown(tmp_path, monkeypatch):
    """Concurrent Host retries do not repeat a live PluginHost disposal path."""
    from server_plugin_api import (
        SERVER_PLUGIN_API_VERSION, ServerPluginDescriptor, ServerPluginRegistration,
    )
    from ordessa_server.composition.plugin_host import ServerPluginHost
    from ordessa_server.composition.runtime import _FailedBuildCleanup

    root = tmp_path / "concurrent-plugin-host-root"
    owner = DataRootOwner(root)
    owner.acquire()
    disposal_entered = Event()
    allow_disposal = Event()
    second_retry_entered = Event()
    second_retry_continue = Event()
    second_active_ids = Event()
    disposal_count = 0
    active_ids_calls = 0
    calls_lock = Lock()

    class LocalControlledPlugin:
        def descriptor(self):
            return ServerPluginDescriptor(
                id="controlled.cleanup",
                display_name="controlled cleanup plugin",
                version="1",
                api_version=SERVER_PLUGIN_API_VERSION,
            )

        def build(self, _context):
            def dispose():
                nonlocal disposal_count
                disposal_count += 1
                disposal_entered.set()
                if not allow_disposal.wait(timeout=5):
                    raise RuntimeError("controlled plugin disposal was not released")
            return ServerPluginRegistration(disposal=dispose)

    host = ServerPluginHost()
    host.activate(LocalControlledPlugin())
    original_active_ids = host.active_ids

    def observed_active_ids():
        nonlocal active_ids_calls
        with calls_lock:
            active_ids_calls += 1
            if active_ids_calls >= 2:
                second_active_ids.set()
        return original_active_ids()

    host.active_ids = observed_active_ids
    pending = _FailedBuildCleanup(
        owner, plugin_host=host, core_binding=None, store=None, environment=None,
    )
    DataRootOwner._retain_failed_build(pending)
    original_retry = _FailedBuildCleanup.retry
    retry_calls = 0

    def observe_second_retry(cleanup):
        nonlocal retry_calls
        with calls_lock:
            retry_calls += 1
            is_second = retry_calls == 2
        if is_second:
            second_retry_entered.set()
            if not second_retry_continue.wait(timeout=5):
                raise RuntimeError("second retry was not released")
        return original_retry(cleanup)

    monkeypatch.setattr(_FailedBuildCleanup, "retry", observe_second_retry)
    futures = []
    pool = ThreadPoolExecutor(max_workers=2)

    def retry_pending():
        return DataRootOwner.retry_pending_build(root)

    try:
        first = pool.submit(retry_pending)
        futures.append(first)
        assert disposal_entered.wait(timeout=5), "first retry did not enter real PluginHost disposal"

        second = pool.submit(retry_pending)
        futures.append(second)
        assert second_retry_entered.wait(timeout=5), "second retry did not reach the same pending cleanup"
        second_retry_continue.set()

        # The first retry remains inside the real local plugin's disposal.
        # With the rev14 per-pending retry lock, the second cannot inspect
        # PluginHost state or finish cleanup until that exact call returns.
        assert not second_active_ids.wait(timeout=0.1)
        assert not second.done()
        allow_disposal.set()
        first.result(timeout=10)
        second.result(timeout=10)

        assert disposal_count == 1
        assert active_ids_calls == 2  # second caller enters only after first completes
        assert host.active_ids() == ()
        assert not owner.acquired
        assert root not in DataRootOwner._pending_builds
    finally:
        # Release controls before joining workers, even when an assertion
        # fails. Restore the monkeypatch only after all worker calls have left.
        allow_disposal.set()
        second_retry_continue.set()
        for future in futures:
            try:
                future.result(timeout=10)
            except BaseException:
                pass
        pool.shutdown(wait=True)
        monkeypatch.undo()
        if root in DataRootOwner._pending_builds:
            _retry_pending(root)
        elif owner.acquired:
            owner.release()


def test_original_cleanup_refuses_same_thread_recursive_disposal(tmp_path):
    from server_plugin_api import SERVER_PLUGIN_API_VERSION, ServerPluginDescriptor, ServerPluginRegistration
    from ordessa_server.composition.plugin_host import ServerPluginHost
    from ordessa_server.composition.runtime import _FailedBuildCleanup
    root=tmp_path/'reentrant-original-cleanup'
    owner=DataRootOwner(root);owner.acquire()
    host=ServerPluginHost();calls=[];pending=None
    class LocalPlugin:
        def descriptor(self):
            return ServerPluginDescriptor(id='controlled.reentry',display_name='controlled reentry',version='1',api_version=SERVER_PLUGIN_API_VERSION)
        def build(self,context):
            def dispose():
                calls.append('dispose')
                with pytest.raises(OwnerAssemblyRefused,match='already in progress'):
                    pending.retry()
            return ServerPluginRegistration(disposal=dispose)
    host.activate(LocalPlugin())
    pending=_FailedBuildCleanup(owner,host,None)
    DataRootOwner._retain_failed_build(pending)
    try:
        DataRootOwner.retry_pending_build(root)
        assert calls==['dispose']
        assert host.active_ids()==()
        assert not owner.acquired
        assert root not in DataRootOwner._pending_builds
        assert pending._retry_active is False
    finally:
        if root in DataRootOwner._pending_builds:
            DataRootOwner.retry_pending_build(root)
        elif owner.acquired:
            owner.release()
