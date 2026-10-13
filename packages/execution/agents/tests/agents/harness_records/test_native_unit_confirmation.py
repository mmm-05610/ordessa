"""Original SQLite owner, controlled process/pipe proof only; no native SDK."""
import copy

import pytest

from agent_tools_fixtures.unit_records import parts, reserve, begin, read, ROOT
from ordessa_units.records.operation_journal import OperationJournal
from ordessa_units.records.unit_records import (
    UnitRecords, UnitRecordsRefused, NativeUnitBinding, UNIT_CONFIRMATION_VERSION,
)


from agent_tools_fixtures.native_evidence import UnitEvidence


def setup(tmp_path):
    p = parts(tmp_path)
    owner = UnitEvidence()
    p[0].native_unit_evidence = owner
    unit, _ = reserve(p)
    return p, owner, unit


def start_unit(p, unit):
    return p[0].begin_unit(unit.unit_ref, p[2].issue('start', 'start', 'start-input'), input_digest='start-input')


def read_confirmation(p, unit):
    return p[0].read_unit_confirmation(unit.unit_ref,
        p[2].issue('query', 'read-unit', 'query-input'), input_digest='query-input')


def test_owned_unit_confirmation_does_not_invent_a_native_session(tmp_path):
    p, owner, unit = setup(tmp_path)
    ticket = start_unit(p, unit)
    binding = p[0].record_unit(ticket, expected_source_revision=2, state='confirmed', evidence=owner.reference(unit, 'receipt'))
    assert type(binding) is NativeUnitBinding and binding.source_revision == 3
    assert binding.native_facts['unitRef'] == unit.public_ref
    assert 'sessionId' not in binding.native_facts
    assert read(p, unit).state == 'notCreated'
    assert read_confirmation(p, unit) == binding
    assert reserve(p)[0].public_ref == unit.public_ref
    with pytest.raises(UnitRecordsRefused, match='start fence'): begin(p, unit)
    with pytest.raises(UnitRecordsRefused, match='start fence'): start_unit(p, unit)
    with pytest.raises(UnitRecordsRefused, match='not owned'):
        p[0].record_unit(ticket, expected_source_revision=3, state='unknown')


def test_missing_unit_evidence_port_refuses_before_consuming_start(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    context = p[2].issue('start', 'start', 'start-input')
    with pytest.raises(UnitRecordsRefused, match='owner is absent'):
        p[0].begin_unit(unit.unit_ref, context, input_digest='start-input')
    assert context in p[2].issued
    assert read_confirmation(p, unit).state == 'notCreated'
    assert read(p, unit).state == 'notCreated'


@pytest.mark.parametrize('damage', ['unit', 'correlation', 'version', 'session', 'ack', 'owner', 'boolean', 'source'])
def test_ack_wrong_identity_or_provenance_never_confirms_unit(tmp_path, damage):
    p, owner, unit = setup(tmp_path)
    ticket = start_unit(p, unit)
    owner.damage = damage
    with pytest.raises(UnitRecordsRefused):
        p[0].record_unit(ticket, expected_source_revision=2, state='confirmed', evidence=owner.reference(unit, 'receipt'))
    assert read_confirmation(p, unit).state == 'opening'
    assert read(p, unit).state == 'notCreated'


def test_unknown_keeps_both_creation_fences_and_can_confirm_original_ticket(tmp_path):
    p, owner, unit = setup(tmp_path)
    ticket = start_unit(p, unit)
    p[0].record_unit(ticket, expected_source_revision=2, state='unknown')
    with pytest.raises(UnitRecordsRefused, match='start fence'): start_unit(p, unit)
    with pytest.raises(UnitRecordsRefused, match='start fence'): begin(p, unit)
    with pytest.raises(UnitRecordsRefused, match='revision conflict'):
        p[0].record_unit(ticket, expected_source_revision=2, state='confirmed', evidence=owner.reference(unit, 'receipt'))
    confirmed = p[0].record_unit(ticket, expected_source_revision=3, state='confirmed', evidence=owner.reference(unit, 'receipt'))
    assert confirmed.state == 'confirmed' and confirmed.source_revision == 4
    assert read(p, unit).state == 'notCreated'


def test_session_creation_prevents_second_unit_start_and_tickets_do_not_cross(tmp_path):
    p, owner, unit = setup(tmp_path)
    session_ticket = begin(p, unit)
    with pytest.raises(UnitRecordsRefused, match='start fence'): start_unit(p, unit)
    with pytest.raises(UnitRecordsRefused, match='not owned'):
        p[0].record_unit(session_ticket, expected_source_revision=2, state='confirmed', evidence=owner.reference(unit, 'receipt'))
    assert read(p, unit).state == 'opening'


def test_unit_ticket_cannot_be_used_as_session_or_copied(tmp_path):
    p, owner, unit = setup(tmp_path)
    ticket = start_unit(p, unit)
    with pytest.raises(TypeError): copy.copy(ticket)
    with pytest.raises(UnitRecordsRefused, match='not owned'):
        p[0].record_session(ticket, expected_source_revision=2, state='confirmed', evidence='real-native-owner-evidence')


def test_cold_read_reverifies_original_owner_and_does_not_reissue_ticket(tmp_path):
    p, owner, unit = setup(tmp_path)
    ticket = start_unit(p, unit)
    binding = p[0].record_unit(ticket, expected_source_revision=2, state='confirmed', evidence=owner.reference(unit, 'receipt'))
    cold = UnitRecords(OperationJournal(p[1].path), scope_authority=p[3], native_evidence=p[4], verifier=p[2], epoch_port=p[5], native_unit_evidence=owner)
    context = p[2].issue('query', 'cold-read', 'query-input')
    assert cold.read_unit_confirmation(unit.unit_ref, context, input_digest='query-input') == binding
    owner.valid = False
    with pytest.raises(UnitRecordsRefused, match='proof unavailable'):
        cold.read_unit_confirmation(unit.unit_ref, p[2].issue('query', 'cold-read', 'query-input'), input_digest='query-input')
    with p[1]._connect() as db:
        assert db.execute('SELECT state FROM harness_unit_confirmations').fetchone()['state'] == 'confirmed'


def test_epoch_change_prevents_unit_ticket_confirmation(tmp_path):
    p, owner, unit = setup(tmp_path)
    ticket = start_unit(p, unit)
    p[5].value = 1
    with pytest.raises(UnitRecordsRefused, match='epoch expired'):
        p[0].record_unit(ticket, expected_source_revision=2, state='confirmed', evidence=owner.reference(unit, 'receipt'))
    with p[1]._connect() as db:
        assert db.execute('SELECT state FROM harness_unit_confirmations').fetchone()['state'] == 'opening'


def test_cold_query_confirms_original_unit_without_creation_ticket(tmp_path):
    p, owner, unit = setup(tmp_path)
    ticket = start_unit(p, unit)
    p[0].record_unit(ticket, expected_source_revision=2, state='unknown')
    cold = UnitRecords(OperationJournal(p[1].path), scope_authority=p[3], native_evidence=p[4], verifier=p[2], epoch_port=p[5], native_unit_evidence=owner)
    assert cold._tickets == {}
    context = p[2].issue('query', 'start', 'start-input')
    confirmed = cold.reconcile_unit_confirmation(unit.unit_ref, context, input_digest='start-input',
        expected_source_revision=3, evidence=owner.reference(unit, 'receipt'))
    assert confirmed.state == 'confirmed' and confirmed.source_revision == 4
    assert cold._tickets == {} and read(p, unit).state == 'notCreated'
    with pytest.raises(UnitRecordsRefused, match='revision conflict'):
        p[0].record_unit(ticket, expected_source_revision=3, state='confirmed', evidence=owner.reference(unit, 'receipt'))
    assert read_confirmation(p, unit) == confirmed


@pytest.mark.parametrize('damage', ['step', 'operation', 'revision', 'proof', 'input'])
def test_cold_query_rejects_other_start_or_late_or_missing_proof(tmp_path, damage):
    p, owner, unit = setup(tmp_path)
    ticket = start_unit(p, unit)
    p[0].record_unit(ticket, expected_source_revision=2, state='unknown')
    digest = 'different-input' if damage == 'input' else 'start-input'
    context = p[2].issue('query', 'start', digest)
    if damage == 'step': p[2].issued[context]['stepId'] = 'other-start'
    elif damage == 'operation': p[2].issued[context]['operationRef'] = 'other-operation'
    elif damage == 'proof': owner.valid = False
    with pytest.raises(UnitRecordsRefused):
        p[0].reconcile_unit_confirmation(unit.unit_ref, context, input_digest=digest,
            expected_source_revision=2 if damage == 'revision' else 3, evidence=owner.reference(unit, 'receipt'))
    assert read_confirmation(p, unit).state == 'unknown'
    assert read(p, unit).state == 'notCreated'


@pytest.mark.parametrize('damage', ['not-created-revision', 'opening-revision', 'unknown-revision', 'orphan-digest', 'downgraded-unknown'])
def test_damaged_confirmation_cannot_reset_start_or_consume_new_claim(tmp_path, damage):
    p, owner, unit = setup(tmp_path)
    if damage != 'not-created-revision' and damage != 'orphan-digest':
        ticket = start_unit(p, unit)
        if damage in ('unknown-revision', 'downgraded-unknown'):
            p[0].record_unit(ticket, expected_source_revision=2, state='unknown')
    with p[1]._connect() as db:
        if damage in ('not-created-revision', 'opening-revision'):
            db.execute('UPDATE harness_unit_confirmations SET source_revision=3')
        elif damage == 'unknown-revision':
            db.execute('UPDATE harness_unit_confirmations SET source_revision=2')
        elif damage == 'orphan-digest':
            db.execute("UPDATE harness_unit_confirmations SET native_digest='orphan'")
        else:
            db.execute("UPDATE harness_unit_confirmations SET state='notCreated',creation_correlation=NULL,input_digest=NULL")
        db.commit()
    context = p[2].issue('start', 'new-start', 'start-input')
    with pytest.raises(UnitRecordsRefused, match='missing or damaged'):
        p[0].begin_unit(unit.unit_ref, context, input_digest='start-input')
    assert context in p[2].issued


def test_native_unit_uses_real_core_start_claim_and_cold_query_keeps_same_operation(tmp_path):
    from agent_tools_fixtures.configuration_records import real_core_parts
    p, unit, store, request, issuer, authority, current, issued = real_core_parts(tmp_path, start_native_session=False)
    owner = UnitEvidence()
    p[0].native_unit_evidence = owner
    try:
        invocation = issued('start')
        ticket = p[0].begin_unit(unit.unit_ref, invocation, input_digest='start-input')
        assert issuer.verified_consumption(invocation)
        assert store.read_operation_step(request, 'start').outcome == 'possibly-dispatched'
        p[0].record_unit(ticket, expected_source_revision=2, state='unknown')
        store.record_operation_step(request, 'flow-digest', 'start', 'start-input', 1, 'unknown', {})
        cold = UnitRecords(OperationJournal(p[1].path), scope_authority=p[3], native_evidence=p[4],
            verifier=p[0].verifier, epoch_port=p[5], native_unit_evidence=owner)
        query = issuer.issue_query(request, 'flow-digest', 'start')
        result = cold.reconcile_unit_confirmation(unit.unit_ref, query, input_digest='start-input',
            expected_source_revision=3, evidence=owner.reference(unit, 'receipt'))
        assert issuer.verified_observation(query)
        assert result.state == 'confirmed' and cold._tickets == {}
        assert store.read_operation_step(request, 'start').outcome == 'unknown'  # Core must separately consume owner observation.
        with pytest.raises(Exception, match='existing step claim'): issued('start')
        authority.allowed = False
        with pytest.raises(Exception): issuer.issue_query(request, 'flow-digest', 'start')
        with p[1]._connect() as db:
            assert db.execute('SELECT state FROM harness_unit_sessions').fetchone()['state'] == 'notCreated'
    finally:
        store.close()


def test_older_unit_has_no_inferred_process_confirmation_or_automatic_backfill(tmp_path):
    p, owner, unit = setup(tmp_path)
    with p[1]._connect() as db:
        db.execute('DELETE FROM harness_unit_confirmations WHERE unit_ref=?', (unit.unit_ref,))
        db.commit()
    with pytest.raises(UnitRecordsRefused, match='missing or damaged'): read_confirmation(p, unit)
    context = p[2].issue('start', 'start', 'start-input')
    with pytest.raises(UnitRecordsRefused, match='missing or damaged'):
        p[0].begin_unit(unit.unit_ref, context, input_digest='start-input')
    assert context in p[2].issued
    with p[1]._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM harness_unit_confirmations').fetchone()[0] == 0
    assert read(p, unit).state == 'notCreated'  # Old session contract remains readable.


def test_changed_owner_source_is_not_overwritten_or_treated_as_same_confirmation(tmp_path):
    p, owner, unit = setup(tmp_path)
    ticket = start_unit(p, unit)
    p[0].record_unit(ticket, expected_source_revision=2, state='confirmed', evidence=owner.reference(unit, 'receipt'))
    with p[1]._connect() as db:
        original = db.execute('SELECT native_json FROM harness_unit_confirmations').fetchone()['native_json']
    owner.damage = 'sourceChanged'
    with pytest.raises(UnitRecordsRefused, match='differs from owner evidence'): read_confirmation(p, unit)
    with p[1]._connect() as db:
        assert db.execute('SELECT native_json FROM harness_unit_confirmations').fetchone()['native_json'] == original


@pytest.mark.parametrize('table', ['harness_unit_confirmations', 'harness_unit_sessions'])
@pytest.mark.parametrize('damage', ['revision', 'digest'])
@pytest.mark.parametrize('route', ['unit', 'session'])
def test_corruption_cannot_escape_through_alternate_creation_route(tmp_path, table, damage, route):
    p, owner, unit = setup(tmp_path)
    with p[1]._connect() as db:
        if damage == 'revision':
            db.execute(f'UPDATE {table} SET source_revision=3')
        else:
            db.execute(f"UPDATE {table} SET native_digest='orphan'")
        db.commit()
    context = p[2].issue('start', 'start', 'start-input')
    method = p[0].begin_unit if route == 'unit' else p[0].begin_session
    with pytest.raises(UnitRecordsRefused, match='damaged'):
        method(unit.unit_ref, context, input_digest='start-input')
    assert context in p[2].issued
    with p[1]._connect() as db:
        assert db.execute('SELECT state FROM harness_unit_confirmations').fetchone()['state'] == 'notCreated'
        assert db.execute('SELECT state FROM harness_unit_sessions').fetchone()['state'] == 'notCreated'
