"""Sole ownership & non-disclosure: foreign principals/sessions get a uniform
not-found, only the owner may close, and close is once-effective + replayable."""
from __future__ import annotations

import pytest

from backend.errors import MCP_CATALOG_MISSING, MCP_OWNER_CONFLICT, McpError
from backend.managed import MCP_LEASE_MISSING
from managed_helpers import ALLOWING, SERVER_SCOPE, TOOLS_ONE


def _live_lease(harness, manager=None, caller=None, definition_id="srv-a"):
    caller = caller or harness.caller()
    revision = harness.install_remote(definition_id)
    manager = manager or harness.manager()
    harness.factory.set(caller.session_ref, definition_id, tools=TOOLS_ONE)
    lease, _, _ = harness.bring_up(manager, caller, definition_id, revision)
    lease = harness.leases.get_lease(lease.lease_id, caller)
    return manager, caller, lease


def test_foreign_principal_cannot_see_the_lease_at_all(harness):
    manager, caller, lease = _live_lease(harness)
    intruder = harness.caller("u-evil", "sess-evil")
    with pytest.raises(McpError) as exc:
        manager.inspect_connection(caller=intruder, lease_id=lease.lease_id)
    assert exc.value.code == MCP_LEASE_MISSING
    # non-disclosure: the refusal reveals no id, fingerprint, catalog or owner
    assert lease.lease_id not in str(exc.value)
    assert lease.endpoint_fingerprint not in str(exc.value)
    with pytest.raises(McpError) as exc2:
        manager.call_tool(caller=intruder, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_name="echo",
                          arguments={"text": "hi"})
    assert exc2.value.code == MCP_LEASE_MISSING


def test_same_principal_foreign_session_cannot_read_the_catalog(harness):
    manager, caller, lease = _live_lease(harness)
    other_session = harness.caller("u-a", "sess-other")
    with pytest.raises(McpError) as exc:
        manager.inspect_connection(caller=other_session, lease_id=lease.lease_id)
    assert exc.value.code == MCP_LEASE_MISSING
    # A's live connection is not visible as a catalog for B's session either.
    with pytest.raises(McpError) as exc2:
        manager.list_tools_for_definition(caller=other_session,
                                          server_scope=SERVER_SCOPE,
                                          definition_id="srv-a", revision=1)
    assert exc2.value.code == MCP_CATALOG_MISSING
    # and the owner's own session does see it (the refusal is isolation, not
    # a broken read path)
    mine = manager.list_tools_for_definition(caller=caller,
                                             server_scope=SERVER_SCOPE,
                                             definition_id="srv-a", revision=1)
    assert [name for name, _ in mine["catalog"].tool_names_and_schema_digests] == ["echo"]


def test_close_requires_the_sole_owner_and_leaks_nothing(harness):
    manager, caller, lease = _live_lease(harness)
    client = harness.factory.produced[-1]
    with pytest.raises(McpError) as exc:
        manager.close_lease(caller=caller, lease_id=lease.lease_id,
                            owner_id="owner-not-it")
    assert exc.value.code == MCP_OWNER_CONFLICT
    assert client.close_count == 0  # refused attempt never reached the client
    result = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    assert result["state"] == "closed"
    assert client.close_count == 1


def test_owner_close_is_effective_once_and_idempotently_replayable(harness):
    manager, caller, lease = _live_lease(harness)
    client = harness.factory.produced[-1]
    first = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                owner_id=lease.owner_id)
    second = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                 owner_id=lease.owner_id)
    third = manager.close_lease(caller=caller, lease_id=lease.lease_id,
                                owner_id=lease.owner_id)
    assert first["replayed"] is False
    assert second["replayed"] is True and third["replayed"] is True
    assert second["cleanupEvidence"] == first["cleanupEvidence"]
    assert client.close_count == 1  # no double release, no leak
    assert client.start_count == 1 and client.connect_count == 1


def test_call_tool_requires_the_owner_even_for_the_right_principal(harness):
    manager, caller, lease = _live_lease(harness, manager=harness.manager(
        authority=ALLOWING()))
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    with pytest.raises(McpError) as exc:
        manager.call_tool(caller=caller, lease_id=lease.lease_id,
                          owner_id="owner-wrong", tool_name="echo",
                          arguments={"text": "x"})
    assert exc.value.code == MCP_OWNER_CONFLICT
    client = harness.factory.produced[-1]
    assert client.executed_calls == []
