"""Native Server identity and CLI validation without launching an Agent."""

from pathlib import Path
import json
import os
import time
import shutil

import pytest
from fastapi.testclient import TestClient

from ordessa_server.bootstrap import build_runtime
from ordessa_server_compat.composition import build_runtime_from_native_adapter
from ordessa_server.wire.errors import WireError
from ordessa_server.transport.http import create_app
from ordessa_server_compat.execution.sidecar import NativeProcessLauncher


HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}
PLUGIN = Path(__file__).resolve().parents[3] / "plugins"  / "harness"


def _native(root: Path):
    return build_runtime_from_native_adapter(
        root, plugin_root=PLUGIN, harness_id="pi",
        adapter_command=shutil.which("node"), adapter_args=("/not-launched.mjs",),
    )


def test_native_hello_stable_profile_and_isolated_hello_unchanged(tmp_path):
    root = tmp_path / "native"
    first = _native(root)
    try:
        first.start()
        identity = first.wire.hello(HELLO)["nativeExecution"]
        assert identity == {
            "mode": "native", "harness": "pi", "profileId": first.native_profile_id,
        }
        assert first.service.readiness()["capabilities"]["harnesses"]["pi"]["available"] is True
        assert first.service.profiles.records.get(identity["profileId"])["harness_type"] == "pi"
    finally:
        first.stop()
    second = _native(root)
    try:
        second.start()
        assert second.wire.hello(HELLO)["nativeExecution"] == identity
    finally:
        second.stop()

    isolated = build_runtime(tmp_path / "isolated")
    try:
        isolated.start()
        assert "nativeExecution" not in isolated.wire.hello(HELLO)
    finally:
        isolated.stop()


def test_native_profile_archive_refuses_restart_and_hello(tmp_path):
    root = tmp_path / "native"
    first = _native(root)
    try:
        first.start()
        profile_id = first.native_profile_id
        with first.database.transaction() as conn:
            conn.execute("UPDATE server_profiles SET archived_at='2026-01-01' WHERE id=?", (profile_id,))
        with pytest.raises(WireError, match="native execution identity is unavailable"):
            first.wire.hello(HELLO)
    finally:
        first.stop()
    second = _native(root)
    try:
        with pytest.raises(RuntimeError, match="NATIVE_PROFILE_CONFLICT"):
            second.start()
    finally:
        second.stop()


def test_native_profile_configuration_change_refuses_hello_and_first_send(tmp_path):
    runtime = _native(tmp_path / "data")
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {runtime.token}"}
        opened = runtime.service.workspaces.open_environment(
            environment={
                "kind": "local", "host": None, "user": None,
            }, path=str(project), expected_version=None,
        )
        workspace_id = opened[1]["id"]
        changed = runtime.objects.publish(json.dumps({
            "schema_version": 1, "harness_type": "pi", "configuration": {"unmanaged": True},
        }).encode())
        with runtime.database.transaction() as conn:
            conn.execute("UPDATE server_profiles SET config_object_digest=? WHERE id=?",
                         (changed.digest, runtime.native_profile_id))
        hello = client.post("/wire/v1/server.hello", headers=headers, json={
            "jsonrpc": "2.0", "id": "hello", "method": "server.hello", "params": HELLO,
        })
        assert "error" in hello.json()
        refused = client.post("/wire/v1/sessions.createAndSend", headers=headers, json={
            "jsonrpc": "2.0", "id": "send", "method": "sessions.createAndSend",
            "params": {"requestId": "mutated-profile", "workspaceId": workspace_id,
                       "profileId": runtime.native_profile_id,
                       "message": {"text": "hello", "attachments": []}, "overrides": []},
        })
        assert refused.json()["error"]["details"]["internalCode"] == "NATIVE_PROFILE_CONFLICT"
        assert runtime.execution._active == {}


def test_native_profile_harness_mismatch_refuses_restart(tmp_path):
    root = tmp_path / "data"
    first = _native(root)
    try:
        first.start()
        with first.database.transaction() as conn:
            conn.execute("UPDATE server_profiles SET harness_type='codex' WHERE id=?",
                         (first.native_profile_id,))
        with pytest.raises(WireError, match="native execution identity is unavailable"):
            first.wire.hello(HELLO)
    finally:
        first.stop()
    second = _native(root)
    try:
        with pytest.raises(RuntimeError, match="NATIVE_PROFILE_CONFLICT"):
            second.start()
    finally:
        second.stop()


def test_native_mode_refuses_invalid_artifact_before_data_root(tmp_path):
    root = tmp_path / "native"
    with pytest.raises(RuntimeError, match="NATIVE_ADAPTER_INVALID"):
        build_runtime_from_native_adapter(
            root, plugin_root=PLUGIN, harness_id="pi",
            adapter_command="relative-adapter",
        )
    assert not root.exists()


def test_wire_and_rest_refuse_other_profile_before_execution(tmp_path, monkeypatch):
    runtime = _native(tmp_path / "data")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(NativeProcessLauncher, "launch", lambda *_args: pytest.fail("native child started"))
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {runtime.token}"}
        _status, rogue = runtime.service.profiles.create(
            "rogue-native-test", {
                "name": "other pi seat", "harness_type": "pi",
                "configuration": {}, "credential_id": None,
            },
        )
        wrong_id = rogue["profile_id"]
        opened = client.post("/wire/v1/workspaces.open", headers=headers, json={
            "jsonrpc": "2.0", "id": "open", "method": "workspaces.open",
            "params": {"requestId": "open-native", "environment": {
                "kind": "local", "host": None, "user": None,
            }, "path": str(project)},
        })
        workspace_id = opened.json()["result"]["workspace"]["id"]
        refused = client.post("/wire/v1/sessions.createAndSend", headers=headers, json={
            "jsonrpc": "2.0", "id": "send", "method": "sessions.createAndSend",
            "params": {"requestId": "send-wrong", "workspaceId": workspace_id,
                       "profileId": wrong_id, "message": {"text": "hello", "attachments": []},
                       "overrides": []},
        })
        assert refused.json()["error"]["details"]["internalCode"] == "NATIVE_PROFILE_CONFLICT"
        pure_create = client.post("/api/v1/sessions", headers={
            **headers, "Idempotency-Key": "rest-wrong",
        }, json={"workspace_id": workspace_id, "profile_id": wrong_id})
        assert pure_create.status_code == 409
        assert pure_create.json()["error"]["code"] == "NATIVE_FIRST_SEND_REQUIRED"
        _status, legacy = runtime.service.sessions.records.create_session(
            key="legacy-wrong", request_digest="legacy-wrong",
            workspace_id=workspace_id, profile_id=wrong_id,
        )
        rest = client.post(f"/api/v1/sessions/{legacy['session_id']}/turns", headers={
            **headers, "Idempotency-Key": "rest-wrong-turn",
        }, json={"text": "hello", "expected_profile_revision": 1})
        assert rest.status_code == 409
        assert rest.json()["error"]["code"] == "NATIVE_PROFILE_CONFLICT"
        continued = client.post("/wire/v1/sessions.send", headers=headers, json={
            "jsonrpc": "2.0", "id": "continued", "method": "sessions.send",
            "params": {"requestId": "send-legacy", "sessionId": legacy["session_id"],
                       "message": {"text": "hello", "attachments": []}, "overrides": []},
        })
        assert continued.json()["error"]["details"]["internalCode"] == "NATIVE_PROFILE_CONFLICT"
        _status, native_session = runtime.service.sessions.records.create_session(
            key="legacy-native", request_digest="legacy-native",
            workspace_id=workspace_id, profile_id=runtime.native_profile_id,
        )
        project.rmdir()
        vanished = client.post("/wire/v1/sessions.createAndSend", headers=headers, json={
            "jsonrpc": "2.0", "id": "vanished", "method": "sessions.createAndSend",
            "params": {"requestId": "send-vanished", "workspaceId": workspace_id,
                       "profileId": runtime.native_profile_id,
                       "message": {"text": "hello", "attachments": []}, "overrides": []},
        })
        assert vanished.json()["error"]["details"]["internalCode"] == "LOCAL_PATH_MISSING"
        rest_vanished = client.post(f"/api/v1/sessions/{native_session['session_id']}/turns", headers={
            **headers, "Idempotency-Key": "rest-vanished",
        }, json={"text": "hello", "expected_profile_revision": 1})
        assert rest_vanished.status_code == 404
        assert rest_vanished.json()["error"]["code"] == "LOCAL_PATH_MISSING"
        assert runtime.execution._active == {}


def test_native_first_send_completes_with_reviewed_fake_acp_peer(tmp_path, monkeypatch):
    node = shutil.which("node")
    fake = PLUGIN / "tests" / "harness_remote" / "fake_acp_peer.mjs"
    runtime = build_runtime_from_native_adapter(
        tmp_path / "data", plugin_root=PLUGIN, harness_id="pi",
        adapter_command=node, adapter_args=(str(fake),),
    )
    project = tmp_path / "project"
    project.mkdir()
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    monkeypatch.setattr(os, "environ", {
        "PATH": os.environ.get("PATH", ""), "HOME": str(empty_home),
        "TMPDIR": str(tmp_path),
    })
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        headers = {"Authorization": f"Bearer {runtime.token}"}
        _created, workspace = runtime.service.workspaces.open_environment(
            environment={"kind": "local", "host": None, "user": None},
            path=str(project), expected_version=None,
        )
        sent = client.post("/wire/v1/sessions.createAndSend", headers=headers, json={
            "jsonrpc": "2.0", "id": "native-first", "method": "sessions.createAndSend",
            "params": {"requestId": "native-fake-first", "workspaceId": workspace["id"],
                       "profileId": runtime.native_profile_id,
                       "message": {"text": "hello fake peer", "attachments": []},
                       "overrides": []},
        })
        assert "result" in sent.json(), sent.json()
        session_id = sent.json()["result"]["session"]["id"]
        assert sent.json()["result"]["outcome"] == "accepted"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            session = runtime.service.sessions.records.get_session(session_id)
            if session["status"] == "ready" and not runtime.execution._active:
                break
            time.sleep(0.05)
        else:
            pytest.fail("fake native turn did not settle")
        assert session["turns"][-1]["state"] == "completed", session["turns"][-1]
        assert session["checkpoint"]["native_id"].startswith("fake-native-")
