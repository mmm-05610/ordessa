"""L2 roundtrip of the Pi managed-lane bridge over a real loopback channel.

The peer is :class:`fake_pi_extension.FakePiExtension` - a Python mirror
of the extension's channel behaviour (explicitly NOT a loaded Pi
process; the real-CLI evidence is reports/t10-pi-probe.md). These tests
prove the *Python side* contract: one-shot bound hello, a ready frame
that carries ONLY the Server-validated subset, and call frames that run
through the manager's double gate into the managed client.
"""
from __future__ import annotations

from fake_pi_extension import FakePiExtension


def test_hello_ready_binds_only_the_approved_subset(live):
    peer = FakePiExtension(live.server.extension_env())
    frame = peer.start()
    assert frame["bridgeId"] == "pib-test"
    assert peer.tools == ["echo"], "the 'list' tool exists in the catalog but " \
                                   "is not in the approved subset - it may never be registered"
    assert live.server.state.bound is True
    assert live.server.state.hellos_accepted == 1
    ready_tool = frame["tools"][0]
    assert ready_tool["name"] == "echo"
    assert ready_tool["inputSchema"]["properties"]["text"]["type"] == "string"


def test_call_roundtrip_executes_through_the_managed_client(live):
    peer = FakePiExtension(live.server.extension_env())
    peer.start()
    response = peer.call("echo", {"text": "hello pi lane"})
    assert response["ok"] is True
    result = response["result"]
    assert result["tool"] == "echo"
    assert "hello pi lane" not in str(result), "the witness shape carries no " \
        "argument bodies back over the channel beyond the client's own result"
    client = live.harness.factory.produced[-1]
    assert client.executed_calls == [("echo", {"text": "hello pi lane"})]
    assert live.server.state.calls_forwarded == 1
    assert live.server.state.calls_refused == 0


def test_authority_decision_is_recorded_before_the_client_runs(live):
    peer = FakePiExtension(live.server.extension_env())
    peer.start()
    peer.call("echo", {"text": "x"})
    authority = live.manager.permission_authority
    assert len(authority.seen) == 1, "the SAME double-gate seam as every " \
        "managed call: catalog gate first, authority second (contracts §4)"
    seen = authority.seen[0]
    assert seen["tool_name"] == "echo"
    assert seen["principal"] == "u-a" and seen["session_ref"] == "sess-a"
    assert seen["lease_id"] == live.lease_id


def test_ready_frame_carries_no_credentials(live):
    peer = FakePiExtension(live.server.extension_env())
    frame = peer.start()
    blob = repr(frame)
    assert live.server.token not in blob
    for forbidden in ("secretRef", "credential", "apiKey", "token"):
        assert forbidden not in blob.lower(), \
            f"the extension process is handed descriptors, never credentials ({forbidden})"
