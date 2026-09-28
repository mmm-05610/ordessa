"""T023 (SC-006): the WS leg of the controlled loopback, in-process client.

`wire/v1/event-stream` is driven with the fastapi TestClient websocket (the
in-process client that exists for it): a session is opened through the same
composed App, one event is persisted BEFORE publish through the owning port,
and the socket must deliver the frame from the snapshot cursor. The typed
pre-accept refusals (4401 unauthenticated, 4400 missing session) and the
ACP-channel leg's typed boundary (4400 UNKNOWN_CONNECTION without a real
harness channel) are pinned next to it — a real-harness/real-model end-to-end
channel is NOT claimed here and is listed as untested.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app
from ordessa_server_compat.execution import (
    CancelOutcome, HarnessDescriptor, HarnessRegistry,
)
from ordessa_server_product.composition import create_composition


class FakeConnector:
    """The controlled machine binding the workspace plugin composes against."""

    def distributions(self):
        return [{"name": "Ubuntu"}]

    def probe(self, distribution, user):
        return {"probe_id": f"probe-{distribution}", "distribution": distribution, "user": user}

    def browse(self, probe_id, path):
        return {"path": path, "directories": ["src"], "files": ["README.md"]}

    def open_workspace(self, probe_id, path):
        return {"connection_id": f"conn-{path}", "distribution": "Ubuntu",
                "user": "tester", "path": path}

    def read_workspace_file(self, *, distribution, user, connection_id,
                            workspace_path, relative_path):
        content = b"t023"
        return content, "sha256:" + hashlib.sha256(content).hexdigest()


class BlockingExecution:
    """Accept records, never spawns: the turn parks so events are the
    fixture's to write (the same controlled stand-in the wire gates use)."""

    def __init__(self):
        self.accepted = []
        self.gate = threading.Event()

    def accept(self, execution_id):
        self.accepted.append(execution_id)
        self.gate.wait(5)

    def cancel(self, execution_id):
        self.gate.set()
        return True

    def cancel_execution(self, execution_id):
        return (CancelOutcome.CONFIRMED_STOPPED if self.cancel(execution_id)
                else CancelOutcome.REFUSED_NO_ACTIVE_RUN)


def _harness_registry():
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "alpha", capability_claims={"stream": True},
        control_options={"model": ("alpha-default", "alpha-fast")},
        security_locked_controls=("sandbox",),
        configuration_validator=lambda v: None if isinstance(v, dict) else ValueError(),
    ))
    return registry


@pytest.fixture(scope="module")
def served():
    """One composed Server (product selection with the controlled stand-ins)."""
    scratch = Path(tempfile.mkdtemp(prefix="ordessa-t023-ws-"))
    runtime = build_runtime(
        scratch / "data",
        server_plugins=create_composition().compatibility_plugins(
            harnesses=_harness_registry(), connector=FakeConnector(),
            execution=BlockingExecution()),
    )
    try:
        runtime.start()
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        headers = {"Authorization": f"Bearer {runtime.token}"}
        counter = iter(range(1, 1000))

        def call(method, params):
            response = client.post(
                f"/wire/v1/{method}", headers=headers,
                json={"jsonrpc": "2.0", "id": f"t023-{next(counter)}",
                      "method": method, "params": params})
            body = response.json()
            assert "result" in body, (method, body)
            return body["result"]

        yield runtime, client, headers, call
    finally:
        runtime.stop()
        shutil.rmtree(scratch, ignore_errors=True)


@pytest.fixture(scope="module")
def live_session(served):
    """A real session with one turn accepted against the blocking execution."""
    _runtime, client, headers, call = served
    workspace = call("workspaces.open", {
        "requestId": "t023-ws-open",
        "environment": {"kind": "wsl", "host": "Ubuntu", "user": None},
        "path": "/home/tester/t023-live",
    })["workspace"]
    profile_response = client.post(
        "/api/v1/profiles", headers={**headers, "Idempotency-Key": "t023-profile"},
        json={"name": "t023-role", "harness_type": "alpha",
              "configuration": {"model": "alpha-default"}, "credential_id": None},
    )
    assert profile_response.status_code == 201, profile_response.json()
    accepted = call("sessions.createAndSend", {
        "requestId": "t023-live-one", "workspaceId": workspace["id"],
        "profileId": profile_response.json()["profile_id"],
        "message": {"text": "hello", "attachments": []}, "overrides": [],
    })
    return accepted


def test_event_stream_ws_delivers_a_persisted_frame_to_the_in_process_client(served, live_session):
    """The positive WS leg: connect with the snapshot resume cursor, persist
    one event through the owning port, and the socket answers with exactly
    that frame — dispatch over the real channel, typed end to end."""
    runtime, client, headers, call = served
    session_id = live_session["session"]["id"]
    snapshot = call("history.snapshot", {"sessionId": session_id})
    path = (f"/wire/v1/event-stream?sessionId={session_id}"
            f"&cursor={snapshot['resumeCursor']}")
    with client.websocket_connect(path, headers={**headers, "Host": "127.0.0.1"}) as socket:
        runtime.plugin_host.provided_port("product.repository").append_turn_event(
            live_session["executionId"], "message.delta",
            {"text": "persisted before publish"},
        )
        runtime.notifier.notify()
        frame = socket.receive_json()
    assert frame["sessionId"] == session_id, frame
    assert frame["event"]["kind"] == "message.delta", frame
    assert frame["event"]["text"] == "persisted before publish", frame
    assert frame["seq"] > snapshot["frames"][-1]["seq"], frame


def test_event_stream_ws_refuses_an_unauthenticated_socket_before_accept(served, live_session):
    """Typed refusal on the WS leg: wrong token closes 4401 UNAUTHENTICATED —
    the channel never opens for an unverified peer."""
    _runtime, client, _headers, _call = served
    path = f"/wire/v1/event-stream?sessionId={live_session['session']['id']}"
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(path, headers={
                "Host": "127.0.0.1", "Authorization": "Bearer t023-wrong-token"}):
            pass  # unreachable: the close lands before accept
    assert refused.value.code == 4401, refused.value
    assert refused.value.reason == "UNAUTHENTICATED", refused.value


def test_event_stream_ws_refuses_a_socket_without_a_session(served):
    """Typed refusal, second shape: an authenticated socket with no
    sessionId closes 4400 INVALID_REQUEST instead of hanging a stream."""
    _runtime, client, headers, _call = served
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(
                "/wire/v1/event-stream", headers={**headers, "Host": "127.0.0.1"}):
            pass
    assert refused.value.code == 4400, refused.value
    assert refused.value.reason == "INVALID_REQUEST", refused.value


def test_acp_channel_ws_stops_at_the_typed_boundary_without_a_real_channel(served):
    """The second WS route (ACP channel relay) needs a live harness-owned
    connection id; without one the composed transport answers the typed
    close 4400 UNKNOWN_CONNECTION. That is the boundary this loopback stops
    at — a real end-to-end ACP channel is registered as untested below."""
    _runtime, client, headers, _call = served
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(
                "/wire/v1/acp-channel/t023-no-such-connection",
                headers={**headers, "Host": "127.0.0.1"}):
            pass
    assert refused.value.code == 4400, refused.value
    assert refused.value.reason == "UNKNOWN_CONNECTION", refused.value
