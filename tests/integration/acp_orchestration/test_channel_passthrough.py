"""Requirements 4 and 5 measured as OLD-CHAIN DIAGNOSTICS at the port seam.

目标验收见 test_managed_acp_channel.py（客户端经 Server 受管理通道与 ACP 对端
双向原样通信）；本模块测量的是现有 envelope/`_forward` 投影层的失真点，供实施
新通道时对照，不作为目标通过标准。  Tests named `*_flows_through` fail while
the product re-projects the channel; the others pin what already holds.
"""
import json
import threading

import pytest

from tests.acp_orchestration.conftest import peer_events, wait_until
from ordessa_server_compat.execution.sidecar import SidecarError


def prompt_in_thread(port, execution_id, text):
    box = {}

    def run():
        try:
            box["result"] = port.prompt(execution_id, text)
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


# -- requirement 4: known flows ----------------------------------------------


def test_request_result_and_upward_notification_flow(ports, project):
    handle = ports(project)
    native = handle.open()
    assert native, "native session id must come back from the real channel"
    result = handle.port.prompt("execution-1", "ping")
    assert result.get("stopReason") == "end_turn", result
    event, payload = handle.event_for("message.delta", "got:ping")
    assert payload == {"text": "got:ping"}, \
        "message content must pass through unchanged"


def test_downward_cancel_reaches_the_agent_and_settles_the_turn(ports, project):
    handle = ports(project)
    handle.open()
    thread, box = prompt_in_thread(handle.port, "execution-1", "scenario:hang")
    # the prompt request must reach the peer before it is cancelled
    wait_until(lambda: any(
        row.get("dir") == "recv"
        and (row.get("frame", {}).get("method") == "session/prompt")
        for row in peer_events(handle.log_base)), timeout=30,
        message="session/prompt to reach the peer")
    assert handle.port.cancel("execution-1") is True
    thread.join(timeout=30)
    assert "error" not in box, box
    wait_until(lambda: any(
        row.get("dir") == "recv"
        and row.get("frame", {}).get("method") == "session/cancel"
        for row in peer_events(handle.log_base)), timeout=15,
        message="session/cancel to reach the peer")


def test_cancelled_stop_reason_flows_through(ports, project):
    """Target contract (R4): the Agent's `stopReason: cancelled` answer reaches
    the port as the prompt result.

    Measured current state: the bridge's generation guard deliberately withholds
    a cancelled turn's response (`acp-service.js` "a cancelled or superseded
    turn stores nothing"), so the worker substitutes the `{done: true}`
    fallback and the ACP result is rewritten at the plugin boundary.
    """
    handle = ports(project)
    handle.open()
    thread, box = prompt_in_thread(handle.port, "execution-1", "scenario:hang")
    wait_until(lambda: any(
        row.get("dir") == "recv"
        and row.get("frame", {}).get("method") == "session/prompt"
        for row in peer_events(handle.log_base)), timeout=30,
        message="session/prompt to reach the peer")
    handle.port.cancel("execution-1")
    thread.join(timeout=30)
    assert box.get("result", {}).get("stopReason") == "cancelled", box


def test_upward_error_carries_the_native_error_identity(ports, project):
    """Target contract (R4): a JSON-RPC error relays with its own identity.

    The comparison is exact, not textual: the numeric `code`, the full
    `message`, and the structured `data` object must each survive the channel
    unchanged.

    Measured current state: the plugin boundary replaces every upstream error
    whose `code` is not a product-shaped string with `SIDECAR_OP_FAILED`, so
    the peer's -32603, its message and its data never reach the Server's
    channel fact.
    """
    handle = ports(project)
    handle.open()
    with pytest.raises(SidecarError) as caught:
        handle.port.prompt("execution-1", "scenario:rpc-error")
    error = caught.value
    code = int(error.code) if isinstance(error.code, str) and error.code.lstrip("-").isdigit() else error.code
    assert code == -32603, \
        f"the JSON-RPC numeric code must survive the channel, got {error.code!r}"
    assert error.message == "hd003 peer internal failure", \
        f"the error message must arrive verbatim, got {error.message!r}"
    data = getattr(error, "data", None)
    assert data == {"vendorDetail": "keep-me"}, \
        f"the structured error data must survive unchanged, got {data!r}"


# -- requirement 5: no whitelist filtering of extensions ---------------------


def test_advertised_session_capability_is_observed(ports, project):
    handle = ports(project)
    handle.open()
    _, resumable = handle.port.capture_execution("execution-1")
    assert resumable is True, \
        "the peer advertised sessionCapabilities.resume; the port must observe it"


def test_unknown_update_kind_flows_through(ports, project):
    """Target contract (R5): an unknown `sessionUpdate` kind is relayed, not filtered.

    Measured current state: `SidecarHarnessPort._forward` handles five known
    kinds and drops everything else.
    """
    handle = ports(project)
    handle.open()
    handle.port.prompt("execution-1", "scenario:custom-update")
    assert handle.event_for("message.delta", "got:scenario:custom-update")
    extensions = [
        event for event in handle.events
        if "hd003_extension" in json.dumps(event, ensure_ascii=False, default=str)]
    assert extensions, "the Agent's extension update must reach the channel consumer"


def test_message_meta_flows_through(ports, project):
    """Target contract (R5): update-level `_meta` is relayed with the chunk.

    Measured current state: the projection emits only {"text": ...}.
    """
    handle = ports(project)
    handle.open()
    handle.port.prompt("execution-1", "scenario:meta")
    event, payload = handle.event_for("message.delta", "meta-payload")
    assert json.dumps(payload, default=str).count("hd003") >= 1, \
        f"the chunk's _meta must not be dropped: {payload}"


def test_advertised_extension_capability_flows_through(ports, project):
    """Target contract (R5): capability declarations are not rewritten.

    The peer advertises `hd003_custom_capability` and an agentInfo extension.
    Measured current state: the only port-visible channel facts are
    {nativeSessionId, provenance}; unknown capability fields never surface.
    """
    handle = ports(project)
    handle.open()
    surfaced = json.dumps({
        "started": [event for _, kind, event in handle.events if kind == "started"],
        "capture": handle.port.capture_execution("execution-1"),
        "capabilities": handle.port.effective_capabilities("execution-1"),
    }, ensure_ascii=False, default=str)
    assert "hd003_custom_capability" in surfaced, (
        f"peer-advertised extension capability must reach the Server view: {surfaced}")
