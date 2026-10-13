"""C: real journals/Issuer; controlled original input and native evidence.

No native input, model, production receipt owner or publication coordinator.
Association proves only Session identity; original core input stays unknown.
"""
import hashlib
import json
from pathlib import Path
import sys
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_tools_fixtures import configuration_records as shared
from agent_tools_fixtures.native_evidence import AssociationEvidence, UnitEvidence, source
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import DomainWrite
from ordessa_execution_api.environment.operations import OperationIntent, StepIntent, safe_json
from ordessa_units.records.operation_journal import OperationJournal
from ordessa_units.records.unit_records import (
    UnitRecords, UnitRecordsRefused, INPUT_SESSION_ASSOCIATION_VERSION,
)
from ordessa_units.channels.reservations import SessionlessNativeInputState, CapturedInputRef, FIRST_SESSION_ATTEMPTS, ManagedInputReservations
from ordessa_units.admission.invocation import InvocationAuthorityRefused, InvocationVerifier


PROVIDER = {'environmentNamespace': 'env', 'providerId': 'controlled.native', 'generation': 1,
            'ownerActivationRef': {'environmentNamespace': 'env', 'pluginId': 'controlled.native', 'generation': 1},
            'contractVersion': 'agent-runtime/2', 'implementationDigest': 'sha256:' + 'e' * 64}
NODE = {'environmentNamespace': 'env', 'instanceId': 'node', 'generation': 1}
DIGEST = 'sha256:' + 'c' * 64



@pytest.fixture
def association(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, 'PROVIDER', PROVIDER)
    monkeypatch.setattr(shared, 'NODE', NODE)
    p, unit, store, flow, issuer, authority, current, issued = shared.real_core_parts(tmp_path, start_native_session=False)
    unit_owner = UnitEvidence()
    p[0].native_unit_evidence = unit_owner
    ticket = p[0].begin_unit(unit.unit_ref, issued('start'), input_digest='start-input')
    p[0].record_unit(ticket, expected_source_revision=2, state='confirmed', evidence=unit_owner.reference(unit, 'receipt'))
    state = SessionlessNativeInputState(NODE, PROVIDER, unit.public_ref,
        unit_owner.reference(unit, 'receipt'), source(unit, 'original-session-absence'), 0,
        current.directory, source(unit, 'configuration-before-input'))
    request = RequestKey('env', 'controlled-principal', 'first-input')
    captured = CapturedInputRef('env', 'capture', 1, 'sha256:' + 'a' * 64).to_dict()
    correlation = {'environmentNamespace': 'env', 'protocol': 'controlled-native/1', 'requestId': 1}
    context = {'environmentNamespace': 'env', 'nodeRef': NODE, 'capturedInputRef': captured,
               'nativeCorrelation': correlation, 'sessionlessInputBinding': state.binding(),
               'directoryBindingRef': current.directory.to_dict(),
               'invocationBindings': {'native-input': {'action': 'submitInput', 'targetRef': unit.public_ref,
                                                      'delegationRef': None, 'cleanup': False}}}
    intent = OperationIntent('original-input', 'managed-input', None, context,
        (StepIntent('native-input', PROVIDER, DIGEST, 'original-native-input', management_epoch=0),), NODE, 0)
    fence_id = ManagedInputReservations._first_fence_id(NODE, unit.public_ref)
    marker = {'nodeRef': NODE, 'unitRef': unit.public_ref, 'state': 'held', 'principalScope': request.principal_scope,
              'requestId': request.request_id, 'operationRef': intent.operation_ref, 'inputDigest': DIGEST,
              'binding': state.binding(), 'providerRef': PROVIDER, 'managementEpoch': 0, 'nativeCorrelation': correlation}
    store.reserve_operation(request, DIGEST, intent, writes=(DomainWrite(FIRST_SESSION_ATTEMPTS, fence_id, 0, marker),))
    expected = {'request': {'environmentNamespace': 'env', 'principalScope': request.principal_scope, 'requestId': request.request_id},
                'operationRef': 'original-input', 'stepId': 'native-input', 'inputDigest': DIGEST, 'providerRef': PROVIDER,
                'unitRef': unit.public_ref, 'nodeRef': NODE, 'managementEpoch': 0, 'nativeCorrelation': correlation,
                'unitConfirmationRef': state.unit_confirmation_ref, 'sessionAbsenceRef': state.session_absence_ref,
                'capturedInputRef': captured}
    owner = AssociationEvidence(unit, expected)
    p[0].input_association_evidence = owner
    yield p, unit, store, request, issuer, authority, current, owner, fence_id
    store.close()


def claim(p):
    service, unit, store, request, issuer, *_ = p
    context = issuer.issue(request, DIGEST, 'native-input', 'submitInput', unit.public_ref)
    service[0].verifier.verify_and_consume(context, 'submitInput', PROVIDER, unit.public_ref, DIGEST)
    store.record_operation_step(request, DIGEST, 'native-input', DIGEST, 1, 'unknown', {})
    return context


def query(p, *, service=None, revision=None, evidence=None):
    parts, unit, store, request, issuer, authority, current, owner, _ = p
    context = issuer.issue_query(request, DIGEST, 'native-input')
    if revision is None:
        return (service or parts[0]).query_input_session(unit.unit_ref, context, input_digest=DIGEST)
    return (service or parts[0]).reconcile_input_session(unit.unit_ref, context, input_digest=DIGEST,
        expected_source_revision=revision, evidence=owner.receipt if evidence is None else evidence)


def row(p):
    with p[0][1]._connect() as db:
        return dict(db.execute('SELECT * FROM harness_unit_sessions').fetchone())


def cold(p):
    parts = p[0]
    return UnitRecords(OperationJournal(parts[1].path), scope_authority=parts[3], native_evidence=parts[4],
        verifier=parts[0].verifier, epoch_port=parts[5], native_unit_evidence=parts[0].native_unit_evidence,
        input_association_evidence=parts[0].input_association_evidence)


def test_unclaimed_query_cannot_invent_first_input_association(association):
    p = association
    before = row(p)
    with pytest.raises(InvocationAuthorityRefused, match='durable claim'): query(p, revision=1)
    assert row(p) == before and p[2].read_operation_step(p[3], 'native-input') is None
    assert p[7].calls == 0 and p[0][0]._tickets == {}


def test_claim_projection_needs_successfully_verified_query_and_has_no_effect_permission(association):
    p = association
    claim(p)
    context = p[4].issue_query(p[3], DIGEST, 'native-input')
    with pytest.raises(InvocationAuthorityRefused):
        p[0][0].verifier.verify_claimed_query(context, PROVIDER, p[1].public_ref, DIGEST, operation_kind='managed-input')
    before = p[2].read_operation_step(p[3], 'native-input')
    p[0][0].verifier.verify_and_consume(context, 'query', PROVIDER, p[1].public_ref, DIGEST)
    result = p[0][0].verifier.verify_claimed_query(context, PROVIDER, p[1].public_ref, DIGEST, operation_kind='managed-input')
    assert result['query'] is True and result['action'] == 'query' and result['claimRevision'] is None
    assert p[2].read_operation_step(p[3], 'native-input') == before
    with pytest.raises(InvocationAuthorityRefused):
        p[0][0].verifier.verify_claimed_query(context, PROVIDER, p[1].public_ref, DIGEST, operation_kind='other-operation')


@pytest.mark.parametrize('damage', ['request', 'operation-kind', 'step', 'digest', 'native-correlation', 'capture', 'original-action'])
def test_other_claimed_operation_cannot_associate_original_input(association, damage):
    p = association
    original = p[2].read_operation(p[3])
    intent = original.intent
    context = json.loads(safe_json(intent.context_ref))
    kind, step_id, digest = 'managed-input', 'native-input', DIGEST
    if damage == 'operation-kind': kind = 'not-input'
    elif damage == 'step':
        step_id = 'other-step'
        context['invocationBindings'][step_id] = context['invocationBindings'].pop('native-input')
    elif damage == 'digest': digest = 'different-input-digest'
    elif damage == 'native-correlation': context['nativeCorrelation']['requestId'] = 2
    elif damage == 'capture': context['capturedInputRef']['contentDigest'] = 'sha256:' + 'b' * 64
    elif damage == 'original-action': context['invocationBindings']['native-input']['action'] = 'prepare'
    key = RequestKey('env', 'controlled-principal', 'substitute')
    changed = OperationIntent('other-input', kind, None, context,
        (StepIntent(step_id, PROVIDER, digest, 'other-native-input', management_epoch=0),), NODE, 0)
    p[2].reserve_operation(key, digest, changed)
    action = context['invocationBindings'][step_id]['action']
    effect = p[4].issue(key, digest, step_id, action, p[1].public_ref)
    p[0][0].verifier.verify_and_consume(effect, action, PROVIDER, p[1].public_ref, digest)
    read = p[4].issue_query(key, digest, step_id)
    with pytest.raises((UnitRecordsRefused, InvocationAuthorityRefused)):
        p[0][0].reconcile_input_session(p[1].unit_ref, read, input_digest=digest, expected_source_revision=1, evidence=p[7].receipt)
    assert row(p)['state'] == 'notCreated'
    if damage in {'operation-kind', 'step', 'original-action'}:
        assert p[7].calls == 0  # Core/record gate refuses before native owner.
    assert p[2].read_domain('env', FIRST_SESSION_ATTEMPTS, p[8])['value']['requestId'] == 'first-input'


def test_original_input_readonly_association_preserves_unknown_and_hold(association):
    p = association
    claim(p)
    before_core = p[2].read_operation(p[3])
    before_hold = p[2].read_domain('env', FIRST_SESSION_ATTEMPTS, p[8])
    assert query(p).state == 'notCreated'
    result = query(p, revision=1)
    assert result.state == 'confirmed' and result.source_revision == 2
    assert set(result.native_facts) == {'nativeRealm', 'sessionId', 'evidenceRef'}
    assert result.native_facts['sessionId'] == 'observed-native-session'
    assert result.association_facts['identity'] == p[7].expected
    assert result.association_facts['contractVersion'] == INPUT_SESSION_ASSOCIATION_VERSION
    assert query(p) == result and query(p, revision=2) == result
    assert p[2].read_operation(p[3]) == before_core and before_core.status == 'unknown'
    assert p[2].read_domain('env', FIRST_SESSION_ATTEMPTS, p[8]) == before_hold
    assert p[0][0]._tickets == {}


def test_cold_original_query_reconciles_without_replacement_ticket_or_input(association):
    p = association
    claim(p)
    reopened = cold(p)
    result = query(p, service=reopened, revision=1)
    assert result.state == 'confirmed' and reopened._tickets == {}
    assert query(p, service=cold(p)) == result
    assert p[2].read_operation_step(p[3], 'native-input').outcome == 'unknown'
    assert p[2].read_domain('env', FIRST_SESSION_ATTEMPTS, p[8])['value']['state'] == 'held'


@pytest.mark.parametrize('damage', ['version', 'extra', 'ack', 'default', 'digest', 'correlation', 'capture', 'boolean-owner', 'source'])
def test_wrong_native_proof_cannot_associate_or_relax_original_session_codec(association, damage):
    p = association
    claim(p)
    p[7].damage = damage
    before = row(p)
    with pytest.raises(UnitRecordsRefused): query(p, revision=1)
    assert row(p) == before and row(p)['state'] == 'notCreated'
    assert p[2].read_operation(p[3]).status == 'unknown'


@pytest.mark.parametrize('revision', [True, 0, 2, 999])
def test_first_association_strict_original_session_cas(association, revision):
    p = association
    claim(p)
    before = row(p)
    with pytest.raises(UnitRecordsRefused, match='revision conflict'): query(p, revision=revision)
    assert row(p) == before


@pytest.mark.parametrize('missing', ['association-owner', 'claimed-query', 'unit-owner'])
def test_missing_owner_or_original_claim_projection_cannot_associate(association, missing):
    p = association
    claim(p)
    if missing == 'association-owner': p[0][0].input_association_evidence = None
    elif missing == 'unit-owner': p[0][0].native_unit_evidence = None
    else:
        p[0][0].verifier = InvocationVerifier(p[4].verify_and_consume, p[4].verify_continuation)
    with pytest.raises((UnitRecordsRefused, InvocationAuthorityRefused)): query(p, revision=1)
    assert row(p)['state'] == 'notCreated'


@pytest.mark.parametrize('change', ['authority', 'activation', 'directory', 'epoch', 'unit-owner', 'association-owner', 'expiry'])
def test_current_authority_or_owner_change_refuses_association(association, change):
    p = association
    claim(p)
    if change == 'authority': p[5].allowed = False
    elif change == 'activation': p[6].active = False
    elif change == 'directory': p[6].permitted = False
    elif change == 'epoch':
        p[6].epoch = p[0][5].value = 1
    elif change == 'unit-owner': p[0][0].native_unit_evidence.valid = False
    elif change == 'association-owner': p[7].valid = False
    else: p[5].expiry = 50
    with pytest.raises((UnitRecordsRefused, InvocationAuthorityRefused)): query(p, revision=1)
    assert row(p)['state'] == 'notCreated'


@pytest.mark.parametrize('change', ['authority', 'epoch'])
def test_revocation_during_native_observation_rolls_back_recordonly_write(association, change):
    p = association
    claim(p)
    def revoke():
        if change == 'authority': p[5].allowed = False
        else: p[6].epoch = p[0][5].value = 1
    p[7].after_verify = revoke
    with pytest.raises((UnitRecordsRefused, InvocationAuthorityRefused)): query(p, revision=1)
    assert row(p)['state'] == 'notCreated'


def test_changed_owner_session_cannot_replace_confirmed_binding(association):
    p = association
    claim(p)
    result = query(p, revision=1)
    before = row(p)
    p[7].damage = 'session'
    with pytest.raises(UnitRecordsRefused, match='differs from native owner'): query(p)
    assert row(p) == before and result.native_facts['sessionId'] == 'observed-native-session'


def test_new_evidence_cannot_replace_already_confirmed_original_association(association):
    p = association
    claim(p)
    query(p, revision=1)
    before = row(p)
    with pytest.raises(UnitRecordsRefused): query(p, revision=2, evidence=source(p[1], 'other-receipt'))
    assert row(p) == before


def test_owner_loss_after_record_does_not_create_legacy_session_or_release_hold(association):
    p = association
    claim(p)
    query(p, revision=1)
    before = row(p)
    reopened = cold(p)
    reopened.input_association_evidence = None
    with pytest.raises(UnitRecordsRefused): query(p, service=reopened)
    assert row(p) == before
    with pytest.raises(UnitRecordsRefused, match='start fence'):
        p[0][0].begin_session(p[1].unit_ref, object(), input_digest='start-input')
    with pytest.raises(UnitRecordsRefused, match='start fence'):
        p[0][0].begin_unit(p[1].unit_ref, object(), input_digest='start-input')
    assert p[2].read_domain('env', FIRST_SESSION_ATTEMPTS, p[8])['value']['state'] == 'held'


def test_concurrent_original_queries_cas_one_recordonly_association(association):
    p = association
    claim(p)
    reopened = cold(p)
    def attempt(service):
        try: return query(p, service=service, revision=1)
        except UnitRecordsRefused as error:
            assert 'revision conflict' in str(error)
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(attempt, (p[0][0], reopened)))
    assert sum(item is not None for item in outcomes) == 1
    assert row(p)['source_revision'] == 2 and query(p).state == 'confirmed'
    assert p[0][0]._tickets == reopened._tickets == {}
    assert p[2].read_operation_step(p[3], 'native-input').outcome == 'unknown'


def test_sqlite_record_failure_preserves_session_absence_and_original_unknown(association):
    p = association
    claim(p)
    before = row(p)
    with p[0][1]._connect() as db:
        db.execute("CREATE TRIGGER reject_association BEFORE UPDATE ON harness_unit_sessions BEGIN SELECT RAISE(ABORT,'controlled failure'); END")
        db.commit()
    with pytest.raises(sqlite3.IntegrityError): query(p, revision=1)
    assert row(p) == before
    assert p[2].read_operation_step(p[3], 'native-input').outcome == 'unknown'
    assert p[2].read_domain('env', FIRST_SESSION_ATTEMPTS, p[8])['value']['state'] == 'held'


def test_commit_followed_by_owner_observation_failure_preserves_record_and_queries_original(association):
    p = association
    claim(p)
    p[7].fail_on = 2  # Initial proof succeeds; post-commit owner recheck fails.
    with pytest.raises(UnitRecordsRefused, match='receipt unavailable'): query(p, revision=1)
    persisted = row(p)
    assert persisted['state'] == 'confirmed' and persisted['source_revision'] == 2
    assert p[2].read_operation_step(p[3], 'native-input').outcome == 'unknown'
    assert p[2].read_domain('env', FIRST_SESSION_ATTEMPTS, p[8])['value']['state'] == 'held'
    p[7].fail_on = None
    observed = query(p, service=cold(p))
    assert observed.state == 'confirmed' and observed.native_json == persisted['native_json']
    with pytest.raises(UnitRecordsRefused, match='revision conflict'): query(p, revision=1)
    assert row(p) == persisted and p[0][0]._tickets == {}


@pytest.mark.parametrize('damage', ['remove-version', 'unknown-version', 'extra-field', 'wrong-digest', 'wrong-identity', 'revision3', 'missing-identity', 'nonmapping-identity', 'missing-native', 'nonmapping-unit'])
def test_damaged_association_never_falls_back_to_old_start_binding(association, damage):
    p = association
    claim(p)
    query(p, revision=1)
    before = row(p)
    proof = json.loads(before['native_json'])
    revision = 2
    if damage == 'remove-version': proof = proof['nativeBinding']
    elif damage == 'unknown-version': proof['contractVersion'] = 'unknown/1'
    elif damage == 'extra-field': proof['accepted'] = True
    elif damage == 'wrong-identity': proof['identity']['providerRef']['generation'] = True
    elif damage == 'revision3': revision = 3
    elif damage == 'missing-identity': del proof['identity']
    elif damage == 'nonmapping-identity': proof['identity'] = None
    elif damage == 'missing-native': del proof['nativeBinding']
    elif damage == 'nonmapping-unit': proof['identity']['unitRef'] = None
    encoded = safe_json(proof)
    digest = 'wrong' if damage == 'wrong-digest' else hashlib.sha256(encoded.encode()).hexdigest()
    with p[0][1]._connect() as db:
        db.execute('UPDATE harness_unit_sessions SET native_json=?,native_digest=?,source_revision=?', (encoded, digest, revision))
        db.commit()
    with pytest.raises(UnitRecordsRefused): query(p)
    assert row(p)['native_json'] == encoded and row(p)['source_revision'] == revision


def test_existing_start_session_keeps_original_codec_and_cannot_be_reinterpreted(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, 'PROVIDER', PROVIDER)
    monkeypatch.setattr(shared, 'NODE', NODE)
    p, unit, store, request, issuer, authority, current, issued = shared.real_core_parts(tmp_path)
    try:
        read = issuer.issue_query(request, 'flow-digest', 'prepare')
        result = p[0].read_session(unit.unit_ref, read, input_digest='input')
        assert result.state == 'confirmed' and result.source_revision == 3 and result.association_facts is None
        assert set(result.native_facts) == {'nativeRealm', 'sessionId', 'evidenceRef'}
        with p[1]._connect() as db:
            db.execute('UPDATE harness_unit_sessions SET source_revision=2')
            db.commit()
        with pytest.raises(UnitRecordsRefused, match='state and revision'):
            p[0].read_session(unit.unit_ref, read, input_digest='input')
        with p[1]._connect() as db:
            assert db.execute('SELECT source_revision FROM harness_unit_sessions').fetchone()['source_revision'] == 2
    finally:
        store.close()
