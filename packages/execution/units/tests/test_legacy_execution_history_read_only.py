"""Current schema fixtures are test-created; no claim of a migration original."""
import hashlib
import json
from importlib.resources import files
import sqlite3
import pytest
from ordessa_units.legacy.read_only import ExecutionHistory, HistoryNotFound, parse_correlation

@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'history.db'
    source = files('pacthold').joinpath('migrations/001_core_schema.sql')
    with sqlite3.connect(path) as conn:
        conn.executescript(source.read_text())
        conn.execute("INSERT INTO core_works VALUES ('work', 'original objective', 'open', NULL, '{}', 'time', 'time', 3)")
        conn.execute("INSERT INTO core_works VALUES ('standalone', 'tooling only', 'open', NULL, '{}', 'time', 'time', 0)")
        conn.execute("INSERT INTO core_executions VALUES ('exec', 'work', 'codex', 'unknown', NULL, NULL, 'stale', 'time', '{}', 'time', NULL, NULL, NULL, 7)")
        for tag in ('SessionRef', 'WorkflowInstanceRef', 'RunRef', 'WorkspaceRef', 'ArtifactRef'):
            conn.execute("INSERT INTO core_execution_refs VALUES ('exec', 'native', ?, 'original-provider', ?, 'native://original', '{}', 'time', NULL)", (tag, tag))
        conn.execute("INSERT INTO core_dispatches VALUES ('dispatch', 'exec', 'key', 'ambiguous', 'old-opaque-token', 'digest', 'time', 'time')")
        conn.execute("INSERT INTO core_events VALUES ('event', 'exec', 'OriginalUnknown', 'time', '{\"fence\":\"original\"}', 'event-key')")
        conn.execute("INSERT INTO core_execution_finalizations VALUES ('exec', 'final-key', 'bundle', 7, 'time')")
    return path

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_reads_preserve_original_unknown_keys_versions_and_wire_tags(database):
    before = digest(database)
    with ExecutionHistory(database) as history:
        assert history.execution('exec')['phase'] == 'unknown'
        assert history.execution('exec')['version'] == 7
        assert history.linked_work('exec')['objective'] == 'original objective'
        assert {ref.tag for _, ref in history.refs('exec')} == {'SessionRef', 'WorkflowInstanceRef', 'RunRef', 'WorkspaceRef', 'ArtifactRef'}
        dispatch = history.dispatches('exec')[0]
        assert (dispatch['idempotency_key'], dispatch['state'], dispatch['provider_correlation_ref']) == ('key', 'ambiguous', 'old-opaque-token')
        assert history.events('exec')[0]['data_json'] == '{"fence":"original"}'
        assert history.finalizations('exec')[0]['bundle_digest'] == 'bundle'
        assert history.observations('exec') == ()
        with pytest.raises(TypeError):
            history.execution('exec')['phase'] = 'completed'
        with pytest.raises(HistoryNotFound):
            history.execution('standalone')
        assert not hasattr(history, 'create_work') and not hasattr(history, 'create_execution')
        assert not hasattr(history, 'dispatch') and not hasattr(history, 'finalize_execution')
        with pytest.raises(sqlite3.OperationalError):
            history._ExecutionHistory__connection.execute("DELETE FROM core_works")
    assert digest(database) == before

def test_missing_history_is_not_created(tmp_path):
    missing = tmp_path / 'absent.db'
    with pytest.raises(FileNotFoundError):
        ExecutionHistory(missing)
    assert not missing.exists()

@pytest.mark.parametrize('value', ['old-token', 'ref:v1:not-json', 'ref:v1:{"type":"FutureTag"}', 'ref:v1:{"type":"RunRef","provider":"p","native_id":"id","metadata":{"k":7}}'])
def test_malformed_and_opaque_correlations_preserve_original_text(value):
    assert parse_correlation(value) == (None, value)

def test_correlation_reads_original_fields_and_bounds():
    payload = {'type': 'SessionRef', 'provider': 'codex', 'native_id': 'session', 'uri': 'original', 'metadata': {'key': 'value'}}
    value = 'ref:v1:' + json.dumps(payload)
    ref, opaque = parse_correlation(value)
    assert opaque is None and ref.tag == 'SessionRef' and ref.metadata == {'key': 'value'}
    with pytest.raises(TypeError):
        ref.metadata['key'] = 'changed'
    assert parse_correlation(None) == (None, None)


def test_historical_execution_list_preserves_isolation_stable_sort_and_missing_work(database):
    with sqlite3.connect(database) as conn:
        for identity, work, created in [('z-tie', 'work', 'ztime'), ('a-tie', 'work', 'ztime'), ('other', 'standalone', 'ztime')]:
            conn.execute("INSERT INTO core_executions SELECT ?, ?, provider_id, phase, outcome, resumable_now, freshness, observed_at, provenance_json, ?, dispatched_at, started_at, ended_at, version FROM core_executions WHERE id='exec'", (identity, work, created))
        conn.execute("INSERT INTO core_works VALUES ('empty', 'no executions', 'completed', 'original closure', '{}', 'time', 'time', 2)")
    before = digest(database)
    with ExecutionHistory(database) as history:
        assert [row['id'] for row in history.executions_for_work('work')] == ['exec', 'a-tie', 'z-tie']
        assert [row['id'] for row in history.executions_for_work('standalone')] == ['other']
        assert history.executions_for_work('empty') == ()
        assert history.historical_work('empty')['closure_reason'] == 'original closure'
        with pytest.raises(HistoryNotFound, match='missing'):
            history.executions_for_work('missing')
    assert digest(database) == before


def test_creation_responsibility_readable_without_inheriting_work_objective(database):
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO core_events VALUES ('created', 'exec', 'ExecutionCreated', 'time', ?, NULL)",
                     (json.dumps({'provider': 'codex', 'responsibility_intent': 'independent execution responsibility'}),))
    with ExecutionHistory(database) as history:
        assert history.responsibility_intent('exec') == 'independent execution responsibility'
        assert history.historical_work('work')['objective'] == 'original objective'
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE core_events SET data_json=? WHERE id='created'", (json.dumps({'provider': 'codex'}),))
    before = digest(database)
    with ExecutionHistory(database) as history:
        assert history.responsibility_intent('exec') is None
    assert digest(database) == before


def test_multiple_exact_input_and_conflicting_unknown_observations_remain_distinct(database):
    with sqlite3.connect(database) as conn:
        for native in ('one', 'two'):
            conn.execute("INSERT INTO core_execution_refs VALUES ('exec', 'input', 'WorkspaceRef', 'workspace', ?, NULL, '{}', 'time', 'workspace@1')", (native,))
        for index, native, result, role in [(1, 'one', 'unknown', 'host_observer'), (2, 'one', 'mismatch', 'resource_provider'), (3, 'two', 'unverifiable', 'external_authority')]:
            conn.execute("""INSERT INTO core_resource_observations (
                execution_id,contract_id,ref_type,ref_provider,ref_native_id,ref_meta_json,
                ref_identity_digest,kind,result,observer_role,observer_id,observed_at,
                coverage,observation_digest,recorded_at,evidence_type,evidence_provider,
                evidence_native_id,evidence_meta_json)
                VALUES ('exec','workspace@1','WorkspaceRef','workspace',?,'{}',?,'read_back',?,?,?,'time','partial',?,'time','ArtifactRef','evidence',?,?)""",
                (native, 'identity-'+native, result, role, 'observer-'+str(index), 'digest-'+str(index), 'evidence-'+str(index), json.dumps({'source': str(index)})))
    before = digest(database)
    with ExecutionHistory(database) as history:
        inputs = [ref.native_id for row, ref in history.refs('exec') if row['relation'] == 'input']
        assert inputs == ['one', 'two']
        observations = history.observations('exec')
        assert [row['result'] for row in observations] == ['unknown', 'mismatch', 'unverifiable']
        assert [row['ref_native_id'] for row in observations] == ['one', 'one', 'two']
        assert [json.loads(row['evidence_meta_json']) for row in observations] == [{'source': '1'}, {'source': '2'}, {'source': '3'}]
        assert len({row['observation_digest'] for row in observations}) == 3
        assert history.execution('exec')['phase'] == 'unknown'
    assert digest(database) == before


def test_historical_resource_state_and_late_terminal_observation_do_not_merge_ledgers(database):
    state_event = {'observation_kind': 'resource', 'ref_type': 'WorkspaceRef',
                   'ref_provider': 'workspace', 'ref_native_id': 'input',
                   'ref_identity_digest': 'original-algorithm-digest', 'resource_state': 'materialized'}
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE core_executions SET phase='terminal',outcome='succeeded',resumable_now=0 WHERE id='exec'")
        conn.execute("INSERT INTO core_events VALUES ('state-event','exec','ExecutionProjectionChanged','later',?,NULL)", (json.dumps(state_event),))
    before = digest(database)
    with ExecutionHistory(database) as history:
        original = history.execution('exec')
        assert (original['phase'], original['outcome'], original['version']) == ('terminal', 'succeeded', 7)
        events = history.events('exec')
        assert json.loads(next(row for row in events if row['id'] == 'state-event')['data_json']) == state_event
        assert history.observations('exec') == ()
        assert history.execution('exec') == original
        assert history.finalizations('exec')[0]['bundle_digest'] == 'bundle'
    assert digest(database) == before
