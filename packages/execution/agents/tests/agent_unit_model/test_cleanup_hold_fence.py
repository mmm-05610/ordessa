"""Controlled same-SQLite counterexamples for the original Node claim fence."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from test_manager_node_joint import joint, managed_lifecycle as lifecycle
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitOperationUnknown
from ordessa_units.definitions.operations import node_holder


def test_stop_claim_blocks_release_until_original_step_concludes(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, stop_request, pin, current = lifecycle
    entered, continue_stop = Event(), Event()
    original_stop = provider.stop

    def delayed_stop(unit_ref, invocation):
        entered.set()
        assert continue_stop.wait(10)
        return original_stop(unit_ref, invocation)

    provider.stop = delayed_stop
    with ThreadPoolExecutor(max_workers=1) as pool:
        stop = pool.submit(coordinator.stop, stop_request, node_ref, {})
        try:
            ready = entered.wait(10)
            if not ready and stop.done():
                stop.result(timeout=1)
            assert ready
            release_request = RequestKey("env", "principal", "release-while-stop-claim-live")
            with pytest.raises(UnitOperationUnknown, match="unresolved effect claim"):
                coordinator.release(release_request, node_ref, {})
            rows = store.read_usages("env", node_holder("env", node_ref.instance_id, node_ref.generation))
            assert rows and all(row["state"] == "active" for row in rows)
            assert store.read_operation_step(stop_request, "stop").outcome == "possibly-dispatched"
            assert store.read_operation_step(release_request, "release") is None
        finally:
            continue_stop.set()
        stop.result(timeout=10)
    assert store.read_operation_step(stop_request, "stop").outcome == "concluded"
    after = RequestKey("env", "principal", "release-after-stop-conclusion")
    coordinator.release(after, node_ref, {})
    assert store.read_operation_step(after, "release").outcome == "concluded"
    assert all(row["state"] == "released" for row in store.read_usages(
        "env", node_holder("env", node_ref.instance_id, node_ref.generation)))


def test_release_first_refuses_new_stop_without_effect(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, pin, current = lifecycle
    # Real Unit release requires original confirmed stop. Arrange that native
    # precondition; the tested release is still the first release operation.
    coordinator.stop(RequestKey('env', 'principal', 'setup-stop'), node_ref, {})
    provider.lifecycle_calls.clear()
    release_request = RequestKey('env', 'principal', 'release-first')
    coordinator.release(release_request, node_ref, {})
    before = list(provider.lifecycle_calls)
    assert store.read_operation_step(release_request, 'release').outcome == 'concluded'
    rows = store.read_usages('env', node_holder('env', node_ref.instance_id, node_ref.generation))
    assert rows and all(row['state'] == 'released' for row in rows)
    from ordessa_units.errors import UnitGuaranteeUnavailable
    with pytest.raises(UnitGuaranteeUnavailable):
        coordinator.stop(request, node_ref, {})
    assert provider.lifecycle_calls == before
    assert store.read_operation(request) is None


def test_unknown_stop_blocks_release_and_keeps_original_holds(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, pin, current = lifecycle
    provider.fail_lifecycle = 'stop'
    coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, 'stop').outcome == 'unknown'
    before = list(provider.lifecycle_calls)
    release_request = RequestKey('env', 'principal', 'release-after-unknown-stop')
    with pytest.raises(UnitOperationUnknown, match='unresolved effect claim'):
        coordinator.release(release_request, node_ref, {})
    assert store.read_operation_step(release_request, 'release') is None
    assert provider.lifecycle_calls == before
    rows = store.read_usages('env', node_holder('env', node_ref.instance_id, node_ref.generation))
    assert rows and all(row['state'] == 'active' for row in rows)
    coordinator.stop(request, node_ref, {})
    assert provider.lifecycle_calls == before

def test_release_claim_blocks_stop_until_original_release_concludes(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, stop_request, pin, current = lifecycle
    # Arrange original native termination before testing the release claim
    # window. This is a real stop, not a forged release/termination receipt.
    coordinator.stop(RequestKey('env', 'principal', 'setup-stop'), node_ref, {})
    provider.lifecycle_calls.clear()
    entered, continue_release = Event(), Event()
    original_release = provider.release
    def delayed_release(unit_ref, invocation):
        entered.set()
        assert continue_release.wait(10)
        return original_release(unit_ref, invocation)
    provider.release = delayed_release
    release_request = RequestKey('env', 'principal', 'release-claim-first')
    with ThreadPoolExecutor(max_workers=1) as pool:
        release = pool.submit(coordinator.release, release_request, node_ref, {})
        try:
            ready = entered.wait(10)
            if not ready and release.done():
                release.result(timeout=1)
            assert ready
            with pytest.raises(UnitOperationUnknown, match='unresolved effect claim'):
                coordinator.stop(stop_request, node_ref, {})
            assert store.read_operation_step(stop_request, 'stop') is None
            assert store.read_operation_step(release_request, 'release').outcome == 'possibly-dispatched'
            rows = store.read_usages('env', node_holder('env', node_ref.instance_id, node_ref.generation))
            assert rows and all(row['state'] == 'active' for row in rows)
            assert provider.lifecycle_calls == []
        finally:
            continue_release.set()
        release.result(timeout=10)
    assert store.read_operation_step(release_request, 'release').outcome == 'concluded'
    rows = store.read_usages('env', node_holder('env', node_ref.instance_id, node_ref.generation))
    assert rows and all(row['state'] == 'released' for row in rows)
    assert provider.lifecycle_calls.count('stop') == 0
    assert provider.lifecycle_calls.count('release') == 1

@pytest.mark.parametrize('change', ['revision', 'rights', 'state'])
def test_original_usage_snapshot_change_is_refused_at_claim(lifecycle, change):
    from ordessa_units.definitions.operations import OperationRevisionConflict
    coordinator, owner, provider, node_ref, node, env, store, request, pin, current = lifecycle
    original_claim = store.claim_operation_step
    rows = store.read_usages('env', node_holder('env', node_ref.instance_id, node_ref.generation))
    assert rows
    usage_id = rows[0]['usageId']
    def changed_claim(key, digest, step, usages=(), **kwargs):
        # Synthetic fault after owner/authority observation and immediately
        # before the original Store transaction: no provider or user data.
        if key == request:
            if change == 'revision':
                store._conn.execute('UPDATE env_usages SET revision=revision+1 WHERE usage_id=?', (usage_id,))
            elif change == 'rights':
                store._conn.execute('UPDATE env_usages SET rights=? WHERE usage_id=?', ('["read"]', usage_id))
            else:
                store._conn.execute('UPDATE env_usages SET state=? WHERE usage_id=?', ('released', usage_id))
            store._conn.commit()
        return original_claim(key, digest, step, usages, **kwargs)
    store.claim_operation_step = changed_claim
    with pytest.raises(OperationRevisionConflict, match='Usage set changed before claim'):
        coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, 'stop') is None
    assert provider.lifecycle_calls == []
