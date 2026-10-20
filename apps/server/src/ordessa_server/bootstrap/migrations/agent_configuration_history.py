"""Explicit read-only access to historical Agent configuration records.

Never a normal configuration authority: no schema creation, draft minting or writes.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

class AgentConfigurationHistoryError(RuntimeError):
    code = "AGENT_CONFIGURATION_HISTORY"

class AgentConfigurationHistoryReader:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        if not self._path.is_file():
            raise AgentConfigurationHistoryError("existing historical configuration file required")
        self._conn = sqlite3.connect(self._path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            tables = {row[0] for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"agent_config", "agent_draft_targets", "agent_observed_records"} <= tables:
                raise AgentConfigurationHistoryError("historical configuration schema unavailable")
        except BaseException:
            self._conn.close()
            raise

    def read(self, target):
        row = self._conn.execute('SELECT payload FROM agent_config WHERE target=?', (target,)).fetchone()
        return None if row is None else json.loads(row[0])

    def read_records(self, target, kind):
        return {row[0]: json.loads(row[1]) for row in self._conn.execute(
            'SELECT record_id,payload FROM agent_observed_records WHERE target=? AND kind=?', (target,kind))}

    def knows_draft(self, target):
        return self._conn.execute('SELECT 1 FROM agent_draft_targets WHERE target=?', (target,)).fetchone() is not None

    def close(self):
        self._conn.close()
