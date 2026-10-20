"""Server dispatch read/reconcile routes and the retired send-entry refusal.

Native effects are exercised through the original RecordedDispatchExecution
owner in test_engineering_effect_consumers.py; this route adapter cannot send.
"""
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope as EngineeringScope
from ordessa_server.composition.engineering_dispatch import dispatch_routes_factory
from ordessa_system_access_bindings.engineering_dispatch import EngineeringDispatchRoutes


class FixtureAccess:
    def require(self, context, operation):
        assert type(context) is CommandContext
        assert operation.startswith("engineering.")


def _context():
    return CommandContext(EngineeringScope("realm", "project"), "fixture",
        ActorRef("fixture", "service", "fixture"), "request",
        "2026-10-11T00:00:00.000000Z", "trace")


def test_retired_dispatch_send_route_refuses_without_creating_work():
    route = EngineeringDispatchRoutes(SimpleNamespace(), FixtureAccess())
    with pytest.raises(ApplicationError, match="OPERATION_UNAVAILABLE"):
        route.invoke("engineering.implementation.dispatch", {
            "run_id": "r", "step_id": "s", "attempt": 1,
            "unit_ref": {}, "params": {}, "actions": ["edit_repository"],
        }, _context())


def test_unbound_reconcile_route_refuses_before_read_or_native_access():
    route = EngineeringDispatchRoutes(SimpleNamespace(), FixtureAccess())
    with pytest.raises(ApplicationError, match="DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE"):
        route.invoke("engineering.implementation.reconcile",
            {"run_id": "r", "step_id": "s", "attempt": 1}, _context())


def test_dispatch_root_passes_the_exact_methodrun_binding():
    from ordessa_system_access_bindings.engineering_wire import Scope

    factory = SimpleNamespace(authority_id="same-authority")
    binding = SimpleNamespace(factory=factory)
    blobs = SimpleNamespace(authority_id="same-authority")
    builder = dispatch_routes_factory(manager=None, blobs=blobs,
        approvals_factory=None, method_runs=binding)
    route = builder(factory, FixtureAccess(), Scope("realm", "project"))
    assert route.method_runs is binding


def test_dispatch_routes_reject_foreign_methodrun_factory():
    with pytest.raises(ApplicationError, match="DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE"):
        EngineeringDispatchRoutes(SimpleNamespace(), FixtureAccess(),
            method_runs=SimpleNamespace(factory=object()))
