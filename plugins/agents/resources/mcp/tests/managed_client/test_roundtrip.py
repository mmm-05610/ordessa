"""L2 roundtrip: the real managed client drives initialize/tools-list/
tools-call/close against the controlled fake stdio MCP server, through the
ManagedSessionManager - one lease, one fresh process, no pooling.
"""
from __future__ import annotations

from managed_helpers import ALLOWING
from client_helpers import (
    build_harness,
    call_events,
    events,
    methods_seen,
    pid_running,
    recorded_pids,
    wait_pids_gone,
)


def _live(tmp_path, *, authority=None):
    harness, revision, statefile = build_harness(tmp_path, mode="normal")
    manager = harness.manager(authority=ALLOWING() if authority is None else authority)
    caller = harness.caller()
    lease, catalog, client = harness.bring_up(manager, caller, "srv-real", revision)
    return harness, manager, caller, lease, catalog, client, statefile


def test_full_roundtrip_through_the_manager(tmp_path):
    harness, manager, caller, lease, catalog, client, statefile = _live(tmp_path)
    fresh = harness.leases.get_lease(lease.lease_id, caller)
    assert fresh.state == "catalog-observed"

    # the handshake really happened and the ACTUAL negotiated version is
    # booked in the lease evidence + the catalog observation
    assert client.negotiated_protocol_version == "2025-11-25"
    assert catalog.protocol_version == "2025-11-25"
    connected = [fact for fact in harness.leases.facts(lease.lease_id, caller)
                 if fact.get("kind") == "state-entry" and fact.get("to") == "connected"]
    assert connected[0]["evidence"]["negotiatedProtocolVersion"] == "2025-11-25"
    assert connected[0]["evidence"]["serverInfo"]["name"] == "fake-mcp-t05"

    # the catalog observation carries names + schema digests (no bodies)
    assert set(catalog.tool_names) == {"echo", "peek"}
    assert all(digest.startswith("sha256:")
               for _, digest in catalog.tool_names_and_schema_digests)

    # server-side witness: exactly initialize + initialized + one tools/list
    assert methods_seen(statefile)[:3] == ["initialize", "notifications/initialized",
                                           "tools/list"]

    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=fresh.owner_id, tool_names=["echo"])
    result = manager.call_tool(caller=caller, lease_id=lease.lease_id,
                               owner_id=fresh.owner_id, tool_name="echo",
                               arguments={"text": "s3cr3t-arg-body"})
    assert result["result"]["content"][0]["text"] == "echo:s3cr3t-arg-body"

    # the server's own log booked the executed call (side effect REALLY ran)
    assert [event["name"] for event in call_events(statefile)] == ["echo"]
    # ...but the argument body never enters the lease facts / audit ledger
    assert "s3cr3t-arg-body" not in str(harness.leases.facts(lease.lease_id, caller))
    assert "s3cr3t-arg-body" not in str(harness.sink.events)

    closed = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=fresh.owner_id)
    assert closed["replayed"] is False and closed["state"] == "closed"

    # no residue: the owned process is gone from /proc (reaped, no zombie)
    pids = wait_pids_gone(statefile)
    assert client.child_pid in pids

    # close is once-effective; the replay carries the recorded evidence
    replay = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=fresh.owner_id)
    assert replay["replayed"] is True
    assert len(call_events(statefile)) == 1  # closing never re-ran anything


def test_two_sessions_two_processes_no_pooling(tmp_path):
    harness, revision, statefile = build_harness(tmp_path, mode="normal")
    manager = harness.manager(authority=ALLOWING())
    caller_a = harness.caller(session="sess-a")
    caller_b = harness.caller(session="sess-b")

    lease_a, _, client_a = harness.bring_up(manager, caller_a, "srv-real", revision)
    lease_b, _, client_b = harness.bring_up(manager, caller_b, "srv-real", revision)

    # one fresh client per lease, two distinct owned OS processes
    assert len(harness.factory.produced) == 2
    assert client_a.child_pid != client_b.child_pid
    assert {client_a.child_pid, client_b.child_pid} <= set(recorded_pids(statefile))
    assert sum(1 for event in events(statefile)
               if event.get("event") == "pid" and event.get("mode") == "normal") == 2

    manager.close_lease(caller=caller_a, lease_id=lease_a.lease_id,
                        owner_id=lease_a.owner_id)
    assert not pid_running(client_a.child_pid)
    assert pid_running(client_b.child_pid)  # closing A must not touch B's process

    manager.close_lease(caller=caller_b, lease_id=lease_b.lease_id,
                        owner_id=lease_b.owner_id)
    assert not pid_running(client_b.child_pid)
