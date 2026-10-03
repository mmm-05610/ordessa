"""tools/list drift measured over the REAL wire: the second observation
answers a different set, the digest changes, the frozen approval goes
stale and the new tool is never callable without re-approval - all while
the server-side call counter shows exactly what ran and what did not.
"""
from __future__ import annotations

import pytest

from backend.errors import CATALOG_CHANGED, McpError
from backend.managed import MCP_TOOL_NOT_APPROVED
from client_helpers import build_harness, call_events
from managed_helpers import ALLOWING


def test_drift_invalidates_digest_and_stale_approval(tmp_path):
    harness, revision, statefile = build_harness(tmp_path, mode="drift")
    manager = harness.manager(authority=ALLOWING())
    caller = harness.caller()
    lease, catalog_v1, client = harness.bring_up(manager, caller, "srv-real", revision)
    assert set(catalog_v1.tool_names) == {"echo"}  # first observation

    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    manager.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments={"text": "before-drift"})
    assert len(call_events(statefile)) == 1

    # re-observation: the fake now answers [echo, extra]
    catalog_v2 = manager.observe_catalog(caller=caller, lease_id=lease.lease_id)
    assert set(catalog_v2.tool_names) == {"echo", "extra"}
    assert catalog_v2.catalog_digest != catalog_v1.catalog_digest
    changed = [fact for fact in harness.leases.facts(lease.lease_id, caller)
               if fact.get("kind") == "catalog-changed"]
    assert changed and changed[0]["fromDigest"] == catalog_v1.catalog_digest
    assert changed[0]["toDigest"] == catalog_v2.catalog_digest

    # the approval frozen against the OLD digest is stale -> call refused,
    # and the refusal happens BEFORE the wire: no new tools/call server-side
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "after-drift"})
    assert exc.value.code == CATALOG_CHANGED
    assert len(call_events(statefile)) == 1  # still only the pre-drift call

    # the newly discovered tool is never auto-approved (FR-04)
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="extra",
                          arguments={"text": "auto?"})
    assert exc.value.code == CATALOG_CHANGED  # stale digest speaks first
    assert len(call_events(statefile)) == 1

    # explicit re-approval against the NEW digest restores the callable
    # subset - and only for the names the owner froze
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="extra",
                          arguments={"text": "not-frozen"})
    assert exc.value.code == MCP_TOOL_NOT_APPROVED
    assert len(call_events(statefile)) == 1
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo", "extra"])
    manager.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="extra",
                      arguments={"text": "now"})
    assert [event["name"] for event in call_events(statefile)] == ["echo", "extra"]
