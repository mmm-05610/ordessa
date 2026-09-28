"""Unconfirmable outcomes on the HTTP lane go through UNKNOWN_OUTCOME,
never a pretend-known answer (FR-10 / counterexample 7 semantics applied
to the remote格): once a frame was written, a timeout / torn transport /
oversized / non-JSON answer books ``call-outcome-unknown`` and reconcile
is the only way out. And close() proves it owns ONLY the local side.
"""
from __future__ import annotations

import threading
import time
from http.client import HTTPConnection

import pytest

from backend.errors import UNKNOWN_OUTCOME, McpError
from backend.managed.client_http import HttpClientPolicy, HttpManagedClient
from backend.managed.client_stdio import ClientRequestUnconfirmed
from backend.managed.lease import MCP_RECONCILE_REQUIRED
from http_helpers import BRIEF, FAST, HttpRealFactory, secret_remote
from managed_helpers import AllowingAuthority


def _live_client(server, policy=FAST):
    return HttpManagedClient(url=f"{server.base_url}/mcp", policy=policy)


def test_initialize_timeout_parks_the_lease_unknown_and_reconciles(harness, endpoint):
    server = endpoint("slow")
    revision = secret_remote(harness, server.base_url, headers={})
    factory = HttpRealFactory(harness.definitions, policy=BRIEF)
    mgr = harness.manager(authority=AllowingAuthority(), factory=factory)
    caller = harness.caller()
    lease = mgr.open_lease(caller=caller, server_scope="scope-1",
                           definition_id="srv-http", revision=revision)
    mgr.plan_connection(caller=caller, lease_id=lease.lease_id)
    with pytest.raises(McpError) as refused:
        mgr.start_connection(caller=caller, lease_id=lease.lease_id)
    assert refused.value.code == UNKNOWN_OUTCOME
    assert mgr.inspect_connection(caller=caller, lease_id=lease.lease_id)["state"] == "unknown"
    # the client closed its own local session on the unconfirmed outcome
    assert factory.produced[-1].closed
    # a second lease on the same key is refused until reconcile (never a
    # bet that the old client exited)
    with pytest.raises(McpError) as blocked:
        mgr.open_lease(caller=caller, server_scope="scope-1",
                       definition_id="srv-http", revision=revision)
    assert blocked.value.code == MCP_RECONCILE_REQUIRED
    mgr.reconcile(caller=caller, lease_id=lease.lease_id, owner_id=lease.owner_id,
                  outcome="terminated", evidence={"queried": "controlled fake"})
    assert server.methods_seen().count("initialize") == 1  # never auto-retried


def test_oversized_answer_is_unconfirmed_not_truncated(harness, endpoint):
    server = endpoint("oversized-list")
    revision = secret_remote(harness, server.base_url, headers={})
    policy = HttpClientPolicy(request_timeout=5.0, initialize_timeout=5.0,
                              max_response_bytes=2048)
    factory = HttpRealFactory(harness.definitions, policy=policy)
    mgr = harness.manager(authority=AllowingAuthority(), factory=factory)
    caller = harness.caller()
    lease = mgr.open_lease(caller=caller, server_scope="scope-1",
                           definition_id="srv-http", revision=revision)
    mgr.plan_connection(caller=caller, lease_id=lease.lease_id)
    mgr.start_connection(caller=caller, lease_id=lease.lease_id)  # init is small
    with pytest.raises(McpError) as refused:
        mgr.observe_catalog(caller=caller, lease_id=lease.lease_id)
    assert refused.value.code == UNKNOWN_OUTCOME
    assert len(server.requests_for("tools/list")) == 1  # no silent retry


def test_non_json_answer_is_unconfirmed(endpoint):
    server = endpoint("badjson")
    client = _live_client(server)
    client.start()
    with pytest.raises(ClientRequestUnconfirmed):
        client.connect()
    assert client.closed  # unconfirmed handshake tears the local session
    assert server.methods_seen() == ["initialize"]


def test_call_error_answer_is_unconfirmed(endpoint):
    server = endpoint("call_error")
    client = _live_client(server)
    client.start()
    client.connect()
    with pytest.raises(ClientRequestUnconfirmed):
        client.call_tool("echo", {"text": "did-it-run?"})
    # the fake never even executed the tool, but the CLIENT may not claim
    # that: the answer was an error after the frame went out -> unconfirmed
    assert server.calls == []


def test_close_cancels_an_in_flight_call_locally(endpoint):
    server = endpoint("normal")
    client = _live_client(server)
    client.start()
    client.connect()
    server.mode = "hang-call"
    outcome: list = []

    def _call():
        try:
            client.call_tool("echo", {"text": "hang"})
        except BaseException as exc:  # noqa: BLE001 - witness capture
            outcome.append(exc)

    thread = threading.Thread(target=_call, daemon=True)
    thread.start()
    time.sleep(0.3)  # the frame is on the wire, the reader is blocked
    client.close()   # local hang-up must wake the blocked reader at once
    thread.join(timeout=3.0)
    assert not thread.is_alive(), "close did not cancel the in-flight request"
    assert len(outcome) == 1 and isinstance(outcome[0], ClientRequestUnconfirmed)
    assert client.close_fact["remoteServiceLifecycle"] == "not-owned"


def test_close_stops_the_local_session_and_nothing_else(endpoint):
    server = endpoint("normal")
    client = _live_client(server)
    client.start()
    client.connect()
    client.close()
    # the client's own fact says it does NOT own the remote lifecycle
    assert client.close_fact == {"localSessionClosed": True,
                                 "sessionIdDropped": True,
                                 "remoteServiceLifecycle": "not-owned"}
    # asymmetric proof: the remote fake is still serving right after close
    probe = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
    probe.request("POST", "/mcp",
                  body=b'{"jsonrpc":"2.0","id":9,"method":"tools/list"}',
                  headers={"Content-Type": "application/json"})
    answer = probe.getresponse()
    assert answer.status == 200  # nothing remote was stopped by our close
    answer.read()
    probe.close()
