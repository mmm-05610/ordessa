"""Counterexample 3 on the HTTP lane: two sessions, one URL, NO pooling.

Every claim here is read from the SERVER side (issued sessions, accepted
connections, per-request presented session ids), never from client
self-report - "shared state is fine" is disproved, not asserted.
"""
from __future__ import annotations

from http_helpers import FAST, HttpRealFactory, bring_up, secret_remote
from managed_helpers import AllowingAuthority


def _two_sessions(harness, endpoint):
    server = endpoint("normal")
    revision = secret_remote(harness, server.base_url, headers={})
    factory = HttpRealFactory(harness.definitions, policy=FAST)
    mgr = harness.manager(authority=AllowingAuthority(), factory=factory)
    caller_a = harness.caller(session="sess-a")
    caller_b = harness.caller(principal="u-b", session="sess-b")
    lease_a, _ = bring_up(mgr, harness, caller_a, "srv-http", revision)
    lease_b, _ = bring_up(mgr, harness, caller_b, "srv-http", revision)
    client_a, client_b = factory.produced[0], factory.produced[1]
    return server, mgr, factory, lease_a, lease_b, caller_a, caller_b, client_a, client_b


def test_two_sessions_one_url_get_two_independent_http_sessions(harness, endpoint):
    (server, mgr, factory, lease_a, lease_b, caller_a, caller_b,
     client_a, client_b) = _two_sessions(harness, endpoint)

    # distinct instances, distinct connections, distinct server-side sessions
    assert client_a is not client_b
    assert client_a.session_id != client_b.session_id
    assert set(server.sessions_issued) == {client_a.session_id, client_b.session_id}
    assert len(server.sessions_issued) == 2
    assert server.connections == 2  # keep-alive: one TCP session per client

    for lease, caller, client in ((lease_a, caller_a, client_a),
                                  (lease_b, caller_b, client_b)):
        mgr.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
        mgr.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments={"text": client.session_id})
    by_session = {r["presented_session"]
                  for r in server.requests_for("tools/call")}
    assert by_session == {client_a.session_id, client_b.session_id}

    # A closes; B is untouched and keeps calling on ITS OWN session
    mgr.close_lease(caller=caller_a, lease_id=lease_a.lease_id,
                    owner_id=lease_a.owner_id)
    assert client_a.closed and client_b.closed is False
    assert client_b.session_id is not None
    mgr.call_tool(caller=caller_b, lease_id=lease_b.lease_id,
                  owner_id=lease_b.owner_id, tool_name="echo",
                  arguments={"text": "still-alive"})
    assert len(server.requests_for("tools/call")) == 3
    assert server.requests_for("tools/call")[-1]["presented_session"] == client_b.session_id


def test_factory_always_produces_a_fresh_instance(harness, endpoint):
    server = endpoint("normal")
    revision = secret_remote(harness, server.base_url, headers={})
    factory = HttpRealFactory(harness.definitions, policy=FAST)
    mgr = harness.manager(authority=AllowingAuthority(), factory=factory)
    caller = harness.caller()
    lease = mgr.open_lease(caller=caller, server_scope="scope-1",
                           definition_id="srv-http", revision=revision)
    mgr.plan_connection(caller=caller, lease_id=lease.lease_id)
    first = factory(lease)
    second = factory(lease)
    third = factory(lease)
    # no cache, no pool: three calls, three worlds, none sharing a socket
    assert len({id(first), id(second), id(third)}) == 3
    assert first is not second and second is not third
    assert first._connection is None and second._connection is None
    assert len(factory.produced) == 3
    assert server.methods_seen() == []  # production alone touches nothing
