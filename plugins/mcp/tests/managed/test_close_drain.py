"""Close/drain: stop new calls -> bounded wait -> manifest -> release once.
Unloading with live leases answers busy (counterexample 9's first half)."""
from __future__ import annotations

import threading

import pytest

from backend.errors import MCP_CATALOG_MISSING, McpError
from backend.managed import MCP_LEASE_BUSY, MCP_NOT_CONNECTED
from managed_helpers import ALLOWING, SERVER_SCOPE, TOOLS_ONE


def _live(harness, *, tools=None, **faults):
    caller = harness.caller()
    revision = harness.install_remote()
    authority = ALLOWING()
    manager = harness.manager(authority=authority)
    harness.factory.set(caller.session_ref, "srv-a",
                        tools=tools or TOOLS_ONE, **faults)
    lease, _, client = harness.bring_up(manager, caller, "srv-a", revision)
    lease = harness.leases.get_lease(lease.lease_id, caller)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id,
                          tool_names=[t["name"] for t in (tools or TOOLS_ONE)])
    return manager, caller, lease, client, authority


def test_inflight_call_blocks_close_into_busy_then_retry_closes(harness):
    gate = threading.Event()
    started = threading.Event()
    manager, caller, lease, client, _ = _live(harness, call_gate=gate,
                                              call_started=started)
    outcome: dict = {}

    def _slow_call():
        try:
            outcome["ok"] = manager.call_tool(
                caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
                tool_name="echo", arguments={"text": "in flight"})
        except BaseException as exc:  # pragma: no cover - asserts below
            outcome["error"] = exc

    worker = threading.Thread(target=_slow_call)
    worker.start()
    assert started.wait(timeout=5.0), "the fake call never started"

    with pytest.raises(McpError) as exc:
        manager.close_lease(caller=caller, lease_id=lease.lease_id,
                            owner_id=lease.owner_id, drain_timeout=0.05)
    assert exc.value.code == MCP_LEASE_BUSY
    # the lease stays in closing (new calls already gated), nothing released
    assert harness.leases.get_lease(lease.lease_id, caller).state == "closing"
    assert client.close_count == 0

    facts = harness.leases.facts(lease.lease_id, caller)
    drain_facts = [f for f in facts if f["kind"] == "drain-timeout"]
    assert len(drain_facts) == 1
    manifest = drain_facts[0]["pending"]
    assert [m["tool"] for m in manifest] == ["echo"]
    assert manifest[0]["argsDigest"].startswith("sha256:")
    assert "in flight" not in str(drain_facts[0])  # body never booked

    # while draining, new calls are refused by the lease-state gate
    with pytest.raises(McpError) as exc2:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "new"})
    assert exc2.value.code == MCP_NOT_CONNECTED

    gate.set()
    worker.join(timeout=5.0)
    assert "ok" in outcome
    result = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id, drain_timeout=1.0)
    assert result["state"] == "closed"
    assert client.close_count == 1  # exactly one release, no leak


def test_close_stops_new_calls_before_the_drain_even_when_idle(harness):
    manager, caller, lease, client, _ = _live(harness)
    result = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert result["state"] == "closed" and client.close_count == 1
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={})
    assert exc.value.code == MCP_NOT_CONNECTED


def test_unload_with_active_lease_is_busy_until_owners_close(harness):
    manager, caller, lease, client, _ = _live(harness)
    with pytest.raises(McpError) as exc:
        manager.request_unload(reason="backend uninstall")
    assert exc.value.code == MCP_LEASE_BUSY
    assert lease.lease_id in exc.value.message  # ids are auditable, secrets are not
    manager.close_lease(caller=caller, lease_id=lease.lease_id,
                        owner_id=lease.owner_id)
    assert manager.request_unload(reason="backend uninstall")["unloadAllowed"] is True


def test_refused_lease_close_replays_without_a_client(harness):
    # no factory wired -> refused (confirmed); close is a no-op replay.
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager(factory=None)
    lease = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision)
    from backend.errors import McpError as _E
    from backend.managed import MCP_CLIENT_FACTORY_MISSING
    manager.plan_connection(caller=caller, lease_id=lease.lease_id)
    with pytest.raises(_E) as exc:
        manager.start_connection(caller=caller, lease_id=lease.lease_id)
    assert exc.value.code == MCP_CLIENT_FACTORY_MISSING
    assert harness.leases.get_lease(lease.lease_id, caller).state == "refused"
    result = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert result["replayed"] is True and result["state"] == "refused"


def test_definition_never_answers_list_tools_for_anyone(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    with pytest.raises(McpError) as exc:
        manager.list_tools_for_definition(caller=caller, server_scope=SERVER_SCOPE,
                                          definition_id="srv-a", revision=revision)
    assert exc.value.code == MCP_CATALOG_MISSING
    assert "not a connection" in exc.value.message
