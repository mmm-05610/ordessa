"""T02 (§C1, C3): the plugin registers the authorizer as a provided port and
exposes decide/query for the approval UI - nothing else is authoritative.

The wire methods let the UI decide or query; the ruling itself is reachable
only as `permissions.authorizer@1` in `provided_ports` (the future C0-owned
pre-effect gate consumes that port - the gate seam is still blocked, G1, and
this test suite does NOT fake it). The forged-allow test proves that a desktop
client sending `allow` cannot cause an execution: only a recorded approval
bound to the same operation digest can settle anything.
"""
from __future__ import annotations

import pytest
from server_plugin_api import (ServerPluginContext, ServerPluginRegistration)
from support import (admin_ceiling, approval_record, clock_at, effective_digest,
                     make_operation, seeded_database, seed_session, utc)

from ordessa_permissions_backend import Authorizer, PermissionsBackendPlugin


@pytest.fixture
def built(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    plugin = PermissionsBackendPlugin()
    registration = plugin.build(ServerPluginContext(
        plugin_id="permissions-backend", data_root=tmp_path,
        ports={"database": database}))
    return database, plugin, registration


def test_descriptor_is_a_valid_server_plugin_declaration(built):
    database, plugin, registration = built
    descriptor = plugin.descriptor()
    assert descriptor.id == "permissions-backend"
    assert descriptor.display_name and descriptor.version
    assert isinstance(registration, ServerPluginRegistration)


def test_authorizer_is_the_provided_port_for_the_pre_effect_gate(built):
    database, plugin, registration = built
    port = registration.provided_ports["permissions.authorizer@1"]
    assert isinstance(port, Authorizer)
    # the port speaks the §C1 surface
    for name in ("evaluate", "decide", "reconcile", "busy"):
        assert callable(getattr(port, name)), name


def test_wire_methods_are_declared_exactly(built):
    database, plugin, registration = built
    methods = {m.method_id: m for m in registration.methods}
    assert set(methods) == {"permissions.approvals.decide", "permissions.approvals.query",
                            "permissions.policy.describe"}
    decide = methods["permissions.approvals.decide"]
    assert decide.required_params == frozenset(
        {"requestId", "approvalId", "expectedVersion", "decision", "scope", "sessionId"})
    assert decide.optional_params == frozenset()
    query = methods["permissions.approvals.query"]
    assert query.required_params == frozenset({"approvalId", "nativeRequestId"})
    assert query.optional_params == frozenset()
    assert all(m.owner == "permissions-backend" for m in registration.methods)


def test_a_forged_client_allow_cannot_produce_a_settled_execution(built):
    database, plugin, registration = built
    authorizer = registration.provided_ports["permissions.authorizer@1"]
    authorizer.policies.store_ceiling(admin_ceiling())
    authorizer.ceiling_provider = authorizer.policies.ceilings_current
    authorizer.intent_provider = lambda: None
    authorizer.clock = clock_at(utc())
    ceilings = authorizer.policies.ceilings_current()

    operation = make_operation(ceilings=ceilings, native_request_id="native-w")
    outcome = authorizer.evaluate(
        principal=operation.principal,
        session_ref={"serverInstanceId": operation.server_instance_id,
                    "sessionId": operation.session_id,
                    "nativeSessionId": operation.native_session_id},
        execution_ref=operation.execution_id, native_generation=operation.native_generation,
        tool_identity=operation.tool_key, target_facts={"target": operation.target},
        argument_digest=operation.argument_digest.value,
        ceiling_revision=effective_digest(ceilings), policy_revision="no-intent",
        native_request_id=operation.native_request_id)
    assert outcome.outcome == "pending_approval"
    approval_id = outcome.approval_id

    decide = {m.method_id: m.handler for m in registration.methods}[
        "permissions.approvals.decide"]
    forged = decide({
        "requestId": "attacker-1", "approvalId": "approval_" + "0" * 32,
        "expectedVersion": 1, "decision": "allow", "scope": {"kind": "once"},
        "sessionId": operation.session_id,
    })
    assert forged["outcome"] == "unknown"          # nothing was recorded there
    assert forged["outcome"] != "recorded"

    # The real operation is still only pending - no client message flipped it.
    again = authorizer.evaluate(
        principal=operation.principal,
        session_ref={"serverInstanceId": operation.server_instance_id,
                    "sessionId": operation.session_id,
                    "nativeSessionId": operation.native_session_id},
        execution_ref=operation.execution_id, native_generation=operation.native_generation,
        tool_identity=operation.tool_key, target_facts={"target": operation.target},
        argument_digest=operation.argument_digest.value,
        ceiling_revision=effective_digest(ceilings), policy_revision="no-intent",
        native_request_id=operation.native_request_id)
    assert again.outcome == "pending_approval"

    # Only deciding the recorded approval bound to this operation digest works.
    recorded = decide({
        "requestId": "ui-1", "approvalId": approval_id, "expectedVersion": 1,
        "decision": "allow", "scope": {"kind": "once"}, "sessionId": operation.session_id,
    })
    assert recorded["outcome"] == "recorded"
    row = authorizer.facts.get(approval_id)
    assert row["operationDigest"] == operation.operation_digest
    assert row["state"] == "settled"


def test_query_wire_method_reports_unknown_for_unresolvable_correlation(built):
    database, plugin, registration = built
    query = {m.method_id: m.handler for m in registration.methods}[
        "permissions.approvals.query"]
    body = query({"approvalId": "approval_" + "1" * 32, "nativeRequestId": "native-ghost"})
    assert body["outcome"] == "unknown"


def test_decide_wire_method_validates_the_declared_shape(built):
    database, plugin, registration = built
    decide = {m.method_id: m.handler for m in registration.methods}[
        "permissions.approvals.decide"]
    with pytest.raises(ValueError):
        decide({"requestId": "x", "approvalId": "approval_" + "2" * 32,
                "expectedVersion": 1, "decision": "maybe",
                "scope": {"kind": "once"}, "sessionId": "session-1"})
    with pytest.raises(ValueError):
        decide({"requestId": "x", "approvalId": "approval_" + "2" * 32,
                "expectedVersion": 1, "decision": "allow",
                "scope": {"kind": "forever-and-ever"}, "sessionId": "session-1"})


def test_build_without_the_database_port_fails_closed(tmp_path):
    plugin = PermissionsBackendPlugin()
    with pytest.raises(KeyError):
        plugin.build(ServerPluginContext(plugin_id="permissions-backend",
                                         data_root=tmp_path, ports={}))
