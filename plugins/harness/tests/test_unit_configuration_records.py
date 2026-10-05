"""Configuration correlation in the original SQLite journal; controlled owner evidence.

No native Harness/SDK/model is run. Current configuration values are never
written here and cannot be used to settle an original native attempt.
"""
import copy
import hashlib
import json

import pytest
from ordessa_environment_api.operations import safe_json

from test_unit_records import parts, reserve, begin, PROVIDER, NODE
from ordessa_harness_records.unit_records import (
    UnitRecords, UnitRecordsRefused, ConfigurationRecordTicket,
)

DIGEST = 'sha256:' + 'a' * 64
NATIVE_DIGEST = 'sha256:' + 'b' * 64


class Evidence:
    def __init__(self):
        self.valid = True
        self.change = None

    def verify_configuration(self, unit, identity, native_id, native_digest, evidence):
        if not self.valid or evidence != 'original-native-receipt':
            raise UnitRecordsRefused('original native receipt unavailable')
        result = {key: identity[key] for key in ('operationRef', 'unitRef', 'scopeRef', 'requestDigest')}
        result.update(nativeRequestId=7, nativeRequestDigest=NATIVE_DIGEST, evidenceRef=evidence)
        if self.change:
            result.update(self.change)
        return result


def setup(tmp_path):
    p = parts(tmp_path)
    unit, _ = reserve(p)
    ticket = begin(p, unit)
    p[0].record_session(ticket, expected_source_revision=2, state='confirmed', evidence='real-native-owner-evidence')
    p[0].configuration_evidence = Evidence()
    return p, unit


def context(p, unit, action='applyConfiguration', step='configuration-apply', digest=DIGEST):
    return p[2].issue(action, step, digest, node=unit.configuration_target_ref)


def opening(p, unit):
    return p[0].begin_configuration_change(unit.unit_ref, context(p, unit), input_digest=DIGEST, expected_revision='native-version-1')


def test_configuration_attempt_keeps_same_scope_with_complete_owner_sources(tmp_path):
    p, unit = setup(tmp_path)
    ticket = opening(p, unit)
    attempt = p[0].bind_configuration_dispatch(ticket, native_request_id=7, native_request_digest=NATIVE_DIGEST)
    assert attempt.identity['unitRef'] == unit.public_ref
    assert attempt.identity['scopeRef'] == unit.configuration_target_ref
    assert {name: attempt.identity['scopeRef'][name] for name in ('environmentNamespace', 'scopeId', 'revision')} == unit.scope_ref.to_dict()
    assert attempt.identity['scopeRef']['ownerProviderRef'] == PROVIDER
    assert attempt.identity['scopeRef']['sourceRevision'].startswith('sha256:')
    assert unit.configuration_target_ref == unit.scope_ref.owner_ref(PROVIDER)


def test_older_incomplete_attempt_is_not_reinterpreted_or_released(tmp_path):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    p[0].record_configuration_change(ticket, expected_source_revision=2, state='unknown')
    with p[1]._connect() as db:
        row = db.execute('SELECT attempt_ref,identity_json FROM harness_unit_configuration_attempts').fetchone()
        identity = json.loads(row['identity_json'])
        identity['unitRef'] = {'environmentNamespace': 'env', 'unitId': unit.unit_ref}
        identity['scopeRef'] = unit.scope_ref.to_dict()
        encoded = safe_json(identity)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        db.execute('UPDATE harness_unit_configuration_attempts SET identity_json=?,identity_digest=? WHERE attempt_ref=?', (encoded, digest, row['attempt_ref']))
        db.commit()
    with pytest.raises(UnitRecordsRefused, match='scope or owner changed'): query(p, unit)
    with pytest.raises(UnitRecordsRefused, match='retains scope fence'):
        p[0].begin_configuration_change(unit.unit_ref, context(p, unit, step='another-key'), input_digest=DIGEST, expected_revision='native-version-1')
    with p[1]._connect() as db:
        unchanged = db.execute('SELECT state,identity_json FROM harness_unit_configuration_attempts').fetchone()
        assert unchanged['state'] == 'unknown' and unchanged['identity_json'] == encoded


def bound(p, unit):
    ticket = opening(p, unit)
    value = p[0].bind_configuration_dispatch(ticket, native_request_id=7, native_request_digest=NATIVE_DIGEST)
    assert value.state == 'opening' and value.source_revision == 2
    return ticket


def query(p, unit, service=None):
    return (service or p[0]).query_configuration_change(unit.unit_ref, 'operation',
        context(p, unit, 'query'), input_digest=DIGEST)


def test_original_request_is_persisted_before_native_dispatch_and_confirmed(tmp_path):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    assert query(p, unit).native_request_id == 7
    result = p[0].record_configuration_change(ticket, expected_source_revision=2,
        state='confirmed', evidence='original-native-receipt')
    assert result.source_revision == 3 and result.confirmation['requestDigest'] == DIGEST
    assert query(p, unit) == result
    with p[1]._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_unit_configuration_attempts').fetchone()[0] == 1
        row = dict(db.execute('SELECT * FROM harness_unit_configuration_attempts').fetchone())
        assert 'actual' not in json.dumps(row) and 'payload' not in json.dumps(row)


def test_unknown_survives_restart_and_cannot_bind_or_create_replacement(tmp_path):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    p[0].record_configuration_change(ticket, expected_source_revision=2, state='unknown')
    reopened = UnitRecords(type(p[1])(p[1].path), scope_authority=p[3], native_evidence=p[4],
        verifier=p[2], epoch_port=p[5], configuration_evidence=p[0].configuration_evidence)
    result = query(p, unit, reopened)
    assert result.state == 'unknown' and result.native_request_id == 7
    with pytest.raises(UnitRecordsRefused, match='not owned'):
        reopened.bind_configuration_dispatch(ticket, native_request_id=8, native_request_digest=NATIVE_DIGEST)
    with pytest.raises(UnitRecordsRefused, match='cannot dispatch again'):
        opening(p, unit)
    with pytest.raises(UnitRecordsRefused, match='retains scope fence'):
        p[0].begin_configuration_change(unit.unit_ref, context(p, unit, step='replacement'),
            input_digest=DIGEST, expected_revision='native-version-2')


def test_duplicate_rpc_binding_never_replaces_original_id(tmp_path):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    with pytest.raises(UnitRecordsRefused, match='already bound'):
        p[0].bind_configuration_dispatch(ticket, native_request_id=8, native_request_digest=NATIVE_DIGEST)
    assert query(p, unit).native_request_id == 7


@pytest.mark.parametrize('bad', [True, None, '', {}, []])
def test_invalid_native_id_refused_before_binding(tmp_path, bad):
    p, unit = setup(tmp_path)
    ticket = opening(p, unit)
    with pytest.raises(UnitRecordsRefused, match='exact native'):
        p[0].bind_configuration_dispatch(ticket, native_request_id=bad, native_request_digest=NATIVE_DIGEST)
    assert query(p, unit).native_request_id is None


def test_ack_current_values_or_missing_receipt_cannot_confirm(tmp_path):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    for evidence in ('ACK', 'matching-current-values', None):
        with pytest.raises(UnitRecordsRefused, match='original native receipt'):
            p[0].record_configuration_change(ticket, expected_source_revision=2, state='confirmed', evidence=evidence)
    assert query(p, unit).state == 'opening'
    p[0].record_configuration_change(ticket, expected_source_revision=2, state='unknown')
    assert p[0].record_configuration_change(ticket, expected_source_revision=3,
        state='confirmed', evidence='original-native-receipt').state == 'confirmed'


@pytest.mark.parametrize('change', [
    {'operationRef':'wrong'}, {'requestDigest':'wrong'}, {'unitRef':NODE},
    {'scopeRef':NODE}, {'nativeRequestId':8}, {'nativeRequestId':True},
    {'nativeRequestDigest':'wrong'}, {'secret':'do-not-persist'},
])
def test_mismatched_confirmation_cannot_settle(tmp_path, change):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    p[0].configuration_evidence.change = change
    with pytest.raises(UnitRecordsRefused, match='identity differs'):
        p[0].record_configuration_change(ticket, expected_source_revision=2,
            state='confirmed', evidence='original-native-receipt')
    assert query(p, unit).state == 'opening'


def test_missing_evidence_port_refuses_before_consuming_context(tmp_path):
    p, unit = setup(tmp_path)
    p[0].configuration_evidence = None
    issued = context(p, unit)
    with pytest.raises(UnitRecordsRefused, match='port unavailable'):
        p[0].begin_configuration_change(unit.unit_ref, issued, input_digest=DIGEST, expected_revision='1')
    assert issued in p[2].issued


def test_forgery_copy_epoch_and_terminal_ticket_refused(tmp_path):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    with pytest.raises(TypeError): copy.copy(ticket)
    with pytest.raises(UnitRecordsRefused, match='not owned'):
        p[0].record_configuration_change(object.__new__(ConfigurationRecordTicket), expected_source_revision=2, state='unknown')
    p[5].value = 1
    with pytest.raises(UnitRecordsRefused, match='epoch expired'):
        p[0].record_configuration_change(ticket, expected_source_revision=2, state='unknown')
    p[5].value = 0
    p[0].record_configuration_change(ticket, expected_source_revision=2, state='confirmed', evidence='original-native-receipt')
    with pytest.raises(UnitRecordsRefused, match='not owned'):
        p[0].record_configuration_change(ticket, expected_source_revision=3, state='unknown')


def test_query_original_identity_and_receipt_revalidation(tmp_path):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    with pytest.raises(UnitRecordsRefused, match='query operation identity'):
        p[0].query_configuration_change(unit.unit_ref, 'foreign', context(p, unit, 'query'), input_digest=DIGEST)
    with pytest.raises(UnitRecordsRefused, match='digest differs'):
        p[0].query_configuration_change(unit.unit_ref, 'operation', context(p, unit, 'query', digest='different'), input_digest='different')
    p[0].record_configuration_change(ticket, expected_source_revision=2, state='confirmed', evidence='original-native-receipt')
    p[0].configuration_evidence.valid = False
    with pytest.raises(UnitRecordsRefused, match='original native receipt'):
        query(p, unit)


def test_revision_conflict_does_not_overwrite_evidence(tmp_path):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    with pytest.raises(UnitRecordsRefused, match='revision conflict'):
        p[0].record_configuration_change(ticket, expected_source_revision=1, state='unknown')
    assert query(p, unit).source_revision == 2


def test_parallel_new_keys_have_one_original_scope_claim(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    p, unit = setup(tmp_path)
    contexts = [context(p, unit, step='configuration-' + str(i)) for i in range(2)]
    def claim(issued):
        try:
            return p[0].begin_configuration_change(unit.unit_ref, issued,
                input_digest=DIGEST, expected_revision='1')
        except UnitRecordsRefused:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, contexts))
    assert sum(result is not None for result in results) == 1
    with p[1]._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_unit_configuration_attempts').fetchone()[0] == 1


def test_confirmed_attempt_does_not_block_new_operation(tmp_path):
    p, unit = setup(tmp_path)
    ticket = bound(p, unit)
    p[0].record_configuration_change(ticket, expected_source_revision=2, state='confirmed', evidence='original-native-receipt')
    next_ticket = p[0].begin_configuration_change(unit.unit_ref, context(p, unit, step='second'),
        input_digest=DIGEST, expected_revision='2')
    assert next_ticket is not ticket
    with p[1]._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_unit_configuration_attempts').fetchone()[0] == 2


def test_damaged_native_request_binding_is_not_reported_as_original(tmp_path):
    p, unit = setup(tmp_path)
    bound(p, unit)
    with p[1]._connect() as db:
        db.execute("UPDATE harness_unit_configuration_attempts SET native_request_json=?", ('{"requestId":true}',))
        db.commit()
    with pytest.raises(UnitRecordsRefused, match='binding damaged'):
        query(p, unit)


def real_core_parts(tmp_path, *, start_native_session=True):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'products/agent-tools/tests/integration'))
    from test_invocation_authority import Authority, CurrentState
    from ordessa_environment_api import RequestKey
    from ordessa_environment_api.operations import OperationIntent, StepIntent
    from ordessa_persistence_sqlite import SqliteStorePort
    from pacthold.agents.directory import DirectoryBindingRef
    from pacthold.agents.invocation import InvocationIssuer
    p = parts(tmp_path)
    target = p[3].scope.owner_ref(PROVIDER)
    request = RequestKey('env', 'controlled-principal', 'unit-flow')
    directory = DirectoryBindingRef('env', 'directory', 1, 'sha256:' + 'd' * 64)
    bindings = {
        'prepare': {'action':'prepare','targetRef':NODE,'delegationRef':None,'cleanup':False},
        'start': {'action':'start','targetRef':NODE,'delegationRef':None,'cleanup':False},
        'configuration': {'action':'applyConfiguration','targetRef':target,'delegationRef':None,'cleanup':False},
    }
    store = SqliteStorePort(tmp_path / 'core.sqlite')
    intent = OperationIntent('flow-operation','controlled-unit-flow',None,
        {'environmentNamespace':'env','directoryBindingRef':directory.to_dict(),'invocationBindings':bindings},
        (StepIntent('prepare',PROVIDER,'input','prepare-correlation'),
         StepIntent('start',PROVIDER,'start-input','start-correlation'),
         StepIntent('configuration',PROVIDER,DIGEST,'config-correlation')))
    store.reserve_operation(request, 'flow-digest', intent)
    authority = Authority()
    current = CurrentState(PROVIDER, directory, target)
    issuer = InvocationIssuer(store, authority, current, clock=lambda:50)
    p[0].verifier = issuer.verifier()
    p[0].configuration_evidence = Evidence()
    def issued(step):
        binding = bindings[step]
        return issuer.issue(request, 'flow-digest', step, binding['action'], binding['targetRef'])
    unit, _ = p[0].reserve_unit(issued('prepare'), provider_ref=PROVIDER,node_ref=NODE,
        input_digest='input',private_root_facts=__import__('test_unit_records').ROOT)
    store.record_operation_step(request,'flow-digest','prepare','input',1,'concluded',{'unitRef':unit.unit_ref})
    if start_native_session:
        session_ticket = p[0].begin_session(unit.unit_ref, issued('start'), input_digest='start-input')
        p[0].record_session(session_ticket, expected_source_revision=2,state='confirmed',evidence='real-native-owner-evidence')
        store.record_operation_step(request,'flow-digest','start','start-input',1,'concluded',{'evidenceRef':'real-native-owner-evidence'})
    return p, unit, store, request, issuer, authority, current, issued


def test_configuration_journal_consumes_real_core_claim_and_queries_same_original_step(tmp_path):
    p, unit, store, request, issuer, _, _, issued = real_core_parts(tmp_path)
    try:
        invocation = issued('configuration')
        ticket = p[0].begin_configuration_change(unit.unit_ref, invocation,
            input_digest=DIGEST, expected_revision='native-1')
        assert issuer.verified_consumption(invocation) is True
        assert store.read_operation_step(request,'configuration').outcome == 'possibly-dispatched'
        p[0].bind_configuration_dispatch(ticket,native_request_id=7,native_request_digest=NATIVE_DIGEST)
        p[0].record_configuration_change(ticket,expected_source_revision=2,state='unknown')
        read_context = issuer.issue_query(request,'flow-digest','configuration')
        original = p[0].query_configuration_change(unit.unit_ref,'flow-operation',read_context,input_digest=DIGEST)
        assert original.state == 'unknown' and original.identity['operationRef'] == 'flow-operation'
        assert issuer.verified_observation(read_context) is True
        with pytest.raises(Exception, match='existing step claim'):
            issued('configuration')
    finally:
        store.close()


@pytest.mark.parametrize('revoke', ['authority','activation','directory','epoch'])
def test_configuration_journal_rejects_real_revoked_core_context_before_reservation(tmp_path, revoke):
    from pacthold.agents.invocation import InvocationAuthorityRefused
    p, unit, store, request, issuer, authority, current, issued = real_core_parts(tmp_path)
    try:
        invocation = issued('configuration')
        if revoke == 'authority': authority.allowed = False
        elif revoke == 'activation': current.active = False
        elif revoke == 'directory': current.permitted = False
        else: current.epoch = 1
        with pytest.raises(InvocationAuthorityRefused):
            p[0].begin_configuration_change(unit.unit_ref, invocation,input_digest=DIGEST,expected_revision='native-1')
        assert issuer.verified_consumption(invocation) is False
        with p[1]._connect() as db:
            assert db.execute('SELECT count(*) FROM harness_unit_configuration_attempts').fetchone()[0] == 0
        assert store.read_operation_step(request,'configuration').outcome == 'possibly-dispatched'
    finally:
        store.close()
