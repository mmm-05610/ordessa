"""The gate-refused-zero-side-effect proof at **L2** - measured on the
SERVER, not in the client's own account.

Every refusal path below must leave the fake's call counter at zero; the
positive controls prove the counter is live (a vacuous zero would make the
refusal assertions meaningless - this is the asymmetric-probe requirement
of the dispatch: if the gate were bypassed, these tests turn red).
"""
from __future__ import annotations

import pytest

from backend.errors import PERMISSION_REFUSED, McpError
from backend.managed import MCP_TOOL_NOT_APPROVED
from backend.permissions import PERMISSION_AUTHORITY_ABSENT
from client_helpers import build_harness, call_events, methods_seen
from managed_helpers import ALLOWING, DENYING


def _live(tmp_path, *, authority, tools=("echo", "peek")):
    harness, revision, statefile = build_harness(tmp_path, mode="normal")
    manager = harness.manager(authority=authority)
    caller = harness.caller()
    lease, catalog, client = harness.bring_up(manager, caller, "srv-real", revision)
    return harness, manager, caller, lease, catalog, client, statefile


# -- the controls: the counter is live and a granted call DOES reach it ----

def test_positive_control_granted_call_reaches_the_server(tmp_path):
    harness, manager, caller, lease, catalog, client, statefile = _live(
        tmp_path, authority=ALLOWING())
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    manager.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments={"text": "count-me"})
    assert len(call_events(statefile)) == 1  # the witness counts for real


# -- the refusals: zero tools/call on the server side --------------------------

def test_denying_authority_means_the_server_never_sees_a_call(tmp_path):
    authority = DENYING()
    harness, manager, caller, lease, catalog, client, statefile = _live(
        tmp_path, authority=authority)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "never"})
    assert exc.value.code == PERMISSION_REFUSED
    assert call_events(statefile) == []
    # not even a tools/call FRAME reached the server - the method log stops
    # at the catalog observation
    assert "tools/call" not in methods_seen(statefile)


def test_absent_authority_fails_closed_with_zero_server_calls(tmp_path):
    harness, manager, caller, lease, catalog, client, statefile = _live(
        tmp_path, authority=None)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "never"})
    assert exc.value.code == PERMISSION_AUTHORITY_ABSENT
    assert call_events(statefile) == []


def test_unapproved_tool_never_reaches_the_authority_or_the_server(tmp_path):
    # an ALLOWING authority would have said yes - the catalog/approval gate
    # alone must stop it (gate order is load-bearing, contracts §4)
    authority = ALLOWING()
    harness, manager, caller, lease, catalog, client, statefile = _live(
        tmp_path, authority=authority)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="peek",
                          arguments={"text": "sneak"})
    assert exc.value.code == MCP_TOOL_NOT_APPROVED
    assert authority.seen == []  # the authority was never consulted
    assert call_events(statefile) == []
