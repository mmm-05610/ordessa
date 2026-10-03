"""026 T006-09: a native Server composed with the startup auto-Profile off.

``bootstrap_native_profile=False``: start creates, binds and asserts no
native Profile (the startup ``_assert_profile_executable`` leg never runs),
the discovery facet publishes no ``nativeExecution`` member (typed absence),
and native session creation is driven by an explicit selection (the REST
create that the bootstrap mode refuses with NATIVE_FIRST_SEND_REQUIRED) and
by the first send (``sessions.createAndSend`` over the normal acceptance
chain, exercised through the reviewed controlled fake ACP peer). The peer's
turn completion is environment-owned and already pinned (red here) by
``test_native_bootstrap_identity_hd002.py`` — this test pins the seam, not
that child outcome.
"""

from pathlib import Path
import json
import os
import shutil

from fastapi.testclient import TestClient

from ordessa_server_compat.composition import build_runtime_from_native_adapter
from ordessa_server.transport.http import create_app


PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "harness"
HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}


def test_native_first_send_and_explicit_selection_without_startup_profile(
        tmp_path, monkeypatch):
    node = shutil.which("node")
    fake = PLUGIN / "tests" / "harness_remote" / "fake_acp_peer.mjs"
    runtime = build_runtime_from_native_adapter(
        tmp_path / "data", plugin_root=PLUGIN, harness_id="pi",
        adapter_command=node, adapter_args=(str(fake),),
        bootstrap_native_profile=False,
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
        service = runtime.plugin_host.provided_port("product.service")
        # start created, bound and asserted nothing
        assert runtime.native_profile_id is None
        assert service.sessions.native_profile_identity is None
        assert service.sessions.native_profile_identities == {}
        with runtime.database.transaction() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM server_profiles").fetchone()[0] == 0
        assert "nativeExecution" not in runtime.wire.hello(HELLO)

        _status, workspace = service.workspaces.open_environment(
            environment={"kind": "local", "host": None, "user": None},
            path=str(project), expected_version=None,
        )
        _status, created = service.profiles.create("explicit-native-seat", {
            "name": "explicit pi seat", "harness_type": "pi",
            "configuration": {}, "credential_id": None,
        })
        profile_id = created["profile_id"]

        # explicit selection drives session creation again (the startup
        # bootstrap mode answers 409 NATIVE_FIRST_SEND_REQUIRED here)
        rest_created = client.post("/api/v1/sessions", headers={
            **headers, "Idempotency-Key": "explicit-seat",
        }, json={"workspace_id": workspace["id"], "profile_id": profile_id})
        assert rest_created.status_code == 201, rest_created.json()
        assert rest_created.json()["profile_id"] == profile_id

        # the first-send path works over the normal acceptance chain
        sent = client.post("/wire/v1/sessions.createAndSend", headers=headers, json={
            "jsonrpc": "2.0", "id": "native-first", "method": "sessions.createAndSend",
            "params": {"requestId": "bootstrap-off-first", "workspaceId": workspace["id"],
                       "profileId": profile_id,
                       "message": {"text": "hello fake peer", "attachments": []},
                       "overrides": []},
        })
        assert "result" in sent.json(), sent.json()
        result = sent.json()["result"]
        assert result["outcome"] == "accepted"
        assert result["executionId"]
        session_id = result["session"]["id"]
        assert result["session"]["profileId"] == profile_id
        session = service.sessions.records.get_session(session_id)
        assert session["workspace_id"] == workspace["id"]
        assert session["turns"], "the accepted intent queued one turn"
        # the fallback display fact, not a claimed summary: the message-derived
        # display name belongs to the bound-identity mode (core_wire.py), and
        # with no bound identity the projection answers the session id.
        assert result["session"]["displayName"] == session_id
