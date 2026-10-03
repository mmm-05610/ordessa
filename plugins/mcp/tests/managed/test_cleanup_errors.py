"""Counterexample 9: cleanup errors are booked, never mask the primary error."""
from __future__ import annotations

import threading

import pytest

from backend.errors import UNKNOWN_OUTCOME, McpError
from backend.managed import MCP_LEASE_BUSY, MCP_RECONCILE_REQUIRED
from managed_helpers import ALLOWING, SERVER_SCOPE, TOOLS_ONE


def _live_with_close_fault(harness, *, sink=None):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager(authority=ALLOWING(), sink=sink)
    harness.factory.set(caller.session_ref, "srv-a", tools=TOOLS_ONE,
                        close_error=RuntimeError("transport teardown hung"))
    lease, _, client = harness.bring_up(manager, caller, "srv-a", revision)
    return manager, caller, harness.leases.get_lease(lease.lease_id, caller), client


def test_client_close_failure_becomes_unknown_and_is_booked(harness):
    manager, caller, lease, client = _live_with_close_fault(harness)
    with pytest.raises(McpError) as exc:
        manager.close_lease(caller=caller, lease_id=lease.lease_id,
                            owner_id=lease.owner_id)
    assert exc.value.code == UNKNOWN_OUTCOME
    refreshed = harness.leases.get_lease(lease.lease_id, caller)
    assert refreshed.state == "unknown"  # never pretended closed
    facts = harness.leases.facts(lease.lease_id, caller)
    assert [f["kind"] for f in facts].count("cleanup-error") == 1
    booked = [f for f in facts if f["kind"] == "cleanup-error"][0]
    assert booked["phase"] == "client-close"
    assert booked["error"] == "RuntimeError"
    assert refreshed.cleanup_evidence["cleanup_errors"]
    # retry now goes through reconcile, not another blind close
    with pytest.raises(McpError) as exc2:
        manager.close_lease(caller=caller, lease_id=lease.lease_id,
                            owner_id=lease.owner_id)
    assert exc2.value.code == MCP_RECONCILE_REQUIRED
    manager.reconcile(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, outcome="terminated",
                      evidence={"source": "manager-query"})
    replay = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert replay["replayed"] is True and replay["state"] == "closed"
    assert client.close_count == 0  # the faulted close is the only attempt


def test_audit_sink_failure_never_masks_the_primary_busy_error(harness):
    sink = harness.sink
    sink.raise_on = {"drain-timeout", "close-failed"}
    gate = threading.Event()
    started = threading.Event()
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager(authority=ALLOWING(), sink=sink)
    harness.factory.set(caller.session_ref, "srv-a", tools=TOOLS_ONE,
                        call_gate=gate, call_started=started)
    lease, _, client = harness.bring_up(manager, caller, "srv-a", revision)
    lease = harness.leases.get_lease(lease.lease_id, caller)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    worker = threading.Thread(target=lambda: manager.call_tool(
        caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
        tool_name="echo", arguments={"text": "slow"}))
    worker.start()
    assert started.wait(timeout=5.0)
    try:
        with pytest.raises(McpError) as exc:
            manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                owner_id=lease.owner_id, drain_timeout=0.05)
        # THE PRIMARY error surfaces even though two audit writes exploded
        assert exc.value.code == MCP_LEASE_BUSY
    finally:
        gate.set()
        worker.join(timeout=5.0)
    facts = harness.leases.facts(lease.lease_id, caller)
    audit_faults = [f for f in facts if f["kind"] == "cleanup-error"
                    and f["phase"] == "audit-sink"]
    assert len(audit_faults) >= 1  # booked, not swallowed silently
    assert client.close_count == 0


def test_audit_sink_failure_on_successful_close_still_succeeds(harness):
    sink = harness.sink
    sink.raise_on = {"lease-closed"}
    manager, caller, lease, client = _live_with_close_fault(harness, sink=sink)
    # close error + audit error: the primary (close) error must surface,
    # not the audit failure.
    with pytest.raises(McpError) as exc:
        manager.close_lease(caller=caller, lease_id=lease.lease_id,
                            owner_id=lease.owner_id)
    assert exc.value.code == UNKNOWN_OUTCOME
    kinds = [f["kind"] for f in harness.leases.facts(lease.lease_id, caller)]
    assert kinds.count("cleanup-error") >= 1
