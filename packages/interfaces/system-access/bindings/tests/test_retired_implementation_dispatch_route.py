"""Old explicit capability cannot reach native send or become canonical access."""
import pytest

from ordessa_engineering.application.api import ApplicationError, EXECUTION_DISPATCH
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant, InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_system_access_bindings.engineering_dispatch import (
    DISPATCH_COMMANDS, EngineeringDispatchRoutes,
)


def test_old_dispatch_capability_refuses_before_any_native_owner_access():
    old_operation = "engineering.implementation.dispatch"
    scope = Scope("controlled-retirement", "dispatch")
    authority = InstanceAccessAuthority(
        lambda: "controlled-old-capability-token", principal_id="controlled-old-capability",
        legacy_principal=None, grants=(AccessGrant(scope, (old_operation,)),))
    caller = authority.authenticate("Bearer controlled-old-capability-token")
    access = EngineeringCommandAccess(authority)
    calls = []

    class UntouchedManager:
        @property
        def records(self):
            calls.append("records")
            raise AssertionError("retired route must not touch original records")

        def find(self, _reference):
            calls.append("find")
            raise AssertionError("retired route must not select a native Unit")

    routes = EngineeringDispatchRoutes(object(), access, manager=UntouchedManager())
    assert old_operation not in DISPATCH_COMMANDS
    assert "engineering.implementation.reconcile" in DISPATCH_COMMANDS
    with access.admit(caller, scope, old_operation,
            request_id="retired-dispatch", trace_id="retired-dispatch") as context:
        with pytest.raises(ApplicationError, match="OPERATION_UNAVAILABLE"):
            routes.invoke(old_operation, {}, context)
        with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
            access.require(context, EXECUTION_DISPATCH)
    assert calls == []
