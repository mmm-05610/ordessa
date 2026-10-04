"""C2 closeout regressions for Environment invoke/query dispatch ownership.

These tests are intentionally authored before the implementation change. They
exercise the public Environment signatures with a durable SQLite port and do
not expand the frozen StorePort protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, Thread

import pytest

from ordessa_environment_api import (
    AdmissionRefusedError, IdentityMismatchError, RequestKey,
)
from ordessa_environment_api.guarantee import GuaranteeLevel
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from pacthold.core.registration import BatchAlreadyUsedError, CoreContributionSet
from pacthold.environment import Environment, InstallationRecord


@dataclass(frozen=True)
class _Contract:
    contract_id: str = "closeout.dispatch@1"


def _key(request_id: str, *, environment: str = "env-closeout", principal: str = "user:local:test") -> RequestKey:
    return RequestKey(environment_namespace=environment, principal_scope=principal,
                       request_id=request_id)


class _DenyInvoke:
    def admit_invoke(self, principal: str, surface: str, guarantee: str) -> bool:
        return False

    def admit_object_access(self, principal: str, object_ref: str, mode: str) -> bool:
        return True


class _AllowInvoke:
    def admit_invoke(self, principal: str, surface: str, guarantee: str) -> bool:
        return True

    def admit_object_access(self, principal: str, object_ref: str, mode: str) -> bool:
        return True


def _environment(store, *, policy="allow") -> Environment:
    env = Environment(
        "env-closeout", store=store,
        policy=_AllowInvoke() if policy == "allow" else policy,
        fingerprint_port=ProtectedFingerprintHmac({"fixture": b"isolated-fixture-key"},
                                                  active_key_id="fixture"),
    )
    env.install(InstallationRecord("closeout.plugin", "a" * 64))
    env.enable("closeout.plugin")
    env.activate("closeout.plugin", CoreContributionSet(contracts=(_Contract,)))
    return env


def _reliable(**kwargs):
    return {"guarantee": GuaranteeLevel.RELIABLE, "input_digest": "b" * 64, **kwargs}


def test_invoke_runs_handler_once_and_persists_result_before_replay(tmp_path):
    store = SqliteStorePort(tmp_path / "environment.sqlite3")
    env = _environment(store)
    effects = []

    first, current = env.invoke(
        "closeout.dispatch", _key("invoke-once"), handler=lambda: effects.append("native") or {"accepted": True},
        **_reliable(),
    )
    replay, replay_current = env.invoke(
        "closeout.dispatch", _key("invoke-once"), handler=lambda: effects.append("duplicate"),
        **_reliable(),
    )

    assert effects == ["native"]
    assert replay == first
    assert replay_current == current
    assert current.outcome == "concluded"
    store.close()


def test_handler_failure_is_durable_unknown_and_never_reissued_after_restart(tmp_path):
    path = tmp_path / "environment.sqlite3"
    store = SqliteStorePort(path)
    env = _environment(store)
    effects = []

    def interrupted_handler():
        effects.append("effect-may-have-started")
        raise RuntimeError("connection lost after dispatch")

    with pytest.raises(RuntimeError, match="connection lost"):
        env.invoke("closeout.dispatch", _key("unknown-after-failure"),
                   handler=interrupted_handler, **_reliable())
    store.close()

    reopened = SqliteStorePort(path, allow_takeover=True)
    restarted = _environment(reopened)
    replay, current = restarted.invoke(
        "closeout.dispatch", _key("unknown-after-failure"),
        handler=lambda: effects.append("must-not-reissue"), **_reliable(),
    )
    assert effects == ["effect-may-have-started"]
    assert replay.delivery == "unknown"
    assert current.outcome == "unknown"
    assert restarted.query(_key("unknown-after-failure")) == (replay, current)
    reopened.close()


def test_policy_refusal_does_not_spend_request_key_before_admission(tmp_path):
    path = tmp_path / "environment.sqlite3"
    store = SqliteStorePort(path)
    denied = _environment(store, policy=_DenyInvoke())
    effects = []
    with pytest.raises(AdmissionRefusedError):
        denied.invoke("closeout.dispatch", _key("policy-retry"),
                      handler=lambda: effects.append("denied"), **_reliable())
    assert effects == []
    store.close()

    reopened = SqliteStorePort(path, allow_takeover=True)
    admitted = _environment(reopened)
    receipt, current = admitted.invoke(
        "closeout.dispatch", _key("policy-retry"),
        handler=lambda: effects.append("admitted") or {"ok": True}, **_reliable(),
    )
    assert effects == ["admitted"]
    assert current.outcome == "concluded"
    assert receipt.delivery == "acknowledged"
    reopened.close()


def test_missing_policy_denies_effect_handler_without_spending_key(tmp_path):
    store = SqliteStorePort(tmp_path / "environment.sqlite3")
    env = _environment(store, policy=None)
    effects = []

    with pytest.raises(AdmissionRefusedError, match="policy"):
        env.invoke("closeout.dispatch", _key("no-policy"),
                   handler=lambda: effects.append("must-not-run"),
                   guarantee=GuaranteeLevel.RELIABLE, input_digest="e" * 64)

    assert effects == []
    assert store.read_request(_key("no-policy")) is None
    store.close()


def test_drain_refuses_invoke_before_durable_claim_or_handler(tmp_path):
    store = SqliteStorePort(tmp_path / "environment.sqlite3")
    env = _environment(store)
    env.drain(env.bind("closeout.dispatch").provider_activation)
    effects = []

    with pytest.raises(AdmissionRefusedError):
        env.invoke("closeout.dispatch", _key("drained"),
                   handler=lambda: effects.append("late"), **_reliable())

    assert effects == []
    assert env.query(_key("drained")) is None
    assert store.read_request(_key("drained")) is None
    store.close()


def test_query_reads_namespaced_durable_history_not_only_instance_memory(tmp_path):
    path = tmp_path / "environment.sqlite3"
    store = SqliteStorePort(path)
    env = _environment(store)
    request = _key("durable-query")
    env.invoke("closeout.dispatch", request, handler=lambda: {"ok": True}, **_reliable())
    store.close()

    reopened = SqliteStorePort(path, allow_takeover=True)
    restarted = Environment("env-closeout", store=reopened)
    history = restarted.query(request)
    assert history is not None
    assert history[0].request == request
    assert history[1].outcome == "concluded"
    # The same request id under another principal/environment is a different
    # logical request and must not resolve the first namespace's history.
    with pytest.raises(IdentityMismatchError):
        restarted.query(_key("durable-query", environment="other-env"))
    assert restarted.query(_key("durable-query", principal="user:local:other")) is None
    reopened.close()


def test_same_key_different_capture_conflicts_after_restart(tmp_path):
    path = tmp_path / "environment.sqlite3"
    store = SqliteStorePort(path)
    env = _environment(store)
    effects = []
    env.invoke("closeout.dispatch", _key("digest-conflict"),
               handler=lambda: effects.append(1), guarantee=GuaranteeLevel.RELIABLE,
               input_digest="c" * 64)
    store.close()

    reopened = SqliteStorePort(path, allow_takeover=True)
    restarted = _environment(reopened)
    with pytest.raises(IdentityMismatchError):
        restarted.invoke("closeout.dispatch", _key("digest-conflict"),
                         handler=lambda: effects.append(2), guarantee=GuaranteeLevel.RELIABLE,
                         input_digest="d" * 64)
    assert effects == [1]
    reopened.close()


def test_activation_stage_reuses_environment_registry_and_retires_through_lifecycle():
    env = Environment("env-closeout")
    env.install(InstallationRecord("closeout.plugin", "a" * 64))
    with pytest.raises(AdmissionRefusedError, match="not enabled"):
        env.stage_activation("closeout.plugin", CoreContributionSet(contracts=(_Contract,)))
    env.enable("closeout.plugin")

    stage = env.stage_activation("closeout.plugin", CoreContributionSet(contracts=(_Contract,)))
    assert stage.state == "staged"
    assert env.registry_snapshot.contract_ids == ()
    receipt = stage.commit()
    assert receipt.activation == stage.receipt.activation
    assert stage.state == "committed"
    assert env.registry_snapshot.contract_ids == ("closeout.dispatch@1",)
    with pytest.raises(BatchAlreadyUsedError):
        stage.rollback()

    state, blockers = env.retire_activation(receipt.activation)
    assert state == "retired" and blockers == ()
    assert stage.state == "retired"
    assert env.registry_snapshot.contract_ids == ()


class _BlockingClaimStore(SqliteStorePort):
    def __init__(self, path):
        self.claim_entered = Event()
        self.allow_claim = Event()
        super().__init__(path)

    def claim_dispatch(self, key, digest):
        self.claim_entered.set()
        if not self.allow_claim.wait(timeout=5):
            raise TimeoutError("test did not release blocked dispatch claim")
        return super().claim_dispatch(key, digest)


def test_reliable_admission_and_claim_linearize_before_drain_but_handler_runs_unlocked(tmp_path):
    store = _BlockingClaimStore(tmp_path / "environment.sqlite3")
    env = _environment(store)
    handler_entered = Event()
    release_handler = Event()
    drained = Event()
    result = []

    def handler():
        handler_entered.set()
        if not release_handler.wait(timeout=5):
            raise TimeoutError("test did not release effect handler")

    invoke_thread = Thread(target=lambda: result.append(env.invoke(
        "closeout.dispatch", _key("claim-drain-order"), handler=handler, **_reliable())))
    invoke_thread.start()
    assert store.claim_entered.wait(timeout=2)

    activation = env.bind("closeout.dispatch").provider_activation
    drain_thread = Thread(target=lambda: (env.drain(activation), drained.set()))
    drain_thread.start()
    try:
        # The claim has entered but not committed. A drain cut must wait for
        # this admitted invoke to either acquire or refuse its durable claim.
        assert not drained.wait(timeout=0.1)
        store.allow_claim.set()
        assert handler_entered.wait(timeout=2)
        # The environment lock is released before external/native code runs, so a
        # drain can close new admissions while this already claimed call is in flight.
        assert drained.wait(timeout=2)
    finally:
        store.allow_claim.set()
        release_handler.set()
        invoke_thread.join(timeout=2)
        drain_thread.join(timeout=2)
        store.close()
    assert not invoke_thread.is_alive() and not drain_thread.is_alive()
    assert result[0][1].outcome == "concluded"


def test_raw_handler_has_one_in_process_claim_for_concurrent_same_key(tmp_path):
    store = SqliteStorePort(tmp_path / "environment.sqlite3")
    env = _environment(store)
    handler_entered = Event()
    duplicate_entered = Event()
    release_handler = Event()
    count_lock = Lock()
    calls = []

    def handler():
        with count_lock:
            calls.append("effect")
            if len(calls) > 1:
                duplicate_entered.set()
        handler_entered.set()
        if not release_handler.wait(timeout=5):
            raise TimeoutError("test did not release effect handler")

    request = _key("raw-process-claim")
    executor = ThreadPoolExecutor(max_workers=2)
    first = executor.submit(env.invoke, "closeout.dispatch", request,
                            guarantee=GuaranteeLevel.RAW, input_digest="f" * 64,
                            handler=handler)
    try:
        assert handler_entered.wait(timeout=2)
        second = executor.submit(env.invoke, "closeout.dispatch", request,
                                 guarantee=GuaranteeLevel.RAW, input_digest="f" * 64,
                                 handler=handler)
        assert not duplicate_entered.wait(timeout=0.1)
        second_result = second.result(timeout=2)
    finally:
        release_handler.set()
        first_result = first.result(timeout=2)
        if "second" in locals():
            second.result(timeout=2)
        executor.shutdown(wait=True)
        store.close()
    assert calls == ["effect"]
    assert second_result[1].outcome == "unknown"
    assert first_result[1].outcome == "concluded"


_SIGKILL_ENVIRONMENT_SCRIPT = textwrap.dedent("""
    import sys, time
    sys.path[:0] = sys.argv[2:5]
    from ordessa_environment_api import RequestKey
    from ordessa_environment_api.guarantee import GuaranteeLevel
    from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
    from pacthold.core.registration import CoreContributionSet
    from pacthold.environment import Environment, InstallationRecord
    store = SqliteStorePort(sys.argv[1])
    env = Environment('env-closeout', store=store,
        policy=type('Allow', (), {'admit_invoke': lambda *a: True,
                                  'admit_object_access': lambda *a: True})(),
        fingerprint_port=ProtectedFingerprintHmac({'fixture': b'isolated-fixture-key'},
                                                  active_key_id='fixture'))
    @__import__('dataclasses').dataclass(frozen=True)
    class Contract:
        contract_id = 'closeout.dispatch@1'
    env.install(InstallationRecord('closeout.plugin', 'a' * 64))
    env.enable('closeout.plugin')
    env.activate('closeout.plugin', CoreContributionSet(contracts=(Contract,)))
    def handler():
        print('CLAIMED', flush=True)
        time.sleep(60)
    env.invoke('closeout.dispatch', RequestKey('env-closeout', 'user:local:test', 'sigkill-window'),
        guarantee=GuaranteeLevel.RELIABLE, input_digest='1' * 64, handler=handler)
""")


def test_sigkill_after_durable_claim_recovers_unknown_without_redispatch(tmp_path):
    test_file = Path(__file__).resolve()
    package_root = test_file.parents[4]
    sources = [
        str(test_file.parents[2] / "src"),
        str(package_root / "backend" / "environment-api" / "src"),
        str(package_root / "backend" / "persistence-sqlite" / "src"),
    ]
    path = tmp_path / "environment.sqlite3"
    child = subprocess.Popen(
        [sys.executable, "-c", _SIGKILL_ENVIRONMENT_SCRIPT, str(path), *sources],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout.readline().strip() == "CLAIMED"
        os.kill(child.pid, signal.SIGKILL)
        assert child.wait(timeout=10) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)

    reopened = SqliteStorePort(path, allow_takeover=True)
    env = _environment(reopened)
    request = _key("sigkill-window")
    history = env.query(request)
    assert history is not None and history[1].outcome == "unknown"
    calls = []
    replay, current = env.invoke("closeout.dispatch", request,
                                 handler=lambda: calls.append("must-not-run"),
                                 guarantee=GuaranteeLevel.RELIABLE, input_digest="1" * 64)
    assert calls == []
    assert replay.delivery == "unknown" and current.outcome == "unknown"
    reopened.close()
