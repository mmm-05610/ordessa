from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import ClassVar

import pytest

from pacthold.work_core import ExecutionStartReceipt, ExecutionStartRequest
from pacthold.work_core.errors import (
    ContractViolation,
    DispatchAmbiguous,
    DispatchFailed,
    DispatchRejected,
    ExecutionStartRejected,
    InputFrozen,
)
from pacthold.work_core.events import CoreEvent, EventType
from datetime import datetime, timezone
from pacthold.work_core.models import Ref, RefType
from pacthold.work_core.registry import ExtensionRegistry, ProviderDescriptor
from pacthold.work_core.repository import CoreRepository, RefRelation
from pacthold.work_core.services import ExecutionService, WorkService


# specs/010 T009: the kernel never seeds business contract types.  These are
# local test fixtures with the same wire shapes and the same historical
# contract ids as the relocated product contracts — protocol, not display
# names — so dispatch semantics stay pinned unchanged.  (The canonical types
# now live in ``pacthold_runtime_compat.resource_contracts``.)
@dataclass(frozen=True)
class WorkspaceV1:
    contract_id: ClassVar[str] = "agent-box.workspace@1"

    path: PurePath
    source_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, PurePath) or not self.path.is_absolute():
            raise ValueError("workspace path must be absolute")
        if not isinstance(self.source_digest, str) or not self.source_digest.strip():
            raise ValueError("workspace source_digest is required")


@dataclass(frozen=True)
class PromptFragmentV1:
    contract_id: ClassVar[str] = "agent-box.prompt-fragment@1"

    title: str
    content: str
    digest: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("title", self.title),
            ("content", self.content),
            ("digest", self.digest),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"prompt fragment {field_name} is required")


class FakeResourceProvider:
    supported_contract_ids = frozenset({
        "agent-box.workspace@1",
        "agent-box.prompt-fragment@1",
    })

    def __init__(self, *, wrong_type=False, fail=False):
        self.wrong_type = wrong_type
        self.fail = fail

    def resolve(self, contract_id, ref):
        if self.fail:
            raise RuntimeError("resource unavailable")
        if self.wrong_type:
            return object()
        if contract_id == WorkspaceV1.contract_id:
            return WorkspaceV1(Path("/tmp/" + ref.native_id), "sha256:" + ref.native_id)
        return PromptFragmentV1(ref.native_id, "content-" + ref.native_id, "sha256:" + ref.native_id)


class FakeExecutionProvider:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.started = []

    def descriptor(self):
        return ProviderDescriptor("fake-execution", "Fake Execution", "test")

    def capabilities(self):
        return {"start": "supported", "observe": "supported"}

    def input_limits(self):
        return {
            WorkspaceV1.contract_id: (1, 1),
            "agent-box.prompt-fragment@1": (0, 2),
        }

    def start(self, request):
        if self.fail:
            raise ExecutionStartRejected("start unavailable")
        assert isinstance(request, ExecutionStartRequest)
        self.started.append(request)
        return ExecutionStartReceipt(
            request.execution_id, request.dispatch_id, request.inputs_digest
        )

    def observe(self, native_ref):
        return native_ref


def _setup(tmp_agent_box_home, *, resource=None, execution=None):
    repo = CoreRepository()
    work = WorkService(repo).create_work("dispatch contract inputs")
    execution_service = ExecutionService(repo)
    execution = execution or execution_service.create_execution(
        work.id, "fake-execution", responsibility_intent="run fake inputs"
    )
    provider = FakeExecutionProvider()
    registry = ExtensionRegistry()
    registry.register_contract(WorkspaceV1)
    registry.register_contract(PromptFragmentV1)
    registry.register_execution_provider(provider)
    registry.register_resource_provider("fake-resource", resource or FakeResourceProvider())
    return repo, execution_service, execution, registry, provider


def _inputs():
    return (
        ("agent-box.prompt-fragment@1", Ref(RefType.ARTIFACT, "fake-resource", "prompt-a")),
        (WorkspaceV1.contract_id, Ref(RefType.WORKSPACE, "fake-resource", "workspace-a")),
        ("agent-box.prompt-fragment@1", Ref(RefType.ARTIFACT, "fake-resource", "prompt-b")),
    )


def test_dispatch_freezes_inputs_and_passes_all_values_with_stable_digest(tmp_agent_box_home):
    repo, service, execution, registry, provider = _setup(tmp_agent_box_home)
    receipt = service.dispatch_execution(execution.id, _inputs(), registry, "dispatch-1")
    request = provider.started[0]

    assert receipt.execution_id == execution.id
    assert receipt.dispatch_id == request.dispatch_id
    assert len(request.inputs["agent-box.prompt-fragment@1"]) == 2
    assert [value.title for value in request.inputs["agent-box.prompt-fragment@1"]] == ["prompt-a", "prompt-b"]
    assert provider.started == [request]
    row = repo.get_dispatch(receipt.dispatch_id)
    assert row["state"] == "accepted"
    assert row["inputs_digest"] == receipt.inputs_digest
    assert len(repo.list_input_refs(execution.id)) == 3
    assert [event.type for event in repo.list_events(execution.id)].count(EventType.EXECUTION_DISPATCH_REQUESTED) == 1

    with pytest.raises(DispatchRejected):
        service.dispatch_execution(execution.id, _inputs(), registry, "dispatch-2")


def test_digest_is_independent_of_host_input_order(tmp_agent_box_home):
    repo, service, first, registry, _ = _setup(tmp_agent_box_home)
    first_request = service.dispatch_execution(first.id, _inputs(), registry, "dispatch-a")
    second = service.create_execution(
        first.work_id, "fake-execution", responsibility_intent="same inputs"
    )
    second_request = service.dispatch_execution(second.id, tuple(reversed(_inputs())), registry, "dispatch-b")
    assert first_request.inputs_digest == second_request.inputs_digest


def test_dispatch_rejects_unknown_contract_or_provider_count_before_persisting(tmp_agent_box_home):
    repo, service, execution, registry, _ = _setup(tmp_agent_box_home)
    with pytest.raises(ContractViolation):
        service.dispatch_execution(
            execution.id,
            (("agent-box.unknown@1", Ref(RefType.ARTIFACT, "fake-resource", "x")),),
            registry,
            "unknown-contract",
        )
    assert repo.get_dispatch_by_key("unknown-contract") is None
    with pytest.raises(ContractViolation):
        service.dispatch_execution(
            execution.id,
            (("agent-box.prompt-fragment@1", Ref(RefType.ARTIFACT, "fake-resource", "x")),),
            registry,
            "missing-workspace",
        )
    assert repo.get_dispatch_by_key("missing-workspace") is None


@pytest.mark.parametrize("resource", [FakeResourceProvider(wrong_type=True), FakeResourceProvider(fail=True)])
def test_resolve_or_type_failure_records_failed_dispatch(tmp_agent_box_home, resource):
    repo, service, execution, registry, provider = _setup(tmp_agent_box_home, resource=resource)
    inputs = ((WorkspaceV1.contract_id, Ref(RefType.WORKSPACE, "fake-resource", "workspace-a")),)
    with pytest.raises(DispatchFailed):
        service.dispatch_execution(execution.id, inputs, registry, "dispatch-fail")
    row = repo.get_dispatch_by_key("dispatch-fail")
    assert row["state"] == "failed"
    assert provider.started == []


def test_input_freeze_allows_native_and_output_but_not_new_input(tmp_agent_box_home):
    repo, service, execution, registry, _ = _setup(tmp_agent_box_home)
    service.dispatch_execution(execution.id, _inputs(), registry, "dispatch-1")
    with pytest.raises(InputFrozen):
        repo.attach_ref(
            execution.id,
            RefRelation.INPUT,
            Ref(RefType.ARTIFACT, "fake-resource", "later"),
            event=CoreEvent("evt_later_input", EventType.REF_ATTACHED, execution.id, datetime.now(timezone.utc)),
            contract_id="agent-box.prompt-fragment@1",
        )
    repo.attach_ref(
        execution.id,
        RefRelation.NATIVE,
        Ref(RefType.SESSION, "fake-execution", "thread-1"),
        event=CoreEvent("evt_native", EventType.NATIVE_REF_DISCOVERED, execution.id, datetime.now(timezone.utc)),
    )
    repo.attach_ref(
        execution.id,
        RefRelation.OUTPUT,
        Ref(RefType.ARTIFACT, "fake-resource", "result"),
        event=CoreEvent("evt_output", EventType.REF_ATTACHED, execution.id, datetime.now(timezone.utc)),
    )
    assert {ref.native_id for ref in repo.list_refs(execution.id)} >= {"thread-1", "result"}


def test_legacy_request_dispatch_no_longer_exists(tmp_agent_box_home):
    repo, service, execution, registry, _ = _setup(tmp_agent_box_home)
    assert not hasattr(service, "request_dispatch")
    # The only dispatch path freezes inputs: an input-less dispatch attempt
    # is rejected by provider input limits before anything is persisted.
    with pytest.raises(ContractViolation):
        service.dispatch_execution(execution.id, (), registry, "legacy-free")
    assert repo.get_dispatch_by_key("legacy-free") is None


def test_replay_of_accepted_dispatch_returns_receipt_without_restarting(tmp_agent_box_home):
    repo, service, execution, registry, provider = _setup(tmp_agent_box_home)
    first = service.dispatch_execution(execution.id, _inputs(), registry, "dispatch-1")
    second = service.dispatch_execution(execution.id, _inputs(), registry, "dispatch-1")
    assert len(provider.started) == 1
    assert provider.started[0].dispatch_id == first.dispatch_id
    assert second.dispatch_id == first.dispatch_id
    assert second.inputs_digest == first.inputs_digest
    assert repo.get_dispatch(first.dispatch_id)["state"] == "accepted"


def test_replay_of_failed_dispatch_raises_recorded_error_without_restarting(tmp_agent_box_home):
    repo, service, execution, registry, provider = _setup(tmp_agent_box_home)
    failing = FakeExecutionProvider(fail=True)
    failing_registry = ExtensionRegistry()
    failing_registry.register_contract(WorkspaceV1)
    failing_registry.register_contract(PromptFragmentV1)
    failing_registry.register_execution_provider(failing)
    failing_registry.register_resource_provider("fake-resource", FakeResourceProvider())
    with pytest.raises(DispatchFailed):
        service.dispatch_execution(execution.id, _inputs(), failing_registry, "dispatch-fail")
    assert failing.started == []
    # Replay with a working provider still re-raises the recorded failure and
    # never calls provider.start.
    with pytest.raises(DispatchFailed, match="start unavailable"):
        service.dispatch_execution(execution.id, _inputs(), registry, "dispatch-fail")
    assert provider.started == []
    assert repo.get_dispatch_by_key("dispatch-fail")["state"] == "failed"


def test_replay_of_requested_dispatch_is_explicitly_ambiguous(tmp_agent_box_home):
    repo, service, execution, registry, provider = _setup(tmp_agent_box_home)
    canonical = service._canonicalize_inputs(_inputs(), registry)
    digest = service._inputs_digest(canonical)
    # Simulate a crash between the dispatch transaction and the terminal
    # start outcome: the row stays 'requested'.
    repo.create_dispatch_with_inputs(
        "dispatch_stuck",
        execution.id,
        canonical,
        digest,
        "dispatch-stuck",
        CoreEvent("evt_stuck", EventType.EXECUTION_DISPATCH_REQUESTED, execution.id, datetime.now(timezone.utc)),
    )
    with pytest.raises(DispatchAmbiguous, match="cannot be proven"):
        service.dispatch_execution(execution.id, _inputs(), registry, "dispatch-stuck")
    assert provider.started == []
    assert repo.get_dispatch("dispatch_stuck")["state"] == "requested"


def test_replay_with_different_execution_or_digest_is_rejected(tmp_agent_box_home):
    repo, service, execution, registry, _ = _setup(tmp_agent_box_home)
    service.dispatch_execution(execution.id, _inputs(), registry, "dispatch-1")
    other = service.create_execution(
        execution.work_id, "fake-execution", responsibility_intent="another execution"
    )
    with pytest.raises(DispatchRejected, match="another execution"):
        service.dispatch_execution(other.id, _inputs(), registry, "dispatch-1")
    with pytest.raises(DispatchRejected, match="different inputs"):
        service.dispatch_execution(
            execution.id,
            ((WorkspaceV1.contract_id, Ref(RefType.WORKSPACE, "fake-resource", "workspace-z")),),
            registry,
            "dispatch-1",
        )


def test_resolved_inputs_preserve_exact_ref_value_pairs_and_read_only_view(
    tmp_agent_box_home,
):
    _, service, execution, registry, provider = _setup(tmp_agent_box_home)
    service.dispatch_execution(execution.id, _inputs(), registry, "pairing")
    request = provider.started[0]
    fragments = [
        item for item in request.resolved_inputs
        if item.contract_id == PromptFragmentV1.contract_id
    ]
    assert [(item.ref.native_id, item.value.title) for item in fragments] == [
        ("prompt-a", "prompt-a"),
        ("prompt-b", "prompt-b"),
    ]
    assert request.inputs[PromptFragmentV1.contract_id] == tuple(
        item.value for item in fragments
    )
    with pytest.raises(TypeError):
        request.inputs[PromptFragmentV1.contract_id] = ()


def test_accepted_replay_does_not_touch_registry_or_providers(tmp_agent_box_home):
    _, service, execution, registry, _ = _setup(tmp_agent_box_home)
    accepted = service.dispatch_execution(execution.id, _inputs(), registry, "sealed")

    class BombRegistry:
        def __getattr__(self, name):
            raise AssertionError(f"replay touched registry.{name}")

    replay = service.dispatch_execution(execution.id, _inputs(), BombRegistry(), "sealed")
    assert replay == accepted


def test_unknown_start_exception_is_ambiguous_and_never_restarted(tmp_agent_box_home):
    _, service, execution, registry, provider = _setup(tmp_agent_box_home)
    provider.start = lambda request: (_ for _ in ()).throw(RuntimeError("lost receipt"))
    with pytest.raises(DispatchAmbiguous, match="lost receipt"):
        service.dispatch_execution(execution.id, _inputs(), registry, "ambiguous")

    class BombRegistry:
        def __getattr__(self, name):
            raise AssertionError(f"ambiguous replay touched registry.{name}")

    with pytest.raises(DispatchAmbiguous):
        service.dispatch_execution(execution.id, _inputs(), BombRegistry(), "ambiguous")


def test_malformed_start_receipt_is_ambiguous(tmp_agent_box_home):
    _, service, execution, registry, provider = _setup(tmp_agent_box_home)
    provider.start = lambda request: "not-a-receipt"
    with pytest.raises(DispatchAmbiguous, match="ExecutionStartReceipt"):
        service.dispatch_execution(execution.id, _inputs(), registry, "bad-receipt")
    assert service.repository.get_dispatch_by_key("bad-receipt")["state"] == "requested"


def test_accepted_receipt_round_trips_after_repository_restart(tmp_agent_box_home):
    _, service, execution, registry, provider = _setup(tmp_agent_box_home)
    correlation = Ref(RefType.SESSION, "fake-execution", "native-session-1")
    provider.start = lambda request: ExecutionStartReceipt(
        request.execution_id,
        request.dispatch_id,
        request.inputs_digest,
        correlation_ref=correlation,
    )
    accepted = service.dispatch_execution(execution.id, _inputs(), registry, "restart")
    restarted = CoreRepository().get_dispatch_receipt(accepted.dispatch_id)
    assert restarted == accepted
    assert restarted.correlation_ref == correlation


def test_pure_preflight_rejects_before_materializing_remaining_inputs(
    tmp_agent_box_home,
):
    class PreflightProvider(FakeExecutionProvider):
        def preflight_contract_ids(self):
            return frozenset({WorkspaceV1.contract_id})

        def resolution_effect(self, contract_id):
            return "pure" if contract_id == WorkspaceV1.contract_id else "idempotent_materialization"

        def preflight(self, request):
            assert request.resolved_inputs[0].contract_id == WorkspaceV1.contract_id
            raise ValueError("dynamic incompatibility")

    resource = FakeResourceProvider()
    calls: list[str] = []
    original_resolve = resource.resolve
    resource.resolve = lambda contract_id, ref: (
        calls.append(contract_id), original_resolve(contract_id, ref)
    )[1]
    repo, service, execution, _, _ = _setup(tmp_agent_box_home, resource=resource)
    provider = PreflightProvider()
    registry = ExtensionRegistry()
    registry.register_contract(WorkspaceV1)
    registry.register_contract(PromptFragmentV1)
    registry.register_execution_provider(provider)
    registry.register_resource_provider("fake-resource", resource)
    with pytest.raises(DispatchFailed, match="dynamic incompatibility"):
        service.dispatch_execution(execution.id, _inputs(), registry, "preflight")
    assert calls == [WorkspaceV1.contract_id]
    assert repo.get_dispatch_by_key("preflight")["state"] == "failed"
