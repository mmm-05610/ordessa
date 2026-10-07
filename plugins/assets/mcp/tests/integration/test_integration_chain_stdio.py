"""T10-INT-01: the full cross-domain chain over one composition (stdio lane).

ServerPluginHost + WireService (real, tests/service precedent) ->
McpAssetServerPlugin activation -> saveRevision/approveRevision over the
real on-disk definition store -> a REAL managed stdio client
(StdioManagedClient) against the controlled loopback fake MCP server ->
tools/list observation into the REAL catalog store -> assign enable frozen
against that REAL observation -> resolvePreview -> approve_tools ->
tools/call through the double gate answered by the REAL
ordessa_permissions_backend authority (t06-wiring seeded DB usage) ->
inspectConnection/listTools witnesses -> close (process tree reaped).

Evidence ID: T10-INT-01 (specs/011-q4-mcp/reports/t10-integration.md).
"""
from __future__ import annotations

import os

from backend.errors import MCP_CATALOG_MISSING
from integration_helpers import read_allow_intent, wire_q5

ALL_MCP_METHODS = {
    "mcp.list", "mcp.get", "mcp.saveRevision", "mcp.approveRevision",
    "mcp.archive", "mcp.probe", "mcp.assign", "mcp.unassign",
    "mcp.resolvePreview", "mcp.inspectConnection", "mcp.listTools",
    "mcp.planForSubmission",
}


def _pid_dead(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_chain_activation_to_tool_call(stack, world):
    # -- 1. activation: the 12 typed mcp.* rows live on the real registry --
    assert ALL_MCP_METHODS <= set(stack.registry.method_ids())

    # -- 2. definition over the wire, stored by the REAL definition store --
    revision, state = stack.install_stdio("chaindemo", mode="normal")
    assert revision == 1
    server_json = (stack.service.root / "mcp" / "chaindemo" / "1" / "server.json")
    assert server_json.is_file()  # real layout: <root>/mcp/<id>/<rev>/server.json
    got = stack.call("mcp.get", serverScope="s1", principal="user-1",
                     definitionId="chaindemo")
    approval = got["latestRevision"]["approval"]
    assert approval["actor"] == "user-1"  # approval is attributed, not self-declared

    # -- 3. managed lease: REAL StdioManagedClient against the fake server --
    caller = stack.caller(principal="user-1", session="session-1", generation=1)
    lease, catalog = stack.bring_up(caller, "chaindemo", 1)
    assert sorted(catalog.tool_names) == ["echo", "peek"]
    booked = [e["method"] for e in stack.witness(state) if e.get("event") == "request"]
    assert booked == ["initialize", "notifications/initialized", "tools/list"]
    pids = stack.child_pids(state)
    assert len(pids) == 1 and _pid_dead(pids[0]["pid"]) is False

    # -- 4. assign ENABLE over the wire, frozen against the REAL observation --
    stack.assign_enable("chaindemo", catalog_digest=catalog.catalog_digest,
                        names=["echo", "peek"], principal="user-1")

    # -- 5. resolvePreview through the REAL catalog store provider --
    preview = stack.call("mcp.resolvePreview", serverScope="s1", principal="user-1")
    snapshot = preview["snapshot"]
    assert snapshot["allowedToolNames"] == ["echo", "peek"]
    entry = snapshot["definitionRevisions"][0]
    assert entry["definitionId"] == "chaindemo" and entry["revision"] == 1
    assert snapshot["needsRevalidation"] == []
    assert snapshot["snapshotDigest"].startswith("sha256:")

    # -- 6. lease approval + the REAL Q5 authority --
    mgr = stack.service.sessions
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])
    _adapter, authorizer = wire_q5(stack, world, intent=read_allow_intent(),
                                   tool_key_map={"echo": "read", "peek": "read"})

    # -- 7. tools/call through the double gate to the fake server --
    out = mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                        owner_id=lease.owner_id, tool_name="echo",
                        arguments={"text": "hello-chain"})
    assert out["result"]["content"][0]["text"] == "echo:hello-chain"
    assert out["catalogDigest"] == catalog.catalog_digest
    assert [c["name"] for c in stack.calls(state)] == ["echo"]  # server witness: 1
    (inputs, outcome), = authorizer.consultations  # the real Q5 ruled exactly once
    import ordessa_permissions_api as q5
    assert isinstance(outcome, q5.AllowedOnce)
    assert inputs["tool_identity"] == "read"

    # -- 8. the wire read faces see the same real state --
    conn = stack.call("mcp.inspectConnection", principal="user-1",
                      sessionRef="session-1", runtimeGeneration=1,
                      leaseId=lease.lease_id)["connection"]
    assert conn["state"] == "catalog-observed"
    kinds = [f["kind"] for f in conn["facts"]]
    assert "tool-call-executed" in kinds
    tools = stack.call("mcp.listTools", principal="user-1", sessionRef="session-1",
                       runtimeGeneration=1, serverScope="s1",
                       definitionId="chaindemo", revision=1)
    assert tools["leaseId"] == lease.lease_id
    assert sorted(tools["catalog"]["toolNames"]) == ["echo", "peek"]

    # -- 9. close: one client close, the child tree reaped -- --
    closed = mgr.close_lease(caller=caller, lease_id=lease.lease_id,
                             owner_id=lease.owner_id)
    assert closed["replayed"] is False and closed["state"] == "closed"
    assert _pid_dead(stack.child_pids(state)[0]["pid"])

    # -- 10. after close, the wire listTools refuses typed: a stored
    # definition is never dressed up as a live connection (contracts §1) --
    stack.expect_refusal("mcp.listTools", family="NOT_FOUND",
                         internal_code=MCP_CATALOG_MISSING,
                         principal="user-1", sessionRef="session-1",
                         runtimeGeneration=1, serverScope="s1",
                         definitionId="chaindemo", revision=1)
