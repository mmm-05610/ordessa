"""T019 (C0 request #2): the old `approvals.decide` wire route, delegated to
the ONE Q5 authorizer.

C0's counterexample: a temporary SQLite `build_runtime` can activate
`PermissionsBackendPlugin` beside the default compat plugin, and then BOTH
`approvals.decide` and `permissions.approvals.decide` write `server_approvals`
while the Q5 `permissions.authorizer@1` port exists. The migration rule is
verbatim: "The single-writer migration must preserve existing IDs/data/events,
route any retained old wire method through one Q5 authorizer, and refuse
absent native operation/session/generation facts before a grant can act."

This suite proves the delegation half (the backend's share):

* `LegacyApprovalDelegate` accepts the OLD wire shape - params exactly as
  `plugins/server-compat/src/ordessa_server_compat/core_wire.py:327-329`
  declares `approvals.decide` (`requestId, approvalId, expectedVersion,
  decision, scope`; no optional, no `sessionId`) - and routes it into the
  SAME `Authorizer.decide`: one store, one event stream, CAS +
  `decideRequestId` idempotency preserved, IDs/tables/event names unchanged.
* a record without the native operation/session/generation facts a grant
  needs is REFUSED (typed unknown) BEFORE the decision writes - never
  silently permitted;
* registration is gated by `PermissionsBackendPlugin(approval_route=
  "legacy-delegated")`, never automatic, and the dual-authority hazard (old
  writer still owning the route) is detected by the platform's own
  `DuplicateMethodError` at activation.
"""
from __future__ import annotations

import json

import pytest
from ordessa_server_compat.approvals.records import ApprovalRecords
from server_plugin_api import (DuplicateMethodError, ServerMethodDescriptor,
                               ServerPluginContext, ServerPluginDescriptor,
                               ServerPluginRegistration)
from support import (admin_ceiling, append_event, approval_record, clock_at,
                     make_operation, seeded_database, seed_session, utc)

from ordessa_permissions_backend import PermissionsBackendPlugin
from ordessa_permissions_backend.errors import DualAuthorityError
from ordessa_permissions_backend.plugin import PLUGIN_ID

#: The OLD wire shape, mirrored from core_wire.py:327-329 (required set) -
#: asserted against the compat source text below so the mirror cannot drift.
LEGACY_REQUIRED = frozenset({"requestId", "approvalId", "expectedVersion", "decision",
                             "scope"})


def _new_host(database, data_root):
    from ordessa_server.plugin_host import (MethodRegistry, ServerPluginHost,
                                            StreamRouteRegistry)
    return ServerPluginHost(methods=MethodRegistry(),
                            stream_routes=StreamRouteRegistry(),
                            data_root=data_root,
                            host_ports={"database": database})


class _OldWriterPlugin:
    """A stand-in for the still-mounted compat route: it owns
    `approvals.decide` exactly like `ServerCompatPlugin` does today."""

    def descriptor(self):
        return ServerPluginDescriptor(id="legacy-approvals",
                                      display_name="legacy approvals writer",
                                      version="1")

    def build(self, context):
        return ServerPluginRegistration(methods=(ServerMethodDescriptor(
            method_id="approvals.decide", required_params=LEGACY_REQUIRED,
            optional_params=frozenset(), owner="legacy-approvals",
            handler=lambda params: {"outcome": "recorded",
                                    "decision": params["decision"]}),))


@pytest.fixture
def delegated(tmp_path):
    """The plugin built with the legacy route delegated to the Q5 authorizer."""
    database = seeded_database(tmp_path)
    seed_session(database)
    plugin = PermissionsBackendPlugin(approval_route="legacy-delegated")
    registration = plugin.build(ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=tmp_path, ports={"database": database}))
    authorizer = registration.provided_ports["permissions.authorizer@1"]
    authorizer.policies.store_ceiling(admin_ceiling())
    authorizer.clock = clock_at(utc())
    handlers = {m.method_id: m for m in registration.methods}
    return database, plugin, registration, authorizer, handlers


def _pending_facts_row(authorizer, *, native="native-deleg"):
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id=native)
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    authorizer.facts.request(session_id=operation.session_id,
                             execution_id=operation.execution_id, request=record)
    return record["approvalId"], operation


def _legacy_params(approval_id, *, request_id="legacy-req", decision="allow",
                   expected_version=1, scope=None):
    # The OLD wire shape exactly: no `sessionId` field.
    return {"requestId": request_id, "approvalId": approval_id,
            "expectedVersion": expected_version, "decision": decision,
            "scope": scope or {"kind": "once"}}


def _settled_events(database):
    with database.read() as conn:
        return conn.execute(
            "SELECT data_json FROM server_session_events WHERE kind='approval.settled'"
        ).fetchall()


# -- gating: the route exists only when composition says so ---------------------


def test_default_route_declares_no_legacy_method(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    registration = PermissionsBackendPlugin().build(ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=tmp_path, ports={"database": database}))
    assert "approvals.decide" not in {m.method_id for m in registration.methods}


def test_unknown_approval_route_is_a_declaration_error(tmp_path):
    database = seeded_database(tmp_path)
    with pytest.raises(ValueError):
        PermissionsBackendPlugin(approval_route="whatever")


def test_delegated_route_declares_the_old_wire_shape_exactly(delegated):
    database, plugin, registration, authorizer, handlers = delegated
    legacy = handlers["approvals.decide"]
    assert legacy.required_params == LEGACY_REQUIRED
    assert legacy.optional_params == frozenset()
    assert legacy.owner == PLUGIN_ID
    # the mirror cannot drift from the compat source it replaces: read the
    # compatibility core's own declared shape (`core_wire._PARAM_SHAPES`,
    # the literal `TransitionCorePlugin` declares `approvals.decide` from)
    from ordessa_server_compat import core_wire
    old_required, old_optional = core_wire._PARAM_SHAPES["approvals.decide"]
    assert frozenset(old_required) == LEGACY_REQUIRED
    assert frozenset(old_optional) == handlers["approvals.decide"].optional_params


# -- one authority: the delegated route writes through the SAME authorizer ------


def test_delegated_decide_records_through_the_q5_authority(delegated):
    database, plugin, registration, authorizer, handlers = delegated
    approval_id, _ = _pending_facts_row(authorizer)
    body = handlers["approvals.decide"].handler(_legacy_params(approval_id))
    assert body["outcome"] == "recorded"
    assert body["decision"] == "allow"
    row = authorizer.facts.get(approval_id)
    assert row["state"] == "settled" and row["version"] == 2
    assert row["decision"] == "allow"
    assert row["request"]["decideRequestId"] == "legacy-req"  # idempotency fact kept


def test_delegated_decide_replays_by_request_id_never_deciding_twice(delegated):
    database, plugin, registration, authorizer, handlers = delegated
    approval_id, _ = _pending_facts_row(authorizer, native="native-deleg-2")
    decide = handlers["approvals.decide"].handler
    assert decide(_legacy_params(approval_id))["outcome"] == "recorded"
    replay = decide(_legacy_params(approval_id))
    assert replay["outcome"] == "already_recorded"
    assert replay["decision"] == "allow"
    assert authorizer.facts.get(approval_id)["version"] == 2
    assert len(_settled_events(database)) == 1


def test_delegated_decide_preserves_ids_table_and_event_names(delegated):
    database, plugin, registration, authorizer, handlers = delegated
    approval_id, _ = _pending_facts_row(authorizer, native="native-deleg-3")
    handlers["approvals.decide"].handler(_legacy_params(approval_id))
    with database.read() as conn:  # the SAME table, the SAME minted id
        row = conn.execute("SELECT * FROM server_approvals WHERE id=?",
                           (approval_id,)).fetchone()
        assert row is not None and row["id"] == approval_id
        kinds = [item["kind"] for item in conn.execute(
            "SELECT kind FROM server_session_events WHERE turn_id='turn-1'").fetchall()]
    assert kinds == ["approval.requested", "approval.settled"]


def test_delegated_version_conflict_is_typed_never_an_overwrite(delegated):
    database, plugin, registration, authorizer, handlers = delegated
    approval_id, _ = _pending_facts_row(authorizer, native="native-deleg-4")
    handlers["approvals.decide"].handler(_legacy_params(approval_id, request_id="a"))
    stale = handlers["approvals.decide"].handler(
        _legacy_params(approval_id, request_id="b", expected_version=1))
    assert stale["outcome"] == "version_conflict"
    assert authorizer.facts.get(approval_id)["decision"] == "allow"


def test_delegated_shape_checks_mirror_the_old_wire(delegated):
    database, plugin, registration, authorizer, handlers = delegated
    approval_id, _ = _pending_facts_row(authorizer, native="native-deleg-5")
    decide = handlers["approvals.decide"].handler
    with pytest.raises(ValueError):       # missing param -> refused, nothing written
        decide({"approvalId": approval_id, "expectedVersion": 1,
                "decision": "allow", "scope": {"kind": "once"}})
    with pytest.raises(ValueError):
        decide(_legacy_params(approval_id, decision="maybe"))
    with pytest.raises(ValueError):       # old rule: `once` carries no other fields
        decide(_legacy_params(approval_id, scope={"kind": "once", "extra": 1}))
    with pytest.raises(ValueError):       # old rule: bounded must be until=session_end
        decide(_legacy_params(approval_id, scope={"kind": "bounded", "until": "forever",
                                                  "environmentId": None}))
    assert len(_settled_events(database)) == 0


# -- refuse absent native facts BEFORE a grant can act ---------------------------


def test_legacy_written_row_is_refused_for_missing_native_facts(delegated):
    """A row the old writer minted has no nativeRequestId/operationDigest/
    nativeGeneration. Delegating the route may NOT silently keep deciding
    such rows: the refusal is typed, the row stays open and queryable."""
    database, plugin, registration, authorizer, handlers = delegated
    legacy = ApprovalRecords(database, append_event=append_event)
    approval = legacy.request(session_id="session-1", execution_id="turn-1",
                              request={"requestId": "req-1", "tool": "bash",
                                       "summary": "run a command"})
    body = handlers["approvals.decide"].handler(_legacy_params(approval["approvalId"]))
    assert body["outcome"] == "unknown"
    assert "native" in body["reason"] and "missing" in body["reason"]
    assert body.get("grantsExecution", False) is False
    row = authorizer.facts.get(approval["approvalId"])
    assert row["state"] == "open" and row["version"] == 1  # never half-written
    assert len(_settled_events(database)) == 0


def test_partially_migrated_row_refuses_missing_operation_digest(delegated):
    """nativeRequestId present but operationDigest NULL: the grant could never
    bind to an operation, so the decide must refuse, not settle."""
    database, plugin, registration, authorizer, handlers = delegated
    approval_id = "approval_" + "9" * 32
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_approvals("
            "id,session_id,execution_id,version,state,decision,scope_json,request_json,"
            "created_at,settled_at,native_request_id,operation_digest,ceiling_revision,"
            "policy_revision,native_generation) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (approval_id, "session-1", "turn-1", 1, "open", None, None,
             json.dumps({"approvalId": approval_id, "sessionId": "session-1",
                         "executionId": "turn-1", "nativeRequestId": "native-half",
                         "requestedAt": utc().isoformat(),
                         "expiresAt": utc(minutes=5).isoformat(), "version": 1}),
             utc().isoformat(), None,
             "native-half", None, None, None, "gen-1"),
        )
    body = handlers["approvals.decide"].handler(_legacy_params(approval_id))
    assert body["outcome"] == "unknown"
    assert "operationDigest" in body["reason"]
    assert authorizer.facts.get(approval_id)["state"] == "open"


def test_unknown_approval_id_refuses_never_forges(delegated):
    database, plugin, registration, authorizer, handlers = delegated
    body = handlers["approvals.decide"].handler(_legacy_params("approval_" + "0" * 32))
    assert body["outcome"] == "unknown"


# -- the dual-authority hazard is detected, not silently tolerated ---------------


def test_enabling_the_delegate_beside_a_live_old_writer_refuses_at_activation(
        delegated, tmp_path):
    """C0's exact counterexample, made impossible: with the compat route still
    owning `approvals.decide`, activating the delegated plugin is a typed
    platform refusal - the host never serves two writers of one method."""
    database = seeded_database(tmp_path)
    seed_session(database)
    host = _new_host(database, tmp_path)
    host.activate(_OldWriterPlugin())
    with pytest.raises(DuplicateMethodError) as refused:
        host.activate(PermissionsBackendPlugin(approval_route="legacy-delegated"))
    assert refused.value.method_id == "approvals.decide"
    # the hazard round rolled back: the delegated owner is not active
    assert not host.is_active(PLUGIN_ID)
    assert host.methods.lookup("approvals.decide").owner == "legacy-approvals"

    # and the honest migration order works: retire the old owner FIRST...
    host.deactivate("legacy-approvals")
    host.activate(PermissionsBackendPlugin(approval_route="legacy-delegated"))
    assert host.methods.lookup("approvals.decide").owner == PLUGIN_ID
    assert host.provided_port("permissions.authorizer@1") is not None


def test_build_refuses_when_the_old_writer_is_visible_on_the_ports(delegated, tmp_path):
    """Belt-and-suspenders gate at build(): if composition ever hands the
    delegated plugin a live compat writer port (`approvals.records`), the
    plugin refuses to build instead of joining it as a second writer."""
    database = seeded_database(tmp_path)
    seed_session(database)
    plugin = PermissionsBackendPlugin(approval_route="legacy-delegated")
    with pytest.raises(DualAuthorityError):
        plugin.build(ServerPluginContext(
            plugin_id=PLUGIN_ID, data_root=tmp_path,
            ports={"database": database, "approvals.records": object()}))
