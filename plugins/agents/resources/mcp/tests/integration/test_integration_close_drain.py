"""T10-INT-04: close / bounded drain / unknown-reconcile on REAL clients.

Cells (dispatch: close/drain/unknown-reconcile):

* clean close is once-effective and idempotently replayable, the owned
  process group (leader pid) is reaped, and the wire listTools face flips
  back to MCP_CATALOG_MISSING;
* drain-timeout: a tools/call that is genuinely in flight **on the fake
  server** (the server's own ledger books the call, then the server sleeps)
  makes close_lease answer MCP_LEASE_BUSY with the pending manifest and
  park the lease in ``closing`` (new calls gated); after the call finishes,
  the retry closes cleanly - the whole sequence witnessed server-side;
* unknown-reconcile: a REAL StdioManagedClient whose connect() answer is
  an unusable protocol version parks the lease in ``unknown`` via the
  manager; a second lease on the same key refuses MCP_RECONCILE_REQUIRED
  (the system never bets the old client exited), close refuses too, and
  only reconcile(terminated) releases the key so a NEW lease over a good
  server can come up.

Evidence ID: T10-INT-04.
"""
from __future__ import annotations

import os
import threading
import time

import pytest
from backend.errors import (
    MCP_LEASE_BUSY,
    MCP_RECONCILE_REQUIRED,
    McpError,
    UNKNOWN_OUTCOME,
)
from integration_helpers import read_allow_intent, wire_q5


def _pid_dead(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_clean_close_idempotent_and_reaps(stack):
    revision, state = stack.install_stdio("closedemo", mode="normal")
    caller = stack.caller()
    lease, _catalog = stack.bring_up(caller, "closedemo", revision)
    mgr = stack.service.sessions
    closed = mgr.close_lease(caller=caller, lease_id=lease.lease_id,
                             owner_id=lease.owner_id)
    assert closed["replayed"] is False and closed["state"] == "closed"
    assert closed["closedAt"]
    replay = mgr.close_lease(caller=caller, lease_id=lease.lease_id,
                             owner_id=lease.owner_id)
    assert replay["replayed"] is True and replay["state"] == "closed"
    assert _pid_dead(stack.child_pids(state)[0]["pid"])
    stack.expect_refusal("mcp.listTools", family="NOT_FOUND",
                         internal_code="MCP_CATALOG_MISSING",
                         principal="user-1", sessionRef="session-1",
                         runtimeGeneration=1, serverScope="s1",
                         definitionId="closedemo", revision=1)


def test_drain_timeout_busy_then_retry_closes(stack, world):
    revision, state = stack.install_stdio("draindemo", mode="slowcall")
    caller = stack.caller()
    lease, catalog = stack.bring_up(caller, "draindemo", revision)
    stack.assign_enable("draindemo", catalog_digest=catalog.catalog_digest,
                        names=["echo", "peek"], principal="user-1")
    mgr = stack.service.sessions
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])
    wire_q5(stack, world, intent=read_allow_intent(),
            tool_key_map={"echo": "read", "peek": "read"})

    errors: list = []

    def run_call():
        try:
            mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "slow"})
        except BaseException as exc:  # noqa: BLE001 - reported via errors
            errors.append(exc)

    thread = threading.Thread(target=run_call)
    thread.start()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not stack.calls(state):
        time.sleep(0.02)
    assert stack.calls(state), "the fake server must book the in-flight call"

    # drain expires while the call is genuinely in flight (server sleeping)
    with pytest.raises(McpError) as info:
        mgr.close_lease(caller=caller, lease_id=lease.lease_id,
                        owner_id=lease.owner_id, drain_timeout=0.2)
    assert info.value.code == MCP_LEASE_BUSY
    conn = mgr.inspect_connection(caller=caller, lease_id=lease.lease_id)
    assert conn["state"] == "closing"
    # new calls are gated while draining
    with pytest.raises(McpError) as info:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments={"text": "late"})
    assert info.value.code == "MCP_NOT_CONNECTED"

    thread.join(timeout=10.0)
    assert not thread.is_alive() and errors == []
    closed = mgr.close_lease(caller=caller, lease_id=lease.lease_id,
                             owner_id=lease.owner_id)
    assert closed["state"] == "closed"
    assert len(stack.calls(state)) == 1  # exactly the one in-flight call ran
    assert _pid_dead(stack.child_pids(state)[0]["pid"])


def test_unknown_outcome_blocks_retry_until_reconcile(stack):
    """connect() failing with the client already adopted is NOT confirmable
    from the manager's seat: the lease parks in ``unknown`` (FR-10,
    counterexample 7) - proven here with the real stdio client against a
    server that answers an unusable protocol version."""
    revision, state = stack.install_stdio("unkdemo", mode="mismatch")
    caller = stack.caller()
    mgr = stack.service.sessions
    lease = mgr.open_lease(caller=caller, server_scope="s1",
                           definition_id="unkdemo", revision=revision)
    mgr.plan_connection(caller=caller, lease_id=lease.lease_id)
    with pytest.raises(McpError) as info:
        mgr.start_connection(caller=caller, lease_id=lease.lease_id)
    assert info.value.code == UNKNOWN_OUTCOME
    conn = mgr.inspect_connection(caller=caller, lease_id=lease.lease_id)
    assert conn["state"] == "unknown"

    # the key stays occupied: no second lease betting the old client exited
    with pytest.raises(McpError) as info:
        mgr.open_lease(caller=caller, server_scope="s1",
                       definition_id="unkdemo", revision=revision)
    assert info.value.code == MCP_RECONCILE_REQUIRED
    with pytest.raises(McpError) as info:
        mgr.close_lease(caller=caller, lease_id=lease.lease_id,
                        owner_id=lease.owner_id)
    assert info.value.code == MCP_RECONCILE_REQUIRED

    # the only exit: a queried reconciliation record
    reconciled = mgr.reconcile(caller=caller, lease_id=lease.lease_id,
                               owner_id=lease.owner_id, outcome="terminated",
                               evidence={"check": "process-table-query"})
    assert reconciled.state == "closed"

    # key released: a NEW lease on the same definition+endpoint can start
    # the chain again (the occupancy refusal is gone)
    reopened = mgr.open_lease(caller=caller, server_scope="s1",
                              definition_id="unkdemo", revision=revision)
    assert reopened.state == "defined"
    mgr.close_lease(caller=caller, lease_id=reopened.lease_id,
                    owner_id=reopened.owner_id)

    # and a GOOD server comes up end to end after the reconciliation
    rev_good, state_good = stack.install_stdio("unkgood", mode="normal")
    lease_g, catalog_g = stack.bring_up(caller, "unkgood", rev_good)
    assert sorted(catalog_g.tool_names) == ["echo", "peek"]
    mgr.close_lease(caller=caller, lease_id=lease_g.lease_id,
                    owner_id=lease_g.owner_id)
    # the mismatch client tore its own child down at connect refusal
    assert _pid_dead(stack.child_pids(state)[0]["pid"])
