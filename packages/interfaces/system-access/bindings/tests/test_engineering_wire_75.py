import pytest
from contextlib import contextmanager
from types import SimpleNamespace

from ordessa_engineering.application.api import (
    BlobRef, DispatchBinding, EXECUTION_DISPATCH, OwnerOperationResult,
)
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_system_access_bindings import engineering_wire as wire
from ordessa_system_access_bindings.engineering_wire import _owner_result
from ordessa_interfaces.system_access.contracts.refs import Scope


def test_owner_operation_projection_preserves_unknown_semantics_and_blob_locator():
    blob = BlobRef(Digest("sha256", "a" * 64), 12, "application/json", "object-123")
    wire_scope = Scope("realm", "project")
    owner_scope = EngineeringScope("realm", "project")
    digest = Digest("sha256", "b" * 64)
    binding = DispatchBinding(
        owner_scope, "run-1", "step-1", 1, 1,
        ImplementationPackageRef("realm", "project", "package-1", digest),
        ApprovalRef("realm", "project", "approval-1", digest), digest, 0,
        (("edit_repository", "action-1"),),
        canonical_bytes({"environmentNamespace": "env", "unitId": "unit",
            "ownerProviderRef": {}, "sourceRevision": "rev-1"}),
        "operation-1", blob, digest, "query-1", ("result-1",),
    )
    result = OwnerOperationResult(
        EXECUTION_DISPATCH, "unknown",
        {"binding": binding, "observation_ref": blob},
        engineering_completed=False, accepted=False, dispatch_phase="possibly_written",
        reason="OWNER_RESULT_MISMATCH",
    )
    projected = _owner_result(result, wire_scope, "request-1")
    assert projected["outcome"] == "unknown"
    assert projected["engineering_completed"] is False
    assert projected["accepted"] is False
    assert projected["dispatch_phase"] == "possibly_written"
    assert projected["reason"] == "OWNER_RESULT_MISMATCH"
    assert projected["value"]["binding"]["prompt_ref"]["storage_object_id"] == "object-123"
    assert projected["value"]["observation_ref"]["storage_object_id"] == "object-123"


def test_owner_operation_projection_does_not_accept_command_result_shape():
    with pytest.raises(ApplicationError, match="INVALID_RESULT"):
        _owner_result(object(), Scope("realm", "project"), "request-1")


def test_owner_operation_projection_rejects_unknown_native_value_shapes():
    result = OwnerOperationResult(EXECUTION_DISPATCH, "unknown",
        {"binding": object(), "observation_ref": None})
    with pytest.raises(ApplicationError, match="INVALID_RESULT"):
        _owner_result(result, Scope("realm", "project"), "request-1")


class _WireContractService:
    """Controlled wire-seam substitute; not evidence for the real owner graph."""
    def __init__(self):
        self.bound = False
        self.calls = []

    def bound_operation_capabilities(self):
        items = ((SimpleNamespace(capability_id=EXECUTION_DISPATCH,
            interface_version="1", contract_digest="a" * 64, contract={}),)
                 if self.bound else ())
        return SimpleNamespace(capabilities=items)

    async def execute(self, operation, parameters, context):
        self.calls.append((operation, parameters, context))
        return OwnerOperationResult(operation, "unknown", None,
            engineering_completed=False, accepted=False,
            dispatch_phase="possibly_written", reason="OWNER_RESULT_MISMATCH")


class _WireContractAccess:
    @contextmanager
    def admit(self, caller, scope, operation, *, request_id, trace_id):
        yield SimpleNamespace(scope=scope, request_id=request_id)


def _wire_binding(monkeypatch, binder):
    factory = object()
    access = _WireContractAccess()
    service = _WireContractService()
    monkeypatch.setattr(wire, "build_engineering_service", lambda *_args, **_kwargs: service)
    monkeypatch.setattr(wire, "EngineeringCommandAccess", lambda _authority: access)
    ports = wire.EngineeringApplicationPorts(execution_dispatch_binder=binder(factory, access, service))
    binding = wire.EngineeringWireBinding(factory, object(), scope=Scope("realm", "project"),
        application_ports_factory=lambda *_args: ports)
    return binding, factory, access, service


@pytest.mark.parametrize("case", ["noop", "foreign_factory", "foreign_access", "missing_execute"])
def test_binder_rejects_noop_and_foreign_ports(monkeypatch, case):
    def binder(factory, access, service):
        def bind(same_service):
            assert same_service is service
            if case != "noop":
                service.bound = True
            return SimpleNamespace(
                factory=object() if case == "foreign_factory" else factory,
                access=object() if case == "foreign_access" else access,
                execute=None if case == "missing_execute" else lambda *_: None,
            )
        return bind

    with pytest.raises(ApplicationError, match="DISPATCH_AUTHORITY_MISMATCH"):
        _wire_binding(monkeypatch, binder)


def test_canonical_dispatch_uses_bound_service_execute_and_bound_capabilities(monkeypatch):
    calls = []

    def binder(factory, access, service):
        def bind(same_service):
            calls.append(same_service)
            same_service.bound = True
            return SimpleNamespace(factory=factory, access=access,
                execute=lambda *_: pytest.fail("wire must execute through EngineeringService"))
        return bind

    binding, _, _, service = _wire_binding(monkeypatch, binder)
    assert calls == [service]
    assert EXECUTION_DISPATCH in binding.capabilities()["supported_methods"]
    assert any(item["operation"] == EXECUTION_DISPATCH
        for item in binding.capabilities()["commands"])
    method_ids = {item.method_id for item in binding.methods()}
    assert set(wire.SUPPORTED_COMMANDS).issubset(method_ids)
    assert set(wire.SUPPORTED_QUERIES).issubset(method_ids)
    assert EXECUTION_DISPATCH in method_ids
    assert "engineering.implementation.dispatch" not in method_ids

    import asyncio
    response = asyncio.run(binding.invoke(EXECUTION_DISPATCH, {
        "scope": {"realm_id": "realm", "project_id": "project"},
        "requestId": "request-1", "parameters": {"native": "input"},
    }, caller=object()))
    assert len(service.calls) == 1
    operation, parameters, context = service.calls[0]
    assert operation == EXECUTION_DISPATCH
    assert parameters == {"native": "input"}
    assert context.request_id == "request-1"
    assert response["outcome"] == "unknown"
    assert response["accepted"] is False
    assert response["engineering_completed"] is False


def test_unbound_service_does_not_advertise_canonical_dispatch(monkeypatch):
    binding, _, _, _ = _wire_binding(monkeypatch, lambda *_: None)
    assert EXECUTION_DISPATCH not in binding.capabilities()["supported_methods"]
    assert binding.capabilities()["commands"] == []
    method_ids = {item.method_id for item in binding.methods()}
    assert set(wire.SUPPORTED_COMMANDS).issubset(method_ids)
    assert set(wire.SUPPORTED_QUERIES).issubset(method_ids)
    assert EXECUTION_DISPATCH not in method_ids
    assert "engineering.implementation.dispatch" not in method_ids
    assert "engineering.capabilities" in method_ids
