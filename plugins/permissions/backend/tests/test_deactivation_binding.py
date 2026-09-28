"""T018 (C0 request #1): the `busy()` fact binds to host deactivation.

C0's exact open request: "the backend's existing `busy()` fact for unresolved
approvals must bind to host deactivation before its port is activated for
production; an open approval cannot disappear with the provider."

The platform's real lifecycle surface is `ServerPluginRegistration.stop_hooks`
(ran by `ServerPluginHost.run_stop_hooks` in reverse activation order, before
any disposal; a raising hook propagates to the caller - see
`apps/server/src/ordessa_server/plugin_host/host.py` and
`plugins/server-compat`'s `SERVER_STOP_TIMEOUT` hook) and `disposal` (run
exactly once on unload/shutdown). This suite drives both through the REAL
host: an open or native-unreconciled approval refuses the stop while the
provider stays active and the row stays queryable; after settle + reconcile
the same stop completes and the decide/admission routes stop accepting new
decisions; a decision in flight refuses with the platform's own
`ContributionOwnerBusyError`.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import NativeReceipt
from server_plugin_api import (
    ContributionOwnerBusyError,
    ServerPluginContext,
    ServerPluginRegistration,
)
from support import (admin_ceiling, approval_record, clock_at, make_operation,
                     seeded_database, seed_session, utc)

from ordessa_permissions_backend import ApprovalFacts, PermissionsBackendPlugin
from ordessa_permissions_backend.errors import (ApprovalRouteClosedError,
                                                PermissionsBackendBusyError)

PLUGIN_ID = "permissions-backend"


def _new_host(database, data_root):
    """The real host, bare registries, database as the only host port -
    same construction `apps/server/tests/platform/contribution_fakes.new_host`
    uses."""
    from ordessa_server.plugin_host import (MethodRegistry, ServerPluginHost,
                                            StreamRouteRegistry)
    return ServerPluginHost(methods=MethodRegistry(),
                            stream_routes=StreamRouteRegistry(),
                            data_root=data_root,
                            host_ports={"database": database})


@pytest.fixture
def built(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    plugin = PermissionsBackendPlugin()
    registration = plugin.build(ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=tmp_path, ports={"database": database}))
    authorizer = registration.provided_ports["permissions.authorizer@1"]
    authorizer.policies.store_ceiling(admin_ceiling())
    authorizer.clock = clock_at(utc())
    return database, plugin, registration, authorizer


def _open_approval(authorizer, *, native="native-stop"):
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id=native)
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    authorizer.facts.request(session_id=operation.session_id,
                             execution_id=operation.execution_id, request=record)
    return record["approvalId"], operation


def _handlers(registration):
    return {m.method_id: m.handler for m in registration.methods}


def _wire_query(registration, approval_id, native_request_id):
    return _handlers(registration)["permissions.approvals.query"](
        {"approvalId": approval_id, "nativeRequestId": native_request_id})


# -- the registration declares the binding ------------------------------------


def test_registration_declares_a_stop_hook_and_disposal(built):
    database, plugin, registration, authorizer = built
    assert isinstance(registration, ServerPluginRegistration)
    assert len(registration.stop_hooks) == 1
    assert callable(registration.stop_hooks[0])
    assert callable(registration.disposal)


# -- the stop refuses while facts are unresolved, and nothing disappears ------


def test_stop_hook_refuses_while_an_approval_is_open(built):
    database, plugin, registration, authorizer = built
    approval_id, operation = _open_approval(authorizer)
    assert authorizer.busy() == 1

    stop = registration.stop_hooks[0]
    with pytest.raises(PermissionsBackendBusyError) as refused:
        stop()
    assert refused.value.busy_count == 1
    assert refused.value.open_count == 1

    # Refused, not deferred silently: the row is still queryable through the
    # route that is still live.
    row = _wire_query(registration, approval_id, operation.native_request_id)
    assert row["outcome"] == "resolved"
    assert row["state"]["state"] == "open"
    assert row["grantsExecution"] is False


def test_stop_hook_refuses_while_a_settled_allow_is_unreconciled(built):
    database, plugin, registration, authorizer = built
    approval_id, _ = _open_approval(authorizer, native="native-stop-2")
    authorizer.decide(approval_id=approval_id, expected_version=1, decision="allow",
                      scope={"kind": "once"}, operation_key="stop-2",
                      session_id="session-1")
    assert authorizer.busy() == 1  # settled-allow, no native receipt yet
    with pytest.raises(PermissionsBackendBusyError):
        registration.stop_hooks[0]()
    # the grant's fate is still observable - it did not disappear with a stop
    assert approval_id in _all_approval_ids(database)


def _all_approval_ids(database):
    with database.read() as conn:
        return {row["id"] for row in
                conn.execute("SELECT id FROM server_approvals").fetchall()}


# -- the refused stop must not orphan the open approval ------------------------


def test_decide_route_still_works_after_a_refused_stop(built):
    """The refusal defers the deactivation, it does not freeze the UI: the
    only way an open approval settles is through this route, so refusing the
    stop must keep the route answerable."""
    database, plugin, registration, authorizer = built
    approval_id, _ = _open_approval(authorizer, native="native-stop-3")
    with pytest.raises(PermissionsBackendBusyError):
        registration.stop_hooks[0]()
    decided = _handlers(registration)["permissions.approvals.decide"]({
        "requestId": "after-refusal", "approvalId": approval_id, "expectedVersion": 1,
        "decision": "deny", "scope": {"kind": "once"}, "sessionId": "session-1",
    })
    assert decided["outcome"] == "recorded"


# -- after settle + reconcile the same stop completes --------------------------


def test_deactivation_allowed_after_settle_and_reconcile(built):
    database, plugin, registration, authorizer = built
    approval_id, operation = _open_approval(authorizer, native="native-stop-4")
    stop = registration.stop_hooks[0]
    with pytest.raises(PermissionsBackendBusyError):
        stop()
    authorizer.decide(approval_id=approval_id, expected_version=1, decision="allow",
                      scope={"kind": "once"}, operation_key="stop-4",
                      session_id="session-1")
    authorizer.facts.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id=operation.native_request_id, approval_id=approval_id,
        confirmed=True, observed_at=utc(minutes=2)))
    assert authorizer.busy() == 0
    stop()  # returns None: the stop may proceed

    # The accepted stop closes the decision routes: a NEW decision is refused
    # type-wise, never silently recorded while the provider goes away.
    fresh_id, _ = _open_approval(authorizer, native="native-stop-5")
    with pytest.raises(ApprovalRouteClosedError):
        _handlers(registration)["permissions.approvals.decide"]({
            "requestId": "late", "approvalId": fresh_id, "expectedVersion": 1,
            "decision": "allow", "scope": {"kind": "once"}, "sessionId": "session-1",
        })
    # the admission grant route stops accepting new decisions too
    admission = registration.provided_ports["acp.admission.gate"]
    result = admission.authorize_permission(None, None)
    assert result.kind == "refused"
    assert "deactivat" in (result.reason or "").lower()


# -- in-flight decisions use the platform's own busy refusal --------------------


def test_stop_hook_refuses_with_the_platform_busy_error_while_a_decision_is_in_flight(
        built):
    """A decision executing across the contributed port is a held reference:
    deactivating now would steal it mid-call. The platform's own refusal
    type - `ContributionOwnerBusyError` - names owner and ports."""
    database, plugin, registration, authorizer = built
    approval_id, _ = _open_approval(authorizer, native="native-stop-6")
    stop = registration.stop_hooks[0]
    ceilings = authorizer.policies.ceilings_current()
    seen = {}

    def reentrant_provider():
        try:
            stop()
        except BaseException as err:
            seen["error"] = err
        return ceilings

    authorizer.ceiling_provider = reentrant_provider
    decided = _handlers(registration)["permissions.approvals.decide"]({
        "requestId": "in-flight", "approvalId": approval_id, "expectedVersion": 1,
        "decision": "allow", "scope": {"kind": "once"}, "sessionId": "session-1",
    })
    assert isinstance(seen.get("error"), ContributionOwnerBusyError)
    assert seen["error"].owner == PLUGIN_ID
    assert "permissions.authorizer@1" in seen["error"].points
    # the in-flight decision was never damaged by the refused stop
    assert decided["outcome"] == "recorded"
    authorizer.ceiling_provider = authorizer.policies.ceilings_current


# -- the disposal refuses: the provider cannot be dropped quietly --------------


def test_disposal_refuses_while_facts_are_unresolved(built):
    database, plugin, registration, authorizer = built
    approval_id, _ = _open_approval(authorizer, native="native-stop-7")
    with pytest.raises(PermissionsBackendBusyError):
        registration.disposal()
    # the fact remains in the store: nobody "cleaned it up" by dropping it
    assert ApprovalFacts(database).peek(approval_id)["state"] == "open"


def test_disposal_allowed_after_settle(built):
    database, plugin, registration, authorizer = built
    approval_id, _ = _open_approval(authorizer, native="native-stop-8")
    authorizer.decide(approval_id=approval_id, expected_version=1, decision="deny",
                      scope={"kind": "once"}, operation_key="stop-8",
                      session_id="session-1")
    assert registration.disposal() is None


# -- the real host runs the phase: refuse, stay active, then allow --------------


def test_the_real_host_refuses_the_stop_phase_then_tears_down_after_reconcile(tmp_path):
    """C0's counterexample surface: `build_runtime`-style SQLite, no Server
    start, no user data - but the SAME host phase sequence the runtime's
    `stop()` uses (`run_stop_hooks` then `shutdown`)."""
    database = seeded_database(tmp_path)
    seed_session(database)
    host = _new_host(database, tmp_path)
    host.activate(PermissionsBackendPlugin())
    plugin_id = PLUGIN_ID
    registration = host.active(plugin_id).registration
    authorizer = registration.provided_ports["permissions.authorizer@1"]
    authorizer.policies.store_ceiling(admin_ceiling())
    authorizer.clock = clock_at(utc())
    approval_id, operation = _open_approval(authorizer, native="native-host-1")

    with pytest.raises(PermissionsBackendBusyError):
        host.run_stop_hooks()
    assert host.is_active(plugin_id)  # the provider did NOT disappear
    row = host.methods.lookup("permissions.approvals.query").handler(
        {"approvalId": approval_id, "nativeRequestId": operation.native_request_id})
    assert row["outcome"] == "resolved" and row["state"]["state"] == "open"

    authorizer.decide(approval_id=approval_id, expected_version=1, decision="allow",
                      scope={"kind": "once"}, operation_key="host-1",
                      session_id="session-1")
    authorizer.facts.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id=operation.native_request_id, approval_id=approval_id,
        confirmed=True, observed_at=utc(minutes=2)))
    host.run_stop_hooks()  # now it settles
    host.shutdown()
    assert not host.is_active(plugin_id)
