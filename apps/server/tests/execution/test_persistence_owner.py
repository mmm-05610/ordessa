"""Controlled owner boundaries, same-TX receipts and explicit history readers."""
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from ordessa_server.bootstrap.storage.product_database import Database
from ordessa_server.bootstrap.system_access.idempotent_records import IdempotentRecords
from ordessa_server.bootstrap.migrations.agent_configuration_history import (
    AgentConfigurationHistoryReader, AgentConfigurationHistoryError,
)
from ordessa_server.bootstrap.migrations.legacy_reader import LegacyCompatReader, LegacySchemaError
from ordessa_workspace.records import WorkspaceRecords


def test_owned_adapter_imports_do_not_open_database_or_create_directories(tmp_path):
    code = '''
import sqlite3
from pathlib import Path

def forbidden(*args, **kwargs):
    raise AssertionError("import caused database/directory IO")
sqlite3.connect = forbidden
Path.mkdir = forbidden
import pacthold.adapters.sqlite.environment.store
import pacthold.adapters.sqlite.environment.operation_records
import pacthold.adapters.sqlite.environment.relationships
import pacthold.adapters.security.fingerprint
import ordessa_server.bootstrap.storage.product_database
import ordessa_server.bootstrap.migrations.legacy_reader
import ordessa_server.bootstrap.migrations.agent_configuration_history
'''
    completed = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                               env=os.environ.copy(), capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert list(tmp_path.iterdir()) == []


def test_workspace_and_receipt_share_transaction_and_rollback_together(tmp_path):
    database = Database(tmp_path / "owned")
    database.initialize()
    class Spy(IdempotentRecords):
        fail = True
        checked_connection = None
        def check(self, conn, *args):
            self.checked_connection = conn
            return super().check(conn, *args)
        def insert(self, conn, *args):
            assert conn is self.checked_connection
            assert conn.execute("SELECT COUNT(*) FROM server_workspaces").fetchone()[0] == 1
            super().insert(conn, *args)
            assert conn.execute("SELECT COUNT(*) FROM server_idempotency").fetchone()[0] == 1
            if self.fail:
                raise RuntimeError("receipt failed after insert")
    idempotency = Spy(database)
    records = WorkspaceRecords(database, idempotency)
    kwargs = dict(key="same", request_digest="digest", distribution="controlled",
                  remote_user=None, remote_path="/controlled", connection_id="conn")
    with pytest.raises(RuntimeError, match="receipt failed"):
        records.create(**kwargs)
    with database.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM server_workspaces").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM server_idempotency").fetchone()[0] == 0
    idempotency.fail = False
    first = records.create(**kwargs)
    assert records.create(**kwargs) == first
    from server_plugin_api.internal_errors import ServerError
    with pytest.raises(ServerError) as conflict:
        records.create(**dict(kwargs, request_digest="different"))
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    with database.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM server_workspaces").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM server_idempotency").fetchone()[0] == 1


def test_configuration_history_missing_file_cannot_create_root(tmp_path):
    path = tmp_path / "absent" / "history.sqlite"
    with pytest.raises(AgentConfigurationHistoryError, match="existing historical"):
        AgentConfigurationHistoryReader(path)
    assert not path.exists()
    assert not path.parent.exists()


def test_configuration_history_reads_exact_old_values_without_writer(tmp_path):
    path = tmp_path / "history.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
CREATE TABLE agent_config(target TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE agent_draft_targets(location TEXT PRIMARY KEY,target TEXT UNIQUE,generation INTEGER);
CREATE TABLE agent_observed_records(target TEXT,kind TEXT,record_id TEXT,payload TEXT,PRIMARY KEY(target,kind,record_id));
INSERT INTO agent_config VALUES('target','{"model":"controlled"}');
INSERT INTO agent_draft_targets VALUES('[null,"draft"]','target',1);
INSERT INTO agent_observed_records VALUES('target','observation','record','{"value":1}');
""")
    before = hashlib.sha256(path.read_bytes()).digest()
    reader = AgentConfigurationHistoryReader(path)
    try:
        assert reader.read("target") == {"model": "controlled"}
        assert reader.read("missing") is None
        assert reader.read_records("target", "observation") == {"record": {"value": 1}}
        assert reader.knows_draft("target") is True
        assert reader.knows_draft("missing") is False
        assert not hasattr(reader, "write")
        assert not hasattr(reader, "write_record")
        assert not hasattr(reader, "resolve_draft")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader._conn.execute("DELETE FROM agent_config")
    finally:
        reader.close()
    assert hashlib.sha256(path.read_bytes()).digest() == before
    assert not Path(str(path) + "-wal").exists()
    assert not Path(str(path) + "-shm").exists()


def test_configuration_history_invalid_schema_is_not_initialized(tmp_path):
    path = tmp_path / "unrelated.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated(value TEXT)")
    before = path.read_bytes()
    with pytest.raises(AgentConfigurationHistoryError, match="schema unavailable"):
        AgentConfigurationHistoryReader(path)
    assert path.read_bytes() == before


def test_legacy_reader_future_version_refuses_without_writing(tmp_path):
    path = tmp_path / "future.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE agentbox_product_schema(singleton INTEGER,version INTEGER)")
        conn.execute("INSERT INTO agentbox_product_schema VALUES(1,22)")
    before = path.read_bytes()
    reader = LegacyCompatReader(path)
    try:
        with pytest.raises(LegacySchemaError, match="newer"):
            reader.neutral_counts()
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader._conn.execute("DELETE FROM agentbox_product_schema")
    finally:
        reader.close()
    assert path.read_bytes() == before
