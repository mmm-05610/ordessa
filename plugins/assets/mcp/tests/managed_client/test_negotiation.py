"""Protocol negotiation evidence (L2): what the client records is what the
SERVER actually answered, and an un-negotiated state never reaches the wire.
"""
from __future__ import annotations

import sys

import pytest

from backend.errors import PROTOCOL_MISMATCH, UNKNOWN_OUTCOME, McpError
from backend.managed.client_stdio import StdioClientPolicy, StdioManagedClient
from client_helpers import FAKE, FAST, build_harness, events, pid_running
from managed_helpers import ALLOWING


def raw_client(tmp_path, mode: str, *, policy: StdioClientPolicy = FAST):
    statefile = tmp_path / f"{mode}.jsonl"
    client = StdioManagedClient(
        argv=[sys.executable, FAKE, mode, str(statefile)], env={"PATH": "/usr/bin:/bin"},
        policy=policy)
    return client, statefile


def test_downgraded_answer_is_the_recorded_version(tmp_path):
    # the fake ALWAYS answers 2024-11-05 although the client offers
    # 2025-11-25: the lease evidence and the catalog must carry the ANSWER.
    harness, revision, statefile = build_harness(tmp_path, mode="downgrade")
    manager = harness.manager(authority=ALLOWING())
    caller = harness.caller()
    lease, catalog, client = harness.bring_up(manager, caller, "srv-real", revision)
    assert client.negotiated_protocol_version == "2024-11-05"
    assert catalog.protocol_version == "2024-11-05"
    connected = [fact for fact in harness.leases.facts(lease.lease_id, caller)
                 if fact.get("to") == "connected"]
    assert connected[0]["evidence"]["negotiatedProtocolVersion"] == "2024-11-05"


def test_unsupported_offered_version_is_refused_and_reaped(tmp_path):
    # the fake refuses an initialize offering 1999-01-01 outright; the
    # client surfaces the typed mismatch AND leaves no live child.
    client, statefile = raw_client(
        tmp_path, "normal",
        policy=StdioClientPolicy(supported_protocol_versions=("1999-01-01",)))
    client.start()
    pid = client.child_pid
    with pytest.raises(McpError) as exc:
        client.connect()
    assert exc.value.code == PROTOCOL_MISMATCH
    refused = [event for event in events(statefile)
               if event.get("event") == "version-refused"]
    assert refused and refused[0]["requested"] == "1999-01-01"
    # connect() reaped the owned process before raising
    deadline = 2.0
    import time
    end = time.monotonic() + deadline
    while pid_running(pid) and time.monotonic() < end:
        time.sleep(0.02)
    assert not pid_running(pid)


def test_mismatched_server_answer_parks_the_lease_without_a_leak(tmp_path):
    # manager-driven: the fake answers 1999-01-01 (not in the supported
    # list) -> start_connection is an unconfirmed failure (unknown, honest)
    # but the child process was torn down by the client itself.
    harness, revision, statefile = build_harness(tmp_path, mode="mismatch")
    manager = harness.manager(authority=ALLOWING())
    caller = harness.caller()
    lease = manager.open_lease(caller=caller, server_scope="scope-1",
                               definition_id="srv-real", revision=revision)
    manager.plan_connection(caller=caller, lease_id=lease.lease_id)
    with pytest.raises(McpError) as exc:
        manager.start_connection(caller=caller, lease_id=lease.lease_id)
    assert exc.value.code == UNKNOWN_OUTCOME
    assert harness.leases.get_lease(lease.lease_id, caller).state == "unknown"
    pids = [event["pid"] for event in events(statefile) if event.get("event") == "pid"]
    assert pids and not any(pid_running(pid) for pid in pids)


def test_requests_before_negotiation_never_leave_the_client(tmp_path):
    # local precondition gate: start() only - no initialize yet - so
    # list_tools/call_tool refuse with a typed McpError BEFORE any frame
    # is written; the fake's witness shows its stdin stayed empty.
    client, statefile = raw_client(tmp_path, "normal")
    client.start()
    with pytest.raises(McpError) as exc:
        client.list_tools()
    assert exc.value.code == "MCP_CLIENT_NOT_CONNECTED"
    with pytest.raises(McpError):
        client.call_tool("echo", {"text": "x"})
    import time
    time.sleep(0.2)  # give any (wrongly) written frame the chance to land
    assert [event for event in events(statefile)
            if event.get("event") == "request"] == []
    client.close()


def test_fake_rejects_un_negotiated_use_on_the_wire(tmp_path):
    # asymmetric check on the fake itself: pushing a tools/list frame past
    # the client's local gate (internal _request, bypassing connect) must
    # be answered with a refusal the SERVER booked - a real server-side
    # guard, not a client-side echo.
    client, statefile = raw_client(tmp_path, "normal")
    client.start()
    answer = client._request(  # noqa: SLF001 - deliberately bypassing the gate
        {"jsonrpc": "2.0", "id": 99, "method": "tools/list", "params": {}},
        timeout=3.0)
    assert "error" in answer
    assert "un-negotiated" in answer["error"]["message"]
    refused = [event for event in events(statefile)
               if event.get("event") == "refused"]
    assert refused and refused[0]["method"] == "tools/list"
    client.close()
