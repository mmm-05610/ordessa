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
    projected_binding = projected["value"]["binding"]
    assert projected_binding["execution_operation_ref"] == "operation-1"
    assert projected_binding["fence"] == 1
    assert projected_binding["prompt_ref"] == {
        "digest": {"algorithm": "sha256", "hex": "a" * 64},
        "byte_length": 12, "media_type": "application/json",
        "storage_object_id": "object-123",
    }
    assert projected["value"]["observation_ref"] == {
        "digest": {"algorithm": "sha256", "hex": "a" * 64},
        "byte_length": 12, "media_type": "application/json",
        "storage_object_id": "object-123",
    }


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
        self.work_bound = False
        self.calls = []
        self.query_calls = []
        self.outcome = "unknown"

    def bound_operation_capabilities(self):
        operations = ([EXECUTION_DISPATCH] if self.bound else [])
        if self.work_bound:
            operations.extend(("engineering.work.start", "engineering.runs.resume"))
        items = tuple(SimpleNamespace(capability_id=operation,
            interface_version="1", contract_digest="a" * 64, contract={})
            for operation in operations)
        return SimpleNamespace(capabilities=items)

    async def execute(self, operation, parameters, context):
        self.calls.append((operation, parameters, context))
        return OwnerOperationResult(operation, self.outcome, None,
            engineering_completed=False, accepted=False,
            dispatch_phase="possibly_written", reason="OWNER_RESULT_MISMATCH")

    async def query(self, operation, parameters, context):
        self.query_calls.append((operation, parameters, context))
        return {"run_id": parameters["run_id"], "status": "FAILED",
            "method_binding": {"method_id": "method-1"},
            "inputs": {"slots": {}}, "registry_ref": {"digest": "registry-digest"},
            "steps": [{"ordinal": 0, "step_id": "native-dispatch",
                "operation": EXECUTION_DISPATCH, "attempt": 1, "status": "failed",
                "receipt_ref": None, "dispatch": {"phase": "failed", "fence": 1,
                    "version": 2, "execution_operation_ref": "operation-1",
                    "result_blob_ref": {"digest": {"algorithm": "sha256", "hex": "c" * 64},
                        "byte_length": 17, "media_type": "application/json",
                        "storage_object_id": "result-object"}}}],
            "outputs": [{"name": "result", "context_slot": "result",
                "available": False, "reference": None}],
            "execution": {"availability": "available", "dispatches": [{
                "step_id": "native-dispatch", "attempt": 1, "phase": "failed",
                "fence": 1, "version": 2, "execution_operation_ref": "operation-1",
                "result_blob_ref": {"digest": {"algorithm": "sha256", "hex": "c" * 64},
                    "byte_length": 17, "media_type": "application/json",
                    "storage_object_id": "result-object"}}]},
            "cursor": 1, "wait_reason": None, "created_at": "created",
            "updated_at": "updated"}


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


def test_canonical_dispatch_failed_result_preserves_nonacceptance(monkeypatch):
    def binder(factory, access, service):
        def bind(same_service):
            assert same_service is service
            same_service.bound = True
            return SimpleNamespace(factory=factory, access=access,
                execute=lambda *_: pytest.fail("wire must execute through EngineeringService"))
        return bind

    binding, _, _, service = _wire_binding(monkeypatch, binder)
    service.outcome = "failed"

    import asyncio
    response = asyncio.run(binding.invoke(EXECUTION_DISPATCH, {
        "scope": {"realm_id": "realm", "project_id": "project"},
        "requestId": "failed-request", "parameters": {"native": "input"},
    }, caller=object()))
    assert response["record_type"] == "owner_operation_result"
    assert response["outcome"] == "failed"
    assert response["engineering_completed"] is False
    assert response["accepted"] is False
    assert response["dispatch_phase"] == "possibly_written"
    assert response["reason"] == "OWNER_RESULT_MISMATCH"


def test_work_status_query_uses_same_retained_engineering_service(monkeypatch):
    binding, _, _, service = _wire_binding(monkeypatch, lambda *_: None)
    params = {"scope": {"realm_id": "realm", "project_id": "project"},
        "requestId": "status-request", "parameters": {"run_id": "run-1"}}

    import asyncio
    response = asyncio.run(binding.invoke("engineering.work.get", params, caller=object()))

    assert len(service.query_calls) == 1
    operation, query_parameters, context = service.query_calls[0]
    assert operation == "engineering.work.get"
    assert query_parameters == {"run_id": "run-1"}
    assert context.request_id == "status-request"
    assert response["contract_version"] == wire.CONTRACT_VERSION
    assert response["query"] == "engineering.work.get"
    assert response["record_type"] == "MethodWork"
    data = response["data"]
    assert data["run_id"] == "run-1"
    assert data["status"] == "FAILED"
    assert data["cursor"] == 1
    assert data["steps"][0]["dispatch"]["phase"] == "failed"
    assert data["steps"][0]["dispatch"]["fence"] == 1
    assert data["steps"][0]["dispatch"]["execution_operation_ref"] == "operation-1"
    assert data["steps"][0]["dispatch"]["result_blob_ref"]["storage_object_id"] == "result-object"
    assert data["execution"]["dispatches"][0]["result_blob_ref"] == \
        data["steps"][0]["dispatch"]["result_blob_ref"]
    assert "accepted" not in data
    assert "engineering_completed" not in data


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


@pytest.mark.parametrize("budget", [
    {"action": "accept_artifact", "limit": 1, "consumed": 0,
     "control": {"state": "granted", "version": 0, "revoked_at": None}},
    {"actions": [{"action": "edit_repository", "limit": 1, "consumed": 1},
                 {"action": "run_checks", "limit": 1, "consumed": 0}],
     "control": {"state": "revoked", "version": 1, "revoked_at": "revoked"}},
])
def test_budget_query_projects_original_owner_result_without_changing_consumption(monkeypatch, budget):
    # Controlled wire peer: real SQLite budget/control semantics are owned by
    # Engineering; this test covers their previously missing public projection.
    binding, _, _, service = _wire_binding(monkeypatch, lambda *_: None)
    seen = []

    async def query(operation, parameters, context):
        seen.append((operation, parameters, context.request_id))
        return budget

    service.query = query
    ref = {"realm_id": "realm", "project_id": "project", "approval_id": "approval-1",
           "grant_digest": {"algorithm": "sha256", "hex": "a" * 64}}
    import asyncio
    response = asyncio.run(binding.invoke("engineering.approvals.get_budget", {
        "scope": {"realm_id": "realm", "project_id": "project"},
        "requestId": "read-budget", "parameters": {"approval_ref": ref},
    }, caller=object()))
    assert seen == [("engineering.approvals.get_budget", {"approval_ref": ref}, "read-budget")]
    assert response["record_type"] == "ApprovalBudget"
    assert response["data"] == budget
    assert response["query"] == "engineering.approvals.get_budget"
    assert response["data"] is not budget
    assert service.calls == []
    with pytest.raises(ApplicationError, match="REFERENCE_OWNER_UNAVAILABLE"):
        wire._record(budget, "engineering.unknown_query")


def test_work_projection_support_tracks_original_work_binding_on_same_service(monkeypatch):
    binding, _, _, service = _wire_binding(monkeypatch, lambda *_: None)
    # Work query names exist in the public query grammar even when no original
    # Work source is selected, so query availability alone must not imply a
    # persisted Work projection.
    assert "engineering.work.get" in binding.capabilities()["queries"]
    assert binding.capabilities()["supports"]["work_projection"] is False

    service.work_bound = True
    # The source-backed command capabilities come from this exact service's
    # validated MethodRunBindings/current-wait owner projection.
    capabilities = binding.capabilities()
    assert capabilities["supports"]["work_projection"] is True
    assert "engineering.work.get" in capabilities["queries"]
    assert "engineering.runs.list" in capabilities["queries"]
