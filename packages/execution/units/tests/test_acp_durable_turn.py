"""Original SQLite/Local/SDK durability, cold authorized reads, no models."""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
import test_unit_instance as helpers
from ordessa_units.records import OperationJournal, UnitRecords, UnitRecordsRefused
from ordessa_units.records import acp_turns


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    def journal(path):
        path.touch(exist_ok=False)
        return OperationJournal(path, acp_turn_opt_in=True)
    def records(*args, **kwargs):
        return UnitRecords(*args, **kwargs, acp_turn_opt_in=True)
    monkeypatch.setattr(helpers, 'OperationJournal', journal)
    monkeypatch.setattr(helpers, 'UnitRecords', records)
    generator = helpers.flow.__wrapped__(tmp_path, monkeypatch)
    flow = next(generator)
    yield flow
    with pytest.raises(StopIteration):
        next(generator)


def start(flow):
    prepared, _ = helpers.prepare_and_start(flow)
    ref = prepared['unitRef']
    return ref, flow.leases.grant(ref)


def query(owner, flow, ref, operation, prompt_digest):
    invocation = flow.authority.issue('query')
    invocation.facts['query'] = True
    invocation.facts['inputDigest'] = UnitRecords.acp_turn_query_digest(ref, operation, prompt_digest)
    return owner.query_acp_turn(ref, operation, invocation,
        input_digest=invocation.facts['inputDigest'], expected_prompt_input_digest=prompt_digest)


def test_recorded_success_original_events_digest_and_cold_authorized_read(recorded, monkeypatch):
    peer = helpers.PEER.replace("elif method=='session/prompt':", """elif method=='session/prompt':
        for sid,text in [('controlled-native-session','original text'),('foreign-session','must not become output')]:
            print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':sid,'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':text}}}}),flush=True)
    elif method=='unused/prompt':""")
    # The original peer still executes its prompt result branch.
    peer = peer.replace("    elif method=='unused/prompt':\n", '')
    monkeypatch.setattr(helpers, 'PEER', peer)
    ref, lease = start(recorded)
    result = recorded.instance.prompt_recorded(ref, lease, operation_ref='turn-1', timeout=2, prompt=[])
    assert result['state'] == 'completed'
    assert result['summary']['text'] == 'original text'
    assert result['summary']['successfulRpcResponse'] is True
    assert result['summary']['modelQualityVerified'] is False
    assert result['request']['raw']['id'] == result['response']['id']
    assert len(result['events']) == 3
    assert result['events'][1]['sessionMatched'] is False
    assert result['inputDigest'] == UnitRecords.acp_prompt_input_digest(ref, {'prompt':[], 'sessionId':'controlled-native-session'})
    assert query(recorded.records, recorded, ref, 'turn-1', result['inputDigest']) == result
    def forbidden(*args, **kwargs):
        raise AssertionError('cold read must not ask live ACP/process evidence')
    cold = UnitRecords(OperationJournal(recorded.records.journal.path), scope_authority=helpers.Scope(),
        native_evidence=SimpleNamespace(verify_binding=forbidden), verifier=recorded.authority,
        epoch_port=SimpleNamespace(current_epoch=lambda node:0))
    assert query(cold, recorded, ref, 'turn-1', result['inputDigest']) == result
    # A separate interpreter has no original factories, threads or SDK handles.
    from ordessa_execution_api.environment.operations import safe_json
    child = r'''
import json,sys
from types import SimpleNamespace
from ordessa_units.records import OperationJournal,UnitRecords
class Scope:
 def verify_scope(self,scope,roots):return scope.environment_namespace=='env'
class Verifier:
 def verify_and_consume(self,ctx,action,provider,node,digest):
  assert ctx is invocation and action=='query' and ctx.facts['query'] is True
  assert (provider,node,digest)==(ctx.facts['providerRef'],ctx.facts['targetRef'],ctx.facts['inputDigest'])
  return ctx.facts
ref=json.loads(sys.argv[2]); expected=sys.argv[3]
records=UnitRecords(OperationJournal(sys.argv[1]),scope_authority=Scope(),native_evidence=object(),
 verifier=Verifier(),epoch_port=SimpleNamespace(current_epoch=lambda node:0))
unit=records.owner_read_unit(ref['unitId'])
query_digest=records.acp_turn_query_digest(ref,'turn-1',expected)
invocation=SimpleNamespace(facts={'query':True,'action':'query','providerRef':dict(unit.facts['providerRef']),
 'targetRef':dict(unit.facts['nodeRef']),'inputDigest':query_digest,'managementEpoch':0})
receipt=records.query_acp_turn(ref,'turn-1',invocation,input_digest=query_digest,expected_prompt_input_digest=expected)
assert receipt['state']=='completed' and receipt['summary']['text']=='original text'
print('cold-authorized-read-confirmed')
'''
    completed = subprocess.run([sys.executable, '-c', child, str(recorded.records.journal.path),
        safe_json(ref), result['inputDigest']], env={'PATH':os.environ['PATH']},
        capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == 'cold-authorized-read-confirmed'
    with pytest.raises(UnitRecordsRefused, match='no replay'):
        recorded.instance.prompt_recorded(ref, lease, operation_ref='turn-1', prompt=[])
    with pytest.raises(UnitRecordsRefused, match='prompt input digest'):
        query(cold, recorded, ref, 'turn-1', 'wrong-prompt-digest')
    with pytest.raises(UnitRecordsRefused, match='not found'):
        query(cold, recorded, ref, 'other-operation', result['inputDigest'])


@pytest.mark.parametrize('mode', ['error', 'malformed', 'lost'])
def test_known_remote_failure_and_unknown_are_not_success_or_replay(recorded, monkeypatch, mode):
    if mode == 'error':
        terminal = "print(json.dumps({'jsonrpc':'2.0','id':q['id'],'error':{'code':-32603,'message':'backend prompt failed','data':{'error':'original Connection error.'}}}),flush=True)"
    elif mode == 'malformed':
        terminal = "print(json.dumps({'jsonrpc':'2.0','id':q['id'],'result':{'stopReason':'error'}}),flush=True)"
    else:
        terminal = 'pass'
    peer = helpers.PEER.replace("elif method=='session/prompt':", "elif method=='session/prompt':\n        "+terminal+"\n        continue\n    elif method=='unused/prompt':")
    monkeypatch.setattr(helpers, 'PEER', peer)
    ref, lease = start(recorded)
    expected = UnitRecords.acp_prompt_input_digest(ref, {'prompt':[], 'sessionId':'controlled-native-session'})
    if mode == 'error':
        result = recorded.instance.prompt_recorded(ref, lease, operation_ref='failure-1', prompt=[], timeout=.2)
        assert result['state'] == 'failed'
        assert result['response']['error']['data'] == {'error':'original Connection error.'}
        assert result['summary']['knownRemoteFailure'] is True
    else:
        with pytest.raises(Exception):
            recorded.instance.prompt_recorded(ref, lease, operation_ref='failure-1', prompt=[], timeout=.2)
        result = query(recorded.records, recorded, ref, 'failure-1', expected)
        assert result['state'] == 'unknown'
        assert result['response'] is None
        from ordessa_units.admission.connection import ConnectionLeaseRefused
        refusal = ConnectionLeaseRefused if mode == 'lost' else UnitRecordsRefused
        with pytest.raises(refusal):
            recorded.instance.prompt_recorded(ref, lease, operation_ref='new-turn', prompt=[], timeout=.2)
        with pytest.raises(UnitRecordsRefused, match='unresolved'):
            acp_turns.reserve(recorded.records, ref, 'new-turn', {'prompt':[], 'sessionId':'controlled-native-session'})
    assert result['summary']['successfulRpcResponse'] is False
    from ordessa_units.admission.connection import ConnectionLeaseRefused
    refusal = ConnectionLeaseRefused if mode == 'lost' else UnitRecordsRefused
    with pytest.raises(refusal):
        recorded.instance.prompt_recorded(ref, lease, operation_ref='failure-1', prompt=[], timeout=.2)
    with recorded.records.journal._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_acp_turn_attempts').fetchone()[0] == 1
    assert recorded.events.count('spawn') == 1


@pytest.mark.parametrize('field,rehash', [('summary', False), ('summary', True), ('frame', True), ('session', True)])
def test_integrity_damage_refuses_cold_result_read(recorded, field, rehash):
    ref, lease = start(recorded)
    result = recorded.instance.prompt_recorded(ref, lease, operation_ref='integrity-1', prompt=[], timeout=2)
    with recorded.records.journal._connect() as db:
        row = db.execute('SELECT * FROM harness_acp_turn_attempts').fetchone()
        body = json.loads(row['body_json'])
        if field == 'summary':
            body['summary']['text'] = 'fabricated'
        elif field == 'frame':
            body['request']['raw']['id'] = 'different'
        else:
            body['nativeBinding']['sessionId'] = 'foreign'
        from ordessa_execution_api.environment.operations import safe_json
        db.execute('UPDATE harness_acp_turn_attempts SET body_json=?,body_digest=?',
                   (safe_json(body), acp_turns.digest(body) if rehash else row['body_digest']))
    with pytest.raises(UnitRecordsRefused):
        query(recorded.records, recorded, ref, 'integrity-1', result['inputDigest'])


def test_frozen_request_mutation_is_refused_before_native_bytes(recorded, monkeypatch):
    ref, lease = start(recorded)
    original = acp_turns.dispatch
    def mutate(owner, operation, raw):
        changed = dict(raw, params=dict(raw['params'], prompt=[{'type':'text','text':'not frozen'}]))
        return original(owner, operation, changed)
    monkeypatch.setattr(acp_turns, 'dispatch', mutate)
    with pytest.raises(UnitRecordsRefused, match='frozen prompt'):
        recorded.instance.prompt_recorded(ref, lease, operation_ref='mutation-1', prompt=[], timeout=2)
    expected = UnitRecords.acp_prompt_input_digest(ref, {'prompt':[], 'sessionId':'controlled-native-session'})
    result = query(recorded.records, recorded, ref, 'mutation-1', expected)
    assert result['state'] == 'unknown' and result['request'] is None
    assert result['events'] == ()


def test_observation_persistence_failure_cannot_be_reported_as_completed(recorded, monkeypatch):
    ref, lease = start(recorded)
    def fail(*args, **kwargs):
        raise RuntimeError('controlled original journal observation failure')
    monkeypatch.setattr(acp_turns, 'observe', fail)
    with pytest.raises(RuntimeError, match='durable ACP observation'):
        recorded.instance.prompt_recorded(ref, lease, operation_ref='capture-1', prompt=[], timeout=2)
    expected = UnitRecords.acp_prompt_input_digest(ref, {'prompt':[], 'sessionId':'controlled-native-session'})
    result = query(recorded.records, recorded, ref, 'capture-1', expected)
    assert result['state'] == 'unknown'
    assert result['summary']['successfulRpcResponse'] is False


def test_query_rejects_foreign_unit_and_nonquery_invocation(recorded):
    ref, lease = start(recorded)
    result = recorded.instance.prompt_recorded(ref, lease, operation_ref='authorized-1', prompt=[], timeout=2)
    invocation = recorded.authority.issue('query')
    invocation.facts['inputDigest'] = UnitRecords.acp_turn_query_digest(ref, 'authorized-1', result['inputDigest'])
    with pytest.raises(UnitRecordsRefused, match='verified invocation'):
        recorded.records.query_acp_turn(ref, 'authorized-1', invocation,
            input_digest=invocation.facts['inputDigest'], expected_prompt_input_digest=result['inputDigest'])
    foreign = dict(ref, sourceRevision='foreign')
    with pytest.raises(UnitRecordsRefused, match='Unit reference differs'):
        query(recorded.records, recorded, foreign, 'authorized-1', result['inputDigest'])


def test_schema_opt_in_cannot_migrate_existing_journal(tmp_path):
    path = tmp_path/'original.sqlite'
    OperationJournal(path)
    from ordessa_units.records import JournalError
    with pytest.raises(JournalError, match='pristine'):
        OperationJournal(path, acp_turn_opt_in=True)


def test_revoked_cached_lease_cannot_reserve_durable_operation(recorded):
    ref, lease = start(recorded)
    recorded.instance.connect(ref, lease)
    recorded.leases.revoke(ref)
    from ordessa_units.admission.connection import ConnectionLeaseRefused
    with pytest.raises(ConnectionLeaseRefused):
        recorded.instance.prompt_recorded(ref, lease, operation_ref='revoked-1', prompt=[], timeout=2)
    with recorded.records.journal._connect() as db:
        assert db.execute('SELECT count(*) FROM harness_acp_turn_attempts').fetchone()[0] == 0
