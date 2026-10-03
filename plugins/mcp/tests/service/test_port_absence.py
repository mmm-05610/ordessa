"""§1 row 6 under absent providers + lease visibility isolation.

`planForSubmission` is REGISTERED and availability-marked planned (the real
mechanism: `ServerMethodDescriptor.availability`, hello says supported=False
with a reason) while its handler answers typed refusals at dispatch:
``APPLICATION_PORT_ABSENT`` without the Harness gate, and — with a gate
injected as a composition seam — the credential layers' own fail-closed
``SECRET_UNRESOLVED``. No path here ever produces a submission success
without its provider, and no provider here is production (gap G3/G2 in
specs/011-q4-mcp/api-requests.md)."""
from __future__ import annotations

from service_helpers import (
    FakeCredentialRecords,
    FakeSecretStore,
    FakeSubmissionGate,
    Stack,
    make_client,
    seed_revision,
)

from backend.managed.lease import LeaseCaller

BASE = {"serverScope": "s1", "principal": "alice", "sessionRef": "sess-1",
        "runtimeGeneration": 1}


def test_plan_without_submission_gate_refuses_and_stays_planned(tmp_path):
    stack = Stack(tmp_path)
    answer = stack.call("server.hello", clientVersions=["wire/1"],
                        clientPresentationSupports=[])
    entry = next(c for c in answer["capabilities"] if c["id"] == "mcp.planForSubmission")
    assert entry == {"id": "mcp.planForSubmission", "supported": False,
                     "reason": "MCP_SUBMISSION_GATE_UNWIRED"}
    stack.expect_refusal("mcp.planForSubmission",
                         family="CAPABILITY_UNSUPPORTED",
                         internal_code="APPLICATION_PORT_ABSENT", **BASE)


def test_plan_with_gate_but_unwired_credentials_refuses_secret(tmp_path):
    gate = FakeSubmissionGate()
    stack = Stack(tmp_path, host_ports={"harness.submission_gate": gate},
                  client_factory=make_client)
    seed_revision(stack, TOKEN={"secretRef": "cred-1"})
    _enable_with_catalog(stack)
    # the snapshot carries the credential binding; the composition has no
    # `credentials`/`secret_store` facades -> fail-closed, whole batch dark
    stack.expect_refusal("mcp.planForSubmission",
                         family="UNAVAILABLE", internal_code="SECRET_UNRESOLVED", **BASE)
    assert gate.planned == []  # the gate was never reached


def test_plan_with_gate_and_credential_layers_completes_through_the_gate(tmp_path):
    gate = FakeSubmissionGate()
    stack = Stack(tmp_path, host_ports={
        "harness.submission_gate": gate,
        "credentials": FakeCredentialRecords(),
        "secret_store": FakeSecretStore(),
    }, client_factory=make_client)
    seed_revision(stack, TOKEN={"secretRef": "cred-1"})
    _enable_with_catalog(stack)
    answer = stack.call("mcp.planForSubmission", **BASE)
    assert answer["submission"]["status"] == "planned-by-gate"
    assert answer["snapshotDigest"].startswith("sha256:")
    refs = answer["credentialReferences"]
    assert refs and refs[0]["credentialId"] == "cred-1"
    assert refs[0]["boundRevision"].startswith("sha256:")
    # FR-08: the answer carries slot + credential id + revisions ONLY
    assert FakeSecretStore.PLAINTEXT not in str(answer)


def _enable_with_catalog(stack):
    service = stack.host.provided_port("asset.mcp.v2")
    caller = LeaseCaller("alice", "sess-1", 1)
    lease = service.sessions.open_lease(
        caller=caller, server_scope="s1", definition_id="demo", revision=1)
    service.sessions.plan_connection(caller=caller, lease_id=lease.lease_id)
    service.sessions.start_connection(caller=caller, lease_id=lease.lease_id)
    catalog = service.sessions.observe_catalog(caller=caller, lease_id=lease.lease_id)
    stack.call("mcp.assign", serverScope="s1", principal="alice",
               scopeKind="user-default", scopeId="alice", definitionId="demo",
               decision="enable", approvedRevision=1,
               toolSelection={"mode": "allowNames", "names": ["read_file"],
                              "catalogDigest": catalog.catalog_digest},
               expectedRowVersion=0, operationKey="op-assign-live")
    return lease


def test_lease_visibility_never_leaks_across_sessions(tmp_path):
    stack = Stack(tmp_path, client_factory=make_client)
    seed_revision(stack)
    lease = _enable_with_catalog(stack)
    # same principal, another session: the lease is invisible, and the
    # refusal says only "missing" — no fingerprint, no state, no existence
    stack.expect_refusal("mcp.inspectConnection",
                         family="NOT_FOUND", internal_code="MCP_LEASE_MISSING",
                         principal="alice", sessionRef="sess-other",
                         runtimeGeneration=1, leaseId=lease.lease_id)
    stack.expect_refusal("mcp.listTools",
                         family="NOT_FOUND", internal_code="MCP_CATALOG_MISSING",
                         principal="bob", sessionRef="sess-1", runtimeGeneration=1,
                         serverScope="s1", definitionId="demo", revision=1)
    # the owning caller does see it
    ok = stack.call("mcp.inspectConnection", principal="alice", sessionRef="sess-1",
                    runtimeGeneration=1, leaseId=lease.lease_id)
    assert ok["connection"]["leaseId"] == lease.lease_id


def test_start_without_client_factory_answers_factory_missing(tmp_path):
    """Even bypassing the wire, the managed lane's honest answer with no
    real SDK client composed is MCP_CLIENT_FACTORY_MISSING — no fake
    connection, no started process (L0/L1, G2/G4 open)."""
    import pytest

    from backend.errors import McpError

    stack = Stack(tmp_path)  # client_factory=None (the production default today)
    seed_revision(stack)
    service = stack.host.provided_port("asset.mcp.v2")
    caller = LeaseCaller("alice", "sess-1", 1)
    lease = service.sessions.open_lease(
        caller=caller, server_scope="s1", definition_id="demo", revision=1)
    service.sessions.plan_connection(caller=caller, lease_id=lease.lease_id)
    with pytest.raises(McpError) as info:
        service.sessions.start_connection(caller=caller, lease_id=lease.lease_id)
    assert info.value.code == "MCP_CLIENT_FACTORY_MISSING"
    # nothing was started: the lease is a confirmed refusal, key released
    assert service.leases.get_lease(lease.lease_id, caller).state == "refused"
