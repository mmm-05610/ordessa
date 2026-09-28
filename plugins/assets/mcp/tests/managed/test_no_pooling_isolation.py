"""Counterexample 3: two sessions, one shared definition, NO pooling - each
gets its own client, catalog and close; A's shutdown never touches B."""
from __future__ import annotations

import pytest

from backend.errors import MCP_OWNER_CONFLICT, McpError
from backend.managed import MCP_TOOL_NOT_APPROVED
from managed_helpers import (
    ALLOWING,
    SERVER_SCOPE,
    TOOLS_ONE,
    TOOLS_TWO,
)


def test_two_sessions_same_url_get_independent_clients_and_catalogs(harness):
    revision = harness.install_remote(url="https://shared.example.test/mcp")
    authority = ALLOWING()
    manager = harness.manager(authority=authority)
    a, b = harness.caller("u-a", "sess-a"), harness.caller("u-b", "sess-b")
    harness.factory.set("sess-a", "srv-a", tools=TOOLS_ONE)
    harness.factory.set("sess-b", "srv-a", tools=TOOLS_TWO)
    lease_a, catalog_a, client_a = harness.bring_up(
        manager, a, "srv-a", revision, credential_revision="cred-rev-1")
    lease_b, catalog_b, client_b = harness.bring_up(
        manager, b, "srv-a", revision, credential_revision="cred-rev-2")

    # no pooling path: the factory was asked twice and got two worlds
    assert harness.factory.production_count == 2
    assert client_a is not client_b
    assert (client_a.start_count, client_a.connect_count) == (1, 1)
    assert (client_b.start_count, client_b.connect_count) == (1, 1)
    assert lease_a.lease_id != lease_b.lease_id
    assert lease_a.credential_revision == "cred-rev-1"
    assert lease_b.credential_revision == "cred-rev-2"
    # catalogs differ per session and never cross
    assert catalog_a.tool_names == ("echo",)
    assert catalog_b.tool_names == ("echo", "list")
    live_a = manager.list_tools_for_definition(caller=a, server_scope=SERVER_SCOPE,
                                               definition_id="srv-a", revision=revision)
    live_b = manager.list_tools_for_definition(caller=b, server_scope=SERVER_SCOPE,
                                               definition_id="srv-a", revision=revision)
    assert live_a["catalog"].catalog_digest == catalog_a.catalog_digest
    assert live_b["catalog"].catalog_digest == catalog_b.catalog_digest

    # A closes: only A's resources are released
    lease_a = harness.leases.get_lease(lease_a.lease_id, a)
    manager.close_lease(caller=a, lease_id=lease_a.lease_id, owner_id=lease_a.owner_id)
    assert client_a.close_count == 1 and client_b.close_count == 0
    assert client_b.connected is True
    # B keeps working with its own lease and catalog
    manager.approve_tools(caller=b, lease_id=lease_b.lease_id,
                          owner_id=lease_b.owner_id, tool_names=["echo", "list"])
    called = manager.call_tool(caller=b, lease_id=lease_b.lease_id,
                               owner_id=lease_b.owner_id, tool_name="list",
                               arguments={})
    assert called["tool"] == "list"
    assert client_b.executed_calls == [("list", {})]


def test_same_session_cannot_stack_a_second_lease_on_one_endpoint(harness):
    # "reuse" attempts on one session are the pooling temptation in disguise:
    # while the first lease is active, the typed refusal is MCP_OWNER_CONFLICT.
    caller = harness.caller()
    revision = harness.install_remote(url="https://shared.example.test/mcp")
    manager = harness.manager()
    manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                       definition_id="srv-a", revision=revision)
    with pytest.raises(McpError) as exc:
        manager.open_lease(caller=caller, server_scope=SERVER_SCOPE,
                           definition_id="srv-a", revision=revision)
    assert exc.value.code == MCP_OWNER_CONFLICT


def test_clients_are_never_shared_even_when_specs_match(harness):
    revision = harness.install_remote(url="https://shared.example.test/mcp")
    manager = harness.manager()
    a, b = harness.caller("u-a", "sess-a"), harness.caller("u-b", "sess-b")
    _, _, client_a = harness.bring_up(manager, a, "srv-a", revision)
    _, _, client_b = harness.bring_up(manager, b, "srv-a", revision)
    assert client_a is not client_b
    # one client's executed calls are invisible to the other
    assert client_a.executed_calls == [] and client_b.executed_calls == []
    manager.approve_tools(caller=a, lease_id=harness.leases.list_leases(a)[0].lease_id,
                          owner_id=harness.leases.list_leases(a)[0].owner_id,
                          tool_names=[])  # empty approval stays legal, calls still gated
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=a,
                          lease_id=harness.leases.list_leases(a)[0].lease_id,
                          owner_id=harness.leases.list_leases(a)[0].owner_id,
                          tool_name="echo", arguments={})
    assert exc.value.code == MCP_TOOL_NOT_APPROVED
