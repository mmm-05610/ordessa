"""Real temporary SQLite; authority/native/verifier ports are controlled L1.

No native process/model, user directory, production admission or L2 claim.
The verifier fixture grants only objects explicitly issued in this test;
it does not establish production InvocationIssuer or native scope evidence.
"""
import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from ordessa_agents.harness.definitions import ApplicationTarget, Plan, Confirmed
from ordessa_units.records.operation_journal import OperationJournal, FenceObservation, JournalError
from ordessa_units.records.unit_records import (
    UnitRecords, UnitRecordsRefused, CanonicalConfigurationScopeRef, RecordTicket,
    TERMINATION_VERSION,
)

from agent_tools_fixtures.unit_records import (
    PROVIDER, NODE, ROOT, Verifier, Scope, Native, Epoch, parts,
    TermEvidence, reserve, begin, read,
)

def test_managed_turn_record_is_revisioned_and_tied_to_original_confirmed_session(tmp_path):
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    p = parts(tmp_path, managed_turn_opt_in=True)
    service, _, _, _, _, _ = p
    assert service.managed_turn_available
    unit, _ = reserve(p)
    ticket = begin(p, unit)
    service.record_session(ticket, expected_source_revision=2, state='confirmed',
                           evidence='real-native-owner-evidence')
    capture_ref = {'environmentNamespace': 'env', 'captureId': 'capture',
                   'captureRevision': 1, 'contentDigest': 'sha256:' + 'c' * 64}
    binding = {'contractVersion': 'harness-managed-codex-turn/1', 'operationRef': 'op-1',
        'unitRef': unit.public_ref, 'providerRef': PROVIDER, 'managementEpoch': 0,
        'protocol': 'codex-app-server/1', 'nativeRequestId': 'req-1',
        'frameDigest': 'sha256:' + 'd' * 64, 'method': 'turn/start',
        'nativeThreadId': 'native-observed-id', 'capturedInputRef': capture_ref,
        'contentDigest': capture_ref['contentDigest']}
    execution = {'contractVersion': 'workspace-managed-execute/1', 'operationRef': 'op-1',
        'environmentNamespace': 'env', 'principalScope': 'principal', 'nodeRef': NODE,
        'unitRef': unit.public_ref, 'captureRef': capture_ref,
        'contentDigest': capture_ref['contentDigest'], 'managementEpoch': 0,
        'evidenceRef': 'workspace-owner:execute-1'}
    request_key = safe_json({'environmentNamespace': 'env', 'principalScope': 'principal',
                             'requestId': 'request-1'})
    record, created = service.reserve_managed_turn(operation_ref='op-1', request_key=request_key,
        unit_ref=unit.unit_ref, input_digest='operation-digest', binding=binding,
        execution_evidence=execution)
    assert created and record.state == 'reserved' and record.revision == 1
    replay, created = service.reserve_managed_turn(operation_ref='op-1', request_key=request_key,
        unit_ref=unit.unit_ref, input_digest='operation-digest', binding=binding,
        execution_evidence=execution)
    assert not created and replay == record
    record = service.transition_managed_turn('op-1', expected_revision=1, state='possibly-written')
    native_receipt = {'contractVersion': 'codex-turn-receipt/1', 'nativeRequestId': 'req-1',
        'frameDigest': binding['frameDigest'], 'nativeThreadId': 'native-observed-id',
        'nativeTurnId': 'turn-1', 'status': 'inProgress', 'receiptDigest': 'sha256:' + 'e' * 64}
    record = service.transition_managed_turn('op-1', expected_revision=2,
        state='accepted', receipt=native_receipt)
    assert record.state == 'accepted' and record.receipt == native_receipt
    terminal = {'contractVersion': 'codex-turn-terminal/1',
        'nativeThreadId': 'native-observed-id', 'nativeTurnId': 'turn-1',
        'status': 'completed', 'eventDigest': 'sha256:' + 'f' * 64,
        'evidenceRef': 'unit-records:op-1:terminal'}
    record = service.transition_managed_turn('op-1', expected_revision=3,
        state='completed', terminal=terminal)
    assert record.state == 'completed' and record.terminal == terminal
    assert service.read_managed_turn('op-1', input_digest='operation-digest') == record
    with pytest.raises(UnitRecordsRefused):
        service.read_managed_turn('op-1', input_digest='different-operation')


def test_default_unit_records_leaves_managed_turn_schema_and_file_unchanged(tmp_path):
    p = parts(tmp_path)
    service, journal, verifier, scope, native, epoch = p
    with journal._connect() as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        before_tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    before_bytes = journal.path.read_bytes()
    assert 'harness_managed_turn_attempts' not in before_tables
    assert not service.managed_turn_available

    UnitRecords(journal, scope_authority=scope, native_evidence=native,
                verifier=verifier, epoch_port=epoch)

    with journal._connect() as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        after_tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert after_tables == before_tables
    assert journal.path.read_bytes() == before_bytes
    with pytest.raises(UnitRecordsRefused, match='without fresh-journal opt-in'):
        service.read_managed_turn('missing', input_digest='missing')


def test_existing_journal_rejects_managed_turn_opt_in_before_schema_effect(tmp_path):
    p = parts(tmp_path)
    _, journal, *_ = p
    with journal._connect() as db:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        before_tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    before_bytes = journal.path.read_bytes()
    with pytest.raises(JournalError, match='pristine pre-open journal'):
        OperationJournal(journal.path, managed_turn_opt_in=True)
    with journal._connect() as db:
        after_tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert after_tables == before_tables
    assert 'harness_managed_turn_attempts' not in after_tables
    assert journal.path.read_bytes() == before_bytes


@pytest.mark.parametrize('field', ['providerRef', 'targetRef'])
def test_verified_bool_generation_cannot_match_integer_reservation_target(tmp_path, field):
    p = parts(tmp_path)
    context = p[2].issue()
    facts = p[2].issued[context]
    original = facts[field]
    facts[field] = {**original, 'generation': True}
    assert facts[field] == original  # Ordinary Python equality loses JSON identity.
    with pytest.raises(UnitRecordsRefused, match='verified invocation facts differ'):
        p[0].reserve_unit(context, provider_ref=PROVIDER, node_ref=NODE,
                          input_digest='input', private_root_facts=ROOT)
    with p[1]._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM harness_unit_reservations').fetchone()[0] == 0


def test_public_unit_ref_binds_original_record_without_private_roots(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    ref = unit.public_ref
    assert set(ref) == {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
    assert ref['unitId'] == unit.unit_ref and ref['ownerProviderRef'] == PROVIDER
    assert ref['sourceRevision'].startswith('sha256:')
    assert ROOT['reservedChild'] not in json.dumps(dict(ref), default=dict)
    with pytest.raises(TypeError): ref['sourceRevision'] = 'forged'
    with pytest.raises(TypeError): ref['ownerProviderRef']['generation'] = 999
    service, _, verifier, *_ = p
    assert service.resolve_unit_reference(ref, verifier.issue('query', 'read', 'query-input'), input_digest='query-input') == unit
    ticket = begin(p, unit)
    service.record_session(ticket, expected_source_revision=2, state='confirmed', evidence='real-native-owner-evidence')
    assert reserve(p)[0].public_ref == ref  # Native session observation is a separate version.
    reopened = UnitRecords(OperationJournal(p[1].path), scope_authority=p[3], native_evidence=p[4], verifier=p[2], epoch_port=p[5])
    assert reopened.resolve_unit_reference(ref, verifier.issue('query', 'cold-read', 'query-input'), input_digest='query-input').public_ref == ref


@pytest.mark.parametrize('field', ['environmentNamespace', 'ownerProviderRef', 'sourceRevision'])
def test_public_unit_ref_forgery_refused_even_for_same_unit_id(tmp_path, field):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    forged = json.loads(json.dumps(dict(unit.public_ref), default=dict))
    if field == 'ownerProviderRef': forged[field]['generation'] += 1
    else: forged[field] = 'forged'
    with pytest.raises(UnitRecordsRefused, match='original owner source'):
        p[0].resolve_unit_reference(forged, p[2].issue('query', 'read', 'query-input'), input_digest='query-input')


def test_raw_unit_ref_and_missing_read_authority_do_not_resolve(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    with pytest.raises(UnitRecordsRefused, match='complete owner-bound'):
        p[0].resolve_unit_reference({'environmentNamespace': 'env', 'unitId': unit.unit_ref}, object(), input_digest='query-input')
    with pytest.raises(UnitRecordsRefused, match='unissued'):
        p[0].resolve_unit_reference(unit.public_ref, object(), input_digest='query-input')


def test_reservation_replay_restart_immutable_and_not_created(tmp_path):
    p = parts(tmp_path)
    unit, created = reserve(p)
    assert created and read(p, unit).state == 'notCreated'
    assert reserve(p) == (unit, False)
    service, journal, verifier, scope, native, epoch = p
    reopened = UnitRecords(OperationJournal(journal.path), scope_authority=scope,
                           native_evidence=native, verifier=verifier, epoch_port=epoch)
    assert reserve((reopened, journal, verifier, scope, native, epoch)) == (unit, False)
    with pytest.raises(TypeError):
        unit.facts['inputDigest'] = 'changed'
    with pytest.raises(UnitRecordsRefused, match='different input'):
        reserve(p, input_digest='different')


def test_start_correlation_unknown_never_reopens_on_restart_or_new_key(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    ticket = begin(p, unit)
    opening = read(p, unit)
    assert opening.state == 'opening' and opening.source_revision == 2
    assert json.loads(opening.creation_correlation)['stepId'] == 'start'
    unknown = p[0].record_session(ticket, expected_source_revision=2, state='unknown')
    assert unknown.source_revision == 3
    service = UnitRecords(OperationJournal(p[1].path), scope_authority=p[3], native_evidence=p[4], verifier=p[2], epoch_port=p[5])
    context = p[2].issue('start', 'new-start-key', 'start-input')
    with pytest.raises(UnitRecordsRefused, match='cannot be dispatched again'):
        service.begin_session(unit.unit_ref, context, input_digest='start-input')
    with pytest.raises(UnitRecordsRefused, match='cannot restart'):
        p[0].record_session(ticket, expected_source_revision=3, state='opening')


def test_confirmed_requires_native_evidence_revision_and_terminal_ticket(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    ticket = begin(p, unit)
    with pytest.raises(UnitRecordsRefused, match='native evidence'):
        p[0].record_session(ticket, expected_source_revision=2, state='confirmed', evidence='random-session')
    assert read(p, unit).state == 'opening'
    confirmed = p[0].record_session(ticket, expected_source_revision=2, state='confirmed', evidence='real-native-owner-evidence')
    assert confirmed.source_revision == 3
    assert confirmed.native_facts['sessionId'] == 'native-observed-id'
    with pytest.raises(UnitRecordsRefused, match='not owned'):
        p[0].record_session(ticket, expected_source_revision=3, state='confirmed', evidence='real-native-owner-evidence')


def test_unknown_to_confirmed_requires_owner_evidence(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    ticket = begin(p, unit)
    p[0].record_session(ticket, expected_source_revision=2, state='unknown')
    confirmed = p[0].record_session(ticket, expected_source_revision=3, state='confirmed', evidence='real-native-owner-evidence')
    assert confirmed.source_revision == 4


def test_ticket_copy_forgery_other_instance_and_epoch_expiry(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    ticket = begin(p, unit)
    with pytest.raises(TypeError): copy.copy(ticket)
    forged = object.__new__(RecordTicket)
    for bad in (forged, object()):
        with pytest.raises(UnitRecordsRefused, match='not owned'):
            p[0].record_session(bad, expected_source_revision=2, state='unknown')
    other = UnitRecords(p[1], scope_authority=p[3], native_evidence=p[4], verifier=p[2], epoch_port=p[5])
    with pytest.raises(UnitRecordsRefused, match='not owned'):
        other.record_session(ticket, expected_source_revision=2, state='unknown')
    p[5].value = 1
    with pytest.raises(UnitRecordsRefused, match='epoch expired'):
        p[0].record_session(ticket, expected_source_revision=2, state='unknown')


def test_scope_not_caller_string_missing_ports_and_changed_mapping(tmp_path):
    p = parts(tmp_path)
    for missing in ('scope_authority', 'native_evidence', 'verifier', 'epoch_port'):
        ports = dict(scope_authority=p[3], native_evidence=p[4], verifier=p[2], epoch_port=p[5])
        ports[missing] = None
        with pytest.raises(UnitRecordsRefused, match='explicit authority'):
            UnitRecords(p[1], **ports)
    p[3].scope = 'caller-string'
    with pytest.raises(UnitRecordsRefused, match='owner-issued'):
        reserve(p)
    p[3].scope = CanonicalConfigurationScopeRef('env', 'physical-shared-configuration', '1')
    unit, _ = reserve(p)
    p[3].valid = False
    with pytest.raises(UnitRecordsRefused, match='scope authority'):
        read(p, unit)


def test_new_node_or_generation_cannot_escape_shared_scope(tmp_path):
    p = parts(tmp_path)
    reserve(p)
    node = {**NODE, 'nodeId': 'other', 'generation': 2}
    context = p[2].issue(step='different-prepare', node=node)
    with pytest.raises(UnitRecordsRefused, match='already reserved'):
        p[0].reserve_unit(context, provider_ref=PROVIDER, node_ref=node, input_digest='input', private_root_facts=ROOT)


def old_operation(journal, *, legacy_confirmed=False):
    now = datetime.now(timezone.utc)
    target = ApplicationTarget('server', 'session', 'channel', 7)
    plan = Plan('old-plan', target, 'a'*64, 'before', 'native', 1, 'auth', 'secret', (now+timedelta(minutes=5)).isoformat())
    journal.register_plan('principal', plan)
    record = journal.reserve('principal', plan.plan_id, 'old-key', FenceObservation.from_plan(plan), now=now)
    if legacy_confirmed:
        from dataclasses import asdict
        result = Confirmed(record.operation_id, 'applied', 'legacy-session', 7, 'unverified', ())
        with journal._connect() as db:
            db.execute("UPDATE operations SET state='confirmed',result_json=? WHERE operation_id=?", (json.dumps(asdict(result)), record.operation_id))


@pytest.mark.parametrize('legacy_confirmed', [False, True])
def test_old_unknown_or_unproven_confirmed_blocks_new_unit(tmp_path, legacy_confirmed):
    p = parts(tmp_path)
    old_operation(p[1], legacy_confirmed=legacy_confirmed)
    with pytest.raises(UnitRecordsRefused, match='legacy unresolved'):
        reserve(p)
    with p[1]._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_unit_reservations').fetchone()[0] == 0


def test_reverse_legacy_gate_requires_same_scope_mapping(tmp_path):
    p = parts(tmp_path)
    reserve(p)
    with p[1]._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        target = ApplicationTarget('server', 'session', 'channel', 7)
        assert p[0].can_admit_legacy(db, target) is False
        p[3].legacy = p[3].scope
        assert p[0].can_admit_legacy(db, target) is False
        p[3].legacy = CanonicalConfigurationScopeRef('env', 'proven-isolated-object', '1')
        assert p[0].can_admit_legacy(db, target) is True


def test_concurrent_connections_reserve_once(tmp_path):
    p = parts(tmp_path)
    def once(_):
        verifier = Verifier()
        service = UnitRecords(OperationJournal(p[1].path), scope_authority=p[3], native_evidence=p[4], verifier=verifier, epoch_port=p[5])
        return service.reserve_unit(verifier.issue(), provider_ref=PROVIDER, node_ref=NODE, input_digest='input', private_root_facts=ROOT)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(once, range(8)))
    assert len({unit.unit_ref for unit, _ in results}) == 1
    assert sum(created for _, created in results) == 1


def test_database_failure_rolls_back_both_records(tmp_path):
    p = parts(tmp_path)
    with p[1]._connect() as db:
        db.execute("CREATE TRIGGER fail_binding BEFORE INSERT ON harness_unit_sessions BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    with pytest.raises(Exception, match='injected failure'):
        reserve(p)
    with p[1]._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_unit_reservations').fetchone()[0] == 0


def test_read_requires_current_authorization_and_binding_cas(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    with pytest.raises(UnitRecordsRefused, match='unissued'):
        p[0].read_unit(unit.unit_ref, object(), input_digest='query-input')
    ticket = begin(p, unit)
    with pytest.raises(UnitRecordsRefused, match='revision conflict'):
        p[0].record_session(ticket, expected_source_revision=1, state='unknown')
    query = p[2].issue('query', 'query', 'query-input')
    assert p[0].read_unit(unit.unit_ref, query, input_digest='query-input') == unit
    assert p[0].read_unit(unit.unit_ref, query, input_digest='query-input') == unit


def test_consumed_or_unissued_context_cannot_reserve_or_start(tmp_path):
    p = parts(tmp_path)
    with pytest.raises(UnitRecordsRefused, match='unissued'):
        p[0].reserve_unit(object(), provider_ref=PROVIDER, node_ref=NODE, input_digest='input', private_root_facts=ROOT)
    context = p[2].issue()
    unit, _ = p[0].reserve_unit(context, provider_ref=PROVIDER, node_ref=NODE, input_digest='input', private_root_facts=ROOT)
    with pytest.raises(UnitRecordsRefused, match='consumed'):
        p[0].reserve_unit(context, provider_ref=PROVIDER, node_ref=NODE, input_digest='input', private_root_facts=ROOT)
    with pytest.raises(UnitRecordsRefused, match='unissued'):
        p[0].begin_session(unit.unit_ref, object(), input_digest='start-input')
    assert read(p, unit).state == 'notCreated'


def test_cross_environment_scope_and_stale_start_epoch_refused(tmp_path):
    p = parts(tmp_path)
    p[3].scope = CanonicalConfigurationScopeRef('foreign-environment', 'physical-object', '1')
    with pytest.raises(UnitRecordsRefused, match='owner-issued'):
        reserve(p)
    p[3].scope = CanonicalConfigurationScopeRef('env', 'physical-shared-configuration', '1')
    unit, _ = reserve(p)
    p[5].value = 1
    with pytest.raises(UnitRecordsRefused, match='unit management epoch'):
        p[0].begin_session(unit.unit_ref, p[2].issue('start', 'start', 'start-input', epoch=1), input_digest='start-input')


def test_persisted_identity_or_native_proof_corruption_is_refused(tmp_path):
    import hashlib
    p = parts(tmp_path)
    unit, _ = reserve(p)
    with p[1]._connect() as db:
        db.execute("UPDATE harness_unit_reservations SET correlation='forged' WHERE unit_ref=?", (unit.unit_ref,))
    with pytest.raises(UnitRecordsRefused, match='correlation damaged'):
        read(p, unit)
    with p[1]._connect() as db:
        db.execute('UPDATE harness_unit_reservations SET correlation=? WHERE unit_ref=?', (unit.facts['correlation'], unit.unit_ref))
    ticket = begin(p, unit)
    p[0].record_session(ticket, expected_source_revision=2, state='confirmed', evidence='real-native-owner-evidence')
    # Recomputed digest is integrity metadata, never authority to replace a
    # native session. Owner verification remains mandatory on persisted reads.
    forged = json.dumps({'nativeRealm': 'controlled-owned-pi', 'sessionId': 'forged',
                         'evidenceRef': 'real-native-owner-evidence'}, sort_keys=True, separators=(',', ':'))
    with p[1]._connect() as db:
        db.execute('UPDATE harness_unit_sessions SET native_json=?,native_digest=? WHERE unit_ref=?',
                   (forged, hashlib.sha256(forged.encode()).hexdigest(), unit.unit_ref))
    with pytest.raises(UnitRecordsRefused, match='native owner evidence'):
        read(p, unit)


def test_legacy_isolation_mapping_must_be_authority_provided(tmp_path):
    p = parts(tmp_path)
    old_operation(p[1])
    p[3].legacy = 'caller-scope-string'
    with pytest.raises(UnitRecordsRefused, match='legacy unresolved'):
        reserve(p)
    p[3].legacy = CanonicalConfigurationScopeRef('env', 'proven-separate-target', '1')
    assert reserve(p)[1] is True


def test_bool_epoch_cannot_satisfy_integer_evidence(tmp_path):
    p = parts(tmp_path)
    p[5].value = False
    with pytest.raises(UnitRecordsRefused, match='epoch evidence unavailable'):
        reserve(p)


def test_legacy_channels_share_authoritative_scope_under_actual_reserve(tmp_path):
    from ordessa_agents.harness.definitions import Refused, ErrorCode
    p = parts(tmp_path)
    p[3].legacy = p[3].scope
    old_operation(p[1])
    now = datetime.now(timezone.utc)
    target = ApplicationTarget('server', 'session', 'other-channel', 8)
    plan = Plan('other-plan', target, 'b'*64, 'before', 'native', 1, 'auth', 'secret', (now+timedelta(minutes=5)).isoformat())
    p[1].register_plan('principal', plan)
    result, created = p[1].reserve_new('principal', plan.plan_id, 'other-key', FenceObservation.from_plan(plan), now=now)
    assert isinstance(result, Refused) and result.code is ErrorCode.BUSY and not created
    with p[1]._connect() as db:
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0] == 1


def test_unit_scope_corruption_blocks_legacy_admission(tmp_path):
    from ordessa_agents.harness.definitions import Refused, ErrorCode
    p = parts(tmp_path)
    unit, _ = reserve(p)
    p[3].legacy = p[3].scope
    with p[1]._connect() as db:
        db.execute("UPDATE harness_unit_reservations SET scope_key='forged-unrelated-scope' WHERE unit_ref=?", (unit.unit_ref,))
        assert not p[0].can_admit_legacy(db, ApplicationTarget('server', 'session', 'channel', 7))
    now = datetime.now(timezone.utc)
    target = ApplicationTarget('server', 'session', 'channel', 7)
    plan = Plan('candidate', target, 'b'*64, 'before', 'native', 1, 'auth', 'secret', (now+timedelta(minutes=5)).isoformat())
    p[1].register_plan('principal', plan)
    result, created = p[1].reserve_new('principal', plan.plan_id, 'fresh', FenceObservation.from_plan(plan), now=now)
    assert isinstance(result, Refused) and result.code is ErrorCode.BUSY and not created


def test_single_guard_authority_cannot_be_replaced(tmp_path):
    p = parts(tmp_path)
    guard = p[1]._unit_records_admission_guard
    UnitRecords(p[1], scope_authority=p[3], native_evidence=p[4], verifier=p[2], epoch_port=p[5])
    assert p[1]._unit_records_admission_guard is guard
    with pytest.raises(UnitRecordsRefused, match='different scope authority'):
        UnitRecords(p[1], scope_authority=Scope(), native_evidence=p[4], verifier=p[2], epoch_port=p[5])


def test_cold_journal_without_guard_refuses_new_legacy_but_replays_old(tmp_path):
    from ordessa_agents.harness.definitions import Refused, ErrorCode
    p = parts(tmp_path)
    # A proven isolated old scope may coexist; the existing row is still safe
    # to replay without granting a new dispatch after a cold reopen.
    p[3].legacy = CanonicalConfigurationScopeRef('env', 'isolated-old-scope', '1')
    old_operation(p[1])
    reserve(p)
    cold = OperationJournal(p[1].path)
    now = datetime.now(timezone.utc)
    target = ApplicationTarget('server', 'session', 'channel', 7)
    with cold._connect() as db:
        stored = db.execute('SELECT plan_json FROM plans WHERE plan_id=?', ('old-plan',)).fetchone()[0]
    values = json.loads(stored)
    values['target'] = ApplicationTarget(**values['target'])
    values.pop('kind')  # Plan.kind is a fixed non-init discriminator.
    plan = Plan(**values)
    replay, created = cold.reserve_new('principal', plan.plan_id, 'old-key', FenceObservation.from_plan(plan), now=now)
    assert replay.result.kind == 'unknown' and created is False
    other_target = ApplicationTarget('different-server', 'different-session', 'different-channel', 1)
    other = Plan('fresh-plan', other_target, 'c'*64, 'before', 'native', 1, 'auth', 'secret', (now+timedelta(minutes=5)).isoformat())
    cold.register_plan('principal', other)
    result, created = cold.reserve_new('principal', other.plan_id, 'new-key', FenceObservation.from_plan(other), now=now)
    assert isinstance(result, Refused) and result.code is ErrorCode.BUSY and not created


def test_unit_and_legacy_reservation_race_has_one_durable_winner(tmp_path):
    from threading import Barrier
    from ordessa_agents.harness.definitions import Refused
    p = parts(tmp_path)
    p[3].legacy = p[3].scope
    now = datetime.now(timezone.utc)
    target = ApplicationTarget('server', 'session', 'channel', 7)
    plan = Plan('race-plan', target, 'd'*64, 'before', 'native', 1, 'auth', 'secret', (now+timedelta(minutes=5)).isoformat())
    p[1].register_plan('principal', plan)
    barrier = Barrier(2)

    def contender(kind):
        journal = OperationJournal(p[1].path)
        verifier = Verifier()
        service = UnitRecords(journal, scope_authority=p[3], native_evidence=p[4], verifier=verifier, epoch_port=p[5])
        barrier.wait(timeout=5)
        if kind == 'unit':
            try:
                return service.reserve_unit(verifier.issue(), provider_ref=PROVIDER, node_ref=NODE,
                                            input_digest='input', private_root_facts=ROOT)[1]
            except UnitRecordsRefused:
                return False
        result, created = journal.reserve_new('principal', plan.plan_id, 'race-key',
                                              FenceObservation.from_plan(plan), now=now)
        assert created or isinstance(result, Refused)
        return created

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, ('unit', 'legacy')))
    assert sum(results) == 1
    with p[1]._connect() as db:
        units = db.execute('SELECT count(*) FROM harness_unit_reservations').fetchone()[0]
        legacy = db.execute('SELECT count(*) FROM operations').fetchone()[0]
        assert units + legacy == 1


# -- unified termination face (stop/release): one ledger for every family -----

def _terminable(tmp_path, *, termination=None, **changes):
    p = parts(tmp_path, termination=termination)
    unit, _ = reserve(p, **changes)
    return p, unit


def test_termination_confirmed_requires_refs_and_concludes(tmp_path):
    term = TermEvidence()
    p, unit = _terminable(tmp_path, termination=term)
    service, _, verifier, *_ = p
    ticket = service.begin_termination(
        unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop')
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(ticket, expected_source_revision=1, state='confirmed')
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(ticket, expected_source_revision=1, state='confirmed', evidence={})
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(ticket, expected_source_revision=1, state='confirmed',
                                   evidence={'ref': 5})
    result = service.record_termination(
        ticket, expected_source_revision=1, state='confirmed',
        evidence={'terminationEvidenceRef': 'sha256:stop-proof'})
    assert result['version'] == TERMINATION_VERSION
    assert result['projection'] == 'owner-read'
    assert result['action'] == 'stop' and result['state'] == 'confirmed'
    # The stored proof is the OWNER port's returned refs, never the caller's
    # strings: a caller cannot fabricate its own "evidence reference".
    assert dict(result['outcome']) == {'terminationEvidenceRef': 'sha256:stop-owner-proof'}
    assert term.calls and term.calls[0][0] == 'stop'
    # confirmed is terminal: the ticket is consumed and cannot be reused
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(ticket, expected_source_revision=2, state='unknown')
    assert service.owner_read_termination(unit.unit_ref, 'stop')['state'] == 'confirmed'


def test_termination_unknown_retains_hold_and_ticket(tmp_path):
    term = TermEvidence()
    p, unit = _terminable(tmp_path, termination=term)
    service, _, verifier, *_ = p
    ticket = service.begin_termination(
        unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop')
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(ticket, expected_source_revision=1, state='unknown',
                                   evidence={'nope': 'unknown-takes-no-evidence'})
    result = service.record_termination(ticket, expected_source_revision=1, state='unknown')
    assert result['state'] == 'unknown' and result['outcome'] is None
    # unknown keeps the live ticket: late real evidence may still conclude it
    result = service.record_termination(
        ticket, expected_source_revision=2, state='confirmed',
        evidence={'terminationEvidenceRef': 'sha256:late-proof'})
    assert result['state'] == 'confirmed' and result['sourceRevision'] == 3
    assert dict(result['outcome']) == {'terminationEvidenceRef': 'sha256:stop-owner-proof'}


def test_one_termination_attempt_per_action_and_identity(tmp_path):
    p, unit = _terminable(tmp_path)
    service, _, verifier, *_ = p
    context = verifier.issue('stop', 'native-stop', 'stop-input')
    ticket = service.begin_termination(unit.unit_ref, context, input_digest='stop-input', action='stop')
    assert ticket is not None
    with pytest.raises(UnitRecordsRefused, match='already claimed'):
        service.begin_termination(unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
                                  input_digest='stop-input', action='stop')
    with pytest.raises(UnitRecordsRefused, match='different termination attempt'):
        service.begin_termination(unit.unit_ref, verifier.issue('stop', 'native-stop', 'other-input'),
                                  input_digest='other-input', action='stop')
    with pytest.raises(UnitRecordsRefused, match='stop or release'):
        service.begin_termination(unit.unit_ref, verifier.issue('disconnect', 'x', 'd-input'),
                                  input_digest='d-input', action='disconnect')
    # stop and release are separate attempts on the same Unit
    other = service.begin_termination(
        unit.unit_ref, verifier.issue('release', 'native-release', 'release-input'),
        input_digest='release-input', action='release')
    assert other is not None
    assert service.owner_read_termination(unit.unit_ref, 'release')['state'] == 'opening'


def test_termination_ticket_forgery_revision_and_epoch_refused(tmp_path):
    p, unit = _terminable(tmp_path)
    service, journal, verifier, scope, native, epoch = p
    ticket = service.begin_termination(
        unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop')
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(object(), expected_source_revision=1, state='unknown')
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(object.__new__(type(ticket)), expected_source_revision=1, state='unknown')
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(ticket, expected_source_revision=99, state='unknown')
    with pytest.raises(UnitRecordsRefused):
        service.record_termination(ticket, expected_source_revision='1', state='unknown')
    epoch.value = 1
    with pytest.raises(UnitRecordsRefused, match='epoch'):
        service.record_termination(ticket, expected_source_revision=1, state='unknown')


def test_owner_read_termination_is_invocation_free_and_strict(tmp_path):
    term = TermEvidence()
    p, unit = _terminable(tmp_path, termination=term)
    service, journal, verifier, scope, native, epoch = p
    assert service.owner_read_termination(unit.unit_ref, 'stop') is None
    with pytest.raises(UnitRecordsRefused):
        service.owner_read_termination(unit.unit_ref, 'disconnect')
    ticket = service.begin_termination(
        unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop')
    service.record_termination(ticket, expected_source_revision=1, state='confirmed',
                               evidence={'stopRef': 'sha256:one'})
    import hashlib
    import json as _json

    def _rehashed(payload):
        return _json.dumps(payload, sort_keys=True), hashlib.sha256(
            _json.dumps(payload, sort_keys=True).encode()).hexdigest()

    # damaged stored outcome is refused, never projected as valid
    with journal._connect() as db:
        db.execute("UPDATE harness_unit_terminations SET outcome_json='{\"stopRef\":\"sha256:two\"}' WHERE unit_ref=?", (unit.unit_ref,))
        db.commit()
    with pytest.raises(UnitRecordsRefused, match='damaged'):
        service.owner_read_termination(unit.unit_ref, 'stop')
    # a recomputed digest over a bool value is still refused on read
    payload, digest = _rehashed({'stopRef': True})
    with journal._connect() as db:
        db.execute("UPDATE harness_unit_terminations SET outcome_json=?, outcome_digest=? WHERE unit_ref=?",
                   (payload, digest, unit.unit_ref))
        db.commit()
    with pytest.raises(UnitRecordsRefused, match='damaged'):
        service.owner_read_termination(unit.unit_ref, 'stop')
    # invalid JSON is refused as damage, never leaked as ValueError
    with journal._connect() as db:
        db.execute("UPDATE harness_unit_terminations SET outcome_json='[]', outcome_digest=? WHERE unit_ref=?",
                   (hashlib.sha256(b'[]').hexdigest(), unit.unit_ref))
        db.commit()
    with pytest.raises(UnitRecordsRefused, match='damaged'):
        service.owner_read_termination(unit.unit_ref, 'stop')
    # identity swapped to another action with a recomputed digest is refused
    plain_unit = json.loads(json.dumps(dict(unit.public_ref), default=dict))
    payload, digest = _rehashed({'action': 'release', 'correlation': 'c', 'inputDigest': 'stop-input',
                                 'unitRef': plain_unit})
    with journal._connect() as db:
        db.execute("UPDATE harness_unit_terminations SET identity_json=?, identity_digest=? WHERE unit_ref=?",
                   (payload, digest, unit.unit_ref))
        db.commit()
    with pytest.raises(UnitRecordsRefused, match='damaged'):
        service.owner_read_termination(unit.unit_ref, 'stop')


def test_termination_forged_owner_evidence_is_refused_and_keeps_hold(tmp_path):
    forged = TermEvidence(valid=False)
    p, unit = _terminable(tmp_path, termination=forged)
    service, journal, verifier, scope, native, epoch = p
    ticket = service.begin_termination(
        unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop')
    with pytest.raises(UnitRecordsRefused, match='forged'):
        service.record_termination(ticket, expected_source_revision=1, state='confirmed',
                                   evidence={'terminationEvidenceRef': 'sha256:made-up'})
    # the refused call changed nothing: still opening, ticket still live
    assert service.owner_read_termination(unit.unit_ref, 'stop')['state'] == 'opening'
    result = service.record_termination(ticket, expected_source_revision=1, state='unknown')
    assert result['state'] == 'unknown'


def test_termination_port_must_return_provenance_refs(tmp_path):
    bad = TermEvidence(refs={'stopRef': True})
    p, unit = _terminable(tmp_path, termination=bad)
    service, _, verifier, *_ = p
    ticket = service.begin_termination(
        unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop')
    with pytest.raises(UnitRecordsRefused, match='provenance refs'):
        service.record_termination(ticket, expected_source_revision=1, state='confirmed',
                                   evidence={'stopRef': 'anything'})


def test_reconcile_termination_recovers_after_restart(tmp_path):
    term = TermEvidence()
    p, unit = _terminable(tmp_path, termination=term)
    service, journal, verifier, scope, native, epoch = p
    ticket = service.begin_termination(
        unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop')
    service.record_termination(ticket, expected_source_revision=1, state='unknown')
    # Restart: a fresh records instance on the same journal; the old ticket
    # is process-local and unusable, the attempt stays retained.
    restarted = UnitRecords(journal, scope_authority=scope, native_evidence=native,
                            verifier=verifier, epoch_port=epoch, termination_evidence=term)
    with pytest.raises(UnitRecordsRefused):
        restarted.record_termination(ticket, expected_source_revision=2, state='unknown')
    assert restarted.owner_read_termination(unit.unit_ref, 'stop')['state'] == 'unknown'
    # a query over a different step is not the original attempt
    with pytest.raises(UnitRecordsRefused, match='original termination attempt'):
        restarted.reconcile_termination(
            unit.unit_ref, verifier.issue('query', 'wrong-step', 'stop-input'),
            input_digest='stop-input', action='stop', expected_source_revision=2,
            state='confirmed', evidence={'stopRef': 'x'})
    result = restarted.reconcile_termination(
        unit.unit_ref, verifier.issue('query', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop', expected_source_revision=2,
        state='confirmed', evidence={'stopRef': 'late-real-proof'})
    assert result['state'] == 'confirmed' and result['sourceRevision'] == 3
    assert dict(result['outcome']) == {'terminationEvidenceRef': 'sha256:stop-owner-proof'}
    # reconcile never re-arms a dispatch: begin stays single-shot forever
    with pytest.raises(UnitRecordsRefused):
        restarted.begin_termination(
            unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
            input_digest='stop-input', action='stop')


# -- reopened history: read-only termination projection, execution fenced -----

def _confirmed_stop(p, unit):
    service, _journal, verifier, *_ = p
    ticket = service.begin_termination(
        unit.unit_ref, verifier.issue('stop', 'native-stop', 'stop-input'),
        input_digest='stop-input', action='stop')
    return service.record_termination(
        ticket, expected_source_revision=1, state='confirmed',
        evidence={'terminationEvidenceRef': 'sha256:stop-proof'})


class _NoLiveScope:
    """A reopened host whose live scope index is genuinely gone."""

    def verify_scope(self, *_args, **_kwargs):
        return False


def _historical_view(p, unit, *, termination=None, scope_authority=None):
    """The host's verified reopen: same journal, every old Unit fenced."""
    from ordessa_units.records.operation_journal import OperationJournal
    service, journal, verifier, scope, native, epoch = p
    reopened = OperationJournal.reopen_for_new_units(
        journal.path, namespace='env', validate_owner=lambda: None,
        managed_turn_opt_in=False, acp_turn_opt_in=False)
    assert unit.unit_ref in reopened.historical_unit_ids
    view = UnitRecords(reopened, scope_authority=scope_authority or scope,
                       native_evidence=native, verifier=verifier, epoch_port=epoch,
                       termination_evidence=termination or TermEvidence())
    return view, reopened


def test_reopened_history_owner_read_termination_is_read_only(tmp_path):
    import hashlib
    term = TermEvidence()
    p, unit = _terminable(tmp_path, termination=term)
    _confirmed_stop(p, unit)
    read_only = TermEvidence()
    view, journal = _historical_view(p, unit, termination=read_only)
    before = hashlib.sha256(journal.path.read_bytes()).hexdigest()
    record = view.owner_read_termination(unit.unit_ref, 'stop')
    assert record['projection'] == 'owner-read' and record['state'] == 'confirmed'
    assert record['action'] == 'stop'
    assert dict(record['outcome'])  # the original persisted proof, not fabricated
    assert view.owner_read_termination(unit.unit_ref, 'release') is None
    # No termination validator was consulted to supply the proof again.
    assert read_only.calls == []
    after = hashlib.sha256(journal.path.read_bytes()).hexdigest()
    assert after == before
    # The historical Unit stays fenced for every execution path.
    with pytest.raises(UnitRecordsRefused, match='historical Unit stays fenced'):
        view.begin_termination(unit.unit_ref,
            p[2].issue('release', 'native-release', 'release-input'),
            input_digest='release-input', action='release')


def _termination_row(journal, unit):
    with journal._connect() as db:
        return db.execute(
            'SELECT * FROM harness_unit_terminations WHERE unit_ref=? AND action=?',
            (unit.unit_ref, 'stop')).fetchone()


def test_reopened_history_owner_read_termination_refuses_damage(tmp_path):
    import hashlib
    import json as _json

    def _rewrite(payload, *, digest_too=True):
        text = _json.dumps(payload, sort_keys=True)
        return text, hashlib.sha256(text.encode()).hexdigest() if digest_too else None

    cases = ('identity-bytes', 'outcome', 'state-revision', 'missing-proof',
             'scope-key', 'identity-unit-ref')
    for case in cases:
        root = tmp_path / case
        root.mkdir()
        p, unit = _terminable(root, termination=TermEvidence())
        _confirmed_stop(p, unit)
        view, journal = _historical_view(p, unit)
        with journal._connect() as db:
            row = _termination_row(journal, unit)
            identity = _json.loads(row['identity_json'])
            if case == 'identity-bytes':
                text, digest = _rewrite(dict(identity, inputDigest='tampered-input'),
                                        digest_too=False)
                db.execute('UPDATE harness_unit_terminations SET identity_json=? WHERE unit_ref=?',
                           (text, unit.unit_ref))
            elif case == 'outcome':
                db.execute('UPDATE harness_unit_terminations SET outcome_json=? WHERE unit_ref=?',
                           (_json.dumps({'terminationEvidenceRef': 'sha256:forged'}),
                            unit.unit_ref))
            elif case == 'state-revision':
                db.execute("UPDATE harness_unit_terminations SET state='opening' WHERE unit_ref=?",
                           (unit.unit_ref,))
            elif case == 'missing-proof':
                db.execute('UPDATE harness_unit_terminations SET outcome_json=NULL, '
                           'outcome_digest=NULL WHERE unit_ref=?', (unit.unit_ref,))
            elif case == 'scope-key':
                db.execute("UPDATE harness_unit_reservations SET scope_key='{}' WHERE unit_ref=?",
                           (unit.unit_ref,))
            elif case == 'identity-unit-ref':
                other = dict(identity, unitRef=dict(identity['unitRef'], unitId='other-unit'))
                text, digest = _rewrite(other)
                db.execute('UPDATE harness_unit_terminations SET identity_json=?, identity_digest=? '
                           'WHERE unit_ref=?', (text, digest, unit.unit_ref))
            db.commit()
        with pytest.raises(UnitRecordsRefused):
            view.owner_read_termination(unit.unit_ref, 'stop')


# -- pure identity read for historical ACP queries ---------------------------

def test_owner_read_unit_for_query_returns_the_immutable_identity(tmp_path):
    import hashlib
    p, unit = _terminable(tmp_path, termination=TermEvidence())
    view, journal = _historical_view(p, unit)
    ref = dict(unit.public_ref)
    before = hashlib.sha256(journal.path.read_bytes()).hexdigest()
    found = view.owner_read_unit_for_query(ref)
    assert found.public_ref == unit.public_ref
    assert found.unit_ref == unit.unit_ref
    assert found.intent_json == unit.intent_json
    assert hashlib.sha256(journal.path.read_bytes()).hexdigest() == before
    # Identity only: the historical Unit stays fenced for execution, and the
    # existing owner read keeps its own fence.
    with pytest.raises(UnitRecordsRefused, match='historical Unit stays fenced'):
        view.owner_read_unit(unit.unit_ref)
    with pytest.raises(UnitRecordsRefused, match='historical Unit stays fenced'):
        view.begin_termination(unit.unit_ref,
            p[2].issue('stop', 'native-stop', 'stop-input'),
            input_digest='stop-input', action='stop')


def test_owner_read_unit_for_query_refuses_wrong_or_tampered_identity(tmp_path):
    import hashlib
    import json as _json

    p, unit = _terminable(tmp_path, termination=TermEvidence())
    view, journal = _historical_view(p, unit)
    ref = dict(unit.public_ref)

    with pytest.raises(UnitRecordsRefused, match='complete owner-bound'):
        view.owner_read_unit_for_query(unit.unit_ref)
    with pytest.raises(UnitRecordsRefused, match='complete owner-bound'):
        view.owner_read_unit_for_query({key: value for key, value in ref.items()
                                        if key != 'sourceRevision'})
    with pytest.raises(UnitRecordsRefused, match='complete owner-bound'):
        view.owner_read_unit_for_query(dict(ref, unitId=''))
    with pytest.raises(UnitRecordsRefused, match='differs from original owner source'):
        view.owner_read_unit_for_query(dict(ref, sourceRevision='sha256:' + '0' * 64))
    with pytest.raises(UnitRecordsRefused, match='differs from original owner source'):
        view.owner_read_unit_for_query(dict(ref, environmentNamespace='other-env'))
    with pytest.raises(UnitRecordsRefused, match='unit missing or immutable facts damaged'):
        view.owner_read_unit_for_query(dict(ref, unitId='other-unit'))

    # A tampered reservation is damage even though the public ref matches.
    with journal._connect() as db:
        db.execute('UPDATE harness_unit_reservations SET intent_json=? WHERE unit_ref=?',
                   ('{}', unit.unit_ref))
        db.commit()
    with pytest.raises(UnitRecordsRefused, match='unit missing or immutable facts damaged'):
        view.owner_read_unit_for_query(ref)


def test_reopened_history_reads_without_a_live_scope_index(tmp_path):
    """The reopened journal has no live scope index; identity reads still work.

    ``verify_scope`` is False on this authority; the live read path must keep
    refusing it, while both historical read ports work from the persisted
    canonical facts alone.
    """
    p, unit = _terminable(tmp_path, termination=TermEvidence())
    _confirmed_stop(p, unit)
    view, journal = _historical_view(p, unit, scope_authority=_NoLiveScope())
    record = view.owner_read_termination(unit.unit_ref, 'stop')
    assert record['state'] == 'confirmed' and dict(record['outcome'])
    found = view.owner_read_unit_for_query(dict(unit.public_ref))
    assert found.public_ref == unit.public_ref
    # The live verification is untouched: the same facts under a missing live
    # scope index are refused by the ordinary path.
    with journal._connect() as db:
        with pytest.raises(UnitRecordsRefused, match='scope authority'):
            view._reservation(db, unit.unit_ref)
    # No execution path is re-enabled for the historical Unit.
    with pytest.raises(UnitRecordsRefused, match='historical Unit stays fenced'):
        view.owner_read_unit(unit.unit_ref)
    with pytest.raises(UnitRecordsRefused, match='historical Unit stays fenced'):
        view.begin_termination(unit.unit_ref,
            p[2].issue('stop', 'native-stop', 'stop-input'),
            input_digest='stop-input', action='stop')
