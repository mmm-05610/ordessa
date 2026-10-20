"""L2 happy path + negotiation honesty of the managed Streamable-HTTP client.

The whole chain (lease -> gates -> real HTTP client -> controlled fake
server) runs through the REAL ``ManagedSessionManager``; the server's own
ledger is the witness.
"""
from __future__ import annotations

import pytest

from backend.errors import MCP_TRANSPORT_UNSUPPORTED, PROTOCOL_MISMATCH, McpError
from backend.managed.client_http import HttpManagedClient
from http_helpers import FAST, HttpRealFactory, bring_up, secret_remote  # noqa: F401
from managed_helpers import AllowingAuthority


def _setup(harness, endpoint, *, mode="normal", definition_id="srv-http", headers=None):
    server = endpoint(mode)
    revision = secret_remote(harness, server.base_url, definition_id=definition_id,
                             headers=headers or {})
    factory = HttpRealFactory(harness.definitions, policy=FAST)
    mgr = harness.manager(authority=AllowingAuthority(), factory=factory)
    return server, mgr, factory, revision


def test_full_roundtrip_through_the_manager(harness, endpoint):
    server, mgr, factory, revision = _setup(harness, endpoint)
    caller = harness.caller()
    lease, catalog = bring_up(mgr, harness, caller, "srv-http", revision)
    client = factory.produced[-1]

    # negotiation facts carry the ACTUAL answered version, not the offer
    inspection = mgr.inspect_connection(caller=caller, lease_id=lease.lease_id)
    assert inspection["levels"]["connected"]["evidence"][
        "negotiatedProtocolVersion"] == "2025-11-25"
    assert catalog.protocol_version == "2025-11-25"
    # the handshake completed server-side (initialized notification arrived)
    assert server.initialized_notifications == 1
    # the server-issued session id lives on this instance and is echoed
    assert client.session_id in server.sessions_issued
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])
    result = mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                           owner_id=lease.owner_id, tool_name="echo",
                           arguments={"text": "hello-http"})
    assert "hello-http" in str(result["result"])
    assert len(server.calls) == 1
    call_record = server.requests_for("tools/call")[0]
    assert call_record["presented_session"] == client.session_id
    assert call_record["protocol_version_header"] == "2025-11-25"

    closed = mgr.close_lease(caller=caller, lease_id=lease.lease_id,
                             owner_id=lease.owner_id)
    assert closed["state"] == "closed"
    assert client.closed and client.session_id is None
    assert client.close_fact["remoteServiceLifecycle"] == "not-owned"


def test_downgrade_records_the_actual_negotiated_version(harness, endpoint):
    server, mgr, factory, revision = _setup(harness, endpoint, mode="downgrade")
    caller = harness.caller()
    lease, catalog = bring_up(mgr, harness, caller, "srv-http", revision)
    client = factory.produced[-1]
    # the server answered 2024-11-05: that is what is recorded, nowhere the
    # offered 2025-11-25
    assert client.negotiated_protocol_version == "2024-11-05"
    assert catalog.protocol_version == "2024-11-05"
    assert server.requests_for("tools/list")[0]["protocol_version_header"] == "2024-11-05"


def test_sse_framed_tools_list_is_accepted(harness, endpoint):
    server, mgr, factory, revision = _setup(harness, endpoint, mode="sse-list")
    caller = harness.caller()
    lease, catalog = bring_up(mgr, harness, caller, "srv-http", revision)
    assert catalog.tool_names == ("echo",) or list(catalog.tool_names) == ["echo"]
    assert server.methods_seen().count("tools/list") == 1


def test_unsupported_protocol_version_is_a_typed_refusal(harness, endpoint):
    server = endpoint("mismatch")
    client = HttpManagedClient(url=f"{server.base_url}/mcp", policy=FAST)
    client.start()
    with pytest.raises(McpError) as refused:
        client.connect()
    assert refused.value.code == PROTOCOL_MISMATCH
    # the local session is torn down by the refusal...
    assert client.closed
    assert client.close_fact["remoteServiceLifecycle"] == "not-owned"
    # ...and exactly one frame ever reached the wire (the initialize).
    assert server.methods_seen() == ["initialize"]


def test_initialize_refused_by_server_surfaces_protocol_mismatch(harness, endpoint):
    server = endpoint("init_error")
    client = HttpManagedClient(url=f"{server.base_url}/mcp", policy=FAST)
    client.start()
    with pytest.raises(McpError) as refused:
        client.connect()
    assert refused.value.code == PROTOCOL_MISMATCH
    assert client.closed
    assert server.methods_seen() == ["initialize"]


def test_stdio_lease_is_a_typed_refusal_for_the_http_factory(harness, endpoint):
    endpoint()  # no server needed; the refusal must happen before any use
    revision = harness.install_stdio(definition_id="srv-stdio")
    factory = HttpRealFactory(harness.definitions, policy=FAST)
    mgr = harness.manager(authority=AllowingAuthority(), factory=factory)
    caller = harness.caller()
    lease = mgr.open_lease(caller=caller, server_scope="scope-1",
                           definition_id="srv-stdio", revision=revision)
    mgr.plan_connection(caller=caller, lease_id=lease.lease_id)
    with pytest.raises(McpError) as refused:
        mgr.start_connection(caller=caller, lease_id=lease.lease_id)
    assert refused.value.code == MCP_TRANSPORT_UNSUPPORTED
