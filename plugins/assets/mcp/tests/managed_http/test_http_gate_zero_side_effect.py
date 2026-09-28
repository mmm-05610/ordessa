"""The Q4 double gate ahead of the HTTP side-effect door.

``tools/call`` must pass the lease-state + catalog/approval gates AND the
Permission authority (``check_tool_callable``) in ``ManagedSessionManager``
before this client writes a byte; a refusal is proven by the SERVER-side
call ledger staying empty - with a positive control, so the zero means
something.
"""
from __future__ import annotations

import pytest

from backend.errors import PERMISSION_REFUSED, McpError
from backend.managed.lease import MCP_TOOL_NOT_APPROVED
from backend.permissions import PERMISSION_AUTHORITY_ABSENT
from http_helpers import FAST, HttpRealFactory, bring_up, secret_remote
from managed_helpers import AllowingAuthority, DenyingAuthority


def _up(harness, endpoint, authority):
    server = endpoint("normal")
    revision = secret_remote(harness, server.base_url, headers={})
    factory = HttpRealFactory(harness.definitions, policy=FAST)
    mgr = harness.manager(authority=authority, factory=factory)
    caller = harness.caller()
    lease, _ = bring_up(mgr, harness, caller, "srv-http", revision)
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])
    return server, mgr, caller, lease


def test_positive_control_granted_call_reaches_the_server(harness, endpoint):
    authority = AllowingAuthority()
    server, mgr, caller, lease = _up(harness, endpoint, authority)
    mgr.call_tool(caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
                  tool_name="echo", arguments={"text": "count-me"})
    assert len(server.calls) == 1  # the zeros below are only meaningful vs this 1
    assert authority.seen, "the authority gate was actually consulted"


def test_denying_authority_means_the_server_never_sees_a_call(harness, endpoint):
    authority = DenyingAuthority()
    server, mgr, caller, lease = _up(harness, endpoint, authority)
    with pytest.raises(McpError) as refused:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
                      tool_name="echo", arguments={"text": "never"})
    assert refused.value.code == PERMISSION_REFUSED
    assert "tools/call" not in server.methods_seen()
    assert server.calls == []


def test_absent_authority_fails_closed_with_zero_server_calls(harness, endpoint):
    server, mgr, caller, lease = _up(harness, endpoint, None)
    with pytest.raises(McpError) as refused:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
                      tool_name="echo", arguments={"text": "never"})
    assert refused.value.code == PERMISSION_AUTHORITY_ABSENT
    assert "tools/call" not in server.methods_seen()
    assert server.calls == []


def test_unapproved_tool_never_reaches_the_server(harness, endpoint):
    authority = AllowingAuthority()
    server, mgr, caller, lease = _up(harness, endpoint, authority)
    with pytest.raises(McpError) as refused:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
                      tool_name="extra-not-approved", arguments={})
    assert refused.value.code == MCP_TOOL_NOT_APPROVED
    assert authority.seen == []  # the authority is not even asked
    assert server.calls == []
