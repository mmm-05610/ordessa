"""Close semantics of the bridge server: teardown is once-effective, idempotent,
and after it no frame flows anywhere (non-loopback unreachable, port gone).
"""
from __future__ import annotations

import socket

from fake_pi_extension import FakePiExtension


def test_close_drops_the_channel_and_refuses_further_calls(live):
    peer = FakePiExtension(live.server.extension_env())
    peer.start()
    outcome = live.server.close()
    assert outcome["replayed"] is False
    assert live.server.state.closed is True
    assert live.server.state.bound is False
    # the bound peer sees EOF, not a silent half-open channel
    assert peer.read() is None
    # the listener is gone: a fresh channel cannot even reach the gate
    try:
        socket.create_connection(("127.0.0.1", live.server.port), timeout=2.0)
    except ConnectionRefusedError:
        pass
    else:
        raise AssertionError("a closed bridge server must not accept new channels")


def test_close_is_idempotent_and_releases_the_port(live):
    port = live.server.port
    live.server.close()
    replayed = live.server.close()
    assert replayed["replayed"] is True
    # the listening socket is gone: binding the same loopback port is free again
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


def test_close_refuses_calls_mid_flight_after_teardown(live):
    peer = FakePiExtension(live.server.extension_env())
    peer.start()
    live.server.close()
    peer.send_raw({"type": "call", "id": "z", "tool": "echo", "params": {}})
    assert peer.read() is None, "no result may be produced by a closed bridge"
    assert live.server.state.calls_forwarded == 0


def test_non_loopback_listen_is_structurally_refused(tmp_path, live):
    from backend.managed.pi_bridge import PiBridgeServer
    import pytest
    from backend.errors import McpError
    with pytest.raises(McpError) as refused:
        PiBridgeServer(live.server.bridge, host="0.0.0.0")
    assert refused.value.code == "MCP_TRANSPORT_UNSUPPORTED"
