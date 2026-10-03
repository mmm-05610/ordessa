"""The call gate: every tools/call must pass the lease-state gate and the
Permission authority - a Pi-extension-shaped caller has no other door, and
an absent authority fails closed (Q4: 实际工具调用必须等真实 Permissions 接线)."""
from __future__ import annotations

import pytest

from backend.errors import (
    McpError,
    PERMISSION_REFUSED,
    UNKNOWN_OUTCOME,
)
from backend.managed import MCP_NOT_CONNECTED
from backend.permissions import PERMISSION_AUTHORITY_ABSENT
from managed_helpers import ALLOWING, DENYING, SERVER_SCOPE, TOOLS_ONE


def _live(harness, *, authority=None, tools=None):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager(authority=authority)
    harness.factory.set(caller.session_ref, "srv-a", tools=tools or TOOLS_ONE)
    lease, _, client = harness.bring_up(manager, caller, "srv-a", revision)
    return manager, caller, harness.leases.get_lease(lease.lease_id, caller), client


def test_call_before_catalog_observed_is_refused_by_the_state_gate(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager(authority=ALLOWING())
    harness.factory.set("sess-a", "srv-a", tools=TOOLS_ONE)
    lease = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision)
    # even a "fully granted" caller cannot call a lease that never connected
    for stage in ("defined", "selected"):
        with pytest.raises(McpError) as exc:
            manager.call_tool(caller=caller, lease_id=lease.lease_id,
                              owner_id=lease.owner_id, tool_name="echo",
                              arguments={"text": "x"})
        assert exc.value.code == MCP_NOT_CONNECTED
        if stage == "defined":
            manager.plan_connection(caller=caller, lease_id=lease.lease_id)
    manager.start_connection(caller=caller, lease_id=lease.lease_id)
    with pytest.raises(McpError) as exc:  # connected but catalog NOT observed
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "x"})
    assert exc.value.code == MCP_NOT_CONNECTED
    client = harness.factory.produced[-1]
    assert client.executed_calls == []  # the server-side fake saw nothing


def test_no_permission_authority_means_no_call_reaches_the_client(harness):
    manager, caller, lease, client = _live(harness, authority=None)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "sneak"})
    # D5: the unified permission seam refuses an absent authority with the
    # typed PERMISSION_AUTHORITY_ABSENT (still fail-closed, still zero
    # frames to the client - backend.permissions is the single gate now)
    assert exc.value.code == PERMISSION_AUTHORITY_ABSENT
    assert client.executed_calls == []
    assert "no Permission authority is wired" in exc.value.message


def test_denying_authority_blocks_before_any_side_effect(harness):
    authority = DENYING()
    manager, caller, lease, client = _live(harness, authority=authority)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "nope"})
    assert exc.value.code == PERMISSION_REFUSED
    assert client.executed_calls == []
    decision = authority.seen[0]
    assert decision["tool_name"] == "echo"
    assert decision["args_digest"].startswith("sha256:")
    assert decision["policy_revision"] == "pol-1"
    assert "arguments" not in decision  # the authority sees a digest, not the body


def test_allowing_authority_runs_exactly_through_the_lease(harness):
    authority = ALLOWING()
    manager, caller, lease, client = _live(harness, authority=authority)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    result = manager.call_tool(caller=caller, lease_id=lease.lease_id,
                               owner_id=lease.owner_id, tool_name="echo",
                               arguments={"text": "go"})
    assert client.executed_calls == [("echo", {"text": "go"})]
    assert result["argsDigest"] == authority.seen[0]["args_digest"]
    facts = harness.leases.facts(lease.lease_id, caller)
    executed = [f for f in facts if f["kind"] == "tool-call-executed"]
    assert executed[0]["tool"] == "echo"
    assert "go" not in str(executed[0])  # only the digest is booked


def test_client_call_fault_becomes_unknown_without_auto_retry(harness):
    manager, caller, lease, client = _live(harness, authority=ALLOWING())
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    client.call_tool = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "x"})
    assert exc.value.code == UNKNOWN_OUTCOME
    kinds = [f["kind"] for f in harness.leases.facts(lease.lease_id, caller)]
    assert kinds.count("call-outcome-unknown") == 1
    # the lease itself is still catalog-observed - the call is not retried
    assert harness.leases.get_lease(lease.lease_id, caller).state == "catalog-observed"
