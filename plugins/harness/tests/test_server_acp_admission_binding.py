"""The ACP owner binds only the explicit public admission port to its live channel."""
from __future__ import annotations

import json
import pytest

from server_plugin_api import AcpAdmissionResult, ServerPluginContext
from server_plugin_api import WireError

from ordessa_harness.server_acp.plugin import AcpChannelServerPlugin, PLUGIN_ID


class _Ledger:
    def create_session(self, **_kwargs):
        return "accepted", {"session_id": "ledger-session-1"}

    def create_turn(self, **_kwargs):
        return True, "accepted", {"turn_id": "execution-1"}

    def finish_cancelled(self, *_args, **_kwargs):
        pass


class _Profiles:
    def get(self, _profile_id):
        return {"config_revision": 0, "config_object_digest": "sha256:profile"}


class _Transport:
    def send_line(self, _line):
        pass

    def terminate(self):
        pass


class PublicPort:
    public_acp_admission_port_version = 1
    ready = True

    def __init__(self):
        self.calls = []
        self.outcome = "accepted"

    def authorize_submission(self, binding, submission):
        self.calls.append(("submission", binding, submission))
        if self.outcome == "unknown":
            return AcpAdmissionResult("unknown", operation_id="operation-1", reason="effect uncertain")
        if self.outcome == "refused":
            return AcpAdmissionResult("refused", code="AUTHORIZATION_REFUSED", reason="no permit")
        return AcpAdmissionResult("accepted", submission_id=submission.submission_id)

    def authorize_permission(self, binding, decision):
        self.calls.append(("permission", binding, decision))
        return AcpAdmissionResult("accepted", submission_id=decision.interaction_id)


def _registration(*, gate=None, launch=None):
    ports = {"workspace.service": object(), "sessions.records": object(),
             "profiles.records": object()}
    if launch is not None:
        ports["sessions.records"] = _Ledger()
        ports["profiles.records"] = _Profiles()
    if gate is not None:
        ports["acp.admission.gate"] = gate
    plugin = AcpChannelServerPlugin(launch=launch)
    registration = plugin.build(ServerPluginContext(plugin_id=PLUGIN_ID, data_root=None, ports=ports))
    return plugin, registration


def _method(registration, method_id):
    return next(item for item in registration.methods if item.method_id == method_id)


def _observe_native(registry, connection_id, native_id="native-1"):
    channel = registry.get(connection_id)
    assert channel is not None
    channel.transport.send_line(json.dumps({"jsonrpc": "2.0", "id": 71,
                                           "method": "session/new", "params": {}}))
    channel.deliver(json.dumps({"jsonrpc": "2.0", "id": 71,
                                "result": {"sessionId": native_id}}))


def test_unobserved_native_session_claim_never_reaches_admission_port(tmp_path):
    gate = PublicPort()
    _, registration = _registration(gate=gate, launch=lambda **_kwargs: _Transport())
    registry = registration.provided_ports["acp.channels"]
    opened = registry.acquire(harness_id="pi", workspace_id="workspace-1",
                              profile_id="profile-1", cwd=str(tmp_path))
    params = {"connectionId": opened["connectionId"], "submission": {
        "submissionId": "submission-1", "nativeSessionId": "native-1", "text": "hello",
        "attachments": [], "configurationDigest": "b" * 64}}
    result = _method(registration, "acp.submission.authorize").handler(params)
    assert result["kind"] == "refused" and gate.calls == []


def test_native_observation_is_bound_to_live_channel_for_submission_and_permission(tmp_path):
    gate = PublicPort()
    _, registration = _registration(gate=gate, launch=lambda **_kwargs: _Transport())
    registry = registration.provided_ports["acp.channels"]
    first = registry.acquire(harness_id="pi", workspace_id="workspace-1",
                             profile_id="profile-1", cwd=str(tmp_path))
    second = registry.acquire(harness_id="pi", workspace_id="workspace-2",
                              profile_id="profile-1", cwd=str(tmp_path))
    _observe_native(registry, first["connectionId"])
    submit = _method(registration, "acp.submission.authorize")
    permission = _method(registration, "acp.permission.authorize")
    body = {"submissionId": "submission-1", "nativeSessionId": "native-1",
            "text": "hello", "attachments": [], "configurationDigest": "b" * 64}
    decision = {"interactionId": "ask-1", "nativeSessionId": "native-1",
                "runId": "run-1", "optionId": "allow"}
    assert submit.handler({"connectionId": second["connectionId"], "submission": body})["kind"] == "refused"
    assert permission.handler({"connectionId": second["connectionId"], "decision": decision})["kind"] == "refused"
    assert gate.calls == []
    assert submit.handler({"connectionId": first["connectionId"], "submission": body})["kind"] == "accepted"
    assert permission.handler({"connectionId": first["connectionId"], "decision": decision})["kind"] == "accepted"
    assert all(call[1].native_session_id == "native-1" and call[1].runtime_generation is None
               for call in gate.calls)
    before = len(gate.calls)
    assert registry.release(first["connectionId"])["released"] is True
    assert submit.handler({"connectionId": first["connectionId"], "submission": body})["kind"] == "refused"
    assert permission.handler({"connectionId": first["connectionId"], "decision": decision})["kind"] == "refused"
    assert len(gate.calls) == before
    registry.stop_all()


@pytest.mark.parametrize("method_id,body", [
    ("acp.submission.authorize", {"connectionId": "conn-1", "submission": {
        "submissionId": "submit-1", "nativeSessionId": "native-1", "text": "hi",
        "attachments": [], "configurationDigest": "digest"}}),
    ("acp.permission.authorize", {"connectionId": "conn-1", "decision": {
        "interactionId": "ask-1", "nativeSessionId": "native-1",
        "runId": "run-1", "optionId": "allow"}}),
])
def test_admission_methods_are_owned_and_fail_closed_without_channel(method_id, body):
    _, registration = _registration()
    descriptor = _method(registration, method_id)
    assert descriptor.owner == PLUGIN_ID
    assert descriptor.availability() == (False, "ACP admission authority is unavailable")
    assert descriptor.handler(body)["code"] == "CAPABILITY_UNSUPPORTED"


def test_live_registry_binding_passes_observed_facts_and_typed_results(tmp_path):
    gate = PublicPort()
    plugin, registration = _registration(gate=gate, launch=lambda **_kwargs: _Transport())
    registry = registration.provided_ports["acp.channels"]
    opened = registry.acquire(harness_id="pi", workspace_id="workspace-1",
                              profile_id="profile-1", cwd=str(tmp_path))
    connection_id = opened["connectionId"]
    _observe_native(registry, connection_id)
    submit = _method(registration, "acp.submission.authorize")
    permission = _method(registration, "acp.permission.authorize")
    assert submit.availability() == (True, None)
    body = {"connectionId": connection_id, "submission": {
        "submissionId": "submission-1", "nativeSessionId": "native-1", "text": "hello",
        "attachments": [{"name": "brief", "uri": "file:///brief", "sha256": "a" * 64}],
        "configurationDigest": "b" * 64}}
    assert submit.handler(body) == {"kind": "accepted", "submissionId": "submission-1"}
    kind, binding, request = gate.calls[-1]
    assert kind == "submission" and binding.connection_id == connection_id
    assert binding.execution_id == opened["executionId"]
    assert binding.ledger_session_id == "ledger-session-1"
    assert binding.harness_id == "pi" and binding.workspace_id == "workspace-1"
    assert binding.native_session_id == "native-1" and binding.runtime_generation is None
    assert request.attachments[0].sha256 == "a" * 64
    gate.outcome = "unknown"
    assert submit.handler(body) == {"kind": "unknown", "operationId": "operation-1",
                                    "reason": "effect uncertain"}
    gate.outcome = "refused"
    assert submit.handler(body) == {"kind": "refused", "code": "AUTHORIZATION_REFUSED",
                                    "reason": "no permit"}
    assert permission.handler({"connectionId": connection_id, "decision": {
        "interactionId": "interaction-1", "nativeSessionId": "native-1",
        "runId": "client-run-1", "optionId": "allow-once"}}) == {
            "kind": "accepted", "submissionId": "interaction-1"}
    assert gate.calls[-1][2].run_id == "client-run-1"
    before = len(gate.calls)
    assert submit.handler({**body, "connectionId": "foreign"})["kind"] == "refused"
    assert len(gate.calls) == before
    plugin._dispose()
    assert submit.availability()[0] is False
    assert submit.handler(body)["kind"] == "refused"


def test_unmarked_or_incompatible_port_is_not_called(tmp_path):
    class RawGate:
        def authorize_submission(self, *_args):
            raise AssertionError("raw internal gate must never be called")

    _, registration = _registration(gate=RawGate(), launch=lambda **_kwargs: _Transport())
    opened = registration.provided_ports["acp.channels"].acquire(
        harness_id="pi", workspace_id="workspace-1", profile_id="profile-1", cwd=str(tmp_path))
    submit = _method(registration, "acp.submission.authorize")
    assert submit.availability()[0] is False
    assert submit.handler({"connectionId": opened["connectionId"], "submission": {}})["code"] == "CAPABILITY_UNSUPPORTED"


def test_wire_dispatch_and_owner_retirement_with_controlled_public_port(tmp_path):
    from ordessa_server.plugin_host import MethodRegistry
    from ordessa_server.wire.handlers import WireService

    gate = PublicPort()
    plugin, registration = _registration(gate=gate, launch=lambda **_kwargs: _Transport())
    opened = registration.provided_ports["acp.channels"].acquire(
        harness_id="pi", workspace_id="workspace-1", profile_id="profile-1", cwd=str(tmp_path))
    _observe_native(registration.provided_ports["acp.channels"], opened["connectionId"])
    methods = MethodRegistry()
    wire = WireService(server_id_provider=lambda: "server-1", cursor_secret=b"test-secret",
                       method_registry=methods)
    for descriptor in registration.methods:
        methods.register(descriptor)
    submission = {"submissionId": "submission-1", "nativeSessionId": "native-1",
                  "text": "hello", "attachments": [], "configurationDigest": "b" * 64}
    params = {"connectionId": opened["connectionId"], "submission": submission}
    assert wire.dispatch("acp.submission.authorize", params) == {
        "kind": "accepted", "submissionId": "submission-1"}
    gate.outcome = "refused"
    assert wire.dispatch("acp.submission.authorize", params)["kind"] == "refused"
    gate.outcome = "unknown"
    assert wire.dispatch("acp.submission.authorize", params)["kind"] == "unknown"
    assert wire.dispatch("acp.permission.authorize", {"connectionId": opened["connectionId"],
        "decision": {"interactionId": "interaction-1", "nativeSessionId": "native-1",
                     "runId": "client-run-1", "optionId": "allow-once"}}) == {
                         "kind": "accepted", "submissionId": "interaction-1"}
    for descriptor in registration.methods:
        methods.unregister(descriptor.method_id, owner=PLUGIN_ID)
    plugin._dispose()
    with pytest.raises(WireError, match="not a wire/1 method"):
        wire.dispatch("acp.submission.authorize", params)


def test_replay_and_moved_payload_are_projected_from_public_port(tmp_path):
    class OneUsePort(PublicPort):
        def __init__(self):
            super().__init__()
            self.first = None

        def authorize_submission(self, binding, submission):
            self.calls.append(("submission", binding, submission))
            if self.first is None:
                self.first = submission
                return AcpAdmissionResult("accepted", submission_id=submission.submission_id)
            if submission == self.first:
                return AcpAdmissionResult("unknown", operation_id=submission.submission_id,
                                          reason="prior send needs reconciliation")
            return AcpAdmissionResult("refused", code="TARGET_CONFLICT", reason="identity changed")

    gate = OneUsePort()
    _, registration = _registration(gate=gate, launch=lambda **_kwargs: _Transport())
    opened = registration.provided_ports["acp.channels"].acquire(
        harness_id="pi", workspace_id="workspace-1", profile_id="profile-1", cwd=str(tmp_path))
    _observe_native(registration.provided_ports["acp.channels"], opened["connectionId"])
    submit = _method(registration, "acp.submission.authorize")
    params = {"connectionId": opened["connectionId"], "submission": {
        "submissionId": "submission-1", "nativeSessionId": "native-1", "text": "hello",
        "attachments": [], "configurationDigest": "b" * 64}}
    assert submit.handler(params)["kind"] == "accepted"
    assert submit.handler(params)["kind"] == "unknown"
    assert submit.handler({**params, "submission": {**params["submission"], "text": "changed"}})["code"] == "TARGET_CONFLICT"


def test_selected_product_host_registers_owner_methods_but_admission_stays_unavailable(tmp_path):
    from ordessa_server.bootstrap import build_runtime

    runtime = build_runtime(tmp_path / "data")
    try:
        for method_id, body in (
            ("acp.submission.authorize", {"connectionId": "missing", "submission": {}}),
            ("acp.permission.authorize", {"connectionId": "missing", "decision": {}}),
        ):
            descriptor = runtime.plugin_host.methods.lookup(method_id)
            assert descriptor is not None and descriptor.owner == PLUGIN_ID
            assert descriptor.availability()[0] is False
            assert runtime.wire.dispatch(method_id, body)["code"] == "CAPABILITY_UNSUPPORTED"
    finally:
        runtime.stop()


def test_submission_port_effect_then_exception_is_unknown_not_refused(tmp_path):
    class EffectThenException(PublicPort):
        def __init__(self):
            super().__init__()
            self.effects = 0

        def authorize_submission(self, binding, submission):
            self.effects += 1
            raise ValueError("reply lost after reservation")

    gate = EffectThenException()
    _, registration = _registration(gate=gate, launch=lambda **_kwargs: _Transport())
    opened = registration.provided_ports["acp.channels"].acquire(
        harness_id="pi", workspace_id="workspace-1", profile_id="profile-1", cwd=str(tmp_path))
    _observe_native(registration.provided_ports["acp.channels"], opened["connectionId"])
    result = _method(registration, "acp.submission.authorize").handler({
        "connectionId": opened["connectionId"], "submission": {
            "submissionId": "submission-1", "nativeSessionId": "native-1", "text": "hello",
            "attachments": [], "configurationDigest": "b" * 64}})
    assert gate.effects == 1
    assert result == {"kind": "unknown", "operationId": "submission-1",
                      "reason": "ACP admission outcome needs reconciliation; query before retry"}


def test_permission_port_effect_then_malformed_result_is_unknown_not_refused(tmp_path):
    class EffectThenMalformed(PublicPort):
        def __init__(self):
            super().__init__()
            self.effects = 0

        def authorize_permission(self, binding, decision):
            self.effects += 1
            return {"kind": "accepted", "submissionId": decision.interaction_id}

    gate = EffectThenMalformed()
    _, registration = _registration(gate=gate, launch=lambda **_kwargs: _Transport())
    opened = registration.provided_ports["acp.channels"].acquire(
        harness_id="pi", workspace_id="workspace-1", profile_id="profile-1", cwd=str(tmp_path))
    _observe_native(registration.provided_ports["acp.channels"], opened["connectionId"])
    result = _method(registration, "acp.permission.authorize").handler({
        "connectionId": opened["connectionId"], "decision": {
            "interactionId": "interaction-1", "nativeSessionId": "native-1",
            "runId": "client-run-1", "optionId": "allow-once"}})
    assert gate.effects == 1
    assert result == {"kind": "unknown", "operationId": "interaction-1",
                      "reason": "ACP admission outcome needs reconciliation; query before retry"}


def test_typed_accepted_reply_with_moved_identity_is_unknown(tmp_path):
    class MovedReply(PublicPort):
        def authorize_submission(self, binding, submission):
            return AcpAdmissionResult("accepted", submission_id="someone-else")

    _, registration = _registration(gate=MovedReply(), launch=lambda **_kwargs: _Transport())
    opened = registration.provided_ports["acp.channels"].acquire(
        harness_id="pi", workspace_id="workspace-1", profile_id="profile-1", cwd=str(tmp_path))
    _observe_native(registration.provided_ports["acp.channels"], opened["connectionId"])
    result = _method(registration, "acp.submission.authorize").handler({
        "connectionId": opened["connectionId"], "submission": {
            "submissionId": "submission-1", "nativeSessionId": "native-1", "text": "hello",
            "attachments": [], "configurationDigest": "b" * 64}})
    assert result["kind"] == "unknown" and result["operationId"] == "submission-1"
