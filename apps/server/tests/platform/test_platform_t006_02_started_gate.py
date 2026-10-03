"""026 T006-02 (test half, first step): the wire round gate.

One composed Server answers business wire/1 methods only for a started round.
Activation populates the method registry at composition time, so a runtime
that is built but never started (or one that has been stopped) used to answer
fabricated empty reads from domains with no live round behind them — the hole
the H slice measured on the default composition. The gate in
`WireService.dispatch` refuses every registered method except the host's
discovery face (`server.hello`) while ``runtime.started`` is False, with an
existing wire family and the internal code ``ROUND_NOT_STARTED`` in details —
no new top-level error face.

Every fixture here is controlled and in-process: ``tmp_path`` data roots,
``fastapi.testclient.TestClient``, no model call, no network and no real data.

Scenarios pinned by this file:

* positive (missing condition) — a never-started default composition refuses
  ``workspaces.list`` and ``sessions.list`` typed (``INVALID_REQUEST`` family,
  ``details.internalCode == "ROUND_NOT_STARTED"``) through BOTH the local
  dispatch and the HTTP entry, while ``server.hello`` stays answerable on both
  (discovery is how a client learns the Server exists at all);
* positive — after ``start()`` the same methods answer the honest empty reads;
* counterexample — after ``start()`` → ``stop()`` the business rows are
  unregistered by shutdown, so the refusal is the pinned T006-05
  unknown-method answer (the round gate adds nothing on top of it), and
  discovery stops advertising the business rows exactly as pinned there;
* counterexample — the transport's stream mounts carry the same gate: an
  event-stream or ACP channel attach against a never-started runtime is
  closed typed (4400 ``ROUND_NOT_STARTED``) instead of reaching the live
  round's ports.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app
from ordessa_server.wire.errors import WireError

from server_plugin_api.wire_errors import FAMILIES

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}
LIST_PARAMS = {"includeArchived": False}
BUSINESS_METHODS = ("workspaces.list", "sessions.list")


def _post_wire(client: TestClient, token: str, method: str, params: dict,
               request_id: str = "t006-02"):
    return client.post(
        f"/wire/v1/{method}",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )


def _assert_round_gate_refusal(error: WireError) -> None:
    """The typed round-gate answer: an existing family, the internal code."""
    assert error.family in FAMILIES
    assert error.family == "INVALID_REQUEST"
    assert error.details.get("internalCode") == "ROUND_NOT_STARTED"


def test_unstarted_default_round_refuses_business_methods_and_keeps_discovery(
        tmp_path):
    """Missing condition (never started): no round, no fabricated empty reads.

    The default composition activates its plugins at ``build_runtime`` time,
    so every business row is registered before ``start()``. The gate must
    refuse the registered business methods — locally and through the HTTP
    entry (TestClient runs WITHOUT a lifespan here, so start() is never
    called) — while ``server.hello`` answers on both entries.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        assert runtime.started is False
        # The rows exist (activation composed them); the round did not start.
        assert runtime.wire._registry.lookup("workspaces.list") is not None
        assert runtime.wire._registry.lookup("sessions.list") is not None
        for method in BUSINESS_METHODS:
            with pytest.raises(WireError) as refused:
                runtime.wire.dispatch(method, dict(LIST_PARAMS))
            _assert_round_gate_refusal(refused.value)

        # The discovery face stays open through the same dispatch path.
        hello = runtime.wire.dispatch("server.hello", dict(HELLO))
        assert hello["protocolVersion"] == "wire/1"
        assert hello["capabilities"], "discovery must still declare the rows"

        # The same refusals and the same open discovery through the HTTP entry
        # of the never-started runtime.
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        for method in BUSINESS_METHODS:
            answer = _post_wire(client, runtime.token, method, dict(LIST_PARAMS))
            assert answer.status_code == 200, answer.text
            error = answer.json()["error"]
            assert error["code"] == "INVALID_REQUEST"
            assert error["details"]["internalCode"] == "ROUND_NOT_STARTED"
        http_hello = _post_wire(client, runtime.token, "server.hello", dict(HELLO))
        assert http_hello.status_code == 200, http_hello.text
        assert http_hello.json()["result"]["protocolVersion"] == "wire/1"
        assert runtime.started is False
    finally:
        runtime.stop()


def test_started_round_answers_the_same_business_methods(tmp_path):
    """Positive: start() opens the gate and the methods answer honestly.

    The same methods the unstarted round refused now return the live round's
    empty reads — the refusal above was the lifecycle state, not a permanent
    property of the methods.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        runtime.start()
        assert runtime.started is True
        assert runtime.wire.dispatch("workspaces.list", dict(LIST_PARAMS)) == {
            "items": [], "nextCursor": None}
        assert runtime.wire.dispatch("sessions.list", dict(LIST_PARAMS)) == {
            "items": [], "nextCursor": None}
        assert runtime.wire.dispatch("server.hello", dict(HELLO))["protocolVersion"] == "wire/1"
    finally:
        runtime.stop()


def test_stopped_round_refusal_matches_the_pinned_unknown_method_answer(tmp_path):
    """Counterexample (round ended): the pinned T006-05 semantics hold.

    After ``start()`` → ``stop()`` the disposal unregisters the business rows,
    so the refusal is the existence refusal those tests pin — the round gate
    must not have replaced it with a different answer. Discovery stops
    advertising the business rows, exactly as pinned.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        runtime.start()
        assert runtime.wire.dispatch("workspaces.list", dict(LIST_PARAMS)) == {
            "items": [], "nextCursor": None}
        runtime.stop()
        assert runtime.started is False
        assert runtime.wire._registry.lookup("workspaces.list") is None
        with pytest.raises(WireError) as refused:
            runtime.wire.dispatch("workspaces.list", dict(LIST_PARAMS))
        assert refused.value.family in FAMILIES
        assert refused.value.family == "INVALID_REQUEST"
        assert "is not a wire/1 method" in refused.value.message
        capabilities = {entry["id"] for entry in runtime.wire.hello(HELLO)["capabilities"]}
        assert capabilities == {"server.hello"}
    finally:
        runtime.stop()


def test_stream_mounts_carry_the_same_round_gate(tmp_path):
    """Counterexample: a never-started runtime serves no stream attach.

    Both stream mounts resolve their business port against the activation
    round, which exists from composition time — so an attach before start()
    must be closed typed by the same gate, not allowed to reach the ports.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        assert runtime.started is False
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        # Explicit headers on a websocket_connect replace the client defaults,
        # so the loopback Host the transport checks must be spelled here too
        # (the same shape the live event-stream test in test_wire_v1 uses).
        auth = {"Authorization": f"Bearer {runtime.token}", "Host": "127.0.0.1"}
        for path in ("/wire/v1/event-stream?sessionId=s1",
                     "/wire/v1/acp-channel/connection-1"):
            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect(path, headers=auth):
                    pytest.fail("a never-started runtime accepted a stream attach")
            assert refused.value.code == 4400
            assert refused.value.reason == "ROUND_NOT_STARTED"
    finally:
        runtime.stop()
