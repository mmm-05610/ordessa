"""Migration uses exact, unique identity evidence, never project/time guesses."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('legacy_import',
    Path(__file__).parents[1] / 'tools/import-legacy-pi-history.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def legacy(tmp_path):
    tmp_path.chmod(0o700)
    for relative in ('state', 'plugins', 'plugins/profile', 'harness-instances',
                     'harness-instances/pi-one', 'harness-instances/pi-one/sessions',
                     'harness-instances/pi-one/sessions/project'):
        (tmp_path / relative).mkdir(mode=0o700)
    with sqlite3.connect(tmp_path / 'state/agentbox.sqlite') as c:
        c.executescript('CREATE TABLE server_idempotency(key TEXT,response_json TEXT,scope TEXT);'
            'CREATE TABLE server_sessions(id TEXT,workspace_id TEXT,profile_id TEXT,archived_at TEXT);'
            'CREATE TABLE server_turns(id TEXT,session_id TEXT);'
            'CREATE TABLE server_profiles(id TEXT,harness_type TEXT);'
            'CREATE TABLE server_workspaces(id TEXT,normalized_path TEXT,archived_at TEXT);'
            "INSERT INTO server_sessions VALUES('ledger','project','profile',NULL);"
            "INSERT INTO server_profiles VALUES('profile','pi');"
            "INSERT INTO server_turns VALUES('execution','ledger');"
            "INSERT INTO server_workspaces VALUES('project','/project',NULL);")
        c.execute('INSERT INTO server_idempotency VALUES(?,?,?)',
                  ('channel', json.dumps({'session_id': 'ledger'}), 'POST:/sessions'))
    with sqlite3.connect(tmp_path / 'plugins/profile/profile-store.sqlite') as c:
        c.executescript('CREATE TABLE profile_sessions(session_uid TEXT,native_session_key TEXT,harness_id TEXT);'
                       "INSERT INTO profile_sessions VALUES('uid','native','pi');")
    with sqlite3.connect(tmp_path / 'plugins/profile/native-configuration.sqlite') as c:
        c.executescript('CREATE TABLE operations(channel_id TEXT,session_id TEXT);'
                       "INSERT INTO operations VALUES('channel','uid');")
    path = tmp_path / 'harness-instances/pi-one/sessions/project/native.jsonl'
    # Tests create fixture files only, never production state.
    path.write_text('\n'.join(json.dumps(entry) for entry in [
        {'type': 'session', 'id': 'native', 'cwd': '/project'},
        {'type': 'message', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': 'hello'}]}},
        {'type': 'message', 'message': {'role': 'assistant', 'content': 'answer'}},
    ]))
    return tmp_path, path


def test_exact_unique_native_and_ledger_association(legacy):
    root, path = legacy
    candidates, linked = module.inventory(root)
    assert linked == 1 and len(candidates) == 1
    row, native, instance, title = candidates[0]
    assert (row['id'], row['execution_id'], native, instance, title) == (
        'ledger', 'execution', 'native', path.parents[2], 'hello')


def test_duplicate_native_files_are_not_guessed(legacy):
    root, path = legacy
    (path.parent / 'duplicate.jsonl').write_bytes(path.read_bytes())
    assert module.inventory(root) == ([], 1)


def test_wrong_project_or_missing_native_file_is_not_imported(legacy):
    root, path = legacy
    path.write_text(path.read_text().replace('/project', '/other'))
    assert module.inventory(root) == ([], 1)
    path.unlink()
    assert module.inventory(root) == ([], 1)


def test_symlink_native_file_is_not_imported(legacy):
    root, path = legacy
    real = path.parent / 'native.txt'
    path.rename(real)
    path.symlink_to(real)
    assert module.inventory(root) == ([], 1)
