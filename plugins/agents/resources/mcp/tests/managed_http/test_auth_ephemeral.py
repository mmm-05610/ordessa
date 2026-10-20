"""FR-05/FR-08 on the HTTP lane: auth headers are transient, fail-closed,
and provably never plaintext anywhere else (counterexample 8).

The credential arrives at the wire ONLY through ``resolve_for_launch`` at
the instant a request is built. Every refusal here (missing plan, missing
slot binding, rotation, expiry) happens BEFORE a single request body is
written - proven by the server's request ledger staying empty.
"""
from __future__ import annotations

import time

import pytest

from backend.errors import AUTH_REQUIRED, SECRET_UNRESOLVED, McpError
from backend.secret import PLAN_STALE
from backend.definition import SecretRef
from backend.managed.client_http import HttpManagedClient
from http_helpers import (
    CRED_ID, FAST, HEADER_SLOT, SENTINEL, FakeCredentialPort, HttpRealFactory,
    bring_up, make_plan, plaintext_hits, secret_remote,
)
from managed_helpers import AllowingAuthority


def _client(server, *, plan, port, policy=FAST, headers=None):
    return HttpManagedClient(
        url=f"{server.base_url}/mcp",
        headers=headers if headers is not None else {HEADER_SLOT: SecretRef(CRED_ID)},
        launch_plan=plan, credential_port=port, policy=policy)


def test_secret_header_reaches_server_and_plaintext_stays_everywhere_else(harness, endpoint):
    server = endpoint("normal")
    revision = secret_remote(harness, server.base_url)
    port = FakeCredentialPort()
    plan = make_plan(definition_id="srv-http", revision=revision)
    factory = HttpRealFactory(harness.definitions, policy=FAST,
                              launch_plan=plan, credential_port=port)
    mgr = harness.manager(authority=AllowingAuthority(), factory=factory)
    caller = harness.caller()
    lease, _ = bring_up(mgr, harness, caller, "srv-http", revision,
                        credential_revision=port.revision)
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])
    result = mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                           owner_id=lease.owner_id, tool_name="echo",
                           arguments={"text": "authed-call"})
    client = factory.produced[-1]

    # ON THE WIRE: every request carried the resolved header (that is the
    # "live client MAY carry an ephemeral auth header" half of the
    # probe/live split - the probe never does)
    for method in ("initialize", "tools/list", "tools/call"):
        assert all(r["authorization"] == SENTINEL
                   for r in server.requests_for(method)), method
    assert port.reads >= 3  # resolved per request, never cached

    # NOWHERE ELSE: events, lease facts, return values, client state, and
    # the exception channels all scan clean for the sentinel.
    assert plaintext_hits(harness.sink.events) == []
    assert plaintext_hits(mgr.inspect_connection(caller=caller,
                                                 lease_id=lease.lease_id)) == []
    assert plaintext_hits(result) == []
    assert plaintext_hits(dict(client.__dict__)) == []
    assert plaintext_hits(str(client)) == []
    assert port.reads >= 3  # still only ever resolved into local dicts


def test_secret_ref_without_plan_fails_closed_before_any_request(harness, endpoint):
    server = endpoint("normal")
    revision = secret_remote(harness, server.base_url)
    factory = HttpRealFactory(harness.definitions, policy=FAST)  # no plan/port
    mgr = harness.manager(authority=AllowingAuthority(), factory=factory)
    caller = harness.caller()
    lease = mgr.open_lease(caller=caller, server_scope="scope-1",
                           definition_id="srv-http", revision=revision)
    mgr.plan_connection(caller=caller, lease_id=lease.lease_id)
    with pytest.raises(McpError) as refused:
        mgr.start_connection(caller=caller, lease_id=lease.lease_id)
    assert refused.value.code == SECRET_UNRESOLVED
    assert SENTINEL not in refused.value.message
    assert server.methods_seen() == []  # nothing ever touched the wire


def test_missing_slot_binding_refused_before_the_wire(harness, endpoint):
    server = endpoint("normal")
    port = FakeCredentialPort()
    plan = make_plan(definition_id="srv-x", revision=1, with_binding=False)
    client = _client(server, plan=plan, port=port)
    client.start()
    with pytest.raises(McpError) as refused:
        client.connect()
    assert refused.value.code == SECRET_UNRESOLVED
    assert HEADER_SLOT in refused.value.message  # names slots, never values
    assert SENTINEL not in refused.value.message
    assert server.methods_seen() == []


def test_rotated_credential_makes_the_plan_stale_zero_requests(harness, endpoint):
    server = endpoint("normal")
    port = FakeCredentialPort()
    plan = make_plan(definition_id="srv-x", revision=1)
    client = _client(server, plan=plan, port=port)
    port.rotate()  # the store moves under the frozen plan
    client.start()
    with pytest.raises(McpError) as refused:
        client.connect()
    assert refused.value.code == PLAN_STALE
    assert SENTINEL not in refused.value.message
    assert server.methods_seen() == []


def test_revoked_credential_is_secret_unresolved(harness, endpoint):
    server = endpoint("normal")
    port = FakeCredentialPort()
    plan = make_plan(definition_id="srv-x", revision=1)
    client = _client(server, plan=plan, port=port)
    port.revoke()
    client.start()
    with pytest.raises(McpError) as refused:
        client.connect()
    assert refused.value.code == SECRET_UNRESOLVED
    assert server.methods_seen() == []


def test_expired_plan_refused_without_touching_the_store(harness, endpoint):
    server = endpoint("normal")
    port = FakeCredentialPort()
    plan = make_plan(definition_id="srv-x", revision=1,
                     expires_at=time.time() - 10)
    client = _client(server, plan=plan, port=port)
    client.start()
    with pytest.raises(McpError) as refused:
        client.connect()
    assert refused.value.code == PLAN_STALE
    assert port.reads == 0  # an expired plan never resolves anything
    assert server.methods_seen() == []


def test_close_clears_every_credential_reference(harness, endpoint):
    server = endpoint("normal")
    port = FakeCredentialPort()
    plan = make_plan(definition_id="srv-x", revision=1)
    client = _client(server, plan=plan, port=port)
    client.start()
    answer = client.connect()
    assert answer["protocolVersion"] == "2025-11-25"
    client.close()
    assert client._launch_plan is None and client._credential_port is None
    with pytest.raises(McpError) as refused:
        client._request_headers()
    assert refused.value.code == SECRET_UNRESOLVED
    with pytest.raises(McpError) as closed_use:
        client.list_tools()
    assert closed_use.value.code == "MCP_CLIENT_CLOSED"
    assert plaintext_hits(dict(client.__dict__)) == []


def test_server_401_is_a_confirmed_auth_required_refusal(harness, endpoint):
    server = endpoint("require-auth", expected_secret="a-different-value")
    port = FakeCredentialPort()
    plan = make_plan(definition_id="srv-x", revision=1)
    client = _client(server, plan=plan, port=port)
    client.start()
    with pytest.raises(McpError) as refused:
        client.connect()
    assert refused.value.code == AUTH_REQUIRED
    assert SENTINEL not in refused.value.message
    assert server.refusals == ["401"]
    assert server.methods_seen() == ["initialize"]  # refused, never retried


def test_unauthorized_plain_client_never_inherits_ambient_credentials(harness, endpoint):
    # a definition with NO declared headers sends NO Authorization header,
    # even while the process env could offer one (never ambient, FR-08)
    server = endpoint("require-auth", expected_secret=SENTINEL)
    revision = secret_remote(harness, server.base_url, headers={})
    factory = HttpRealFactory(harness.definitions, policy=FAST)
    client = factory(_FakeLease(harness, revision))
    client.start()
    with pytest.raises(McpError) as refused:
        client.connect()
    assert refused.value.code == AUTH_REQUIRED
    assert server.requests_for("initialize")[0]["authorization"] is None


class _FakeLease:
    def __init__(self, harness, revision):
        self.server_scope = "scope-1"
        self.definition_id = "srv-http"
        self.revision = revision
