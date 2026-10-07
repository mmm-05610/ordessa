"""T10-INT-03: the dual-session cell - two sessions on ONE definition.

Requirements covered (dispatch 双会话格): independent leases (uniqueness
key contains the sessionRef; one fresh REAL client - one fresh fake-server
child - per lease, no pooling), different frozen toolSelection per session
(assignment rows at the session scope + per-lease approved subsets), a
close of A that does not touch B, a cross-session claim by B against A's
lease that dies at the visibility wall (MCP_LEASE_MISSING; A learns
nothing and B gets no door), and the unload counterexample: the backend
may not unload while a managed lease is live (MCP_LEASE_BUSY with the
honest manifest).

Server-side evidence: each session's own fake-server child keeps its own
call ledger (two witness files, two pids), so "independent" is not the
client's word - it is booked twice, apart.

Evidence ID: T10-INT-03.
"""
from __future__ import annotations

import os
import pytest
from backend.errors import (
    MCP_LEASE_BUSY,
    MCP_LEASE_MISSING,
    MCP_TOOL_NOT_APPROVED,
    McpError,
)
from integration_helpers import read_allow_intent, wire_q5


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_dual_session_independent_leases_and_close(stack, world):
    revision, state = stack.install_stdio("twinsrv", mode="normal")
    _adapter, authorizer = wire_q5(
        stack, world, intent=read_allow_intent(),
        tool_key_map={"echo": "read", "peek": "read"})
    mgr = stack.service.sessions

    caller_a = stack.caller(principal="user-1", session="session-1", generation=1)
    caller_b = stack.caller(principal="user-1", session="session-2", generation=1)
    lease_a, catalog_a = stack.bring_up(caller_a, "twinsrv", revision)
    lease_b, catalog_b = stack.bring_up(caller_b, "twinsrv", revision)

    # independence, server side: TWO children for ONE endpoint (no pooling)
    assert len(stack.child_pids(state)) == 2
    assert lease_a.lease_id != lease_b.lease_id
    assert catalog_a.catalog_digest == catalog_b.catalog_digest  # same tools

    # different frozen toolSelection per session (session-scope assignment)
    stack.assign_enable("twinsrv", catalog_digest=catalog_a.catalog_digest,
                        names=["echo"], principal="user-1",
                        scope_kind="session", scope_id="session-1")
    stack.assign_enable("twinsrv", catalog_digest=catalog_b.catalog_digest,
                        names=["peek"], principal="user-1",
                        scope_kind="session", scope_id="session-2")
    snap_a = stack.call("mcp.resolvePreview", serverScope="s1",
                        principal="user-1", sessionRef="session-1")
    snap_b = stack.call("mcp.resolvePreview", serverScope="s1",
                        principal="user-1", sessionRef="session-2")
    assert snap_a["snapshot"]["allowedToolNames"] == ["echo"]
    assert snap_b["snapshot"]["allowedToolNames"] == ["peek"]

    # different per-lease approved subsets
    mgr.approve_tools(caller=caller_a, lease_id=lease_a.lease_id,
                      owner_id=lease_a.owner_id, tool_names=["echo"])
    mgr.approve_tools(caller=caller_b, lease_id=lease_b.lease_id,
                      owner_id=lease_b.owner_id, tool_names=["peek"])

    out_a = mgr.call_tool(caller=caller_a, lease_id=lease_a.lease_id,
                          owner_id=lease_a.owner_id, tool_name="echo",
                          arguments={"text": "A"})
    out_b = mgr.call_tool(caller=caller_b, lease_id=lease_b.lease_id,
                          owner_id=lease_b.owner_id, tool_name="peek",
                          arguments={"text": "B"})
    assert out_a["result"]["content"][0]["text"] == "echo:A"
    assert out_b["result"]["content"][0]["text"] == "peek:B"
    calls = [c["name"] for c in stack.calls(state)]
    assert sorted(calls) == ["echo", "peek"]
    consults = [i["tool_identity"] for (i, _o) in authorizer.consultations]
    assert consults == ["read", "read"]  # real authority saw both, separately

    # B crossing into A's tool subset is refused by A-side gate rules... on B
    with pytest.raises(McpError) as info:
        mgr.call_tool(caller=caller_b, lease_id=lease_b.lease_id,
                      owner_id=lease_b.owner_id, tool_name="echo",
                      arguments={"text": "B-steals"})
    assert info.value.code == MCP_TOOL_NOT_APPROVED

    # B fraudulently claiming A's lease: uniform not-found, A untouched
    with pytest.raises(McpError) as info:
        mgr.inspect_connection(caller=caller_b, lease_id=lease_a.lease_id)
    assert info.value.code == MCP_LEASE_MISSING
    with pytest.raises(McpError) as info:
        mgr.close_lease(caller=caller_b, lease_id=lease_a.lease_id,
                        owner_id=lease_a.owner_id)
    assert info.value.code == MCP_LEASE_MISSING
    assert mgr.inspect_connection(caller=caller_a,
                                  lease_id=lease_a.lease_id)["state"] \
        == "catalog-observed"

    # A closes: only A's child is reaped; B stays live and callable
    closed_a = mgr.close_lease(caller=caller_a, lease_id=lease_a.lease_id,
                               owner_id=lease_a.owner_id)
    assert closed_a["state"] == "closed"
    pid_a = stack.child_pids(state)[0]["pid"]
    assert not _pid_alive(pid_a)
    assert stack.call("mcp.inspectConnection", principal="user-1",
                      sessionRef="session-2", runtimeGeneration=1,
                      leaseId=lease_b.lease_id)["connection"]["state"] \
        == "catalog-observed"
    out_b2 = mgr.call_tool(caller=caller_b, lease_id=lease_b.lease_id,
                           owner_id=lease_b.owner_id, tool_name="peek",
                           arguments={"text": "B2"})
    assert out_b2["result"]["content"][0]["text"] == "peek:B2"

    # unload counterexample: a foreign unload request must answer busy
    # while ANY managed lease is live (no silent teardown of B)
    with pytest.raises(McpError) as info:
        mgr.request_unload(reason="product-shutdown")
    assert info.value.code == MCP_LEASE_BUSY
    assert lease_b.lease_id in info.value.message

    # after B closes, the same request is allowed
    mgr.close_lease(caller=caller_b, lease_id=lease_b.lease_id,
                    owner_id=lease_b.owner_id)
    assert mgr.request_unload(reason="product-shutdown")["unloadAllowed"] is True
