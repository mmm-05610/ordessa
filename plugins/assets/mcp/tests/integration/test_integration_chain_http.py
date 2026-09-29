"""T10-INT-06: the remote lane through the REAL managed HTTP client, with
the rotation refusal cell.

Chain: wire save/approve of a remote definition whose Authorization header
is a ``secretRef`` -> ManagedSessionManager + the real Streamable-HTTP
limited-substitute client against a loopback fake MCP server (ledger
witnesses: per-connection, per-session, per-request with the header it
actually saw) -> catalog observation -> wire assignment frozen against it
-> tools/call through the double gate answered by the real Q5 authority.

Refusal cell (dispatch: 轮换凭据 零副作用): the T07 launch plan is frozen
against the credential revision at composition; after the secret store
ROTATES (new bytes -> new content digest through the real
HostCredentialPort), the next tools/call is refused with PLAN_STALE by the
real ``backend.secret.resolve_for_launch`` INSIDE the client, before a
single byte is written - proven by the server ledger: no new request of any
kind arrives while the gate refuses.

Also proven here: the remote ``not-owned`` close fact and the no-pooling
witness (a reopened lease is a NEW server-visible session).

Evidence ID: T10-INT-06.
"""
from __future__ import annotations

import pytest
from backend.errors import McpError, PLAN_STALE, SECRET_UNRESOLVED
from integration_helpers import (
    SENTINEL,
    FakeCredentialRecords,
    FakeSecretStore,
    Q5World,
    make_stack,
    read_allow_intent,
    wire_q5,
)
from integration_fake_http_server import FakeIntegrationHttpServer


@pytest.fixture
def http_server():
    created: list = []

    def make(mode: str = "normal"):
        server = FakeIntegrationHttpServer(mode)
        created.append(server)
        return server

    yield make
    for server in created:
        server.close()


def test_http_chain_and_rotation_zero_side_effect(tmp_path, http_server):
    server = http_server()
    store = FakeSecretStore()  # rotates: the plan must go stale
    stack = make_stack(tmp_path, host_ports={
        "credentials": FakeCredentialRecords(("cred-1",)),
        "secret_store": store})
    url = f"{server.base_url}/mcp"
    revision = stack.install_remote("webdemo", url, headers={
        "Authorization": {"secretRef": "cred-1"}})

    # the T07 pair the composition hands the http factory (plan bound NOW)
    port = stack.service.credential_port
    _plaintext, bound_revision = port.read("cred-1")
    plan = stack.router.http_launch_plan = _plan_for(bound_revision)
    stack.router.http_credential_port = port

    caller = stack.caller()
    lease, catalog = stack.bring_up(caller, "webdemo", revision)
    assert sorted(catalog.tool_names) == ["echo", "peek"]
    stack.assign_enable("webdemo", catalog_digest=catalog.catalog_digest,
                        names=["echo", "peek"], principal="user-1")

    world = Q5World.build(tmp_path / "q5")
    _adapter, authorizer = wire_q5(stack, world, intent=read_allow_intent(),
                                   tool_key_map={"echo": "read", "peek": "read"})
    mgr = stack.service.sessions
    mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_names=["echo"])

    out = mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                        owner_id=lease.owner_id, tool_name="echo",
                        arguments={"text": "over-http"})
    assert out["result"]["content"][0]["text"] == "echo:over-http"
    assert len(server.calls) == 1
    # server-side witness: the transient Authorization DID ride the request
    assert SENTINEL in server.authorization_seen()
    assert len(server.sessions_issued) == 1  # one server session so far

    # -- rotation cell -----------------------------------------------------
    store.rotate()
    requests_before = len(server.requests)
    with pytest.raises(McpError) as info:
        mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments={"text": "after-rotation"})
    assert info.value.code == PLAN_STALE
    assert len(server.calls) == 1  # side-effect ledger unchanged...
    assert len(server.requests) == requests_before  # ...and ZERO bytes written
    assert SENTINEL not in server.authorization_seen()[requests_before:]

    # -- close: local session drops, remote stays not-owned ----------------
    closed = mgr.close_lease(caller=caller, lease_id=lease.lease_id,
                             owner_id=lease.owner_id)
    assert closed["state"] == "closed"
    client = stack.router.produced[-1][1]
    assert client.remote_service_lifecycle == "not-owned"

    # -- no pooling: a reopened lease is a NEW server-visible session.
    # The composition re-freezes the launch plan after the rotation (a stale
    # plan stays stale; re-resolution is a new plan, exactly T07 semantics) --
    stack.router.http_launch_plan = _plan_for(port.read("cred-1")[1])
    lease2, _ = stack.bring_up(caller, "webdemo", revision)
    assert len(server.sessions_issued) == 2
    mgr.close_lease(caller=caller, lease_id=lease2.lease_id,
                    owner_id=lease2.owner_id)
    # and the sentinel never appears in any event/fact surface of the chain
    facts = stack.call("mcp.inspectConnection", principal="user-1",
                       sessionRef="session-1", runtimeGeneration=1,
                       leaseId=lease2.lease_id)["connection"]["facts"]
    assert SENTINEL not in str(facts)


def test_http_secretref_without_plan_fails_closed(tmp_path, http_server):
    """A declared SecretRef header with no launch plan wired is a typed
    SECRET_UNRESOLVED at client production - the fail-closed G7 convention,
    proven before any request reaches the fake server."""
    server = http_server()
    stack = make_stack(tmp_path)
    revision = stack.install_remote("nosecret", f"{server.base_url}/mcp",
                                    headers={"Authorization": {"secretRef": "cred-x"}})
    caller = stack.caller()
    mgr = stack.service.sessions
    lease = mgr.open_lease(caller=caller, server_scope="s1",
                           definition_id="nosecret", revision=revision)
    mgr.plan_connection(caller=caller, lease_id=lease.lease_id)
    with pytest.raises(McpError) as info:
        mgr.start_connection(caller=caller, lease_id=lease.lease_id)
    assert info.value.code == SECRET_UNRESOLVED
    assert server.calls == []
    # a start() failure before the client lived is a confirmed refusal
    assert mgr.inspect_connection(caller=caller,
                                  lease_id=lease.lease_id)["state"] == "refused"


def _plan_for(bound_revision: str):
    from integration_helpers import CredentialBinding, LaunchPlan

    return LaunchPlan(
        principal="user-1",
        bindings=(CredentialBinding(definition_id="webdemo", revision=1,
                                    slot="Authorization",
                                    credential_id="cred-1",
                                    bound_revision=bound_revision,
                                    kind="header"),),
        session_ref="session-1")
