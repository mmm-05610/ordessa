"""Controlled Server ACP fence: no native process or real model."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ordessa_server.acp_admission import (
    AcpAdmissionGate, AcpAdmissionPortAdapter, AcpAdmissionRefused,
    BoundAdmission, _digest, prompt_input,
)
from server_plugin_api import (
    ACP_ADMISSION_PORT, AcpAttachmentReference, AcpChannelBinding,
    AcpPermissionDecision, AcpSubmissionRequest,
)
from ordessa_server.transport.http import create_app
from ordessa_server.bootstrap import build_runtime
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


CONNECTION = SimpleNamespace(connection_id="connection-1")
SUBMISSION = {
    "submissionId": "submission-1", "nativeSessionId": "session-1",
    "text": "hello", "attachments": [{"name": "brief", "uri": "file:///brief", "sha256": "a" * 64}],
    "configurationDigest": "b" * 64,
}


def prompt(submission=SUBMISSION, *, request_id=7):
    session_id, blocks = prompt_input(submission)
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": "session/prompt",
                       "params": {"sessionId": session_id, "prompt": blocks}})


class Authority:
    def __init__(self):
        self.submission_calls = 0
        self.permission_calls = 0

    def authorize_submission(self, connection, submission):
        self.submission_calls += 1
        session_id, blocks = prompt_input(submission)
        return BoundAdmission("alice", connection.connection_id, session_id, 7,
            submission["submissionId"], _digest({"sessionId": session_id, "prompt": blocks}),
            submission["configurationDigest"], 200)

    def authorize_permission(self, connection, request, decision):
        self.permission_calls += 1
        return decision["runId"] == "run-1"


def test_raw_prompt_refused_without_injected_authority():
    gate = AcpAdmissionGate(clock=lambda: 100)
    with pytest.raises(AcpAdmissionRefused, match="lacks matching"):
        gate.admit_client_frame(CONNECTION, prompt())
    with pytest.raises(AcpAdmissionRefused, match="authority is absent"):
        gate.authorize_submission(CONNECTION, SUBMISSION)


def test_same_target_digest_one_use_and_unknown_after_effect():
    authority = Authority()
    gate = AcpAdmissionGate(authority, clock=lambda: 100)
    assert gate.authorize_submission(CONNECTION, SUBMISSION) == {
        "kind": "accepted", "submissionId": "submission-1"}
    assert authority.submission_calls == 1
    with pytest.raises(AcpAdmissionRefused, match="lacks matching"):
        gate.admit_client_frame(CONNECTION, prompt({**SUBMISSION, "text": "changed"}))
    gate.admit_client_frame(CONNECTION, prompt())
    with pytest.raises(AcpAdmissionRefused, match="already used"):
        gate.admit_client_frame(CONNECTION, prompt())
    assert gate.authorize_submission(CONNECTION, SUBMISSION)["kind"] == "unknown"
    assert authority.submission_calls == 1
    with pytest.raises(AcpAdmissionRefused) as changed:
        gate.authorize_submission(CONNECTION, {**SUBMISSION, "text": "changed"})
    assert changed.value.code == "TARGET_CONFLICT"
    with pytest.raises(AcpAdmissionRefused) as busy:
        gate.authorize_submission(CONNECTION, {**SUBMISSION, "submissionId": "other"})
    assert busy.value.code == "BUSY"
    with pytest.raises(AcpAdmissionRefused, match="lacks matching"):
        gate.admit_client_frame(SimpleNamespace(connection_id="other-channel"), prompt())


def test_permission_answer_needs_observed_request_and_one_use_authorization():
    authority = Authority()
    gate = AcpAdmissionGate(authority, clock=lambda: 100)
    response = json.dumps({"jsonrpc": "2.0", "id": 19,
                           "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}}})
    with pytest.raises(AcpAdmissionRefused, match="no observed request"):
        gate.admit_client_frame(CONNECTION, response)
    gate.observe_agent_frame(CONNECTION.connection_id, json.dumps({"jsonrpc": "2.0", "id": 19,
        "method": "session/request_permission", "params": {"sessionId": "session-1",
            "options": [{"optionId": "allow-once"}]}}))
    with pytest.raises(AcpAdmissionRefused, match="lacks matching"):
        gate.admit_client_frame(CONNECTION, response)
    assert gate.authorize_permission(CONNECTION, {"interactionId": "client-interaction-1",
        "nativeSessionId": "session-1", "runId": "run-1", "optionId": "allow-once"}) == {
            "kind": "accepted", "submissionId": "client-interaction-1"}
    assert authority.permission_calls == 1
    gate.admit_client_frame(CONNECTION, response)
    with pytest.raises(AcpAdmissionRefused, match="already consumed"):
        gate.admit_client_frame(CONNECTION, response)


class FakeChannel:
    connection_id = "connection-1"

    def __init__(self, inbound=None):
        self.sent = []
        self.transport = SimpleNamespace(send_line=self.sent.append)
        self.inbound = inbound

    def attach(self, loop, sink):
        if self.inbound is not None:
            sink(self.inbound)

    def detach(self, loop, sink):
        pass


def test_websocket_raw_prompt_and_permission_answer_cannot_bypass_absent_authority(tmp_path, monkeypatch):
    inbound = json.dumps({"jsonrpc": "2.0", "id": 19, "method": "session/request_permission",
        "params": {"sessionId": "session-1", "options": [{"optionId": "allow-once"}]}})
    for frame, incoming in ((prompt(), None),
                            (json.dumps({"jsonrpc": "2.0", "id": 19,
                                "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}}}), inbound)):
        channel = FakeChannel(incoming)
        runtime = build_runtime(tmp_path / f"data-{len(frame)}-{bool(incoming)}")
        runtime.wire.acp_admission_gate = AcpAdmissionGate(clock=lambda: 100)
        monkeypatch.setattr(runtime.wire.stream_routes, "resolve",
            lambda route, identity: channel if route == "acp-channel" and identity == "connection-1" else None)
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect("/wire/v1/acp-channel/connection-1",
                                              headers={"Authorization": f"Bearer {runtime.token}"}) as ws:
                    ws.send_text(frame)
                    while True:
                        ws.receive_text()
            assert refused.value.code == 4403
        assert channel.sent == []


def test_correlated_prompt_terminal_allows_next_key_but_unanswered_effect_stays_unknown():
    authority = Authority()
    gate = AcpAdmissionGate(authority, clock=lambda: 100)
    assert gate.authorize_submission(CONNECTION, SUBMISSION)["kind"] == "accepted"
    gate.admit_client_frame(CONNECTION, prompt())
    second = {**SUBMISSION, "submissionId": "submission-2", "text": "next"}
    with pytest.raises(AcpAdmissionRefused) as busy:
        gate.authorize_submission(CONNECTION, second)
    assert busy.value.code == "BUSY"
    gate.observe_agent_frame(CONNECTION.connection_id, json.dumps({"jsonrpc": "2.0", "id": 7,
        "result": {"stopReason": "end_turn"}}))
    assert gate.authorize_submission(CONNECTION, second)["kind"] == "accepted"
    gate.admit_client_frame(CONNECTION, prompt(second, request_id=8))
    # No terminal response for the second prompt: after reconnect it remains Unknown.
    third = {**SUBMISSION, "submissionId": "submission-3", "text": "third"}
    with pytest.raises(AcpAdmissionRefused) as busy_again:
        gate.authorize_submission(CONNECTION, third)
    assert busy_again.value.code == "BUSY"


def test_observed_non_permission_reverse_answer_is_one_use():
    gate = AcpAdmissionGate(clock=lambda: 100)
    response = json.dumps({"jsonrpc": "2.0", "id": 51, "result": {"content": "hello"}})
    with pytest.raises(AcpAdmissionRefused, match="no observed request"):
        gate.admit_client_frame(CONNECTION, response)
    gate.observe_agent_frame(CONNECTION.connection_id, json.dumps({"jsonrpc": "2.0", "id": 51,
        "method": "fs/read_text_file", "params": {"path": "/safe/file"}}))
    gate.admit_client_frame(CONNECTION, response)
    with pytest.raises(AcpAdmissionRefused, match="already consumed"):
        gate.admit_client_frame(CONNECTION, response)


def test_reused_reverse_id_cannot_turn_permission_into_generic_answer():
    gate = AcpAdmissionGate(clock=lambda: 100)
    gate.observe_agent_frame(CONNECTION.connection_id, json.dumps({"jsonrpc": "2.0", "id": 51,
        "method": "fs/read_text_file", "params": {"path": "/safe/file"}}))
    gate.observe_agent_frame(CONNECTION.connection_id, json.dumps({"jsonrpc": "2.0", "id": 51,
        "method": "session/request_permission", "params": {"sessionId": "session-1",
            "options": [{"optionId": "allow-once"}]}}))
    with pytest.raises(AcpAdmissionRefused, match="id was reused"):
        gate.admit_client_frame(CONNECTION, json.dumps({"jsonrpc": "2.0", "id": 51,
            "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}}}))


def test_channel_release_retires_volatile_admissions_and_request_ids():
    gate = AcpAdmissionGate(Authority(), clock=lambda: 100)
    gate.authorize_submission(CONNECTION, SUBMISSION)
    gate.admit_client_frame(CONNECTION, prompt())
    gate.forget_channel(CONNECTION.connection_id)
    with pytest.raises(AcpAdmissionRefused, match="lacks matching"):
        gate.admit_client_frame(CONNECTION, prompt())
    assert gate.authorize_submission(CONNECTION, SUBMISSION)["kind"] == "accepted"


def test_confirmed_wire_release_prunes_gate_without_a_websocket_subscriber():
    from ordessa_server.plugin_host import MethodRegistry, StreamRouteRegistry
    from ordessa_server.wire.handlers import WireService
    from server_plugin_api import ServerMethodDescriptor, StreamRouteDescriptor

    gate = AcpAdmissionGate(Authority(), clock=lambda: 100)
    gate.authorize_submission(CONNECTION, SUBMISSION)
    gate.admit_client_frame(CONNECTION, prompt())
    live = {CONNECTION.connection_id: CONNECTION}
    released = False

    def release(params):
        if released:
            live.pop(params["connectionId"], None)
        return {"released": released, "connectionId": params["connectionId"]}

    methods, routes = MethodRegistry(), StreamRouteRegistry()
    methods.register(ServerMethodDescriptor(method_id="acp.channel.release",
        required_params=frozenset({"connectionId"}), optional_params=frozenset(),
        handler=release, owner="test.acp"))
    routes.register(StreamRouteDescriptor(route_id="acp-channel", resolver=live.get,
        owner="test.acp"))
    wire = WireService(server_id_provider=lambda: "server", cursor_secret=b"secret",
        method_registry=methods, stream_routes=routes, acp_admission_gate=gate)

    assert wire.dispatch("acp.channel.release", {"connectionId": CONNECTION.connection_id})["released"] is False
    assert gate._submissions  # an unconfirmed release preserves the Unknown fence
    released = True
    assert wire.dispatch("acp.channel.release", {"connectionId": CONNECTION.connection_id})["released"] is True
    assert not gate._submissions and not gate._used_prompt_ids


def _public_binding(**changes):
    values = dict(connection_id="connection-1", execution_id="execution-1",
                  ledger_session_id="ledger-1", harness_id="codex",
                  workspace_id="workspace-1", native_session_id="session-1",
                  runtime_generation=7)
    values.update(changes)
    return AcpChannelBinding(**values)


def _public_submission():
    return AcpSubmissionRequest("submission-1", "session-1", "hello",
        (AcpAttachmentReference("brief", "file:///brief", "a" * 64),), "b" * 64)


def _public_adapter(authority=None):
    authority = authority or Authority()
    gate = AcpAdmissionGate(authority, clock=lambda: 100)
    channel = SimpleNamespace(connection_id="connection-1", execution_id="execution-1",
        session_id="ledger-1", harness_id="codex", workspace_id="workspace-1",
        native_session_id="session-1", runtime_generation=7,
        transport=object(), ended=False)
    routes = SimpleNamespace(resolve=lambda route, identity: channel
        if route == "acp-channel" and identity == channel.connection_id else None)
    return AcpAdmissionPortAdapter(gate, routes), gate, authority, channel


def test_public_admission_port_converts_dtos_and_keeps_raw_relay_one_use():
    port, gate, authority, channel = _public_adapter()
    assert port.public_acp_admission_port_version == 1
    # S-06/S-03：authority 注入即 ready（产品组合现在真的注入权限后端）；
    # 原断言（"测试注入不算产品证据"）随 ready 语义修正退役——
    # ready 的另一半（native evidence）仍诚实缺席，见 report。
    assert port.ready is True  # authority wired by the test injection
    accepted = port.authorize_submission(_public_binding(), _public_submission())
    assert accepted.kind == "accepted" and accepted.submission_id == "submission-1"
    assert authority.submission_calls == 1
    stale = port.authorize_submission(_public_binding(runtime_generation=8), _public_submission())
    assert stale.kind == "refused" and stale.code == "AUTHORIZATION_REFUSED"
    with pytest.raises(AcpAdmissionRefused, match="lacks matching"):
        gate.admit_client_frame(channel, prompt({**SUBMISSION, "text": "changed"}))
    gate.admit_client_frame(channel, prompt())
    assert port.authorize_submission(_public_binding(), _public_submission()).kind == "unknown"
    with pytest.raises(AcpAdmissionRefused, match="already used"):
        gate.admit_client_frame(channel, prompt())
    gate.observe_agent_frame(channel.connection_id, json.dumps({"jsonrpc": "2.0", "id": 19,
        "method": "session/request_permission", "params": {"sessionId": "session-1",
            "options": [{"optionId": "allow-once"}]}}))
    decision = AcpPermissionDecision("session-1", "interaction-1", "run-1", "allow-once")
    permission = port.authorize_permission(_public_binding(), decision)
    assert permission.kind == "accepted" and permission.submission_id == "interaction-1"
    response = json.dumps({"jsonrpc": "2.0", "id": 19,
        "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}}})
    gate.admit_client_frame(channel, response)
    with pytest.raises(AcpAdmissionRefused, match="already consumed"):
        gate.admit_client_frame(channel, response)
    gate.forget_channel(channel.connection_id)
    assert not gate._submissions and not gate._answered_permissions


@pytest.mark.parametrize("binding", [
    _public_binding(native_session_id=None),
    _public_binding(runtime_generation=None),
    _public_binding(native_session_id="other-native"),
    _public_binding(runtime_generation=8),
    _public_binding(workspace_id="other-workspace"),
])
def test_public_port_refuses_missing_or_mismatched_channel_evidence(binding):
    port, gate, authority, _ = _public_adapter()
    result = port.authorize_submission(binding, _public_submission())
    assert result.kind == "refused" and result.code == "AUTHORIZATION_REFUSED"
    assert not gate._submissions
    if binding.runtime_generation != 8:
        assert authority.submission_calls == 0


def test_public_port_missing_authority_and_permission_generation_refuse():
    port, gate, authority, channel = _public_adapter()
    gate.authority = None
    refused = port.authorize_submission(_public_binding(), _public_submission())
    assert refused.kind == "refused" and refused.code == "CAPABILITY_UNSUPPORTED"
    gate.authority = authority
    gate.observe_agent_frame(channel.connection_id, json.dumps({"jsonrpc": "2.0", "id": 19,
        "method": "session/request_permission", "params": {"sessionId": "session-1",
            "options": [{"optionId": "allow-once"}]}}))
    decision = AcpPermissionDecision("session-1", "interaction-1", "run-1", "allow-once")
    refused = port.authorize_permission(_public_binding(), decision)
    assert refused.kind == "refused" and refused.code == "AUTHORIZATION_REFUSED"
    assert authority.permission_calls == 0


@pytest.mark.parametrize("missing", ["native_session_id", "runtime_generation"])
def test_public_port_requires_native_and_generation_on_live_channel(missing):
    port, gate, authority, channel = _public_adapter()
    delattr(channel, missing)
    result = port.authorize_submission(_public_binding(), _public_submission())
    assert result.kind == "refused" and result.code == "AUTHORIZATION_REFUSED"
    assert authority.submission_calls == 0 and not gate._submissions


def test_composition_exposes_public_port_not_raw_gate(tmp_path):
    runtime = build_runtime(tmp_path / "data")
    try:
        port = runtime.plugin_host.host_ports[ACP_ADMISSION_PORT]
        assert isinstance(port, AcpAdmissionPortAdapter)
        assert port is not runtime.wire.acp_admission_gate
        assert port.public_acp_admission_port_version == 1
        assert port.ready is False
        assert port.authorize_submission(_public_binding(), _public_submission()).kind == "refused"
    finally:
        runtime.stop()
