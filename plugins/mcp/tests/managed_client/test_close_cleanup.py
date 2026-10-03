"""Close/cleanup evidence at L2: idempotent close, whole-process-group
reaping (grandchildren too, via /proc), the SIGTERM->SIGKILL escalation
against a stubborn child, and the honest ``unknown`` booking when a call's
outcome cannot be confirmed.
"""
from __future__ import annotations

import time

import pytest

from backend.errors import UNKNOWN_OUTCOME, McpError
from client_helpers import BRIEF, build_harness, wait_pids_gone
from managed_helpers import ALLOWING


def _live(tmp_path, mode="normal", *, policy=None):
    harness, revision, statefile = build_harness(tmp_path, mode=mode, policy=policy)
    manager = harness.manager(authority=ALLOWING())
    caller = harness.caller()
    lease, catalog, client = harness.bring_up(manager, caller, "srv-real", revision)
    return harness, manager, caller, lease, client, statefile


def test_close_is_idempotent_and_reaps(tmp_path):
    harness, manager, caller, lease, client, statefile = _live(tmp_path, "normal")
    pid = client.child_pid
    closed = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert closed["state"] == "closed"
    # a second direct client close is a no-op (once-effective semantics)
    client.close()
    client.close()
    wait_pids_gone(statefile)
    from client_helpers import pid_running
    assert not pid_running(pid)


def test_process_group_with_grandchild_leaves_no_residue(tmp_path):
    harness, manager, caller, lease, client, statefile = _live(tmp_path, "tree")
    # the fake spawned a grandchild into the same process group and both
    # pids are on the witness; close must reach the whole tree
    deadline = time.monotonic() + 3.0
    from client_helpers import events, recorded_pids
    while time.monotonic() < deadline and len(recorded_pids(statefile)) < 2:
        time.sleep(0.02)
    pids = recorded_pids(statefile)
    assert len(pids) == 2, "the fake did not register its tree"
    manager.close_lease(caller=caller, lease_id=lease.lease_id,
                        owner_id=lease.owner_id)
    gone = wait_pids_gone(statefile, timeout=5.0)
    assert sorted(gone) == sorted(pids)


def test_stubborn_server_is_killed_past_the_grace(tmp_path):
    # the fake ignores SIGTERM *and* stdin EOF: only the escalation path
    # (SIGKILL to the process group) may end it; close must still succeed
    from backend.managed.client_stdio import StdioClientPolicy
    policy = StdioClientPolicy(request_timeout=6.0, initialize_timeout=6.0,
                               exit_grace=0.2, kill_grace=0.5)
    harness, manager, caller, lease, client, statefile = _live(tmp_path, "stubborn",
                                                               policy=policy)
    closed = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert closed["state"] == "closed"
    assert closed["cleanupEvidence"].get("cleanup_errors") in ([], None)
    wait_pids_gone(statefile)


def test_unconfirmed_call_books_unknown_not_a_fake_success(tmp_path):
    # slowcall answers after 1.5s; the client gave up at 0.3s: the manager
    # must book call-outcome-unknown / UNKNOWN_OUTCOME, never a result
    harness, manager, caller, lease, client, statefile = _live(tmp_path, "slowcall",
                                                               policy=BRIEF)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "slow"})
    assert exc.value.code == UNKNOWN_OUTCOME
    facts = harness.leases.facts(lease.lease_id, caller)
    assert any(fact.get("kind") == "call-outcome-unknown" for fact in facts)
    # the lease stays open and honestly closeable once the server caught up
    time.sleep(1.5)
    closed = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert closed["state"] == "closed"
    wait_pids_gone(statefile)
