"""Gate refusals forward **zero** work (verification.md counterexample style).

Two distinct refusal places are proven separately:

* the bridge-level binding gate (unregistered tool, catalog drift after
  binding, descriptor/observation mismatch at bind time) refuses before
  :meth:`ManagedSessionManager.call_tool` is even entered;
* the manager-level double gate (PermissionAuthority refusal) still runs
  unchanged below the bridge - the bridge adds no second permission
  model - and the managed client records zero executed calls.
"""
from __future__ import annotations

import pytest

from backend.errors import McpError
from fake_pi_extension import FakePiExtension
from managed_helpers import TOOLS_TWO, DENYING


def _bound_peer(live):
    peer = FakePiExtension(live.server.extension_env())
    peer.start()
    return peer


def test_unregistered_tool_refused_zero_forwarded(live, monkeypatch):
    peer = _bound_peer(live)
    entered = []
    real_call_tool = live.manager.call_tool

    def spy(**kwargs):
        entered.append(kwargs["tool_name"])
        return real_call_tool(**kwargs)

    monkeypatch.setattr(type(live.manager), "call_tool",
                        lambda self, **kw: spy(**kw), raising=True)
    response = peer.call("list", {})
    assert response["ok"] is False
    assert response["code"] == "MCP_TOOL_NOT_APPROVED"
    assert entered == [], "'list' is in the catalog but not in the bridge's " \
                          "registered subset: the manager door was never entered"
    client = live.harness.factory.produced[-1]
    assert client.executed_calls == []
    assert live.server.state.calls_refused == 1
    assert live.server.state.calls_forwarded == 0


def test_authority_refusal_reaches_the_client_zero_times(live):
    # swap in a DENYING authority under the SAME bound bridge: the refusal
    # must come from the unchanged double gate inside the manager, before
    # the managed client sees anything.
    harness = live.harness
    live.manager.permission_authority = DENYING()
    peer = _bound_peer(live)
    response = peer.call("echo", {"text": "no"})
    assert response["ok"] is False
    assert response["code"] == "PERMISSION_REFUSED"
    client = harness.factory.produced[-1]
    assert client.executed_calls == [], "the double gate refuses before a " \
                                        "single frame reaches the managed client"
    assert live.server.state.calls_refused == 1


def test_catalog_drift_after_binding_refuses_every_call(live):
    peer = _bound_peer(live)
    client = live.harness.factory.produced[-1]
    # the live server's catalog drifts (a tool joins) and is re-observed:
    client.tools = [dict(tool) for tool in TOOLS_TWO] + [
        {"name": "extra", "inputSchema": {"type": "object"}}]
    live.manager.observe_catalog(caller=live.caller, lease_id=live.lease_id)
    response = peer.call("echo", {"text": "stale"})
    assert response["ok"] is False
    assert response["code"] == "CATALOG_CHANGED"
    assert client.executed_calls == [], "drift must not be served from memory"


def test_bind_refuses_descriptor_that_differs_from_observation(live):
    from backend.managed.pi_bridge import bind_bridge
    drifted = [{"name": "echo",
                "inputSchema": {"type": "object",
                                "properties": {"text": {"type": "number"}}}}]
    with pytest.raises(McpError) as refused:
        bind_bridge(manager=live.manager, caller=live.caller,
                    owner_id=live.owner_id, lease_id=live.lease_id,
                    tools=drifted, start=False)
    assert refused.value.code == "MCP_VERIFICATION_MISMATCH"


def test_bind_refuses_tool_outside_the_approved_subset(live):
    from backend.managed.pi_bridge import bind_bridge
    with pytest.raises(McpError) as refused:
        bind_bridge(manager=live.manager, caller=live.caller,
                    owner_id=live.owner_id, lease_id=live.lease_id,
                    tools=[dict(t) for t in TOOLS_TWO], start=False)
    assert refused.value.code == "MCP_TOOL_NOT_APPROVED"


def test_bind_needs_a_live_observation_not_a_stored_definition(live):
    from backend.managed.pi_bridge import bind_bridge
    harness = live.harness
    # a second definition installed but never connected/observed:
    revision = harness.install_remote(definition_id="srv-quiet")
    manager = harness.manager(authority=DENYING())
    quiet_lease = manager.open_lease(
        caller=harness.caller(session="sess-quiet"), server_scope="scope-1",
        definition_id="srv-quiet", revision=revision)
    with pytest.raises(McpError) as refused:
        bind_bridge(manager=manager, caller=harness.caller(session="sess-quiet"),
                    owner_id=quiet_lease.owner_id, lease_id=quiet_lease.lease_id,
                    tools=[{"name": "echo", "inputSchema": {}}], start=False)
    assert refused.value.code == "MCP_NOT_CONNECTED"
