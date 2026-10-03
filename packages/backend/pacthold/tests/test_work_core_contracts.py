from datetime import datetime, timezone

import pytest

from pacthold.work_core import (
    Execution,
    ExecutionStartReceipt,
    ExecutionProjection,
    ExtensionRegistry,
    Freshness,
    Outcome,
    Phase,
    ProviderDescriptor,
    Ref,
    RefType,
    Work,
    WorkLifecycle,
)
from pacthold.work_core.errors import CapabilityUnsupported, InvalidProjection, InvalidRef


NOW = datetime(2026, 8, 21, tzinfo=timezone.utc)


def _projection():
    return ExecutionProjection(Phase.ACTIVE, None, True, Freshness.OBSERVED, NOW)


def test_work_has_no_provider_or_execution_state_and_lifecycle_is_independent():
    work = Work("work_1", "small change", WorkLifecycle.OPEN, NOW, NOW)
    execution = Execution("exec_1", work.id, "fake", _projection(), NOW)
    assert work.lifecycle is WorkLifecycle.OPEN
    assert execution.projection.phase is Phase.ACTIVE
    assert not hasattr(work, "provider_id")
    assert not hasattr(work, "workflow_state")


def test_projection_requires_terminal_outcome_and_rejects_outcome_elsewhere():
    with pytest.raises(InvalidProjection):
        ExecutionProjection(Phase.TERMINAL, None, False, Freshness.OBSERVED, NOW)
    with pytest.raises(InvalidProjection):
        ExecutionProjection(Phase.ACTIVE, Outcome.SUCCEEDED, True, Freshness.OBSERVED, NOW)
    unknown = ExecutionProjection(Phase.UNKNOWN, None, None, Freshness.UNREACHABLE, NOW)
    assert unknown.resumable_now is None


def test_ref_is_a_bounded_flat_value_not_provider_payload():
    ref = Ref(RefType.SESSION, "external-runtime", "session-1", metadata={"profile": "main"})
    assert ref.metadata == {"profile": "main"}
    with pytest.raises(InvalidRef):
        Ref(RefType.SESSION, "external-runtime", "session-1", metadata={"payload": {"native": "state"}})
    with pytest.raises(InvalidRef):
        Ref(RefType.SESSION, "external-runtime", "session-1", metadata={str(i): "x" for i in range(17)})


class FakeProvider:
    def descriptor(self):
        return ProviderDescriptor("fake-security", "Fake Security", "1")

    def capabilities(self):
        return {"start": "supported", "resume": "unsupported"}

    def start(self, request):
        return ExecutionStartReceipt(
            request.execution_id, request.dispatch_id, request.inputs_digest
        )

    def observe(self, native_ref):
        return native_ref


def test_registry_accepts_a_new_provider_without_core_branch():
    registry = ExtensionRegistry()
    registry.register_execution_provider(FakeProvider())
    assert registry.get("fake-security").descriptor().display_name == "Fake Security"
    with pytest.raises(ValueError):
        registry.register_execution_provider(FakeProvider())


def test_registry_uses_declared_capabilities_without_provider_special_cases():
    registry = ExtensionRegistry()
    registry.register_execution_provider(FakeProvider())
    assert registry.require_capability("fake-security", "start").descriptor().id == "fake-security"
    with pytest.raises(CapabilityUnsupported):
        registry.require_capability("fake-security", "resume")
