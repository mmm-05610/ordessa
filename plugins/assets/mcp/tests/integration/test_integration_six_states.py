"""T10-INT-05: the six-level fact ladder, each level separable on the WIRE.

The FR-02 requirement: defined -> selected -> planned -> connecting ->
connected -> catalog-observed -> closed are SIX independent facts, never
one boolean. The chain proof: after each real step, ``mcp.inspectConnection``
shows a distinct state, ``levels`` grows exactly one observed entry, and
``mcp.listTools`` distinguishes the two states a caller could otherwise
confuse (connected-without-observation still answers MCP_CATALOG_MISSING —
"connecting/connected is not yet usable", while catalog-observed is; after
close it flips back).

The transient ``connecting`` level is captured with a pure OBSERVER wrapper
around the real client (delegation only; it adds no gate and stubs nothing:
it reads the manager's own inspect face while the real handshake is under
way), so even the level with no stable wire window is proven distinct.

Evidence ID: T10-INT-05.
"""
from __future__ import annotations

from backend.managed.client_stdio import StdioManagedClient


class StateObservingClient:
    """Instrumentation wrapper (delegates EVERYTHING to the real client):
    at chosen lifecycle points it records the lease state as the composed
    manager sees it. No gate, no substitution - a periscope, not a double."""

    def __init__(self, inner: StdioManagedClient, record):
        self._inner = inner
        self._record = record

    def start(self) -> None:
        self._record("at-start", self._state())
        self._inner.start()

    def connect(self):
        answer = self._inner.connect()
        self._record("post-connect", self._state())
        return answer

    def _state(self) -> str:
        return self._manager.inspect_connection(caller=self._caller,
                                                lease_id=self._lease_id)["state"]

    # bind after construction (the manager knows the lease, the factory does not)
    def bind(self, manager, caller, lease_id):
        self._manager = manager
        self._caller = caller
        self._lease_id = lease_id
        return self

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_six_level_ladder_is_distinguishable_from_the_wire(stack):
    captured: dict = {}
    stack.router.wrap = lambda lease, client: (
        StateObservingClient(client, lambda point, state: captured.__setitem__(
            point, state)).bind(stack.service.sessions, stack.caller(),
            lease.lease_id))

    revision, state = stack.install_stdio("ladderdemo", mode="normal")
    caller = stack.caller()
    mgr = stack.service.sessions

    def wire_conn(lease_id):
        return stack.call("mcp.inspectConnection", principal="user-1",
                          sessionRef="session-1", runtimeGeneration=1,
                          leaseId=lease_id)["connection"]

    def list_tools():
        return stack.wire.dispatch("mcp.listTools", {
            "principal": "user-1", "sessionRef": "session-1",
            "runtimeGeneration": 1, "serverScope": "s1",
            "definitionId": "ladderdemo", "revision": 1})

    lease = mgr.open_lease(caller=caller, server_scope="s1",
                           definition_id="ladderdemo", revision=revision)
    conn = wire_conn(lease.lease_id)
    assert conn["state"] == "defined"
    observed = sorted(s for s, f in conn["levels"].items() if f.get("to") == s)
    assert observed == ["defined"]
    stack.expect_refusal("mcp.listTools", family="NOT_FOUND",
                         internal_code="MCP_CATALOG_MISSING",
                         principal="user-1", sessionRef="session-1",
                         runtimeGeneration=1, serverScope="s1",
                         definitionId="ladderdemo", revision=1)

    planned = mgr.plan_connection(caller=caller, lease_id=lease.lease_id,
                                  submission_id="sub-ladder")
    conn = wire_conn(planned.lease_id)
    assert conn["state"] == "planned"
    observed = sorted(s for s, f in conn["levels"].items() if f.get("to") == s)
    assert observed == ["defined", "planned", "selected"]
    assert conn["levels"]["connecting"]["observed"] is False

    mgr.start_connection(caller=caller, lease_id=lease.lease_id)
    # the periscope caught the transient level as a DISTINCT fact...
    assert captured["at-start"] == "connecting"
    assert captured["post-connect"] == "connecting"
    # ...and the wire face shows the settled level with its own evidence
    conn = wire_conn(lease.lease_id)
    assert conn["state"] == "connected"
    connected_fact = conn["levels"]["connected"]
    assert connected_fact.get("to") == "connected"
    assert connected_fact["evidence"]["negotiatedProtocolVersion"] == "2025-11-25"
    # connected is STILL not a usable catalog face: distinguishable from
    # catalog-observed through listTools alone
    stack.expect_refusal("mcp.listTools", family="NOT_FOUND",
                         internal_code="MCP_CATALOG_MISSING",
                         principal="user-1", sessionRef="session-1",
                         runtimeGeneration=1, serverScope="s1",
                         definitionId="ladderdemo", revision=1)

    catalog = mgr.observe_catalog(caller=caller, lease_id=lease.lease_id)
    conn = wire_conn(lease.lease_id)
    assert conn["state"] == "catalog-observed"
    assert conn["catalogDigest"] == catalog.catalog_digest
    tools = list_tools()
    assert sorted(tools["catalog"]["toolNames"]) == ["echo", "peek"]

    mgr.close_lease(caller=caller, lease_id=lease.lease_id,
                    owner_id=lease.owner_id)
    conn = wire_conn(lease.lease_id)
    assert conn["state"] == "closed"
    assert conn["closedAt"]
    stack.expect_refusal("mcp.listTools", family="NOT_FOUND",
                         internal_code="MCP_CATALOG_MISSING",
                         principal="user-1", sessionRef="session-1",
                         runtimeGeneration=1, serverScope="s1",
                         definitionId="ladderdemo", revision=1)
    # every level of the ladder is now an independent booked fact
    conn = wire_conn(lease.lease_id)
    for level in ("defined", "selected", "planned", "connecting", "connected",
                  "catalog-observed"):
        assert conn["levels"][level].get("to") == level, level
