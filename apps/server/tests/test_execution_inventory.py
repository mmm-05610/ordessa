"""Order 64: the running-execution inventory - ledger-sourced, null-honest.

Counterexamples: nothing running (empty list, not an error), a finished turn
disappears, an unreported pid stays null with its reason, the row count is
bounded, and no host path appears anywhere.
"""
from __future__ import annotations

import pytest

from ordessa_server_compat.execution.inventory import (
    MAX_EXECUTIONS,
    InventoryError,
    list_executions,
)
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.profiles import ProfileRecords
from ordessa_server_compat.sessions import SessionRecords
from ordessa_workspace import WorkspaceRecords
from pacthold.storage import Database


def _pieces(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    sessions = SessionRecords(database, idempotency)
    return database, idempotency, profiles, workspaces, sessions


def _active_turn(database, profiles, workspaces, sessions, *, name="role"):
    profile = profiles.create(
        key=f"p-{name}", request_digest=name, name=name, harness_type="codex",
        config_digest="sha256:" + "0" * 64, credential_id=None)[1]
    workspace = workspaces.create(
        key=f"w-{name}", request_digest=name, distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace/secret-path", connection_id=f"connection-{name}")[1]
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_sessions(id,workspace_id,profile_id,status,version,"
            "created_at,updated_at) VALUES (?,?,?,'active',1,'t','t')",
            (f"session_{name}", workspace["workspace_id"], profile["profile_id"]),
        )
        conn.execute(
            "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
            "native_generation,state,capture_state,cleanup_state,input_object_digest,"
            "created_at,updated_at) VALUES (?,?,?,1,0,'accepted','pending','pending','x','t','t')",
            (f"turn_{name}", f"session_{name}", profile["profile_id"]),
        )
    return f"turn_{name}", workspace


def test_nothing_running_is_an_empty_list_and_finished_rows_disappear(tmp_path):
    database, _idem, profiles, workspaces, sessions = _pieces(tmp_path)
    assert list_executions(database) == []

    turn_id, _workspace = _active_turn(database, profiles, workspaces, sessions)
    rows = list_executions(database)
    assert [row["turnId"] for row in rows] == [turn_id]
    assert rows[0]["state"] == "queued"
    assert rows[0]["placement"] == "wsl"

    with database.transaction() as conn:
        conn.execute("UPDATE server_turns SET state='completed' WHERE id=?", (turn_id,))
    assert list_executions(database) == [], "a finished turn leaves the inventory"


def test_an_unreported_pid_is_null_with_its_reason(tmp_path):
    database, _idem, profiles, workspaces, sessions = _pieces(tmp_path)
    turn_id, _workspace = _active_turn(database, profiles, workspaces, sessions)

    # No execution port at all: both pids null, each with a reason.
    rows = list_executions(database)
    assert rows[0]["pid"] is None and rows[0]["pidReason"] == "PID_NOT_REPORTED"
    assert rows[0]["adapterPid"] is None

    class _Port:
        def pid_for(self, turn: str) -> int | None:
            return 4242 if turn == turn_id else None

    rows = list_executions(database, execution_port=_Port())
    assert rows[0]["pid"] == 4242 and rows[0]["pidReason"] is None

    class _Silent:
        def pid_for(self, turn: str) -> int | None:
            return None

    rows = list_executions(database, execution_port=_Silent())
    assert rows[0]["pid"] is None and rows[0]["pidReason"] == "PID_NOT_REPORTED"


def test_the_rows_carry_no_host_paths_and_the_count_is_bounded(tmp_path):
    database, _idem, profiles, workspaces, sessions = _pieces(tmp_path)
    _active_turn(database, profiles, workspaces, sessions)

    rows = list_executions(database)
    import json

    serialized = json.dumps(rows)
    assert "/workspace/secret-path" not in serialized
    assert rows[0]["workspace"] in {"workspace", rows[0]["workspaceId"]}

    with pytest.raises(InventoryError) as bound:
        list_executions(database, limit=0)
    assert bound.value.code == "INVENTORY_LIMIT_INVALID"

    # Over the bound: the list refuses rather than returning a partial view.
    for index in range(2):
        _active_turn(database, profiles, workspaces, sessions, name=f"extra{index}")
    with pytest.raises(InventoryError) as exceeded:
        list_executions(database, limit=1)
    assert exceeded.value.code == "INVENTORY_LIMIT_EXCEEDED"
    assert MAX_EXECUTIONS == 200


def test_the_wire_face_returns_the_inventory_or_an_empty_list(tmp_path):
    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    runtime = build_runtime(tmp_path / "server")
    runtime.start()
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token
        result = client.post("/wire/v1/executions.list", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "i", "method": "executions.list",
            "params": {"requestId": "inventory-1"},
        }).json()["result"]["executions"]
        assert result == []

        refused = client.post("/wire/v1/executions.list", headers={
            "Authorization": f"Bearer {token}"}, json={
            "jsonrpc": "2.0", "id": "i2", "method": "executions.list",
            "params": {"requestId": "inventory-2", "limit": 0},
        }).json()
        assert refused["error"]["code"] == "INVALID_REQUEST"
