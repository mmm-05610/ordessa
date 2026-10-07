"""Agent-owned configuration journal; Environment remains the effect writer.

Only fixture/new roots are opened by closeout. Existing native/legacy stores
keep their identity; this additive domain schema never rewrites their tables.
"""
import json
import sqlite3
from uuid import uuid4
from pathlib import Path
from threading import RLock

class ConfigRepository:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('CREATE TABLE IF NOT EXISTS agent_config(target TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.connection.execute('CREATE TABLE IF NOT EXISTS agent_draft_targets(location TEXT PRIMARY KEY, target TEXT UNIQUE NOT NULL, generation INTEGER NOT NULL)')
        self.connection.execute('CREATE TABLE IF NOT EXISTS agent_observed_records(target TEXT NOT NULL, kind TEXT NOT NULL, record_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(target,kind,record_id))')
        self.connection.commit()

    def read(self, target):
        with self.lock:
            row = self.connection.execute('SELECT payload FROM agent_config WHERE target=?', (target,)).fetchone()
            return None if row is None else json.loads(row[0])

    def write(self, target, payload):
        with self.lock, self.connection:
            self.connection.execute('INSERT INTO agent_config VALUES(?,?) ON CONFLICT(target) DO UPDATE SET payload=excluded.payload',
                                    (target, json.dumps(payload, sort_keys=True, allow_nan=False)))

    def close(self):
        self.connection.close()

    def read_records(self, target, kind):
        with self.lock:
            return {row[0]: json.loads(row[1]) for row in self.connection.execute(
                'SELECT record_id,payload FROM agent_observed_records WHERE target=? AND kind=?', (target,kind))}

    def write_record(self, target, kind, record_id, payload):
        with self.lock, self.connection:
            self.connection.execute('INSERT INTO agent_observed_records VALUES(?,?,?,?) ON CONFLICT(target,kind,record_id) DO UPDATE SET payload=excluded.payload',
                (target, kind, record_id, json.dumps(payload, sort_keys=True, allow_nan=False)))

    def resolve_draft(self, location):
        # UI draft references name intent buffers, never native sessions.
        key = json.dumps([location.get('connectionId'), location['draftId']], separators=(',', ':'))
        with self.lock, self.connection:
            row = self.connection.execute('SELECT target,generation FROM agent_draft_targets WHERE location=?', (key,)).fetchone()
            if row is None:
                row = ('agent-draft-' + uuid4().hex, 1)
                self.connection.execute('INSERT INTO agent_draft_targets VALUES(?,?,?)', (key, *row))
            return {'target':row[0], 'generation':row[1]}

    def knows_draft(self, target):
        with self.lock:
            return self.connection.execute('SELECT 1 FROM agent_draft_targets WHERE target=?', (target,)).fetchone() is not None
