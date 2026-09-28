"""旧链路诊断（R6 侧）：现有 register/prompt/permission_decision 信封在权限
往返上的行为测量。 目标验收见 test_managed_acp_channel.py —— 客户端经 Server
受管理通道直接原样往返 ACP 帧；旧信封补字段不构成目标通过路径。

Round trip under test: peer `session/request_permission` -> bridge -> worker
`permission_request` event -> port `approval.requested` -> (test acting as the
client) `register_approval`/`decide_approval` -> worker -> bridge -> the peer's
own JSON-RPC response.  The peer is the only component that ever decides.
"""
import time

from tests.integration.acp_orchestration.conftest import peer_events


def open_pending_permission(ports, project, prompt="scenario:permission"):
    handle = ports(project)
    handle.open()
    thread, box = _prompt(handle, prompt)
    event, payload = handle.event_for("approval.requested", "requestId")
    return handle, thread, box, payload["request"]


def _prompt(handle, text):
    box = {}
    import threading

    def run():
        try:
            box["result"] = handle.port.prompt("execution-1", text)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def test_reverse_request_arrives_verbatim_and_answer_completes_round_trip(ports, project):
    handle, thread, box, request = open_pending_permission(ports, project)

    # The native request is projected, not rewritten: the peer's own toolCall
    # and option identifiers must be exactly what the peer sent.
    assert request["toolCall"]["title"] == "hd003 approval", request
    options = {option["optionId"]: option["kind"] for option in request["options"]}
    grant = next(oid for oid in options if oid.startswith("grant-"))
    assert options[grant] == "allow_once", options

    # The Server must not fabricate an answer while the client still holds it.
    time.sleep(1.0)
    assert not [row for row in peer_events(handle.log_base)
                if row.get("event") == "permission-answer"], \
        "an approval was answered before the client decided"

    handle.port.register_approval("approval-1", "execution-1", request["requestId"])
    handle.port.decide_approval("approval-1", "allow", {"kind": "once"})
    thread.join(timeout=30)
    assert "error" not in box, box
    answers = [row for row in peer_events(handle.log_base)
               if row.get("event") == "permission-answer"]
    assert answers, "the client's decision never reached the Agent"
    outcome = answers[0]["frame"]["result"]["outcome"]
    assert outcome["outcome"] == "selected" and outcome["optionId"] == grant, outcome


def test_client_chosen_option_id_is_not_replaced_by_a_kind_guess(ports, project):
    """Diagnostic (R6): the client's chosen optionId must survive the round trip.

    The peer offers TWO options sharing one kind (`allow_once`) whose ids
    differ (`pick-1-<peerId>`, `pick-2-<peerId>`), so kind alone cannot
    identify the client's choice.  The client here chooses the second id.  The
    assertion is an exact optionId comparison, not a substring or prefix check:
    a middle layer that resolves the decision by kind table answers pick-1 and
    this test fails — measured current state of the envelope.
    """
    handle, thread, box, request = open_pending_permission(
        ports, project, "scenario:permission twin-options")
    allow_options = [option for option in request["options"]
                     if option["kind"] == "allow_once"]
    assert len(allow_options) == 2, request  # the twin premise is real
    chosen = next(option["optionId"] for option in allow_options
                  if option["optionId"].startswith("pick-2-"))
    assert chosen, allow_options

    handle.port.register_approval("approval-2", "execution-1", request["requestId"])
    # The client's explicit selection is the second optionId.  The existing
    # envelope cannot carry it (only allow/deny + scope), which is exactly the
    # gap this test pins: whatever the middleware answers must equal the id the
    # client chose.
    handle.port.decide_approval("approval-2", "allow",
                                {"kind": "once", "optionId": chosen})
    thread.join(timeout=30)
    assert "error" not in box, box
    answers = [row for row in peer_events(handle.log_base)
               if row.get("event") == "permission-answer"]
    assert answers, "the client's chosen option never reached the Agent"
    outcome = answers[0]["frame"]["result"]["outcome"]
    assert outcome["outcome"] == "selected"
    assert outcome["optionId"] == chosen, (
        f"the middle layer answered {outcome['optionId']!r} instead of the "
        f"client-chosen {chosen!r}")


def test_permission_request_without_a_decision_is_not_answered_by_the_server(ports, project):
    handle, thread, box, request = open_pending_permission(ports, project)
    time.sleep(1.0)
    assert not [row for row in peer_events(handle.log_base)
                if row.get("event") == "permission-answer"]
    assert "result" not in box and "error" not in box, \
        "the prompt settled without a client decision"
    # Cleanup: the owned channel is closed explicitly, not left to a timeout.
    handle.port.stop()
