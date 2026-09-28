"""Tool catalog: observations only from live connected leases, deterministic
digests, drift invalidates old digests and never auto-widens approvals;
the resolve.py catalog_provider seam sees the drift."""
from __future__ import annotations

import copy

import pytest

from backend.errors import (
    CATALOG_CHANGED,
    MCP_CATALOG_MISSING,
    MCP_TOOL_NOT_OBSERVED,
    McpError,
)
from backend.managed import (
    LANE_MANAGED,
    MCP_CATALOG_UNOBSERVABLE,
    MCP_NOT_CONNECTED,
    MCP_TOOL_NOT_APPROVED,
    McpConnectionLease,
    catalog_digest_of,
    make_catalog_provider,
    tool_schema_digest,
)
from managed_helpers import (
    ALLOWING,
    SERVER_SCOPE,
    TOOL_ECHO,
    TOOL_LIST,
    TOOLS_ONE,
    TOOLS_TWO,
)


def _live(harness, tools=TOOLS_ONE):
    caller = harness.caller()
    revision = harness.install_remote()
    authority = ALLOWING()
    manager = harness.manager(authority=authority)
    harness.factory.set(caller.session_ref, "srv-a", tools=tools)
    lease, catalog, client = harness.bring_up(manager, caller, "srv-a", revision)
    return manager, caller, lease, catalog, client, authority


# -- observation provenance ---------------------------------------------------


def test_catalog_store_refuses_observation_over_a_dead_lease(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    lease = manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                               definition_id="srv-a", revision=revision)
    with pytest.raises(McpError) as exc:
        harness.catalogs.record_observation(
            lease, tools=TOOLS_ONE, protocol_version="2024-11-05",
            server_info={"name": "x", "version": "1"})
    assert exc.value.code == MCP_CATALOG_UNOBSERVABLE


def test_closed_lease_can_no_longer_produce_observations(harness):
    manager, caller, lease, _, client, _ = _live(harness)
    lease = harness.leases.get_lease(lease.lease_id, caller)
    manager.close_lease(caller=caller, lease_id=lease.lease_id,
                        owner_id=lease.owner_id)
    with pytest.raises(McpError) as exc:
        manager.observe_catalog(caller=caller, lease_id=lease.lease_id)
    assert exc.value.code == MCP_NOT_CONNECTED
    # the definition remains stored - but it is NOT presented as live:
    with pytest.raises(McpError) as exc2:
        manager.list_tools_for_definition(caller=caller, server_scope=SERVER_SCOPE,
                                          definition_id="srv-a", revision=1)
    assert exc2.value.code == MCP_CATALOG_MISSING


def test_catalog_carries_source_evidence_and_lease_binding(harness):
    manager, caller, lease, catalog, _, _ = _live(harness)
    assert catalog.lease_id == lease.lease_id
    assert catalog.source_evidence["origin"] == "tools-list"
    assert catalog.source_evidence["lane"] == LANE_MANAGED
    assert catalog.source_evidence["lease_state_observed_from"] == "connected"
    assert catalog.protocol_version == "2024-11-05"
    assert catalog.server_info == {"name": "in-memory-fake", "version": "0"}
    assert catalog.status == "current"
    live = manager.list_tools_for_definition(caller=caller, server_scope=SERVER_SCOPE,
                                             definition_id="srv-a", revision=1)
    assert live["catalog"].catalog_digest == catalog.catalog_digest


# -- digests ---------------------------------------------------------------------


def test_digest_is_deterministic_across_order_and_metadata_noise():
    def observe(tools):
        pairs = sorted({(t["name"], tool_schema_digest(t)) for t in tools})
        return catalog_digest_of(definition_id="srv-a", revision=1,
                                 protocol_version="2024-11-05", tools=pairs)
    a = observe([TOOL_ECHO, TOOL_LIST])
    b = observe([copy.deepcopy(TOOL_LIST), copy.deepcopy(TOOL_ECHO)])
    assert a == b and a.startswith("sha256:")
    changed = copy.deepcopy(TOOL_ECHO)
    changed["inputSchema"]["properties"]["text"]["maxLength"] = 10
    assert observe([changed, TOOL_LIST]) != a  # schema drift changes digest


# -- drift ------------------------------------------------------------------------


def test_drift_supersedes_old_digest_books_catalog_changed_and_stales_approval(harness):
    client_tools = [copy.deepcopy(TOOL_ECHO)]
    manager, caller, lease, catalog_v1, client, authority = _live(harness,
                                                                  tools=client_tools)
    lease = harness.leases.get_lease(lease.lease_id, caller)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    ok = manager.call_tool(caller=caller, lease_id=lease.lease_id,
                           owner_id=lease.owner_id, tool_name="echo",
                           arguments={"text": "one"})
    assert ok["catalogDigest"] == catalog_v1.catalog_digest

    # the (fake) server now also exposes "list" -> re-observe drifts
    client.tools.append(copy.deepcopy(TOOL_LIST))
    catalog_v2 = manager.observe_catalog(caller=caller, lease_id=lease.lease_id)
    assert catalog_v2.catalog_digest != catalog_v1.catalog_digest
    assert harness.catalogs.is_digest_current(definition_id="srv-a", revision=1,
                                              catalog_digest=catalog_v1.catalog_digest) is False
    assert harness.catalogs.is_digest_current(definition_id="srv-a", revision=1,
                                              catalog_digest=catalog_v2.catalog_digest)
    facts = [f for f in harness.leases.facts(lease.lease_id, caller)
             if f["kind"] == "catalog-changed"]
    assert len(facts) == 1
    assert facts[0]["fromDigest"] == catalog_v1.catalog_digest
    assert facts[0]["toDigest"] == catalog_v2.catalog_digest
    assert "catalog-changed" in harness.sink.kinds()

    # every frozen approval is stale until re-approved (fail closed, even
    # for the previously approved tool)
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "two"})
    assert exc.value.code == CATALOG_CHANGED
    before = len(client.executed_calls)

    # re-approval covers only explicitly named, still-observed tools; the
    # newly discovered one is NOT in it (no auto-widening)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    again = manager.call_tool(caller=caller, lease_id=lease.lease_id,
                              owner_id=lease.owner_id, tool_name="echo",
                              arguments={"text": "two"})
    assert again["catalogDigest"] == catalog_v2.catalog_digest
    assert len(client.executed_calls) == before + 1
    with pytest.raises(McpError) as exc2:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="list",
                          arguments={})
    assert exc2.value.code == MCP_TOOL_NOT_APPROVED
    # approval can never name an unobserved tool either
    with pytest.raises(McpError) as exc3:
        manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                              owner_id=lease.owner_id, tool_names=["ghost"])
    assert exc3.value.code == MCP_TOOL_NOT_OBSERVED


def test_no_approval_means_nothing_is_callable(harness):
    manager, caller, lease, _, _, _ = _live(harness)
    lease = harness.leases.get_lease(lease.lease_id, caller)
    assert lease.approved_tool_names == () and lease.approved_catalog_digest is None
    authority = manager.permission_authority
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "x"})
    assert exc.value.code == MCP_TOOL_NOT_APPROVED
    assert authority.seen == []  # approval gate sits BEFORE the permission call


# -- resolve.py seam ------------------------------------------------------------


def test_catalog_provider_feeds_resolve_needs_revalidation_on_drift(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    harness.factory.set(caller.session_ref, "srv-a", tools=TOOLS_ONE)
    lease, catalog_v1, _ = harness.bring_up(manager, caller, "srv-a", revision)

    # freeze an allObserved selection against the CURRENT digest via T02 store
    provider = make_catalog_provider(harness.catalogs)
    frozen = provider("srv-a", revision)
    assert frozen == {"catalogDigest": catalog_v1.catalog_digest,
                      "toolNames": ["echo"]}
    harness.assignments.assign(
        server_scope=SERVER_SCOPE, principal=caller.principal,
        scope_kind="session", scope_id=caller.session_ref, harness=None,
        definition_id="srv-a", decision="enable", approved_revision=revision,
        tool_selection={"mode": "allObserved", "names": ["echo"],
                        "catalogDigest": frozen["catalogDigest"]},
        observed_catalog=frozen, expected_row_version=0,
        operation_key="assign-sess-a")

    from backend.resolve import resolve_preview
    quiet = resolve_preview(server_scope=SERVER_SCOPE, principal=caller.principal,
                            assignments=harness.assignments,
                            definitions=harness.definitions,
                            session_ref=caller.session_ref,
                            catalog_provider=provider)
    assert quiet.needs_revalidation == ()

    # drift: a fresh observation with an extra tool must mark the snapshot
    lease_model = harness.leases.get_lease(lease.lease_id, caller)
    harness.catalogs.record_observation(
        McpConnectionLease(**{**lease_model.__dict__, "state": "catalog-observed"}),
        tools=TOOLS_TWO, protocol_version="2024-11-05",
        server_info={"name": "in-memory-fake", "version": "0"})
    drifted = resolve_preview(server_scope=SERVER_SCOPE, principal=caller.principal,
                              assignments=harness.assignments,
                              definitions=harness.definitions,
                              session_ref=caller.session_ref,
                              catalog_provider=provider)
    assert drifted.needs_revalidation == ("srv-a",)
    assert provider("srv-a", revision)["toolNames"] == ["echo", "list"]
    assert provider("srv-a", 999) is None  # unseen revision -> no claim
