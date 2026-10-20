"""One-shot token binding of the loopback control channel (counterexamples).

The token is minted per bridge and delivered only through the launched
Pi process's environment (server-compat bridge-token precedent). What the
gate must refuse: no token, a wrong token, a replayed token (same token a
second time - even after the first peer vanished), a second concurrent
hello while bound, and a wrong protocol version. Every refusal is
counted and never registers a channel.
"""
from __future__ import annotations

import copy

import pytest

from fake_pi_extension import FakePiExtension


def _hello(peer, **overrides):
    frame = {"type": "hello", "proto": 1,
             "token": peer.env["ORDESSA_PI_BRIDGE_TOKEN"], "pid": 1}
    frame.update(overrides)
    peer.send_raw(frame)
    return peer.read()


def test_missing_token_is_refused_and_nothing_binds(live):
    env = copy.deepcopy(live.server.extension_env())
    env["ORDESSA_PI_BRIDGE_TOKEN"] = ""
    peer = FakePiExtension.raw(env)
    response = _hello(peer, token="")
    assert response["type"] == "error"
    assert response["code"] == "PERMISSION_REFUSED"
    assert live.server.state.bound is False
    assert live.server.state.hellos_refused == 1


def test_wrong_token_is_refused(live):
    peer = FakePiExtension.raw(live.server.extension_env())
    response = _hello(peer, token="0" * 32)
    assert response["type"] == "error"
    assert "PERMISSION_REFUSED" in response["code"]
    assert live.server.state.bound is False
    assert live.server.state.calls_forwarded == 0


def test_token_is_one_shot_even_after_the_peer_vanishes(live):
    first = FakePiExtension(live.server.extension_env())
    first.start()
    first.close()
    import time
    deadline = time.monotonic() + 2.0
    while live.server.state.bound and time.monotonic() < deadline:
        time.sleep(0.02)
    assert live.server.state.bound is False, \
        "a vanished peer must clear the live-channel flag (cleanup, no half-open)"
    assert live.server.state.token_consumed is True, \
        "but the token stays spent: disconnect never re-arms the binding"
    # the honest extension left; the token was spent. A re-connect with the
    # SAME (leaked-by-environment) token must never re-bind the channel.
    second = FakePiExtension.raw(live.server.extension_env())
    response = _hello(second)
    assert response["type"] == "error"
    assert "one-shot" in response["reason"] or live.server.state.bound is False
    assert response["code"] == "PERMISSION_REFUSED"
    assert live.server.state.bound is False


def test_second_hello_on_a_live_channel_is_refused(live):
    first = FakePiExtension(live.server.extension_env())
    first.start()
    rival = FakePiExtension.raw(live.server.extension_env())
    response = _hello(rival)
    assert response["type"] == "error"
    assert live.server.state.hellos_accepted == 1, \
        "exactly one bound channel; the rival never registered"


def test_wrong_protocol_and_non_hello_first_frame_are_refused(live):
    peer = FakePiExtension.raw(live.server.extension_env())
    assert _hello(peer, proto=99)["type"] == "error"
    stranger = FakePiExtension.raw(live.server.extension_env())
    stranger.send_raw({"type": "call", "id": "x", "tool": "echo", "params": {}})
    assert stranger.read()["type"] == "error"
    assert live.server.state.bound is False


def test_malformed_frame_drops_the_channel(live):
    peer = FakePiExtension(live.server.extension_env())
    peer.start()
    peer.send_text("not json at all\n")
    assert peer.read() is None, "a malformed frame must close the channel, " \
                                "not answer and keep serving"
    assert any("malformed" in reason for reason in
               live.server.state.refusal_reasons)


def test_oversized_frame_is_never_parsed(live):
    peer = FakePiExtension(live.server.extension_env())
    peer.start()
    peer.send_text("[" + "1," * 600_000)  # > 1 MiB, no newline
    assert peer.read() is None
    assert live.server.state.calls_forwarded == 0


def test_extension_env_is_loopback_bound(live):
    env = live.server.extension_env()
    assert env["ORDESSA_PI_BRIDGE_HOST"] == "127.0.0.1"
    assert env["ORDESSA_PI_BRIDGE_PORT"] == str(live.server.port)
    assert len(env["ORDESSA_PI_BRIDGE_TOKEN"]) >= 16
