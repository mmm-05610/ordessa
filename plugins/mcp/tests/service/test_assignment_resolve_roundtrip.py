"""§1 rows 3-5 roundtrip through the real dispatch: assign -> resolvePreview
-> listTools/inspectConnection -> unassign, plus the pre-acceptance guards
(approval, archived, catalog binding, row CAS, principal isolation).

The live catalog observation is produced by the domain's labelled in-memory
fake client (the L0/L1 evidence level of backend/managed — reports
t04-t05-research.md), opened through the service's OWN session manager on
the real lease/catalog stores. `listTools` reading it back proves the
catalog is a connection fact, and its refusal without one proves a stored
definition is never dressed up as a live connection (§1 row 5)."""
from __future__ import annotations

from service_helpers import Stack, make_client, seed_revision

from backend.managed.lease import LeaseCaller


def _live_catalog(stack, *, scope="s1", principal="alice", session="sess-1",
                  generation=1, definition_id="demo", revision=1):
    service = stack.host.provided_port("asset.mcp.v2")
    caller = LeaseCaller(principal, session, generation)
    lease = service.sessions.open_lease(
        caller=caller, server_scope=scope, definition_id=definition_id,
        revision=revision)
    service.sessions.plan_connection(caller=caller, lease_id=lease.lease_id,
                                     submission_id="sub-live-1")
    service.sessions.start_connection(caller=caller, lease_id=lease.lease_id)
    catalog = service.sessions.observe_catalog(caller=caller, lease_id=lease.lease_id)
    return lease, catalog


def _enable_params(digest_value, *, names=("read_file",), **overrides):
    params = {
        "serverScope": "s1", "principal": "alice", "scopeKind": "user-default",
        "scopeId": "alice", "definitionId": "demo", "decision": "enable",
        "approvedRevision": 1,
        "toolSelection": {"mode": "allowNames", "names": list(names),
                          "catalogDigest": digest_value},
        "expectedRowVersion": 0, "operationKey": "op-assign-1",
    }
    params.update(overrides)
    return params


def test_enable_without_any_observation_refuses_catalog_missing(tmp_path):
    stack = Stack(tmp_path, client_factory=make_client)
    seed_revision(stack)
    # the definition exists and is approved — but nothing has connected:
    # enabling against a frozen selection must not pretend a catalog exists
    stack.expect_refusal(
        "mcp.listTools", family="NOT_FOUND", internal_code="MCP_CATALOG_MISSING",
        principal="alice", sessionRef="sess-1", runtimeGeneration=1,
        serverScope="s1", definitionId="demo", revision=1)
    stack.expect_refusal(
        "mcp.assign", family="NOT_FOUND", internal_code="MCP_CATALOG_MISSING",
        **_enable_params("sha256:none"))


def test_assign_resolve_listtools_inspect_unassign_roundtrip(tmp_path):
    stack = Stack(tmp_path, client_factory=make_client)
    seed_revision(stack)
    lease, catalog = _live_catalog(stack)

    assigned = stack.call("mcp.assign", **_enable_params(catalog.catalog_digest))
    assert assigned["assignment"] == {
        "scopeKind": "user-default", "scopeId": "alice", "harness": "any",
        "definitionId": "demo", "decision": "enable", "approvedRevision": 1,
        "rowVersion": 1}
    assert assigned["replayed"] is False

    preview = stack.call("mcp.resolvePreview", serverScope="s1", principal="alice",
                         sessionRef="sess-1", runtimeGeneration=1)
    snapshot = preview["snapshot"]
    assert [e["definitionId"] for e in snapshot["definitionRevisions"]] == ["demo"]
    assert snapshot["definitionRevisions"][0]["canonicalDigest"].startswith("sha256:")
    assert snapshot["allowedToolNames"] == ["read_file"]
    assert snapshot["laneByDefinition"]["demo"]["lane"] == "managed"
    assert snapshot["snapshotDigest"].startswith("sha256:")

    tools = stack.call("mcp.listTools", principal="alice", sessionRef="sess-1",
                       runtimeGeneration=1, serverScope="s1",
                       definitionId="demo", revision=1)
    assert tools["leaseId"] == lease.lease_id
    assert tools["catalog"]["toolNames"] == ["read_file", "write_file"]
    assert tools["catalog"]["catalogDigest"] == catalog.catalog_digest
    assert tools["catalog"]["sourceEvidence"]["origin"] == "tools-list"

    connection = stack.call("mcp.inspectConnection", principal="alice",
                            sessionRef="sess-1", runtimeGeneration=1,
                            leaseId=lease.lease_id)
    facts = connection["connection"]
    assert facts["state"] == "catalog-observed"
    # each FR-02 level carries its own independent fact record (levels are
    # never collapsed into a boolean)
    assert facts["levels"]["connected"]["to"] == "connected"
    assert facts["levels"]["defined"]["to"] == "defined"
    assert facts["levels"]["selected"]["to"] == "selected"
    assert facts["catalogDigest"] == catalog.catalog_digest

    unassigned = stack.call("mcp.unassign", serverScope="s1", principal="alice",
                            scopeKind="user-default", scopeId="alice",
                            definitionId="demo", expectedRowVersion=1,
                            operationKey="op-unassign-1")
    assert unassigned["assignment"]["decision"] == "inherit"
    assert unassigned["assignment"]["removed"] is True
    after = stack.call("mcp.resolvePreview", serverScope="s1", principal="alice")
    assert after["snapshot"]["definitionRevisions"] == []
    assert after["snapshot"]["allowedToolNames"] == []


def test_selection_must_match_the_live_observation(tmp_path):
    stack = Stack(tmp_path, client_factory=make_client)
    seed_revision(stack)
    _live_catalog(stack)
    # an unobserved tool name never enters the frozen subset
    stack.expect_refusal(
        "mcp.assign", family="INVALID_REQUEST", internal_code="MCP_TOOL_NOT_OBSERVED",
        **_enable_params(_digest_of_live(stack), names=("nope",)))
    # digest drift: the selection must bind THIS observation
    stack.expect_refusal(
        "mcp.assign", family="NOT_FOUND", internal_code="MCP_CATALOG_MISSING",
        **_enable_params("sha256:stale-digest"))


def _digest_of_live(stack):
    service = stack.host.provided_port("asset.mcp.v2")
    latest = service.catalogs.latest(definition_id="demo", revision=1)
    return latest.catalog_digest


def test_row_cas_and_principal_isolation(tmp_path):
    stack = Stack(tmp_path, client_factory=make_client)
    seed_revision(stack)
    stack.call("mcp.assign", serverScope="s1", principal="alice",
               scopeKind="project", scopeId="proj-1", definitionId="demo",
               decision="disable", expectedRowVersion=0, operationKey="op-dis-1")
    stack.expect_refusal(
        "mcp.assign", family="CONFLICT_VERSION", internal_code="MCP_CAS_CONFLICT",
        serverScope="s1", principal="alice", scopeKind="project", scopeId="proj-1",
        definitionId="demo", decision="disable", expectedRowVersion=0,
        operationKey="op-dis-2")
    # bob cannot take over alice's row: ownership refuses before content
    stack.expect_refusal(
        "mcp.assign", family="CONFLICT_REQUEST", internal_code="MCP_OWNER_CONFLICT",
        serverScope="s1", principal="bob", scopeKind="project", scopeId="proj-1",
        definitionId="demo", decision="disable", expectedRowVersion=1,
        operationKey="op-dis-3")
    # ...and bob's resolution never sees alice's rows
    preview = stack.call("mcp.resolvePreview", serverScope="s1", principal="bob",
                         projectId="proj-1")
    assert preview["snapshot"]["assignmentRevisions"] == []


def test_archived_definition_blocks_new_assignment(tmp_path):
    stack = Stack(tmp_path, client_factory=make_client)
    seed_revision(stack)
    _live_catalog(stack)
    stack.call("mcp.archive", serverScope="s1", principal="alice", definitionId="demo")
    service = stack.host.provided_port("asset.mcp.v2")
    digest_value = _digest_of_live(stack)
    stack.expect_refusal(
        "mcp.assign", family="CONFLICT_REQUEST", internal_code="MCP_DEFINITION_ARCHIVED",
        **_enable_params(digest_value))
    assert service is not None


def test_enable_requires_approved_revision(tmp_path):
    stack = Stack(tmp_path, client_factory=make_client)
    # save WITHOUT approval: enable is refused before anything is stored
    stack.call("mcp.saveRevision", serverScope="s1", principal="alice",
               definitionId="demo",
               definition={"name": "demo", "transport": {"stdio": {"command": "/bin/true"}}},
               expectedVersion=0, operationKey="op-save-unapproved")
    stack.expect_refusal(
        "mcp.assign", family="CONFLICT_REQUEST",
        internal_code="MCP_REVISION_NOT_APPROVED",
        serverScope="s1", principal="alice", scopeKind="user-default",
        scopeId="alice", definitionId="demo", decision="enable",
        approvedRevision=1,
        toolSelection={"mode": "allObserved", "names": [], "catalogDigest": "x"},
        expectedRowVersion=0, operationKey="op-assign-unapproved")
