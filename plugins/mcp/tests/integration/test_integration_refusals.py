"""T10-INT-02: the refusal cells of the chain - each with the double
asymmetric witness (the fake MCP server's own call ledger AND the real Q5
authority's consultation ledger stay at zero while a gate refuses).

Cells (report.md §一 T06/T05 rows composed cross-domain, dispatch:
未批准工具 / 过期授权 / 目录漂移 各自的零副作用断言):

* a tool outside the lease's frozen approved subset -> ``MCP_TOOL_NOT_APPROVED``
  before the authority is even consulted (FR-04: newly discovered / not
  explicitly approved is never callable);
* no Permission authority composed -> ``PERMISSION_AUTHORITY_ABSENT``
  fail-closed (G3: unattended is not implicit consent);
* the REAL Q5 one-time grant flow: pending (refused, 0 effects) -> user
  allow + native receipt settled in the real DB -> allowed (1 effect) ->
  the spent grant answers ``[expired]`` (still 1 effect) - the expiry cell
  executed through the whole chain, not only the adapter;
* catalog drift: a re-observation changes the digest -> the frozen approval
  goes stale (``CATALOG_CHANGED``, 0 new effects), re-approval against the
  new digest restores the door, and the wire ``resolvePreview`` marks the
  definition ``needsRevalidation``.

Evidence ID: T10-INT-02.
"""
from __future__ import annotations

import ordessa_permissions_api as q5
import pytest
from backend.errors import (
    CATALOG_CHANGED,
    MCP_TOOL_NOT_APPROVED,
    PERMISSION_AUTHORITY_ABSENT,
    PERMISSION_REFUSED,
    McpError,
)
from integration_helpers import args_digest_for, read_allow_intent, wire_q5


def _bring_up_approved(stack, world, *, intent="allow", tool_key_map=None,
                       mode="normal", definition_id="refusdemo"):
    """intent: "allow" (Q5 intent rule), "none" (wire the real authority
    with NO intent: every call answers pending), None (do not wire any
    authority: the fail-closed absence path)."""
    revision, state = stack.install_stdio(definition_id, mode=mode)
    caller = stack.caller()
    lease, catalog = stack.bring_up(caller, definition_id, revision)
    stack.assign_enable(definition_id, catalog_digest=catalog.catalog_digest,
                        names=sorted(catalog.tool_names), principal="user-1")
    mgr = stack.service.sessions
    authorizer = None
    if intent is not None:
        mapping = tool_key_map or {"echo": "read", "peek": "read", "extra": "read"}
        _a, authorizer = wire_q5(stack, world,
                                 intent=read_allow_intent() if intent == "allow"
                                 else None, tool_key_map=mapping)
    return revision, state, caller, lease, catalog, mgr, authorizer


def test_unapproved_tool_refuses_before_authority_and_server(stack, world):
    revision, state, caller, lease, catalog, mgr, authorizer = _bring_up_approved(
        stack, world)
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])
    with pytest.raises(McpError) as info:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="peek",
                      arguments={"text": "should-not-run"})
    assert info.value.code == MCP_TOOL_NOT_APPROVED
    # asymmetric witnesses: the server saw zero tool calls...
    assert stack.calls(state) == []
    # ...and the REAL authority was never consulted (gate order is the contract)
    assert authorizer.consultations == []


def test_missing_authority_fails_closed_with_zero_side_effects(stack):
    revision, state = stack.install_stdio("noauthdemo", mode="normal")
    caller = stack.caller()
    lease, catalog = stack.bring_up(caller, "noauthdemo", revision)
    mgr = stack.service.sessions
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])
    # no authority injected: PERMISSION_AUTHORITY_ABSENT, not a default allow
    with pytest.raises(McpError) as info:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments={"text": "unattended"})
    assert info.value.code == PERMISSION_AUTHORITY_ABSENT
    assert stack.calls(state) == []


def test_expired_grant_real_q5_once_then_refused(stack, world):
    """The full approval loop through the chain: pending is NOT callable,
    the settled one-time grant runs exactly once, and the spent grant is
    the expired refusal - all with server-side call counting."""
    revision, state, caller, lease, catalog, mgr, authorizer = _bring_up_approved(
        stack, world, intent="none")  # real authority, no intent: Q5 rule 3
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])
    arguments = {"text": "once-only"}
    digest_hex = args_digest_for("echo", arguments)[len("sha256:"):]

    # 1. pending: refused before any effect; the server saw nothing
    with pytest.raises(McpError) as info:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments=arguments)
    assert info.value.code == PERMISSION_REFUSED
    assert stack.calls(state) == []
    (_inputs, outcome), = authorizer.consultations
    assert isinstance(outcome, q5.PendingApproval)

    # 2. the REAL approval loop settles in the real DB (allow + receipt)
    approval_id = world.settle_allow(tool_key="read", argument_digest=digest_hex,
                                     native_request_id="nr-s1")
    assert world.facts.peek(approval_id)["state"] == "settled"

    # 3. now the same call runs - exactly one server-side effect
    out = mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                        owner_id=lease.owner_id, tool_name="echo",
                        arguments=arguments)
    assert out["result"]["content"][0]["text"] == "echo:once-only"
    assert [c["name"] for c in stack.calls(state)] == ["echo"]

    # 4. the one-time grant is spent: the repeat is the expired refusal and
    # the server ledger STAYS at one call (no silent re-allow, no retry)
    with pytest.raises(McpError) as info:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments=arguments)
    assert info.value.code == PERMISSION_REFUSED
    assert "[expired]" in info.value.message
    assert q5.RefusalCode.APPROVAL_STALE.value in info.value.message
    assert len(stack.calls(state)) == 1
    assert world.facts.grant_fields(approval_id)["consumed"] is True


def test_catalog_drift_stales_the_approval_then_recovers(stack, world):
    revision, state, caller, lease, catalog, mgr, authorizer = _bring_up_approved(
        stack, world, mode="drift")
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])

    # call over the frozen digest: one server effect
    mgr.call_tool(caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
                  tool_name="echo", arguments={"text": "a"})
    assert len(stack.calls(state)) == 1

    # re-observation: the fake's tools/list changed -> drift fact + new digest
    drifted = mgr.observe_catalog(caller=caller, lease_id=lease.lease_id)
    assert drifted.catalog_digest != catalog.catalog_digest
    assert "extra" in drifted.tool_names

    # the frozen approval is stale: refused, ZERO new server-side effects
    with pytest.raises(McpError) as info:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments={"text": "b"})
    assert info.value.code == CATALOG_CHANGED
    assert len(stack.calls(state)) == 1

    # explicit re-approval against the NEW digest re-opens the door
    # (newly discovered tools are never auto-approved: 'extra' needs its own
    #  owner action - FR-04)
    with pytest.raises(McpError) as info:
        mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo", "nope"])
    assert info.value.code == "MCP_TOOL_NOT_OBSERVED"
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo", "extra"])
    mgr.call_tool(caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
                  tool_name="extra", arguments={"text": "c"})
    assert [c["name"] for c in stack.calls(state)] == ["echo", "extra"]

    # the wire resolvePreview now reports the frozen selection as drifted:
    # the enable assignment was frozen against the PRE-drift digest by the
    # helper, and the live observation moved (FR-04 needs-revalidation face)
    preview = stack.call("mcp.resolvePreview", serverScope="s1", principal="user-1")
    assert preview["snapshot"]["needsRevalidation"] == ["refusdemo"]
