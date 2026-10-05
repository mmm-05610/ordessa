"""Real temporary SQLite; authority/native/verifier ports are controlled L1.

No native process/model, user directory, production admission or L2 claim.
The verifier fixture grants only objects explicitly issued in this test;
it does not establish production InvocationIssuer or native scope evidence.
"""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from ordessa_harness_api import ApplicationTarget, Plan, Confirmed
from ordessa_harness.application.operation_journal import OperationJournal, FenceObservation
from ordessa_harness.application.unit_records import (
    UnitRecords, UnitRecordsRefused, CanonicalConfigurationScopeRef, RecordTicket,
)

PROVIDER = {'environmentNamespace': 'env', 'providerId': 'pi', 'generation': 1}
NODE = {'environmentNamespace': 'env', 'nodeId': 'node', 'generation': 1}
ROOT = {'host': 'controlled-host', 'filesystem': 1, 'parentObject': 42,
        'reservedChild': 'private-unit', 'isolationEvidence': 'controlled-proof'}


class Verifier:
    def __init__(self):
        self.issued = {}

    def issue(self, action='prepare', step='prepare', digest='input', epoch=0, node=NODE):
        context = object()
        facts = {'query': action == 'query', 'action': action, 'providerRef': PROVIDER,
                 'targetRef': node, 'inputDigest': digest, 'managementEpoch': epoch,
                 'request': {'environmentNamespace': 'env', 'principalScope': 'principal', 'requestId': 'request'},
                 'operationRef': 'operation', 'stepId': step}
        self.issued[context] = facts
        return context

    def verify_and_consume(self, context, action, provider, node, digest):
        if context not in self.issued:
            raise UnitRecordsRefused('unissued or consumed invocation')
        facts = self.issued[context]
        assert (action, provider, node, digest) == (facts['action'], facts['providerRef'], facts['targetRef'], facts['inputDigest'])
        if not facts['query']:
            del self.issued[context]
        return facts


class Scope:
    def __init__(self):
        self.valid = True
        self.scope = CanonicalConfigurationScopeRef('env', 'physical-shared-configuration', '1')
        self.legacy = None

    def issue_scope(self, provider, node, root):
        return self.scope

    def verify_scope(self, scope, root):
        return self.valid and scope == self.scope and root == ROOT

    def map_legacy_scope(self, target):
        assert isinstance(target, ApplicationTarget)
        return self.legacy


class Native:
    def __init__(self):
        self.valid = True

    def verify_binding(self, unit, correlation, evidence):
        if not self.valid or evidence != 'real-native-owner-evidence':
            raise UnitRecordsRefused('native evidence missing or forged')
        return {'nativeRealm': 'controlled-owned-pi', 'sessionId': 'native-observed-id',
                'evidenceRef': evidence}


class Epoch:
    value = 0

    def current_epoch(self, node):
        return self.value


def parts(tmp_path):
    journal = OperationJournal(tmp_path / 'journal.sqlite')
    verifier, scope, native, epoch = Verifier(), Scope(), Native(), Epoch()
    service = UnitRecords(journal, scope_authority=scope, native_evidence=native,
                          verifier=verifier, epoch_port=epoch)
    return service, journal, verifier, scope, native, epoch


def reserve(parts_, **changes):
    service, _, verifier, *_ = parts_
    values = {'provider_ref': PROVIDER, 'node_ref': NODE, 'input_digest': 'input', 'private_root_facts': ROOT}
    values.update(changes)
    return service.reserve_unit(verifier.issue(digest=values['input_digest'], node=values['node_ref']), **values)


def begin(parts_, unit):
    service, _, verifier, *_ = parts_
    return service.begin_session(unit.unit_ref, verifier.issue('start', 'start', 'start-input'), input_digest='start-input')


def read(parts_, unit):
    service, _, verifier, *_ = parts_
    return service.read_session(unit.unit_ref, verifier.issue('query', 'query', 'query-input'), input_digest='query-input')


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
    from ordessa_harness_api import Refused, ErrorCode
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
    from ordessa_harness_api import Refused, ErrorCode
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
    from ordessa_harness_api import Refused, ErrorCode
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
    from ordessa_harness_api import Refused
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
