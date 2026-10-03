"""In-flight drain against the REAL client (L2): a tools/call that is
actually executing in the child process keeps close_lease honest -
``MCP_LEASE_BUSY`` with the pending manifest while it runs, a clean close
after it lands. The lease state machine and the client transport agree on
the same in-flight notion the L0/L1 fakes modelled.
"""
from __future__ import annotations

import threading
import time

import pytest

from backend.errors import McpError
from backend.managed import MCP_LEASE_BUSY
from client_helpers import FAST, build_harness, call_events, wait_pids_gone
from managed_helpers import ALLOWING


def test_close_drains_a_real_inflight_call_then_succeeds(tmp_path):
    harness, revision, statefile = build_harness(tmp_path, mode="slowcall",
                                                 policy=FAST)
    manager = harness.manager(authority=ALLOWING())
    caller = harness.caller()
    lease, catalog, client = harness.bring_up(manager, caller, "srv-real", revision)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])

    outcome: dict = {}

    def worker():
        try:
            outcome["result"] = manager.call_tool(
                caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
                tool_name="echo", arguments={"text": "in-flight"})
        except BaseException as exc:  # pragma: no cover - failure surfaces below
            outcome["error"] = exc

    thread = threading.Thread(target=worker)
    thread.start()

    # wait until the SERVER booked the call: it is really in flight there
    deadline = time.monotonic() + 3.0
    while not call_events(statefile) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert call_events(statefile), "the fake never received the call frame"

    # close NOW: drain window far shorter than the call -> busy refusal,
    # pending manifest booked, lease stays in closing (new calls gated)
    with pytest.raises(McpError) as exc:
        manager.close_lease(caller=caller, lease_id=lease.lease_id,
                            owner_id=lease.owner_id, drain_timeout=0.05)
    assert exc.value.code == MCP_LEASE_BUSY
    facts = harness.leases.facts(lease.lease_id, caller)
    drain = [fact for fact in facts if fact.get("kind") == "drain-timeout"]
    assert drain and drain[0]["pending"][0]["tool"] == "echo"
    assert drain[0]["pending"][0]["argsDigest"].startswith("sha256:")

    thread.join(timeout=10.0)
    assert "result" in outcome and "error" not in outcome
    assert outcome["result"]["result"]["content"][0]["text"] == "echo:in-flight"

    # the call landed; the retry of close completes (idempotent owner path)
    closed = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert closed["state"] == "closed"
    wait_pids_gone(statefile)
    assert len(call_events(statefile)) == 1  # nothing ran twice
