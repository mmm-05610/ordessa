"""One-shot, offline import of provably associated pre-v1 Pi conversations.

The legacy Profile databases are read-only migration evidence, not a runtime
dependency. No native process, credential read, configuration write or inference.
Default is a dry run. Run --apply only with the Desktop/Server stopped.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from ordessa_harness.server_acp.history import NativeSessionHistory
from ordessa_harness.server_acp.instance_directory import _private
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.bootstrap.runtime import DataRootOwner
from ordessa_server_compat.sessions import SessionRecords
from pacthold_runtime_compat.storage import Database


def readonly(path):
    if path.resolve() != path or path.is_symlink() or path.stat().st_uid != os.getuid():
        raise ValueError('Migration evidence must be owned and symlink-free')
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def inventory(root):
    _private(root)
    instances = root / 'harness-instances'
    _private(instances)
    with readonly(root / 'plugins/profile/profile-store.sqlite') as profile:
        native = {r['session_uid']: r['native_session_key'] for r in profile.execute(
            "SELECT session_uid,native_session_key FROM profile_sessions WHERE harness_id='pi'")}
    with readonly(root / 'state/agentbox.sqlite') as ledger:
        connections = {r['key']: json.loads(r['response_json'])['session_id'] for r in ledger.execute(
            "SELECT key,response_json FROM server_idempotency WHERE scope='POST:/sessions'")}
        sessions = {r['id']: dict(r) for r in ledger.execute(
            'SELECT s.id,s.workspace_id,w.normalized_path,t.id AS execution_id,p.harness_type '
            'FROM server_sessions s JOIN server_workspaces w ON w.id=s.workspace_id '
            'JOIN server_turns t ON t.session_id=s.id JOIN server_profiles p ON p.id=s.profile_id '
            'WHERE s.archived_at IS NULL AND w.archived_at IS NULL')}
    links = {}
    with readonly(root / 'plugins/profile/native-configuration.sqlite') as journal:
        for row in journal.execute('SELECT channel_id,session_id FROM operations'):
            native_id, session_id = native.get(row['session_id']), connections.get(row['channel_id'])
            if native_id and session_id:
                links.setdefault(native_id, set()).add(session_id)
    files = {}
    for instance in instances.iterdir():
        _private(instance)
        session_root = instance / 'sessions'
        if not session_root.is_dir() or session_root.resolve() != session_root:
            continue
        for path in session_root.rglob('*.jsonl'):
            if path.resolve() != path or path.stat().st_uid != os.getuid() or path.stat().st_size > 16 * 1024 * 1024:
                continue
            with path.open() as source:
                try:
                    header = json.loads(source.readline(65537))
                except ValueError:
                    continue
                if not isinstance(header, dict) or header.get('type') != 'session':
                    continue
                title, assistant_seen = None, False
                for index, line in enumerate(source):
                    if index >= 30000 or len(line) > 262144:
                        break
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        break
                    message = entry.get('message', {}) if isinstance(entry, dict) else {}
                    if not isinstance(message, dict):
                        continue
                    if message.get('role') == 'assistant':
                        assistant_seen = True
                    if title is None and message.get('role') == 'user':
                        content = message.get('content')
                        if isinstance(content, str):
                            title = content[:160]
                        elif isinstance(content, list):
                            title = next((b['text'][:160] for b in content if isinstance(b, dict)
                                          and b.get('type') == 'text' and isinstance(b.get('text'), str)), None)
                files.setdefault(header.get('id'), []).append((header, instance, title, assistant_seen))
    candidates = []
    for native_id, possible in links.items():
        matches = files.get(native_id, [])
        if len(possible) != 1 or len(matches) != 1:
            continue
        session_id = next(iter(possible))
        row = sessions.get(session_id)
        header, instance, title, assistant_seen = matches[0]
        if (not row or row['harness_type'] != 'pi' or header.get('cwd') != row['normalized_path']
                or not title or not assistant_seen):
            continue
        candidates.append((row, native_id, instance, title))
    return candidates, len(links)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('data_root', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    candidates, linked = inventory(args.data_root)
    report = {'linkedConversations': linked, 'verifiedCandidates': len(candidates),
              'unmatchedOrUnproven': linked - len(candidates), 'mode': 'dry-run'}
    if args.apply:
        # Server remains the only live writer: an import must not race it.
        lock = args.data_root / 'instance.lock'
        if lock.exists():
            raise ValueError('Close Desktop/Server before applying the import')
        backups = args.data_root / 'backups'
        backups.mkdir(mode=0o700, exist_ok=True)
        _private(backups)
        backup = backups / ('native-history-pre-v1-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.sqlite')
        owner = DataRootOwner(args.data_root)
        owner.acquire()
        try:
            # Repeat validation after taking the authoritative Server write lock.
            candidates, linked = inventory(args.data_root)
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            with readonly(args.data_root / 'state/agentbox.sqlite') as source, sqlite3.connect(backup) as target:
                source.backup(target)
            database = Database(args.data_root)
            history = NativeSessionHistory(SessionRecords(database, IdempotentRecords(database)))
            for row, native_id, instance, title in candidates:
                history.remember(SimpleNamespace(session_id=row['id'], history_id=row['id'],
                    execution_id=row['execution_id'], harness_id='pi', workspace_id=row['workspace_id'],
                    transport=SimpleNamespace(instance_directory=str(instance))), native_id, title)
        finally:
            owner.release()
        report.update(mode='applied', imported=len(candidates), backup=backup.name)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
