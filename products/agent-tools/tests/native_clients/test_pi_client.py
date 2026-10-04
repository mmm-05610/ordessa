"""Counter-example and positive tests for the pi native RPC consumer client.

**Fake upstream, fixture level (L1)** — every test runs against a scripted
fake ``pi`` peer process that reproduces the record shapes pinned in N003
(strict JSONL, not JSON-RPC 2.0). These tests prove the consumer's framing/
identity/typed-failure behaviour only; they are NOT real-process L2 evidence
(``pi`` binary is never executed here — real L2 is the main executor's job)
and they must not be counted as upstream compatibility.

Gates covered (specs/030-native-harness-expansion/acceptance.md):

- G4  unknown/extension records preserved verbatim; same-id extension-UI
      replies; parse-error records (no id) kept in the event stream.
- G5  framing stays in the frozen transport; stderr never parsed as protocol.
- G6  prompt receipt is not completion; ``handled`` means no settle wait;
      no fabricated sessionId; cancel returns the raw abort response.
- G11 no re-send: timeout/lost receipt keeps the ledger entry; the peer saw
      exactly one write per request.
- Cross-node isolation: two clients' request ids / streams never cross.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ordessa_agent_tools.native_clients import LaunchSpec, ProcessChannel, RequestTimeout
from ordessa_agent_tools.native_clients.pi import (
    FAMILY_ID,
    KNOWN_COMMANDS,
    PiCommandError,
    PiRpcClient,
    describe,
    rpc_launch_argv,
)


def _send(obj, stream="out") -> None:
    if stream == "out":
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()
    else:
        sys.stderr.write(json.dumps(obj) + "\n")
        sys.stderr.flush()


def _read():
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(0)
    return json.loads(line)


# -- fake pi peer modes (L1 fixture; record shapes pinned by N003) ------------

PEER = textwrap.dedent(
    r"""
    import json, sys
    mode = sys.argv[1]

    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def read():
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(0)
        return json.loads(line)

    if mode == "state":  # get_state handshake round trip
        msg = read()
        assert msg["type"] == "get_state"
        send({"id": msg["id"], "type": "response", "command": "get_state",
              "success": True, "data": {"model": "fake-model",
                                        "steeringMode": "all"}})
    elif mode == "prompt-started":  # receipt then event stream to settled
        msg = read()
        assert msg["type"] == "prompt" and "message" in msg
        send({"id": msg["id"], "type": "response", "command": "prompt",
              "success": True, "data": {"disposition": "started"}})
        send({"type": "message_update", "role": "assistant", "text": "hi"})
        send({"type": "weird_future_event", "payload": {"q": [1, 2]}})
        send({"type": "agent_end", "stop": "exit"})
        send({"type": "agent_settled"})
    elif mode == "prompt-error":  # success:false with error text
        msg = read()
        send({"id": msg["id"], "type": "response", "command": "prompt",
              "success": False, "error": "no provider configured"})
    elif mode == "prompt-handled":  # handled: no run, settle must not be awaited
        msg = read()
        send({"id": msg["id"], "type": "response", "command": "prompt",
              "success": True, "data": {"disposition": "handled"}})
        while True:  # keep reading; emits nothing else
            read()
    elif mode == "prompt-silent":  # written but never answered
        recv = 0
        prompts = 0
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            recv += 1
            if json.loads(line).get("type") == "prompt":
                prompts += 1
        sys.stderr.write("recv=%d prompts=%d" % (recv, prompts))
        sys.stderr.flush()
    elif mode == "parse-error":  # peer-sent parse-error record carries NO id
        decoy_done = False
        while True:  # keep serving round trips after the decoy
            line = sys.stdin.readline()
            if not line:
                break
            msg = json.loads(line)
            if not decoy_done:
                # decoys arrive WHILE get_state is being waited on
                send({"type": "response", "command": "parse", "success": False,
                      "error": "invalid json 1f 0x"})
                send({"type": "compaction_start", "reason": "manual"})
                decoy_done = True
            send({"id": msg["id"], "type": "response", "command": msg["type"],
                  "success": True, "data": {}})
    elif mode == "extension-ui":  # bidirectional extension UI record
        msg = read()
        send({"id": "ext-77", "type": "extension_ui_request",
              "action": "approval", "prompt": "allow run?"})
        reply = read()  # the same-id extension_ui_response
        send({"type": "extension_ui_ack", "reply": reply})
        # echo the command receipt only after the UI round trip finished
        data = ({"disposition": "started"} if msg["type"] == "prompt" else {})
        send({"id": msg["id"], "type": "response", "command": msg["type"],
              "success": True, "data": data})
        send({"type": "agent_settled"})
    elif mode == "abort":  # cancel returns raw abort response
        first = read()
        if first["type"] == "clear_queue":
            send({"id": first["id"], "type": "response", "command": "clear_queue",
                  "success": True, "data": {"cleared": 2}})
            second = read()
        else:
            second = first
        send({"id": second["id"], "type": "response", "command": "abort",
              "success": True, "data": {"aborted": True}})
    elif mode == "session":  # new_session returns native data
        msg = read()
        send({"id": msg["id"], "type": "response", "command": "new_session",
              "success": True, "data": {"sessionId": "sess-native-1"}})
    elif mode == "cross":  # id-namespace isolation: decoys cannot steal receipts
        a = read()
        send({"id": a["id"], "type": "response", "command": a["type"],
              "success": True, "data": {"for": a["id"]}})
        send({"type": "response", "command": "parse", "success": False,
              "error": "unparseable line"})  # decoy: no id at all (G4 shape)
        send({"id": "other-node-req-9", "type": "response", "command": "steer",
              "success": True, "data": {"for": "other-node-req-9"}})  # foreign id
        b = read()
        send({"id": b["id"], "type": "response", "command": b["type"],
              "success": True, "data": {"for": b["id"]}})
    """
)


def launch_client(tmp_path, mode: str) -> PiRpcClient:
    script = tmp_path / "fake_pi_peer.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build(
        [sys.executable, str(script), mode],
        home=str(tmp_path / "home"),
        cwd=str(tmp_path),
    )
    return PiRpcClient.launch(spec, name=f"fake-pi-{mode}")


# -- positive paths ------------------------------------------------------------


def test_describe_has_no_runtime_ready_claim() -> None:
    """Channel facts are static; describe() never asserts runtimeReady."""
    facts = describe()
    assert facts["familyId"] == FAMILY_ID == "pi"
    assert facts["channel"] == "rpc-jsonl"
    assert facts["protocol"] == "pi-rpc/1"
    assert "runtimeReady" not in json.dumps(facts)
    assert "initialize" not in facts["knownCommands"]  # no negotiation invented
    assert "get_state" in facts["knownCommands"]
    assert "prompt" in facts["knownCommands"]
    assert len(KNOWN_COMMANDS) == 33


def test_rpc_launch_argv_plan_matches_pinned_facts() -> None:
    """Launch plan stays deliberative (pure data) and uses documented flags."""
    assert rpc_launch_argv() == ("pi", "--mode", "rpc", "--no-session")
    assert rpc_launch_argv(offline=True, minimal=True)[-6:] == (
        "--offline",
        "--no-extensions",
        "--no-skills",
        "--no-context-files",
        "--no-prompt-templates",
        "--no-approve",
    )


def test_initialize_is_get_state_round_trip(tmp_path) -> None:
    """Handshake = documented get_state data, verbatim; nothing invented."""
    client = launch_client(tmp_path, "state")
    try:
        state = client.initialize(timeout=5)
        assert state == {"model": "fake-model", "steeringMode": "all"}
        assert client.pending == {}  # receipt resolved, ledger clean
    finally:
        client.close()


def test_send_prompt_returns_started_receipt_verbatim(tmp_path) -> None:
    """The receipt is NOT completion: disposition 'started' returned as-is."""
    client = launch_client(tmp_path, "prompt-started")
    try:
        receipt = client.send_prompt("hi", timeout=5)
        assert receipt == {"disposition": "started"}
        assert "disposition" in receipt  # raw data record, not a helper value
        settled = client.wait_settled(timeout=5)
        assert settled["type"] == "agent_settled"
        types = [e["type"] for e in client.events()]
        # the receipt is a response, the rest are session events in order
        assert "message_update" in types and "agent_end" in types
    finally:
        client.close()


def test_unknown_event_type_preserved_verbatim(tmp_path) -> None:
    """G4: a future/unknown session event keeps native identity, is not
    dropped or rewritten."""
    client = launch_client(tmp_path, "prompt-started")
    try:
        client.send_prompt("hi", timeout=5)
        client.wait_settled(timeout=5)
        unknown = [e for e in client.events() if e.get("type") == "weird_future_event"]
        assert len(unknown) == 1
        assert unknown[0]["payload"] == {"q": [1, 2]}  # raw fields intact
    finally:
        client.close()


def test_extension_ui_request_replied_with_same_id(tmp_path) -> None:
    """G4: bidirectional extension-UI record answered on the SAME id; the
    reply produced no regular response (it never resolves a command)."""
    client = launch_client(tmp_path, "extension-ui")
    seen = []

    def on_event(raw) -> None:
        if raw.get("type") == "extension_ui_request":
            seen.append(raw)
            client.reply_extension_ui(
                raw["id"], {"action": "respond", "text": "pending"}
            )

    try:
        # prompt is the in-flight command when the extension-UI request
        # arrives; its SAME-id reply goes out while it is being waited on.
        # peer sends the prompt receipt only after the UI round trip completes.
        receipt = client.send_prompt("x", timeout=5, on_event=on_event)
        assert receipt == {"disposition": "started"}  # UI reply made no receipt
        assert seen and seen[0]["id"] == "ext-77"
        assert seen[0]["action"] == "approval"
        ack = [e for e in client.events() if e.get("type") == "extension_ui_ack"]
        assert ack and ack[0]["reply"]["id"] == "ext-77"  # same id echoed back
        assert ack[0]["reply"]["text"] == "pending"
    finally:
        client.close()


def test_create_session_returns_prepared_with_native_data(tmp_path) -> None:
    """G6: session stays 'prepared'; the sessionId inside data (if any) is
    the peer's native value, never fabricated by this client."""
    client = launch_client(tmp_path, "session")
    try:
        prepared = client.create_session(timeout=5)
        assert prepared["status"] == "prepared"
        assert prepared["command"] == "new_session"
        assert prepared["data"]["sessionId"] == "sess-native-1"  # peer-native
    finally:
        client.close()


def test_cancel_returns_raw_abort_response(tmp_path) -> None:
    """G6: cancel evidence is the raw abort success record — never 'completed'."""
    client = launch_client(tmp_path, "abort")
    try:
        raw = client.cancel(timeout=5, clear_queue=True)
        assert raw["command"] == "abort"
        assert raw["success"] is True and raw["data"] == {"aborted": True}
        assert raw["type"] == "response"
    finally:
        client.close()


# -- counter-examples --------------------------------------------------------


def test_success_false_raises_pi_command_error_with_verbatim_text(tmp_path) -> None:
    """G4/G6: a success:false receipt surfaces as typed PiCommandError with
    the peer's error text kept verbatim; no retry is attempted."""
    client = launch_client(tmp_path, "prompt-error")
    try:
        with pytest.raises(PiCommandError) as excinfo:
            client.send_prompt("hi", timeout=5)
        assert excinfo.value.error == "no provider configured"
        assert excinfo.value.command == "prompt"
        assert excinfo.value.raw["success"] is False
        assert excinfo.value.code == "PI_COMMAND_ERROR"
        assert client.pending == {}  # receipt (negative) resolved it
    finally:
        client.close()


def test_handled_disposition_does_not_wait_for_settled(tmp_path) -> None:
    """G6: disposition 'handled' means no run started, so wait_settled must
    return immediately with the no-run marker — no settle boundary exists
    and no completion is faked."""
    client = launch_client(tmp_path, "prompt-handled")
    try:
        receipt = client.send_prompt("hi", timeout=5)
        assert receipt["disposition"] == "handled"
        marker = client.wait_settled(timeout=0.2)  # would time out if it waited
        assert marker["outcome"] == "no-run"
    finally:
        client.close()


def test_prompt_timeout_is_typed_and_never_resent(tmp_path) -> None:
    """G11: the prompt attempt is written exactly once; timeout surfaces as
    RequestTimeout and the pending entry stays (outcome unknown)."""
    client = launch_client(tmp_path, "prompt-silent")
    try:
        with pytest.raises(RequestTimeout) as excinfo:
            client.send_prompt("once", timeout=0.5)
        assert excinfo.value.method == "prompt"
        assert excinfo.value.code == "REQUEST_TIMEOUT"
        assert list(client.pending.values()) == ["prompt"]  # still unknown
        # the attempt is not retried: the event stream stayed empty
        assert len(client._events) == 0
    finally:
        exit_code = client.close()
        assert exit_code == 0  # owned process reaped by identity (G6/G8)
    # the peer counted its reads after stdin EOF (close waits for exit before
    # draining stderr): exactly one prompt was ever written — no retry (G11)
    assert "recv=1 prompts=1" in client.stderr_tail()


def test_parse_error_record_without_id_stays_in_event_stream(tmp_path) -> None:
    """G4: the peer's no-id parse-error response record is preserved verbatim
    in the event stream — never dropped, never mistaken for a command
    receipt (G6). pump() surfaces records that arrived off the request path."""
    client = launch_client(tmp_path, "parse-error")
    try:
        client.initialize(timeout=5)
        client.pump(timeout=0.5)
        records = [e for e in client.events() if e.get("type") == "response"]
        parse_errors = [
            r for r in records if r.get("command") == "parse" and "id" not in r
        ]
        assert len(parse_errors) == 1
        assert parse_errors[0]["error"] == "invalid json 1f 0x"
        assert parse_errors[0]["success"] is False
        # the idless record did not resolve or break the get_state receipt
        assert client.pending == {}
        assert client.initialize(timeout=5) == {}  # receipts keep working
        assert any(e.get("type") == "compaction_start" for e in client.events())
    finally:
        client.close()


def test_two_clients_ids_and_streams_do_not_cross(tmp_path) -> None:
    """G4/G6: two independent clients (two nodes) each keep their own
    request-id namespace — a no-id parse decoy and a foreign-id receipt on
    the same stream never steal or resolve the live request, and each
    client's id sequence stays its own (req-1, req-2...)."""
    alpha = launch_client(tmp_path, "cross")
    bravo = launch_client(tmp_path, "cross")
    try:
        results = {}

        def run(client, key):
            first = client.command("get_state", timeout=5)["data"]
            pump_count = client.pump(timeout=0.2)
            second = client.command("get_messages", timeout=5)["data"]
            results[key] = {
                "first": first,
                "second": second,
                "pump_count": pump_count,
                "events": [e.get("id") for e in client.events()
                           if e.get("type") == "response"],
            }

        for client, key in ((alpha, "alpha"), (bravo, "bravo")):
            run(client, key)
        for key, value in results.items():
            assert value["first"] == {"for": "req-1"}
            assert value["second"] == {"for": "req-2"}  # per-client seq, not shared
            # decoys preserved verbatim, never mistaken for a receipt (G4)
            assert value["pump_count"] == 2
            assert "other-node-req-9" in value["events"]
            assert alpha.pending == {} and bravo.pending == {}
        foreign = [e for e in alpha.events() if e.get("id") == "other-node-req-9"]
        assert foreign and foreign[0]["command"] == "steer"
    finally:
        alpha.close()
        bravo.close()


def test_close_releases_only_owned_process(tmp_path) -> None:
    """G6/G8: close() reaps this client's owned fake peer only; a second
    client's channel stays functional."""
    kept = launch_client(tmp_path, "state")
    released = launch_client(tmp_path, "state")
    try:
        assert released.initialize(timeout=5) is not None
        released.close()
        # the OTHER client still works — close released only its own process
        assert kept.initialize(timeout=5) == {"model": "fake-model",
                                              "steeringMode": "all"}
    finally:
        kept.close()


def test_l1_lost_receipt_marks_unknown_not_no_run(tmp_path) -> None:
    # G11 counter-example: a lost prompt receipt means the run MAY exist —
    # wait_settled must answer "unknown", never the fabricated "no-run".
    client = launch_client(tmp_path, "prompt-silent")
    try:
        with pytest.raises(RequestTimeout):
            client.send_prompt("hello", timeout=1)
        outcome = client.wait_settled(timeout=1)
        assert outcome["outcome"] == "unknown"
    finally:
        client.close()
