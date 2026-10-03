"""Continuation metadata survives restart; native ownership never does.

SQLite event-log fixture and correlated ACP frames only. No model inference.
"""
import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ordessa_harness.server_acp.history import NativeSessionHistory
from ordessa_harness.server_acp.instance_directory import allocate_instance_directory
from ordessa_harness.server_acp.registry import _Channel, _ObservedTransport


@pytest.fixture
def records(tmp_path):
    path = tmp_path / 'history.sqlite'
    @contextmanager
    def read():
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            yield conn
    with read() as conn:
        conn.executescript('CREATE TABLE server_sessions(id TEXT,archived_at TEXT);'
            'CREATE TABLE server_session_events(session_id TEXT,data_json TEXT,created_at TEXT,kind TEXT);'
            "INSERT INTO server_sessions VALUES('ledger',NULL);")
    def append(turn, kind, data):
        assert turn == 'execution'
        with read() as conn:
            conn.execute('INSERT INTO server_session_events VALUES(?,?,?,?)',
                         ('ledger', json.dumps(data), '2026-10-03T00:00:00Z', kind))
    return SimpleNamespace(database=SimpleNamespace(data_root=tmp_path, read=read), append_turn_event=append)


def channel(records):
    value = _Channel(connection_id='connection', harness_id='pi', workspace_id='project',
                     profile_id='native', cwd='/project', session_scope_id='attempt')
    value.session_id, value.execution_id = 'ledger', 'execution'
    value.transport = _ObservedTransport(value, SimpleNamespace(
        instance_directory=str(allocate_instance_directory(records.database.data_root)), send_line=lambda _: None))
    value.history_writer = NativeSessionHistory(records).remember
    return value


def request(value, id, method, **params):
    value.transport.send_line(json.dumps(dict(jsonrpc='2.0', id=id, method=method, params=params)))


def reply(value, id, **body):
    value.deliver(json.dumps(dict(jsonrpc='2.0', id=id, **body)))


def test_empty_new_and_failed_prompt_do_not_become_history(records):
    value = channel(records)
    request(value, 'new', 'session/new')
    reply(value, 'new', result={'sessionId': 'native'})
    assert NativeSessionHistory(records).list('pi') == []
    request(value, 'prompt', 'session/prompt', sessionId='native', prompt=[{'type': 'text', 'text': 'hello'}])
    reply(value, 'prompt', error={'code': -1})
    assert NativeSessionHistory(records).list('pi') == []


def test_completed_prompt_persists_without_secrets_or_profile_dependency(records):
    value = channel(records)
    request(value, 'new', 'session/new')
    reply(value, 'new', result={'sessionId': 'native'})
    for id, text in [('first', 'hello'), ('second', 'followup')]:
        request(value, id, 'session/prompt', sessionId='native', prompt=[{'type': 'text', 'text': text}])
        reply(value, id, result={'stopReason': 'end_turn'})
    history = NativeSessionHistory(records)  # cold projection, no live channels
    assert history.list('pi') == [{'id': 'ledger', 'title': 'hello', 'workspaceId': 'project',
                                  'updatedAt': '2026-10-03T00:00:00Z'}]
    assert history.list('codex') == []
    retained = history.lookup('pi', 'ledger', 'project')
    assert retained['nativeId'] == 'native'
    assert 'configurationProfileId' not in retained
    with pytest.raises(ValueError):
        history.lookup('pi', 'ledger', 'other-project')
    with pytest.raises(ValueError):
        history.lookup('claude-code', 'ledger', 'project')


def test_instance_missing_or_symlink_refuses_and_keeps_listing(records):
    value = channel(records)
    NativeSessionHistory(records).remember(value, 'native', 'hello')
    from pathlib import Path
    directory = Path(value.transport.instance_directory)
    directory.rmdir()
    directory.symlink_to(records.database.data_root, target_is_directory=True)
    history = NativeSessionHistory(records)
    with pytest.raises(ValueError):
        history.lookup('pi', 'ledger', 'project')
    assert len(history.list('pi')) == 1


def test_load_confirmation_creates_fresh_owner_but_foreign_or_error_does_not(records):
    value = channel(records)
    value.restore_native_id = 'native'
    request(value, 'foreign', 'session/load', sessionId='other')
    reply(value, 'foreign', result={})
    assert value.native_session_observation('other') is None
    request(value, 'bad', 'session/load', sessionId='native')
    reply(value, 'bad', error={'code': -1})
    assert value.native_session_observation('native') is None
    request(value, 'good', 'session/load', sessionId='native')
    reply(value, 'good', result={})
    owner = value.native_session_observation('native')
    assert owner.connection_id == 'connection'
    assert owner.execution_id == 'execution'
    assert NativeSessionHistory(records).list('pi') == []


def test_duplicate_request_and_persistence_error_never_claim_history(records):
    value = channel(records)
    request(value, 'new', 'session/new')
    reply(value, 'new', result={'sessionId': 'native'})
    for _ in range(2):
        request(value, 'ambiguous', 'session/prompt', sessionId='native', prompt=[])
    reply(value, 'ambiguous', result={})
    assert NativeSessionHistory(records).list('pi') == []
    def fail(*_):
        raise OSError('fixture unavailable')
    value.history_writer = fail
    request(value, 'failed-write', 'session/prompt', sessionId='native', prompt=[])
    reply(value, 'failed-write', result={})
    assert value.history_error
    assert NativeSessionHistory(records).list('pi') == []


def test_restore_reuses_only_original_directory_and_serializes_history_owner(records, monkeypatch):
    import ordessa_harness.server_acp.registry as implementation
    original = channel(records)
    NativeSessionHistory(records).remember(original, 'native', 'hello')
    launches = []
    monkeypatch.setattr(implementation, 'open_run', lambda **_: ('fresh-ledger', 'fresh-execution', {}))
    records.finish_cancelled = lambda *_, **__: None
    def launch(**kw):
        launches.append(kw)
        return SimpleNamespace(instance_directory=kw['retained_instance_directory'], terminate=lambda: None)
    registry = implementation.AcpChannelRegistry(session_records=records, profile_records=None, launch=launch)
    kwargs = dict(harness_id='pi', workspace_id='project', profile_id='native', cwd='/project',
                  history_session_id='ledger', session_scope_id='caller-one')
    opened = registry.acquire(**kwargs)
    assert opened['historySessionId'] == 'ledger' and opened['nativeSessionId'] == 'native'
    assert launches[0]['retained_instance_directory'] == original.transport.instance_directory
    assert 'configuration_profile_id' not in launches[0]
    assert registry.acquire(**{**kwargs, 'session_scope_id': 'caller-two'}) == opened
    assert len(launches) == 1
    assert registry.native_session_observation(opened['connectionId'], 'native') is None
    registry.release(opened['connectionId'])
    reopened = registry.acquire(**kwargs)
    assert reopened['connectionId'] != opened['connectionId']
    assert reopened['historySessionId'] == opened['historySessionId']
    assert len(launches) == 2
    registry.release(reopened['connectionId'])
