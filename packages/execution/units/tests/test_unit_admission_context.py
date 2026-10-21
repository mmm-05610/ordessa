"""Original SQLite fencing and owner shutdown, with no Kernel implementation."""
import hashlib
from types import SimpleNamespace
import pytest

from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.definitions.operations import OperationIntent, StepIntent
from ordessa_agents.harness.providers.registry.definition_admission import HarnessCatalog
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.admission.generation import (
    seed_fresh_environment, reserve_next_generation, read_fresh_basis,
    bind_journal, verify_journal_binding, ActivationGenerationRefused,
)
from ordessa_units.persistence.sqlite.store import SqliteUnitStore, WriterLockHeldError
from ordessa_units.management.manager import UnitManager, UnitManagementRefused


class Policy:
    def admit_object_access(self, *args):
        return True


class Fingerprint:
    def fingerprint(self, request, surface, digest):
        return hashlib.sha256((surface + digest).encode()).hexdigest()


def context(store):
    policy = Policy()
    return UnitAdmissionContext('env', store=store, policy=policy,
        fingerprint_port=Fingerprint(), harness_catalog=HarnessCatalog('env', policy=policy),
        material_catalog=MaterialCatalog('env'))


def test_original_generation_and_journal_survive_cold_store(tmp_path):
    path = tmp_path / 'original.sqlite'
    store = SqliteUnitStore(path)
    with store.transaction() as connection:
        seed_fresh_environment(connection, 'env')
    assert reserve_next_generation(store, 'env', 'brand', fingerprint_port=Fingerprint()) == 1
    basis = read_fresh_basis(store, 'env')
    bind_journal(store, 'env', '/exact/original-journal.sqlite')
    store.close()
    cold = SqliteUnitStore(path)
    try:
        assert read_fresh_basis(cold, 'env') == basis
        assert reserve_next_generation(cold, 'env', 'brand', fingerprint_port=Fingerprint()) == 2
        verify_journal_binding(cold, 'env', '/exact/original-journal.sqlite')
        with pytest.raises(ActivationGenerationRefused):
            verify_journal_binding(cold, 'env', '/different.sqlite')
    finally:
        cold.close()


def test_existing_unseeded_store_never_allocates_generation(tmp_path):
    store = SqliteUnitStore(tmp_path / 'existing.sqlite')
    try:
        with pytest.raises(ActivationGenerationRefused, match='lacks fresh'):
            reserve_next_generation(store, 'env', 'brand', fingerprint_port=Fingerprint())
        assert read_fresh_basis(store, 'env') is None
    finally:
        store.close()


def test_pending_operation_refuses_context_close_and_keeps_original_writer(tmp_path):
    path = tmp_path / 'original.sqlite'
    store = SqliteUnitStore(path)
    owner = context(store)
    request = RequestKey('env', 'local', 'start-1')
    intent = OperationIntent('original-start', 'unit-start', None,
        {'environmentNamespace': 'env'},
        (StepIntent('spawn', {'environmentNamespace': 'env'}, 'fixed-input', 'original-spawn'),))
    store.reserve_operation(request, 'fixed-input', intent)
    assert owner.pending()['operationRefs'] == ('original-start',)
    with pytest.raises(UnitGuaranteeUnavailable, match='pending'):
        owner.close()
    assert owner.draining is True
    owner.check_open()
    assert store.read_operation(request).status == 'reserved'
    with pytest.raises(WriterLockHeldError):
        SqliteUnitStore(path)
    store.close()  # fixture teardown is explicit; owner did not claim release.


def test_context_close_does_not_close_store_or_delete_history(tmp_path):
    path = tmp_path / 'original.sqlite'
    store = SqliteUnitStore(path)
    owner = context(store)
    store.record_key_tombstone('original-key')
    owner.close()
    assert store.has_key_tombstone('original-key')
    assert store.writer_token
    store.close()
    cold = SqliteUnitStore(path)
    try:
        assert cold.has_key_tombstone('original-key')
        with cold.transaction() as connection:
            tables = {row['name'] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'env_requests' in tables and 'env_usages' in tables
        assert not tables.intersection({'env_objects', 'response_slots', 'relations', 'change_reservations'})
    finally:
        cold.close()


def test_unknown_original_usage_blocks_close_without_releasing_it(tmp_path):
    store = SqliteUnitStore(tmp_path / 'original.sqlite')
    owner = context(store)
    with store.transaction() as connection:
        connection.execute("INSERT INTO env_usages(usage_id,environment,state,rights) VALUES('original-use','env','unknown','[]')")
    assert owner.pending()['usageIds'] == ('original-use',)
    with pytest.raises(UnitGuaranteeUnavailable):
        owner.close()
    assert owner.pending()['usageIds'] == ('original-use',)
    store.close()


def test_reserved_read_authorization_does_not_invent_terminal_or_block_close(tmp_path):
    store = SqliteUnitStore(tmp_path / 'original.sqlite')
    owner = context(store)
    request = RequestKey('env', 'local', 'cold-read')
    step = StepIntent('read', {'environmentNamespace': 'env'}, 'query-digest', 'cold-read.step')
    intent = OperationIntent('cold-read', 'unit-acp-query', None,
        {'environmentNamespace': 'env', 'acpTurnRead': {
            'unitRef': {'original': 'fixed'}, 'operationRef': 'original-prompt',
            'expectedPromptInputDigest': 'sha256:' + 'a' * 64}}, (step,))
    store.reserve_operation(request, 'query-digest', intent)
    assert owner.pending()['operationRefs'] == ()
    assert store.read_operation(request).status == 'reserved'
    # Any actual claim disables this exclusion: a kind string is no proof.
    assert store.claim_operation_step(request, 'query-digest', step).claimed
    assert owner.pending()['operationRefs'] == ('cold-read',)
    with pytest.raises(UnitGuaranteeUnavailable):
        owner.close()
    store.close()


def test_unclassified_historical_request_is_not_silently_dropped(tmp_path):
    store = SqliteUnitStore(tmp_path / 'original.sqlite')
    owner = context(store)
    store.reserve_request(RequestKey('env', 'local', 'old-spent'), 'original-digest')
    assert owner.pending()['unclassifiedRequests'] == ({
        'environmentNamespace': 'env', 'principalScope': 'local', 'requestId': 'old-spent'},)
    with pytest.raises(UnitGuaranteeUnavailable):
        owner.close()
    assert store.read_request(RequestKey('env', 'local', 'old-spent'))['digest'] == 'original-digest'
    store.close()


def test_unknown_factory_attempt_remains_pending_and_drain_never_replays(tmp_path):
    store = SqliteUnitStore(tmp_path / 'original.sqlite')
    owner = context(store)
    verifier = object()
    calls = []
    def factory(plan):
        calls.append(plan)
        raise RuntimeError('controlled factory failure before receipt')
    manager = UnitManager(create_instance=factory,
        records=SimpleNamespace(verifier=verifier), verifier=verifier)
    owner._agent_services = SimpleNamespace(unit_manager=manager)
    invocation = SimpleNamespace(facts={'action': 'prepare', 'query': False,
        'request': {'original': 'request'}, 'operationRef': 'original-prepare', 'stepId': 'prepare'})
    assert manager.references() == ()
    with pytest.raises(RuntimeError, match='factory failure'):
        manager.create({'fixed': 'plan'}, invocation)
    assert owner.pending()['creationHolds'] is True
    with pytest.raises(UnitGuaranteeUnavailable):
        owner.close()
    with pytest.raises(UnitManagementRefused, match='draining'):
        manager.create({'fixed': 'plan'}, invocation)
    assert len(calls) == 1
    store.close()
