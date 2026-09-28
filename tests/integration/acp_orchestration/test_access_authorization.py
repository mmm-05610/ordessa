"""Requirement 2: unauthorised connections are refused, and a refusal never
reaches the launch boundary.

Pins the real auth surface: bearer-token wire/1, the loopback Host/Origin
policy, REST session reads, and the WS event channel's pre-accept close codes.
The positive control keeps the negatives honest: the same stack must accept an
authorised send and show peer evidence.
"""
import re
import time

import pytest

from tests.integration.acp_orchestration.conftest import HELLO, session_new_events


def ws_close_code(server, url, headers):
    client = server.client
    try:
        with client.websocket_connect(url, headers=headers):
            return "ACCEPTED"
    except Exception as exc:  # noqa: BLE001 - the close code is the fact under test
        code = getattr(exc, "code", None)
        if isinstance(code, int):
            return code
        match = re.search(r"[Cc]losed with (?:code )?(\d{3,4})", str(exc))
        if match:
            return int(match.group(1))
        raise


def test_wire_requires_the_exact_bearer_token(server):
    for label, token in (("wrong", "nope"), ("", None)):
        headers = {} if token is None else {"authorization": f"Bearer {token}"}
        response = server.client.post(
            "/wire/v1/server.hello",
            json={"jsonrpc": "2.0", "id": "x", "method": "server.hello", "params": HELLO},
            headers=headers)
        assert response.status_code == 401, (label, response.status_code, response.text)
        body = response.json() if response.content else {}
        assert "AUTHENTICATION_REQUIRED" in str(body), (label, body)
    # Positive control over the very same route.
    assert "result" in server.wire("server.hello", HELLO)


def test_rest_and_wire_share_the_policy(server):
    response = server.client.get("/api/v1/sessions/does-not-exist",
                                 headers={"authorization": "Bearer wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_non_loopback_origin_is_rejected_before_authentication(server):
    response = server.client.post(
        "/wire/v1/server.hello",
        json={"jsonrpc": "2.0", "id": "x", "method": "server.hello", "params": HELLO},
        headers={"authorization": "Bearer " + server.token,
                 "origin": "http://evil.example"})
    assert response.status_code == 403, response.text
    assert "LOOPBACK_POLICY_REJECTED" in response.text


def test_event_stream_ws_close_codes(server, tmp_path):
    profile_id = server.native_profile_id()
    project = tmp_path / "ws-project"
    project.mkdir()
    workspace_id = server.open_workspace(project)
    session_id = server.create_and_send(workspace_id, profile_id, "ws-control")["session"]["id"]
    server.settled(session_id, 1)
    # TestClient defaults websocket URLs to host `testserver`, which the
    # loopback policy rejects; pin the loopback authority in the URL itself.
    base = f"ws://127.0.0.1/wire/v1/event-stream?sessionId={session_id}"
    good = {"authorization": "Bearer " + server.token}
    assert ws_close_code(server, base, {"origin": "http://evil.example", **good}) == 4403
    assert ws_close_code(server, base, {"authorization": "Bearer wrong"}) == 4401
    assert ws_close_code(server, "ws://127.0.0.1/wire/v1/event-stream", good) == 4400
    assert ws_close_code(server, base, {}) == 4401
    # Positive control: an authorised handshake receives the persisted frames.
    with server.client.websocket_connect(base, headers=good) as socket:
        kinds = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(kinds) < 2:
            frame = socket.receive_json()
            kind = (frame.get("event") or {}).get("kind")
            if kind:
                kinds.append(kind)
        assert kinds, "authorised event stream delivered nothing"


def test_unauthorised_send_launches_nothing(server, tmp_path):
    project = tmp_path / "quiet"
    project.mkdir()
    workspace_id = server.open_workspace(project)
    real_profile = server.native_profile_id()
    answer = server.wire("sessions.createAndSend", {
        "requestId": "hd003-bad-profile", "workspaceId": workspace_id,
        "profileId": "profile-does-not-exist",
        "message": {"text": "must-not-launch", "attachments": []},
        "overrides": [],
    })
    assert "error" in answer, answer
    assert session_new_events(server.log_base) == []
    # Positive control on the same workspace: the stack is alive.
    sent = server.create_and_send(workspace_id, real_profile, "live-control")
    assert server.settled(sent["session"]["id"], 1)["turns"][-1]["state"] == "completed"
    assert len(session_new_events(server.log_base)) == 1
