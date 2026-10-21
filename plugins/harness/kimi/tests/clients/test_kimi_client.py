"""Positive and counter-example tests for the kimi Wire consumer client.

**Fake upstream, fixture level (L1)** — every test runs against a scripted
fake peer process that reproduces the JSON-RPC 2.0 record shapes pinned in
N006 from the official Wire mode docs (protocol 1.10). These tests prove the
consumer's framing/identity/typed-failure/fence behaviour only; they are NOT
real-process L2 evidence (no ``kimi`` binary is installed or executed here)
and must not be counted as upstream compatibility.

Gates covered (docs/implementation/specifications/030-native-harness-expansion/acceptance.md):

- G4  unknown events/requests preserved verbatim; reverse requests answered on
      the SAME JSON-RPC id; no auto-approve.
- G6  prompt terminal status is the peer's verbatim value; cancel is real
      evidence; no fabricated sessionId; missing session-create method stays
      'prepared'.
- G11 lost receipt: timeout keeps the ledger entry; the peer saw exactly one
      write per request (no re-send).
- N006 fence: requests observed during ``replay`` are never answered
      (automatic or explicit) — replay must never approve history again.
- Cross-request isolation: nested ``steer``/``cancel`` while ``prompt`` is
      pending; out-of-order receipts never resolve the wrong request.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ordessa_agents.harness.transport.channel import (
    ChannelClosed,
    LaunchSpec,
    ProcessChannel,
    RequestTimeout,
)
from ordessa_harness_kimi.client import (
    FAMILY_ID,
    WIRE_PROTOCOL_VERSION,
    KimiRpcError,
    KimiWireClient,
    ReplayResponseRefused,
    describe,
)

PEER = textwrap.dedent(
    r"""
    import json, sys

    MODE = sys.argv[2] if len(sys.argv) > 2 else "echo"
    counts = {"recv": 0, "replies": 0}

    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def read():
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(0)
        counts["recv"] += 1
        return json.loads(line)

    def drain():
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            counts["recv"] += 1
            msg = json.loads(line)
            if "id" in msg and "method" not in msg:
                counts["replies"] += 1

    def note():
        sys.stderr.write("recv=%d replies=%d" % (counts["recv"], counts["replies"]))
        sys.stderr.flush()

    if MODE == "initialize":
        msg = read()
        assert msg["method"] == "initialize"
        assert msg["params"]["protocol_version"] == "1.10"
        assert msg["params"]["capabilities"]["supports_question"] is True
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocol_version": "1.10",
            "server": {"name": "Kimi Code CLI", "version": "1.52.0"},
            "slash_commands": [{"name": "init", "description": "x", "aliases": []}],
            "capabilities": {"supports_question": True}}})
    elif MODE == "initialize-mismatch":
        msg = read()
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocol_version": "1.9",
            "server": {"name": "Kimi Code CLI", "version": "1.51.0"},
            "slash_commands": []}})
    elif MODE == "initialize-unsupported":
        msg = read()
        send({"jsonrpc": "2.0", "id": msg["id"],
              "error": {"code": -32601, "message": "Method not found"}})
    elif MODE == "prompt-events":
        msg = read()
        send({"jsonrpc": "2.0", "method": "event", "params": {"type": "TurnBegin", "payload": {"user_input": "hi"}}})
        send({"jsonrpc": "2.0", "method": "event", "params": {"type": "ContentPart", "payload": {"type": "text", "text": "hello"}}})
        send({"jsonrpc": "2.0", "method": "event", "params": {"type": "weird_future_event", "payload": {"keep": [1, 2]}}})
        send({"jsonrpc": "2.0", "method": "event", "params": {"type": "TurnEnd", "payload": {}}})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"status": "finished"}})
    elif MODE == "prompt-error":
        msg = read()
        send({"jsonrpc": "2.0", "id": msg["id"],
              "error": {"code": -32001, "message": "LLM is not set"}})
    elif MODE == "approval-live":
        msg = read()
        send({"jsonrpc": "2.0", "method": "event", "params": {"type": "TurnBegin", "payload": {}}})
        send({"jsonrpc": "2.0", "id": "srv-approval-1", "method": "request", "params": {
            "type": "ApprovalRequest",
            "payload": {"id": "approval-1", "tool_call_id": "tc-1", "sender": "Shell",
                        "action": "run shell command", "description": "Run ls", "display": []}}})
        approval_reply = read()
        counts["replies"] += 1
        send({"jsonrpc": "2.0", "id": "srv-question-1", "method": "request", "params": {
            "type": "QuestionRequest",
            "payload": {"id": "q-1", "tool_call_id": "tc-2", "questions": [
                {"question": "Which language?", "header": "Lang",
                 "options": [{"label": "Python"}, {"label": "Rust"}], "multi_select": False}]}}})
        question_reply = read()
        counts["replies"] += 1
        send({"jsonrpc": "2.0", "method": "event", "params": {
            "type": "ApprovalResponse", "payload": approval_reply["result"]}})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "status": "finished", "approval": approval_reply["result"],
            "question": question_reply["result"]}})
    elif MODE == "approval-unhandled":
        msg = read()
        send({"jsonrpc": "2.0", "id": "srv-approval-9", "method": "request", "params": {
            "type": "ApprovalRequest",
            "payload": {"id": "approval-9", "tool_call_id": "tc-9", "sender": "Shell",
                        "action": "rm -rf", "description": "dangerous", "display": []}}})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"status": "finished"}})
    elif MODE == "replay-history":
        msg = read()
        send({"jsonrpc": "2.0", "id": "hist-approval-1", "method": "request", "params": {
            "type": "ApprovalRequest",
            "payload": {"id": "approval-hist-1", "tool_call_id": "tc-h1", "sender": "Shell",
                        "action": "run", "description": "history", "display": []}}})
        send({"jsonrpc": "2.0", "id": "hist-question-1", "method": "request", "params": {
            "type": "QuestionRequest",
            "payload": {"id": "q-hist-1", "tool_call_id": "tc-h2", "questions": [
                {"question": "hist?", "options": [{"label": "A"}]}]}}})
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "status": "finished", "events": 5, "requests": 2}})
    elif MODE == "steer-cross":
        prompt_msg = read()
        send({"jsonrpc": "2.0", "method": "event", "params": {"type": "TurnBegin", "payload": {}}})
        steer_msg = read()
        send({"jsonrpc": "2.0", "id": prompt_msg["id"], "result": {"status": "finished"}})
        send({"jsonrpc": "2.0", "id": steer_msg["id"], "result": {"status": "steered"}})
    elif MODE == "cancel":
        prompt_msg = read()
        send({"jsonrpc": "2.0", "method": "event", "params": {"type": "TurnBegin", "payload": {}}})
        cancel_msg = read()
        send({"jsonrpc": "2.0", "id": cancel_msg["id"], "result": {}})
        send({"jsonrpc": "2.0", "id": prompt_msg["id"], "result": {"status": "cancelled"}})
    elif MODE == "silent":
        pass
    else:
        raise SystemExit("unknown mode %s" % MODE)
    drain()
    note()
    """
)


def launch_client(tmp_path, mode: str) -> KimiWireClient:
    script = tmp_path / "fake_kimi_peer.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build(
        [sys.executable, str(script), "--wire", mode],
        home=str(tmp_path / "home"),
        cwd=str(tmp_path),
    )
    return KimiWireClient.launch(spec, name=f"fake-kimi-{mode}")


# -- positive paths ------------------------------------------------------------


def test_describe_has_no_runtime_ready_claim() -> None:
    facts = describe()
    assert facts["familyId"] == FAMILY_ID == "kimi"
    assert facts["protocol"] == "kimi-wire/1.10"
    assert facts["wireVersion"] == WIRE_PROTOCOL_VERSION == "1.10"
    assert "runtimeReady" not in json.dumps(facts)
    assert "prompt" in facts["knownMethods"] and "replay" in facts["knownMethods"]
    assert "ApprovalRequest" in facts["inboundRequestTypes"]


def test_initialize_negotiates_version_fields_verbatim(tmp_path) -> None:
    client = launch_client(tmp_path, "initialize")
    try:
        negotiated = client.initialize(timeout=5)
        assert negotiated["handshake"] == "initialized"
        assert negotiated["client_declared_version"] == "1.10"
        assert negotiated["server_reported_version"] == "1.10"
        assert negotiated["version_match"] is True
        assert negotiated["server"]["version"] == "1.52.0"
        assert negotiated["result"]["slash_commands"][0]["name"] == "init"
        assert client.pending == {}
    finally:
        client.close()


def test_initialize_version_mismatch_is_surfaced_not_invented(tmp_path) -> None:
    """No documented mismatch policy → report False, never downgrade/retry."""
    client = launch_client(tmp_path, "initialize-mismatch")
    try:
        negotiated = client.initialize(timeout=5)
        assert negotiated["server_reported_version"] == "1.9"
        assert negotiated["version_match"] is False
        assert negotiated["result"]["protocol_version"] == "1.9"  # raw kept
    finally:
        client.close()


def test_initialize_unsupported_falls_back_to_no_handshake(tmp_path) -> None:
    """Documented: -32601 means the server lacks initialize; no-handshake."""
    client = launch_client(tmp_path, "initialize-unsupported")
    try:
        negotiated = client.initialize(timeout=5)
        assert negotiated["handshake"] == "no-handshake"
        assert negotiated["version_match"] == "unknown"
        assert client.handshake == "no-handshake"
    finally:
        client.close()


def test_send_prompt_returns_terminal_status_verbatim(tmp_path) -> None:
    """The documented prompt response is the turn-end result; status verbatim."""
    client = launch_client(tmp_path, "prompt-events")
    try:
        result = client.send_prompt("hi", timeout=5)
        assert result == {"status": "finished"}  # never remapped to "completed"
        types = [e.get("params", {}).get("type") for e in client.events()]
        assert "TurnBegin" in types and "TurnEnd" in types
        assert client.pending == {}
    finally:
        client.close()


def test_unknown_event_type_preserved_verbatim(tmp_path) -> None:
    """G4: a future/unknown Wire message keeps its raw type and payload."""
    client = launch_client(tmp_path, "prompt-events")
    try:
        client.send_prompt("hi", timeout=5)
        unknown = [
            e for e in client.events()
            if e.get("params", {}).get("type") == "weird_future_event"
        ]
        assert len(unknown) == 1
        assert unknown[0]["params"]["payload"] == {"keep": [1, 2]}
    finally:
        client.close()


def test_live_approval_and_question_answered_on_same_jsonrpc_id(tmp_path) -> None:
    """G4: caller-decided replies echo the JSON-RPC id and the payload token."""
    client = launch_client(tmp_path, "approval-live")

    def on_request(frame) -> None:
        if frame["params"]["type"] == "ApprovalRequest":
            client.reply_approval(frame["id"], "reject")  # documented decision
        elif frame["params"]["type"] == "QuestionRequest":
            client.reply_question(frame["id"], {"Which language?": "Rust"})

    try:
        result = client.send_prompt("hi", timeout=5, on_request=on_request)
        assert result["status"] == "finished"
        assert result["approval"] == {"request_id": "approval-1", "response": "reject"}
        assert result["question"] == {
            "request_id": "q-1",
            "answers": {"Which language?": "Rust"},
        }
        # ids: the request frames kept the server-chosen JSON-RPC ids
        inbound = {f["id"]: f for f in client.inbound_requests()}
        assert inbound["srv-approval-1"]["params"]["payload"]["id"] == "approval-1"
        assert inbound["srv-question-1"]["params"]["payload"]["id"] == "q-1"
        events = [e for e in client.events() if e.get("method") == "event"]
        assert any(e["params"]["type"] == "ApprovalResponse" for e in events)
    finally:
        exit_code = client.close()
        assert exit_code == 0
    assert "recv=3" in client.stderr_tail()  # prompt + 2 replies, no extra writes


def test_inbound_request_without_handler_is_never_auto_approved(tmp_path) -> None:
    """SAFETY: no on_request → the approval stays unanswered and verbatim."""
    client = launch_client(tmp_path, "approval-unhandled")
    try:
        result = client.send_prompt("hi", timeout=5)
        assert result["status"] == "finished"
        pending = client.unanswered_requests()
        assert len(pending) == 1
        assert pending[0]["id"] == "srv-approval-9"
        assert pending[0]["params"]["payload"]["action"] == "rm -rf"
    finally:
        client.close()
    assert client.stderr_tail() == "recv=1 replies=0"  # nothing answered


def test_replay_history_requests_are_fenced_and_never_answered(tmp_path) -> None:
    """N006 fence: replay is read-only; historical approvals stay unanswered
    even against an explicit caller reply."""
    client = launch_client(tmp_path, "replay-history")
    try:
        result = client.replay(timeout=5)
        assert result == {"status": "finished", "events": 5, "requests": 2}
        replayed = [f for f in client.inbound_requests() if f["id"] == "hist-approval-1"]
        assert replayed
        assert replayed[0]["params"]["payload"]["id"] == "approval-hist-1"
        for request_id, call in (
            ("hist-approval-1", lambda: client.reply_approval(request_id, "approve")),
            ("hist-question-1", lambda: client.reply_question(request_id, {"hist?": "A"})),
            ("hist-approval-1", lambda: client.reply_request(request_id, {"ok": True})),
        ):
            with pytest.raises(ReplayResponseRefused) as excinfo:
                call()
            assert excinfo.value.request_id == request_id
        assert client.unanswered_requests() == ()  # fenced, never queued for reply
    finally:
        client.close()
    assert client.stderr_tail() == "recv=1 replies=0"  # only the replay write


def test_prompt_timeout_is_typed_and_never_resent(tmp_path) -> None:
    """G11: one write, typed timeout, ledger stays unknown, no re-send."""
    client = launch_client(tmp_path, "silent")
    try:
        with pytest.raises(RequestTimeout) as excinfo:
            client.send_prompt("once", timeout=0.5)
        assert excinfo.value.method == "prompt"
        assert excinfo.value.code == "REQUEST_TIMEOUT"
        assert list(client.pending.values()) == ["prompt"]
        assert client.events() == ()
    finally:
        exit_code = client.close()
        assert exit_code == 0
    assert client.stderr_tail() == "recv=1 replies=0"  # peer saw exactly one write


def test_nested_steer_and_prompt_ids_do_not_cross(tmp_path) -> None:
    """G6: a steer issued from an event callback while prompt is pending gets
    its own receipt; the out-of-order prompt receipt is stashed, not stolen."""
    client = launch_client(tmp_path, "steer-cross")
    steered = {}

    def on_event(frame) -> None:
        if frame["params"]["type"] == "TurnBegin":
            steered["result"] = client.steer("use python", timeout=5)

    try:
        result = client.send_prompt("hi", timeout=5, on_event=on_event)
        assert result == {"status": "finished"}
        assert steered["result"] == {"status": "steered"}
        assert client.pending == {} and client._responses == {}
    finally:
        client.close()
    assert client.stderr_tail() == "recv=2 replies=0"


def test_cancel_is_real_evidence_and_prompt_reports_cancelled(tmp_path) -> None:
    client = launch_client(tmp_path, "cancel")
    cancelled = {}

    def on_event(frame) -> None:
        if frame["params"]["type"] == "TurnBegin":
            cancelled["result"] = client.cancel(timeout=5)

    try:
        result = client.send_prompt("hi", timeout=5, on_event=on_event)
        assert cancelled["result"] == {}  # documented empty cancel result
        assert result == {"status": "cancelled"}  # peer's verbatim terminal value
        assert client.pending == {}
    finally:
        client.close()


def test_create_session_stays_prepared_and_sends_nothing(tmp_path) -> None:
    """G6: no Wire session-create method exists → nothing is sent and no
    sessionId is fabricated."""
    client = launch_client(tmp_path, "silent")
    try:
        prepared = client.create_session(timeout=5)
        assert prepared["status"] == "prepared"
        assert prepared["session"] is None
        assert prepared["method"] is None
        assert client.pending == {}
    finally:
        client.close()
    assert client.stderr_tail() == "recv=0 replies=0"


# -- counter-examples --------------------------------------------------------


def test_prompt_error_is_typed_with_code_and_raw_kept(tmp_path) -> None:
    """Wire's -32001 'LLM is not set' surfaces typed; nothing retried."""
    client = launch_client(tmp_path, "prompt-error")
    try:
        with pytest.raises(KimiRpcError) as excinfo:
            client.send_prompt("hi", timeout=5)
        assert excinfo.value.remote_code == -32001
        assert "LLM is not set" in str(excinfo.value)
        assert excinfo.value.raw_error == {"code": -32001, "message": "LLM is not set"}
        assert client.pending == {}  # negative receipt resolved the attempt
    finally:
        client.close()


def test_launch_requires_wire_entry_before_spawn(tmp_path, monkeypatch) -> None:
    """G1/attack-3: a Rust-style argv without `--wire` is refused before any
    process is spawned; no substitution is attempted."""
    def explode(*args, **kwargs):
        raise AssertionError("must not spawn for a refused launch spec")

    monkeypatch.setattr("subprocess.Popen", explode)
    spec = LaunchSpec.build(
        [sys.executable, "kimi-agent"], home=str(tmp_path / "h"), cwd=str(tmp_path)
    )
    with pytest.raises(ValueError) as excinfo:
        KimiWireClient.launch(spec)
    assert "--wire" in str(excinfo.value)


def test_launch_refuses_auto_approve_flags_before_spawn(tmp_path, monkeypatch) -> None:
    """SAFETY: --yolo/--afk launch flags are refused before any process."""
    def explode(*args, **kwargs):
        raise AssertionError("must not spawn for a refused launch spec")

    monkeypatch.setattr("subprocess.Popen", explode)
    spec = LaunchSpec.build(
        [sys.executable, "--wire", "--yolo"], home=str(tmp_path / "h"), cwd=str(tmp_path)
    )
    with pytest.raises(ValueError) as excinfo:
        KimiWireClient.launch(spec)
    assert "--yolo" in str(excinfo.value)


def test_close_then_use_is_channel_closed(tmp_path) -> None:
    """G6/G8: close() reaps this client's owned fake peer only."""
    client = launch_client(tmp_path, "initialize")
    try:
        assert client.initialize(timeout=5)["handshake"] == "initialized"
    finally:
        client.close()
    with pytest.raises(ChannelClosed):
        client.command("prompt", timeout=2, user_input="hi")


def test_close_releases_only_owned_process(tmp_path) -> None:
    """G8: a second client's channel stays functional after the first closes."""
    kept = launch_client(tmp_path, "initialize")
    released = launch_client(tmp_path, "initialize")
    try:
        assert released.initialize(timeout=5)["server_reported_version"] == "1.10"
        released.close()
        assert kept.initialize(timeout=5)["version_match"] is True
    finally:
        kept.close()


def test_reply_to_unknown_request_id_refuses_to_fabricate_identity(tmp_path) -> None:
    """The client never invents a payload identity for a frame it never saw."""
    client = launch_client(tmp_path, "initialize")
    try:
        with pytest.raises(ValueError):
            client.reply_approval("never-seen", "approve")
    finally:
        client.close()
