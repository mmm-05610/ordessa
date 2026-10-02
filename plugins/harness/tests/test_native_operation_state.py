"""Operation-presence classification over a controlled transport: the native's
own invalid-params answer distinguishes a pre-effect refusal from an unproven
reply; every other failure stays NativeConfigurationUnavailable."""
import json
import queue

import pytest

from ordessa_harness.server_acp.registry import (
    AcpChannelRegistry, _Channel, _ObservedTransport,
    NativeConfigurationUnavailable,
)


@pytest.fixture
def rig():
    channel = _Channel(connection_id="channel", harness_id="pi", workspace_id="project",
                       profile_id="fixture-profile", cwd="/fixture-project")
    channel.session_id = "fixture-ledger"
    channel.execution_id = "fixture-execution"
    replies = queue.Queue()
    mode = {"operation": "result"}

    class ControlledTransport:
        def send_line(self, line):
            frame = json.loads(line)
            if frame["method"] == "session/new":
                channel.deliver(json.dumps({"jsonrpc": "2.0", "id": frame["id"],
                    "result": {"sessionId": "native-a"}}))
                return
            assert frame["method"] == "_ordessa/session/configuration/operation"
            if mode["operation"] == "result":
                channel.deliver(json.dumps({"jsonrpc": "2.0", "id": frame["id"],
                    "result": {"sessionId": "native-a", "operationId": frame["params"]["operationId"],
                               "state": "observed"}}))
            elif mode["operation"] == "invalid-params":
                channel.deliver(json.dumps({"jsonrpc": "2.0", "id": frame["id"],
                    "error": {"code": -32602, "message": "Unknown provider registration"}}))
            elif mode["operation"] == "method-not-found":
                channel.deliver(json.dumps({"jsonrpc": "2.0", "id": frame["id"],
                    "error": {"code": -32601, "message": "Method not found"}}))
            # silence: no reply at all

    class ImmediateLoop:
        def call_soon_threadsafe(self, callback, item):
            callback(item)

    channel.transport = _ObservedTransport(channel, ControlledTransport())
    channel.attach(ImmediateLoop(), lambda line: replies.put(json.loads(line)))
    channel.transport.send_line(json.dumps({"jsonrpc": "2.0", "id": "new", "method": "session/new",
                                            "params": {}}))
    registry = AcpChannelRegistry(session_records=None, profile_records=None,
                                  launch=lambda **kwargs: pytest.fail("fixture must not launch"))
    with registry._lock:
        registry._by_id[channel.connection_id] = channel
        registry._by_pair[channel.pair] = channel
    return registry, channel, mode


def test_operation_query_result_classifies_present(rig):
    registry, channel, mode = rig
    assert registry.query_native_operation_state("channel", "native-a", "provider:op") == "present"
    owner, record = registry.query_native_operation("channel", "native-a", "provider:op")
    assert record["state"] == "observed"


def test_invalid_params_answer_classifies_refused(rig):
    registry, channel, mode = rig
    mode["operation"] = "invalid-params"
    assert registry.query_native_operation_state("channel", "native-a", "provider:op") == "refused"
    with pytest.raises(NativeConfigurationUnavailable):
        registry.query_native_operation("channel", "native-a", "provider:op")


def test_foreign_error_class_stays_unavailable(rig):
    registry, channel, mode = rig
    mode["operation"] = "method-not-found"
    with pytest.raises(NativeConfigurationUnavailable):
        registry.query_native_operation_state("channel", "native-a", "provider:op")


def test_lost_reply_is_never_a_refusal(rig):
    registry, channel, mode = rig
    mode["operation"] = "silence"
    with pytest.raises(NativeConfigurationUnavailable):
        registry.query_native_operation_state("channel", "native-a", "provider:op", timeout=1)


def test_ended_channel_never_classifies(rig):
    registry, channel, mode = rig
    with channel._lock:
        channel._ended = True
    with pytest.raises(NativeConfigurationUnavailable):
        registry.query_native_operation_state("channel", "native-a", "provider:op")
