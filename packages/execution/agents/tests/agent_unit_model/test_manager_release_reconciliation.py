"""Negative reconciliation cases against the real same-owner joint fixture."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import sqlite3
from threading import Event

import pytest

from test_manager_node_joint import joint
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_units.definitions.operations import node_holder
from ordessa_units.management import UnitManager
from ordessa_units.management.manager import ManagerReleaseReceipt, UnitManagementRefused


def _release_with_node_commit_failure(joint):
    """Create a real live release receipt while preserving the Node claim."""
    operation = joint.services.assembly.prepare(
        RequestKey('env', 'principal', 'reconcile-prepare'), joint.profile, {}, {})
    assert operation.status == 'published'
    from ordessa_units.bindings.publication import decode_node_ref
    node_ref = decode_node_ref(operation.intent.node_ref)
    node = joint.services.nodes.read(node_ref)
    unit_ref = node['binding']['harnessUnitRef']
    unit = joint.manager.find(unit_ref)
    joint.current.acquired = dict(operation.intent.node_ref)
    joint.current.evidence = dict(unit_ref)
    joint.services.lifecycle.stop(RequestKey('env', 'principal', 'reconcile-setup-stop'), node_ref, {})

    request = RequestKey('env', 'principal', 'reconcile-release-commit-failure')
    original = joint.store.record_operation_step

    def fail_node_commit(key, *args, **kwargs):
        if key == request:
            raise RuntimeError('controlled original Node COMMIT failure')
        return original(key, *args, **kwargs)

    joint.store.record_operation_step = fail_node_commit
    try:
        with pytest.raises(RuntimeError, match='Node COMMIT'):
            joint.services.lifecycle.release(request, node_ref, {})
    finally:
        joint.store.record_operation_step = original

    assert joint.manager.find(unit_ref) is unit
    return joint, node_ref, node, unit_ref, unit, request


def test_cold_manager_and_mismatched_identity_cannot_reconcile_or_replay(joint):
    j, node_ref, node, unit_ref, unit, request = _release_with_node_commit_failure(joint)
    before = list(j.events)
    # Inspect the same public Journal path through an independent read-only
    # SQLite connection. This proves durable rows survive while a fresh
    # Manager still has no live Unit/receipt to reconcile them.
    journal_path = j.records.journal.path.resolve()
    original_unit = j.records.owner_read_unit(unit_ref['unitId'])
    original_termination = j.records.owner_read_termination(unit_ref['unitId'], 'release')
    with closing(sqlite3.connect(journal_path.as_uri() + '?mode=ro', uri=True)) as readonly:
        reservation = readonly.execute(
            'SELECT unit_ref,intent_json FROM harness_unit_reservations WHERE unit_ref=?',
            (unit_ref['unitId'],)).fetchone()
        termination = readonly.execute(
            'SELECT state,source_revision,identity_json,outcome_json '
            'FROM harness_unit_terminations WHERE unit_ref=? AND action=?',
            (unit_ref['unitId'], 'release')).fetchone()
    assert reservation == (unit_ref['unitId'], original_unit.intent_json)
    assert termination is not None
    assert termination[0] == original_termination['state'] == 'confirmed'
    assert termination[1] == original_termination['sourceRevision']
    assert json.loads(termination[2]) == dict(original_termination['identity'])
    assert json.loads(termination[3]) == dict(original_termination['outcome'])

    factory_calls = []
    cold = UnitManager(create_instance=lambda plan: factory_calls.append(plan), records=j.records,
                       verifier=j.manager.verifier)
    with pytest.raises(UnitManagementRefused):
        cold.find(unit_ref)
    with pytest.raises(UnitManagementRefused):
        cold.release_reconciliation(unit_ref, request=request)
    assert factory_calls == []
    with pytest.raises(UnitManagementRefused):
        j.manager.release_reconciliation(
            unit_ref, request=RequestKey('env', 'principal', 'different-release'))
    wrong_ref = dict(unit_ref, unitId=unit_ref['unitId'] + '-foreign')
    with pytest.raises(UnitManagementRefused):
        j.manager.release_reconciliation(wrong_ref, request=request)
    assert j.events == before
    assert j.manager.find(unit_ref) is unit
    assert j.store.read_operation_step(request, 'release').outcome == 'possibly-dispatched'


def test_usage_revision_change_blocks_original_live_reconciliation(joint):
    j, node_ref, node, unit_ref, unit, request = _release_with_node_commit_failure(joint)
    holder = node_holder('env', node_ref.instance_id, node_ref.generation)
    rows = j.store.read_usages('env', holder)
    assert rows
    usage_id = rows[0]['usageId']
    j.store._conn.execute(
        'UPDATE env_usages SET revision=revision+1 WHERE usage_id=?', (usage_id,))
    j.store._conn.commit()

    with pytest.raises(UnitGuaranteeUnavailable):
        j.services.lifecycle.reconcile_release(request)
    assert j.store.read_operation_step(request, 'release').outcome == 'possibly-dispatched'
    assert j.manager.find(unit_ref) is unit
    assert j.events.count('spawn') == 1


def test_direct_manager_release_cannot_pop_deferred_node_handle(joint):
    j, node_ref, node, unit_ref, unit, request = _release_with_node_commit_failure(joint)
    context, result, receipt = j.manager.release_reconciliation(unit_ref, request=request)
    assert result['state'] == 'confirmed'
    before = list(j.events)
    with pytest.raises(UnitManagementRefused):
        j.manager.release(unit_ref, context)
    assert j.manager.find(unit_ref) is unit
    assert j.events == before
    assert j.store.read_operation_step(request, 'release').outcome == 'possibly-dispatched'


def test_pending_node_release_fences_concurrent_direct_manager_release(joint):
    j = joint
    operation = j.services.assembly.prepare(
        RequestKey('env', 'principal', 'pending-release-prepare'), j.profile, {}, {})
    assert operation.status == 'published'
    from ordessa_units.bindings.publication import decode_node_ref
    node_ref = decode_node_ref(operation.intent.node_ref)
    node = j.services.nodes.read(node_ref)
    unit_ref = node['binding']['harnessUnitRef']
    unit = j.manager.find(unit_ref)
    j.current.acquired = dict(operation.intent.node_ref)
    j.current.evidence = dict(unit_ref)
    j.services.lifecycle.stop(RequestKey('env', 'principal', 'pending-release-setup-stop'), node_ref, {})

    entered_release, allow_release = Event(), Event()
    original_release = unit.release
    original_invocation = []
    release_calls = []

    def delayed_original_release(ref, invocation):
        release_calls.append(invocation)
        if len(release_calls) == 1:
            original_invocation.append(invocation)
            entered_release.set()
            if not allow_release.wait(10):
                raise TimeoutError('test did not release controlled Unit effect')
            return original_release(ref, invocation)
        raise AssertionError('concurrent direct Manager release reached the Unit effect')

    unit.release = delayed_original_release
    request = RequestKey('env', 'principal', 'pending-release-concurrent')
    with ThreadPoolExecutor(max_workers=1) as pool:
        release = pool.submit(j.services.lifecycle.release, request, node_ref, {})
        try:
            assert entered_release.wait(10)
            assert len(original_invocation) == 1
            before = list(j.events)
            with pytest.raises(UnitManagementRefused):
                j.manager.release(unit_ref, original_invocation[0])
            assert j.manager.find(unit_ref) is unit
            assert j.events == before
            assert j.store.read_operation_step(request, 'release').outcome == 'possibly-dispatched'
            holder = node_holder('env', node_ref.instance_id, node_ref.generation)
            assert all(row['state'] == 'active' for row in j.store.read_usages('env', holder))
        finally:
            allow_release.set()
        result = release.result(timeout=10)

    assert result['action'] == 'release'
    assert result['operationRef'] == j.store.read_operation(request).intent.operation_ref
    assert j.store.read_operation_step(request, 'release').outcome == 'concluded'
    holder = node_holder('env', node_ref.instance_id, node_ref.generation)
    assert all(row['state'] == 'released' for row in j.store.read_usages('env', holder))
    assert j.manager.list() == ()
    assert len(release_calls) == 1
    assert j.events.count('spawn') == 1


def test_finalize_rejects_forged_receipt_and_changed_manager_binding(joint):
    j, node_ref, node, unit_ref, unit, request = _release_with_node_commit_failure(joint)
    _, _, receipt = j.manager.release_reconciliation(unit_ref, request=request)
    with pytest.raises(TypeError):
        ManagerReleaseReceipt()
    with pytest.raises(UnitManagementRefused):
        j.manager.finalize_release(object(), request=request)
    original_verifier = j.manager.verifier
    j.manager.verifier = object()
    try:
        with pytest.raises(UnitManagementRefused, match='binding changed'):
            j.manager.finalize_release(receipt, request=request)
    finally:
        j.manager.verifier = original_verifier
    assert j.manager.find(unit_ref) is unit
    assert j.store.read_operation_step(request, 'release').outcome == 'possibly-dispatched'


def test_committed_release_finalize_failure_recovers_without_replaying_effect(joint):
    j = joint
    operation = j.services.assembly.prepare(
        RequestKey('env', 'principal', 'committed-finalize-prepare'), j.profile, {}, {})
    assert operation.status == 'published'
    from ordessa_units.bindings.publication import decode_node_ref
    node_ref = decode_node_ref(operation.intent.node_ref)
    node = j.services.nodes.read(node_ref)
    unit_ref = node['binding']['harnessUnitRef']
    unit = j.manager.find(unit_ref)
    j.current.acquired = dict(operation.intent.node_ref)
    j.current.evidence = dict(unit_ref)
    j.services.lifecycle.stop(RequestKey('env', 'principal', 'committed-finalize-setup-stop'), node_ref, {})

    request = RequestKey('env', 'principal', 'committed-finalize-recovery')
    original_release = unit.release
    release_calls = []

    def count_original_release(ref, invocation):
        release_calls.append(invocation)
        return original_release(ref, invocation)

    unit.release = count_original_release
    original_finalize = j.manager.finalize_release

    def fail_before_finalize(*_args, **_kwargs):
        raise RuntimeError('controlled Manager retirement failure after Node COMMIT')

    j.manager.finalize_release = fail_before_finalize
    try:
        with pytest.raises(RuntimeError, match='after Node COMMIT'):
            j.services.lifecycle.release(request, node_ref, {})
    finally:
        j.manager.finalize_release = original_finalize

    claim = j.store.read_operation_step(request, 'release')
    holder = node_holder('env', node_ref.instance_id, node_ref.generation)
    usages = j.store.read_usages('env', holder)
    assert claim.outcome == 'concluded'
    assert usages and all(row['state'] == 'released' for row in usages)
    assert j.manager.find(unit_ref) is unit
    assert len(release_calls) == 1
    before_events = list(j.events)

    recovered = j.services.lifecycle.finalize_release(request)
    assert recovered['operationRef'] == j.store.read_operation(request).intent.operation_ref
    assert j.manager.list() == ()
    assert j.store.read_operation_step(request, 'release') == claim
    assert j.store.read_usages('env', holder) == usages
    assert len(release_calls) == 1
    assert j.events == before_events

    repeated = j.services.lifecycle.finalize_release(request)
    assert repeated == recovered
    assert j.store.read_operation_step(request, 'release') == claim
    assert j.store.read_usages('env', holder) == usages
    assert len(release_calls) == 1
    assert j.events == before_events


def test_finalize_committed_release_refuses_wrong_request_and_uncommitted_step(joint):
    j, node_ref, node, unit_ref, unit, request = _release_with_node_commit_failure(joint)
    before = list(j.events)
    holder = node_holder('env', node_ref.instance_id, node_ref.generation)
    usages = j.store.read_usages('env', holder)
    with pytest.raises(UnitGuaranteeUnavailable):
        j.services.lifecycle.finalize_release(
            RequestKey('env', 'principal', 'different-committed-release'))
    with pytest.raises(UnitManagementRefused):
        j.services.lifecycle.finalize_release(request)
    assert j.store.read_operation_step(request, 'release').outcome == 'possibly-dispatched'
    assert j.store.read_usages('env', holder) == usages
    assert all(row['state'] == 'active' for row in usages)
    assert j.manager.find(unit_ref) is unit
    assert j.events == before


def test_unknown_release_claim_cannot_be_promoted_by_reconciliation(joint):
    j = joint
    operation = j.services.assembly.prepare(
        RequestKey('env', 'principal', 'unknown-release-prepare'), j.profile, {}, {})
    assert operation.status == 'published'
    from ordessa_units.bindings.publication import decode_node_ref
    node_ref = decode_node_ref(operation.intent.node_ref)
    node = j.services.nodes.read(node_ref)
    unit_ref = node['binding']['harnessUnitRef']
    unit = j.manager.find(unit_ref)
    j.current.acquired = dict(operation.intent.node_ref)
    j.current.evidence = dict(unit_ref)
    j.services.lifecycle.stop(RequestKey('env', 'principal', 'unknown-release-setup-stop'), node_ref, {})
    request = RequestKey('env', 'principal', 'unknown-release-claim')

    def unavailable_observation(*_args, **_kwargs):
        raise UnitGuaranteeUnavailable('controlled missing owner observation')

    j.services.lifecycle._observation_port.observe = unavailable_observation
    result = j.services.lifecycle.release(request, node_ref, {})
    assert result['status'] == 'unknown'
    assert j.store.read_operation_step(request, 'release').outcome == 'unknown'
    before = list(j.events)
    with pytest.raises(UnitGuaranteeUnavailable):
        j.services.lifecycle.reconcile_release(request)
    assert j.store.read_operation_step(request, 'release').outcome == 'unknown'
    assert j.manager.find(unit_ref) is unit
    assert j.events == before


@pytest.mark.parametrize('change', ['revoked', 'expired'])
def test_original_grant_revocation_or_expiry_blocks_live_reconciliation(joint, change):
    j, node_ref, node, unit_ref, unit, request = _release_with_node_commit_failure(joint)
    authority = j.issuer._authority
    if change == 'revoked':
        authority.allowed = False
    else:
        authority.expiry = 49  # The original fixture clock is 50.

    before = list(j.events)
    with pytest.raises(UnitManagementRefused):
        j.services.lifecycle.reconcile_release(request)
    assert j.store.read_operation_step(request, 'release').outcome == 'possibly-dispatched'
    assert j.manager.find(unit_ref) is unit
    assert j.events == before
