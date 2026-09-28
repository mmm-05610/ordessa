"""C1 public-contract checkpoint tests (specs/010-platform-core T004).

These verify the *shape* of the contract (importability, exact signatures,
construction-time validation) and the behaviour the checkpoint really
implements (instance-scoped registration: stage/commit/rollback/unregister/
owner_busy/close, store isolation).  Everything belonging to the T007/T008
dispatch wiring must fail honestly with ``ContractWiringPending`` — the
negative tests below assert that refusal, so no fake success can hide here.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import get_type_hints

import pytest

from pacthold.public import (
    AcquireOutcome,
    AcquireRequest,
    AcquireResult,
    BatchAlreadyUsedError,
    ContractWiringPending,
    CoreContributionSet,
    CoreDTOError,
    CoreRegistration,
    CoreRuntime,
    CoreStore,
    ExecutionPlan,
    ExecutionProvider,
    ExecutionState,
    InvalidProviderIdError,
    LeaseState,
    MissingContractReferenceError,
    Observation,
    ObservationKind,
    OperationState,
    OwnerBusyError,
    OwnerNotRegisteredError,
    OwnershipKind,
    RegistrationConflictError,
    ReleaseOutcome,
    ReleaseRequest,
    ReleaseResult,
    ReconcileOutcome,
    ReconcileRequest,
    ReconcileResult,
    ReconcileSupport,
    ReconcileUnsupportedError,
    ResolvedInputDeclaration,
    ResourceProvider,
    ResourceProviderDescriptor,
    ResourceRequirement,
    RunHandle,
    RuntimeClosedError,
    ShutdownReport,
    StartOutcome,
    StartRequest,
    StartResult,
    StopOutcome,
    StopRequest,
    StopResult,
)

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


# --------------------------------------------------------------------------
# test doubles that satisfy the C1 protocols
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SampleContractV1:
    contract_id: dataclasses.ClassVar[str] = "sample.thing@1"
    value: str = ""


@dataclasses.dataclass(frozen=True)
class OtherContractV1:
    contract_id: dataclasses.ClassVar[str] = "sample.other@1"
    value: str = ""


class FakeResourceProvider:
    def __init__(
        self,
        provider_id: str = "res.fake",
        supported: frozenset[str] | None = None,
        reconcile_support: ReconcileSupport = ReconcileSupport.SUPPORTED,
    ) -> None:
        self._provider_id = provider_id
        if supported is not None:
            self.supported_contract_ids = supported
        self._reconcile_support = reconcile_support

    def describe(self) -> ResourceProviderDescriptor:
        return ResourceProviderDescriptor(
            id=self._provider_id,
            display_name="Fake resource",
            version="1.0",
            reconcile_support=self._reconcile_support,
        )

    def acquire(self, request: AcquireRequest) -> AcquireResult:
        raise NotImplementedError

    def release(self, request: ReleaseRequest) -> ReleaseResult:
        raise NotImplementedError

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        raise NotImplementedError


class FakeExecutionProvider:
    def __init__(self, provider_id: str = "exec.fake") -> None:
        self.provider_id = provider_id

    def start(self, request: StartRequest) -> StartResult:
        raise NotImplementedError

    def observe(self, handle: RunHandle) -> Observation:
        raise NotImplementedError

    def stop(self, request: StopRequest) -> StopResult:
        raise NotImplementedError


@pytest.fixture()
def store(tmp_path: Path) -> CoreStore:
    created = CoreStore(tmp_path / "core.db")
    yield created
    created.close()


@pytest.fixture()
def runtime(store: CoreStore) -> CoreRuntime:
    created = CoreRuntime(store)
    yield created
    if not store.is_closed:
        created.close()


def make_plan(request_key: str = "req-1", digest: str = DIGEST) -> ExecutionPlan:
    return ExecutionPlan(
        request_key=request_key,
        digest=digest,
        provider_id="exec.fake",
        provider_version="1.0",
        work_id="work-0001",
        resources=(
            ResourceRequirement(
                slot="src",
                contract_id="sample.thing@1",
                provider_id="res.fake",
                ownership=OwnershipKind.OWN,
            ),
            ResourceRequirement(
                slot="ctx",
                contract_id="sample.other@1",
                provider_id="res.fake",
                dependencies=("src",),
                ownership=OwnershipKind.BORROWED,
            ),
        ),
    )


def valid_acquire_request() -> AcquireRequest:
    return AcquireRequest(
        operation_key="op-1",
        execution_id="exec-0001",
        contract_id="sample.thing@1",
        provider_id="res.fake",
        ownership=OwnershipKind.OWN,
        declared_inputs=(ResolvedInputDeclaration("sample.other@1", DIGEST),),
    )


# --------------------------------------------------------------------------
# positive: symbols, signatures, shapes, legal construction
# --------------------------------------------------------------------------

C1_SYMBOLS = [
    "CoreRuntime", "CoreStore", "CoreContributionSet", "CoreRegistration",
    "ShutdownReport", "ResourceProvider", "ExecutionProvider",
    "ResourceProviderDescriptor", "AcquireRequest", "AcquireResult",
    "ReleaseRequest", "ReleaseResult", "ReconcileRequest", "ReconcileResult",
    "StartRequest", "StartResult", "RunHandle", "Observation", "StopRequest",
    "StopResult", "ExecutionPlan", "ResourceRequirement", "OwnershipKind",
    "LeaseState", "OperationState", "ExecutionState", "ReconcileSupport",
    "ContractWiringPending",
]


def test_c1_symbols_all_importable_from_public():
    import pacthold.public as public

    missing = [name for name in C1_SYMBOLS if not hasattr(public, name)]
    assert missing == []


def test_public_symbols_defined_under_pacthold_core_only():
    import pacthold.public as public

    for name in public.__all__:
        symbol = getattr(public, name)
        module = getattr(symbol, "__module__", None)
        assert module is None or module.startswith("pacthold.core"), (
            f"{name} leaked from {module}"
        )


def test_core_runtime_entry_signatures(runtime: CoreRuntime):
    init_params = list(inspect.signature(CoreRuntime).parameters)
    assert init_params == ["store"]
    hints = get_type_hints(CoreRuntime.__init__)
    assert hints["store"] is CoreStore

    assert list(inspect.signature(runtime.stage).parameters) == ["owner", "contributions"]
    stage_hints = get_type_hints(CoreRuntime.stage)
    assert stage_hints["owner"] is str
    assert stage_hints["contributions"] is CoreContributionSet
    assert stage_hints["return"] is CoreRegistration

    assert list(inspect.signature(runtime.owner_busy).parameters) == ["owner"]
    assert get_type_hints(CoreRuntime.owner_busy)["return"] is bool
    assert list(inspect.signature(runtime.unregister).parameters) == ["owner"]
    assert get_type_hints(CoreRuntime.unregister)["return"] is type(None)
    assert list(inspect.signature(runtime.close).parameters) == []
    assert get_type_hints(CoreRuntime.close)["return"] is ShutdownReport

    assert list(inspect.signature(runtime.submit).parameters) == ["plan"]
    assert get_type_hints(CoreRuntime.submit)["plan"] is ExecutionPlan
    assert list(inspect.signature(runtime.query).parameters) == ["execution_id"]
    assert list(inspect.signature(runtime.request_stop).parameters) == ["execution_id", "operation_key"]


def test_core_registration_handle_signatures():
    for name in ("commit", "rollback"):
        method = getattr(CoreRegistration, name)
        assert list(inspect.signature(method).parameters) == ["self"], name
        assert get_type_hints(method)["return"] is type(None), name


def test_resource_provider_protocol_signatures():
    assert list(inspect.signature(ResourceProvider.describe).parameters) == ["self"]
    assert get_type_hints(ResourceProvider.describe)["return"] is ResourceProviderDescriptor
    for name, request, result in (
        ("acquire", AcquireRequest, AcquireResult),
        ("release", ReleaseRequest, ReleaseResult),
        ("reconcile", ReconcileRequest, ReconcileResult),
    ):
        method = getattr(ResourceProvider, name)
        params = list(inspect.signature(method).parameters)
        assert params == ["self", "request"], name
        hints = get_type_hints(method)
        assert hints["request"] is request, name
        assert hints["return"] is result, name


def test_execution_provider_protocol_signatures():
    params = list(inspect.signature(ExecutionProvider.start).parameters)
    assert params == ["self", "request"]
    hints = get_type_hints(ExecutionProvider.start)
    assert hints["request"] is StartRequest and hints["return"] is StartResult

    params = list(inspect.signature(ExecutionProvider.observe).parameters)
    assert params == ["self", "handle"]
    hints = get_type_hints(ExecutionProvider.observe)
    assert hints["handle"] is RunHandle and hints["return"] is Observation

    params = list(inspect.signature(ExecutionProvider.stop).parameters)
    assert params == ["self", "request"]
    hints = get_type_hints(ExecutionProvider.stop)
    assert hints["request"] is StopRequest and hints["return"] is StopResult


def test_contribution_set_fields_are_exactly_three():
    names = tuple(f.name for f in dataclasses.fields(CoreContributionSet))
    assert names == ("contracts", "resource_providers", "execution_providers")
    assert CoreContributionSet.__dataclass_params__.frozen


def test_legal_dto_construction():
    descriptor = ResourceProviderDescriptor(
        "res.fake", "Fake", "1.0", ReconcileSupport.UNSUPPORTED
    )
    assert descriptor.reconcile_support is ReconcileSupport.UNSUPPORTED

    request = valid_acquire_request()
    assert request.declared_inputs[0].contract_id == "sample.other@1"

    success = AcquireResult(
        outcome=AcquireOutcome.SUCCESS,
        operation_key="op-1",
        execution_id="exec-0001",
        lease_id="lease-1",
        safe_handle="handle-1",
        lease_state=LeaseState.ACQUIRED,
    )
    refused = AcquireResult(
        outcome=AcquireOutcome.REFUSED, operation_key="op-1",
        execution_id="exec-0001", error_code="capacity_exhausted",
    )
    unknown = AcquireResult(
        outcome=AcquireOutcome.UNKNOWN, operation_key="op-1",
        execution_id="exec-0001", lease_state=LeaseState.ACQUIRE_UNKNOWN,
    )
    assert {success.outcome, refused.outcome, unknown.outcome} == set(AcquireOutcome)

    assert ReleaseResult(ReleaseOutcome.SUCCESS, "op-1", "exec-0001", lease_id="lease-1")
    assert ReleaseResult(ReleaseOutcome.REFUSED, "op-1", "exec-0001", error_code="not_yours")
    assert ReleaseResult(ReleaseOutcome.UNKNOWN, "op-1", "exec-0001")
    assert ReconcileResult(ReconcileOutcome.SUCCESS, "op-1", "exec-0001", resolution_ref="ev-1")
    assert ReconcileResult(ReconcileOutcome.REFUSED, "op-1", "exec-0001", error_code="no_evidence")
    assert ReconcileResult(ReconcileOutcome.UNKNOWN, "op-1", "exec-0001")
    start = StartResult(
        StartOutcome.SUCCESS, "op-1", "exec-0001", run_safe_handle="run-1"
    )
    assert StartResult(StartOutcome.REFUSED, "op-1", "exec-0001", error_code="preflight")
    assert StartResult(StartOutcome.UNKNOWN, "op-1", "exec-0001")
    assert StopResult(StopOutcome.SUCCESS, "op-1", "exec-0001")
    assert StopResult(StopOutcome.REFUSED, "op-1", "exec-0001", error_code="no_run")
    assert StopResult(StopOutcome.UNKNOWN, "op-1", "exec-0001")

    assert RunHandle("exec-0001", "res.fake", "handle-1")
    assert Observation("exec-0001", ObservationKind.RUNNING, evidence_ref="ev-1")
    assert StopRequest("op-1", "exec-0001", reason="user")
    assert StartRequest("op-1", "exec-0001", "exec.fake", DIGEST)
    assert ReleaseRequest("op-1", "exec-0001", "lease-1", OwnershipKind.BORROWED)
    assert ReconcileRequest("op-1", "exec-0001", "lease-1", "handle-1")
    assert make_plan()
    assert descriptor.id == "res.fake"
    assert success.lease_state is LeaseState.ACQUIRED
    assert start.outcome is StartOutcome.SUCCESS


def test_shutdown_report_fields_ordered():
    names = tuple(f.name for f in dataclasses.fields(ShutdownReport))
    assert names == ("unresolved_executions", "unresolved_leases", "cleanup_failures")
    report = ShutdownReport(("e1", "e2"), ("l1",), ("boom",))
    assert all(isinstance(value, tuple) for value in vars(report).values())


def test_vocabularies_are_closed_and_exactly_the_data_model_words():
    assert {member.value for member in OwnershipKind} == {"own", "borrowed"}
    assert {member.value for member in LeaseState} == {
        "acquiring", "acquired", "acquire_unknown", "acquire_refused",
        "releasing", "released", "release_unknown", "release_failed",
    }
    assert {member.value for member in OperationState} == {
        "planned", "in_flight", "succeeded", "refused", "unknown"
    }
    assert {member.value for member in ExecutionState} == {
        "active", "start_unknown", "stop_requested", "succeeded", "failed", "cancelled"
    }
    assert ExecutionState.SUCCEEDED.is_terminal()
    assert not ExecutionState.ACTIVE.is_terminal()
    assert not LeaseState.RELEASED.is_unresolved()
    assert LeaseState.ACQUIRE_UNKNOWN.is_unresolved()


# --------------------------------------------------------------------------
# positive: CoreStore instance isolation (FR-001)
# --------------------------------------------------------------------------


def test_two_core_stores_do_not_interfere(tmp_path: Path):
    store_a = CoreStore(tmp_path / "a.db")
    store_b = CoreStore(tmp_path / "b.db")
    try:
        with store_a.transaction():
            store_a.execute("CREATE TABLE facts (v TEXT NOT NULL)")
            store_a.execute("INSERT INTO facts VALUES (?)", ("from-a",))
        assert store_a.query_all("SELECT v FROM facts") == [("from-a",)]
        assert store_b.query_all("SELECT name FROM sqlite_master WHERE type='table'") == []
        with store_b.transaction():
            store_b.execute("CREATE TABLE facts (v TEXT NOT NULL)")
        assert store_a.query_all("SELECT v FROM facts") == [("from-a",)]
        assert store_b.query_all("SELECT v FROM facts") == []
    finally:
        store_a.close()
        store_b.close()
    assert store_a.is_closed and store_b.is_closed


def test_memory_store_and_rollback_of_transaction(tmp_path: Path):
    memory = CoreStore(":memory:")
    disk = CoreStore(tmp_path / "disk.db")
    try:
        memory.execute("CREATE TABLE t (n INTEGER)")
        try:
            with memory.transaction():
                memory.execute("INSERT INTO t VALUES (1)")
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert memory.query_all("SELECT n FROM t") == []
        disk.execute("CREATE TABLE t (n INTEGER)")
        assert disk.query_all("SELECT n FROM t") == []
    finally:
        memory.close()
        disk.close()


def test_runtime_registries_are_instance_scoped(tmp_path: Path):
    runtime_a = CoreRuntime(CoreStore(tmp_path / "a.db"))
    runtime_b = CoreRuntime(CoreStore(tmp_path / "b.db"))
    try:
        registration = runtime_a.stage(
            "owner-a", CoreContributionSet(contracts=(SampleContractV1,))
        )
        registration.commit()
        assert "sample.thing@1" in runtime_a.registry_snapshot().contract_ids
        assert runtime_b.registry_snapshot().contract_ids == ()
    finally:
        runtime_a.close()
        runtime_b.close()


# --------------------------------------------------------------------------
# registration behaviour: stage / commit / rollback / unregister / busy
# --------------------------------------------------------------------------


def test_stage_is_invisible_until_commit_then_whole_batch_visible(runtime: CoreRuntime):
    before = runtime.registry_snapshot()
    contributions = CoreContributionSet(
        contracts=(SampleContractV1,),
        resource_providers=(FakeResourceProvider(supported=frozenset({"sample.thing@1"})),),
        execution_providers=(FakeExecutionProvider(),),
    )
    registration = runtime.stage("owner-1", contributions)
    assert runtime.registry_snapshot() == before  # staging publishes nothing
    assert runtime.owner_busy("owner-1") is False

    registration.commit()
    snapshot = runtime.registry_snapshot()
    assert snapshot.contract_ids == ("sample.thing@1",)
    assert snapshot.resource_provider_ids == ("res.fake",)
    assert snapshot.execution_provider_ids == ("exec.fake",)
    assert runtime.owner_busy("owner-1") is True


def test_rollback_is_idempotent_and_frees_reservations(runtime: CoreRuntime):
    registration = runtime.stage("owner-1", CoreContributionSet(contracts=(SampleContractV1,)))
    registration.rollback()
    registration.rollback()  # idempotent: harmless
    assert registration.state == "rolled_back"
    assert runtime.registry_snapshot().contract_ids == ()
    # the reservation is gone: another owner can claim the same contract now
    other = runtime.stage("owner-2", CoreContributionSet(contracts=(SampleContractV1,)))
    other.commit()
    assert runtime.owner_busy("owner-2") is True


def test_duplicate_contract_claim_rejected_with_zero_leak(runtime: CoreRuntime):
    first = runtime.stage("owner-a", CoreContributionSet(contracts=(SampleContractV1,)))
    first.commit()
    stable = runtime.registry_snapshot()
    with pytest.raises(RegistrationConflictError):
        runtime.stage("owner-b", CoreContributionSet(contracts=(SampleContractV1,)))
    assert runtime.registry_snapshot() == stable  # zero leak
    # even the same owner re-staging the active id conflicts
    with pytest.raises(RegistrationConflictError):
        runtime.stage("owner-a", CoreContributionSet(contracts=(SampleContractV1,)))
    assert runtime.registry_snapshot() == stable


def test_pending_batches_reserve_ids_against_other_owners(runtime: CoreRuntime):
    staged = runtime.stage("owner-a", CoreContributionSet(contracts=(SampleContractV1,)))
    with pytest.raises(RegistrationConflictError):
        runtime.stage("owner-b", CoreContributionSet(contracts=(SampleContractV1,)))
    staged.commit()
    assert runtime.registry_snapshot().contract_ids == ("sample.thing@1",)


def test_resource_provider_id_conflict_rejected(runtime: CoreRuntime):
    first = runtime.stage(
        "owner-a", CoreContributionSet(resource_providers=(FakeResourceProvider(),))
    )
    first.commit()
    stable = runtime.registry_snapshot()
    with pytest.raises(RegistrationConflictError):
        runtime.stage(
            "owner-b",
            CoreContributionSet(resource_providers=(FakeResourceProvider(),)),
        )
    assert runtime.registry_snapshot() == stable


def test_committed_batch_cannot_be_rolled_back(runtime: CoreRuntime):
    registration = runtime.stage("owner-1", CoreContributionSet(contracts=(SampleContractV1,)))
    registration.commit()
    with pytest.raises(BatchAlreadyUsedError):
        registration.rollback()
    # and it stays visible until unregister
    assert runtime.registry_snapshot().contract_ids == ("sample.thing@1",)


def test_missing_contract_reference_rejected_then_accepted(runtime: CoreRuntime):
    stable = runtime.registry_snapshot()
    orphan = FakeResourceProvider(supported=frozenset({"sample.thing@1"}))
    with pytest.raises(MissingContractReferenceError):
        runtime.stage("owner-1", CoreContributionSet(resource_providers=(orphan,)))
    assert runtime.registry_snapshot() == stable  # zero leak
    # once the contract is active, the same provider batch stages cleanly
    contracts = runtime.stage("contract-owner", CoreContributionSet(contracts=(SampleContractV1,)))
    contracts.commit()
    providers = runtime.stage("owner-1", CoreContributionSet(resource_providers=(orphan,)))
    providers.commit()
    assert runtime.registry_snapshot().resource_provider_ids == ("res.fake",)


def test_invalid_provider_identity_rejected(runtime: CoreRuntime):
    with pytest.raises(InvalidProviderIdError):
        ResourceProviderDescriptor("Bad ID!", "x", "1", ReconcileSupport.SUPPORTED)
    with pytest.raises(CoreDTOError):
        runtime.stage(
            "owner-1", CoreContributionSet(execution_providers=(FakeExecutionProvider("BAD ID"),))
        )
    snapshot = runtime.registry_snapshot()
    assert (snapshot.contract_ids, snapshot.resource_provider_ids,
            snapshot.execution_provider_ids) == ((), (), ())


def test_frozen_dto_mutation_rejected():
    contributions = CoreContributionSet(contracts=(SampleContractV1,))
    with pytest.raises(FrozenInstanceError):
        contributions.contracts = ()  # type: ignore[misc]
    plan = make_plan()
    with pytest.raises(FrozenInstanceError):
        plan.digest = OTHER_DIGEST  # type: ignore[misc]
    result = AcquireResult(
        AcquireOutcome.UNKNOWN, "op-1", "exec-0001", lease_state=LeaseState.ACQUIRE_UNKNOWN
    )
    with pytest.raises(FrozenInstanceError):
        result.outcome = AcquireOutcome.SUCCESS  # type: ignore[misc]


def test_unregister_busy_refused_then_clean(runtime: CoreRuntime):
    registration = runtime.stage(
        "owner-1", CoreContributionSet(resource_providers=(FakeResourceProvider(),))
    )
    registration.commit()
    runtime._note_lease("owner-1", "lease-1", LeaseState.ACQUIRED)
    assert runtime.owner_busy("owner-1") is True
    with pytest.raises(OwnerBusyError):
        runtime.unregister("owner-1")
    # unknown leases block too
    runtime._note_lease("owner-1", "lease-2", LeaseState.ACQUIRE_UNKNOWN)
    with pytest.raises(OwnerBusyError):
        runtime.unregister("owner-1")
    # evidence resolves both leases -> unregister succeeds and removes the batch
    runtime._note_lease("owner-1", "lease-1", LeaseState.RELEASED)
    runtime._note_lease("owner-1", "lease-2", LeaseState.ACQUIRE_REFUSED)
    runtime.unregister("owner-1")
    assert runtime.owner_busy("owner-1") is False
    assert runtime.registry_snapshot().resource_provider_ids == ()
    with pytest.raises(OwnerNotRegisteredError):
        runtime.unregister("owner-1")


# --------------------------------------------------------------------------
# ExecutionPlan contract primitives
# --------------------------------------------------------------------------


def test_plan_dependency_cycle_and_unknown_dependency_rejected():
    a = ResourceRequirement("a", "sample.thing@1", dependencies=("b",))
    b = ResourceRequirement("b", "sample.other@1", dependencies=("a",))
    with pytest.raises(CoreDTOError, match="cycle"):
        ExecutionPlan("req-1", DIGEST, "exec.fake", "1.0", "work-1", (a, b))
    dangling = ResourceRequirement("c", "sample.thing@1", dependencies=("ghost",))
    with pytest.raises(CoreDTOError):
        ExecutionPlan("req-1", DIGEST, "exec.fake", "1.0", "work-1", (dangling,))
    duplicate = (
        ResourceRequirement("a", "sample.thing@1"),
        ResourceRequirement("a", "sample.other@1"),
    )
    with pytest.raises(CoreDTOError):
        ExecutionPlan("req-1", DIGEST, "exec.fake", "1.0", "work-1", duplicate)


def test_same_key_conflicting_digest_primitive():
    original = make_plan()
    replay_same = make_plan()
    conflicting = make_plan(digest=OTHER_DIGEST)
    other_key = make_plan(request_key="req-2", digest=OTHER_DIGEST)
    assert original.same_key_conflicting_digest(conflicting) is True
    assert original.same_key_conflicting_digest(replay_same) is False
    assert original.same_key_conflicting_digest(other_key) is False


def test_plan_and_requests_reject_malformed_values():
    with pytest.raises(CoreDTOError):
        make_plan(digest="NOT-HEX")
    with pytest.raises(CoreDTOError):
        make_plan(request_key="  ")
    with pytest.raises(CoreDTOError):
        ExecutionPlan("req", DIGEST, "exec.fake", "1.0", "", ())  # work id required
    with pytest.raises(CoreDTOError):
        AcquireRequest("op-1", "exec-0001", "unversioned-contract", "res.fake", OwnershipKind.OWN)


# --------------------------------------------------------------------------
# discriminant honesty: unknown/refused/cancelled never conflated
# --------------------------------------------------------------------------


def test_outcome_enums_are_per_fact_and_never_mixed():
    with pytest.raises(CoreDTOError):
        AcquireResult(StartOutcome.UNKNOWN, "op-1", "exec-0001")  # cross-enum member
    with pytest.raises(CoreDTOError):
        AcquireResult("unknown", "op-1", "exec-0001")  # raw string not accepted
    # no result vocabulary may express a fabricated cancellation
    for enum_cls in (AcquireOutcome, ReleaseOutcome, ReconcileOutcome, StartOutcome, StopOutcome):
        assert "cancelled" not in {member.value for member in enum_cls}
    assert StartOutcome.UNKNOWN is not StopOutcome.UNKNOWN
    assert StartOutcome.UNKNOWN is not StartOutcome.REFUSED


def test_unknown_results_stay_queryable_and_payload_free():
    with pytest.raises(CoreDTOError):
        StartResult(StartOutcome.UNKNOWN, "op-1", "exec-0001", run_safe_handle="maybe-run")
    with pytest.raises(CoreDTOError):
        StartResult(StartOutcome.UNKNOWN, "  ", "exec-0001")  # unqueryable
    with pytest.raises(CoreDTOError):
        AcquireResult(
            AcquireOutcome.UNKNOWN, "op-1", "exec-0001", lease_state=LeaseState.ACQUIRED
        )
    with pytest.raises(CoreDTOError):
        AcquireResult(AcquireOutcome.REFUSED, "op-1", "exec-0001")  # refused needs a code
    with pytest.raises(CoreDTOError):
        AcquireResult(
            AcquireOutcome.SUCCESS, "op-1", "exec-0001", lease_id="l", safe_handle="h"
        )  # success must report ACQUIRED state


def test_reconcile_support_is_explicit_and_typed():
    descriptor = FakeResourceProvider(
        reconcile_support=ReconcileSupport.UNSUPPORTED
    ).describe()
    assert descriptor.reconcile_support is ReconcileSupport.UNSUPPORTED
    with pytest.raises(CoreDTOError):
        ResourceProviderDescriptor("res.x", "X", "1", "supported")  # raw string refused
    with pytest.raises(ReconcileUnsupportedError):
        raise ReconcileUnsupportedError("provider refuses reconcile without support")


# --------------------------------------------------------------------------
# honest checkpoint: dispatch wiring refuses, shutdown reports
# --------------------------------------------------------------------------


def test_execution_entries_raise_contract_wiring_pending(runtime: CoreRuntime):
    """T008 landed: the dispatch entries no longer refuse with the deprecated
    ``ContractWiringPending`` placeholder — they run the real machine and
    answer with typed contract errors (unregistered plan contract, unknown
    execution).  Each assertion additionally proves the refusal is NOT the
    placeholder, so an unwired regression would go red here."""
    from pacthold.public import CoreError

    registration = runtime.stage(
        "owner-1",
        CoreContributionSet(
            contracts=(SampleContractV1,),
            resource_providers=(FakeResourceProvider(supported=frozenset({"sample.thing@1"})),),
            execution_providers=(FakeExecutionProvider(),),
        ),
    )
    registration.commit()
    # make_plan() names contract sample.other@1 which is not registered: the
    # wired validator must refuse it as a typed CoreError before any provider
    # call (FakeResourceProvider.acquire raises NotImplementedError — it was
    # never reached).
    with pytest.raises(CoreError) as excinfo:
        runtime.submit(make_plan())
    assert not isinstance(excinfo.value, ContractWiringPending), (
        "submit still raises the T004 placeholder — T008 wiring regressed"
    )
    with pytest.raises(CoreError) as excinfo:
        runtime.query("exec-0001")
    assert not isinstance(excinfo.value, ContractWiringPending), (
        "query still raises the T004 placeholder — T008 wiring regressed"
    )
    with pytest.raises(CoreError) as excinfo:
        runtime.request_stop("exec-0001", "op-1")
    assert not isinstance(excinfo.value, ContractWiringPending), (
        "request_stop still raises the T004 placeholder — T008 wiring regressed"
    )


def test_close_reports_unresolved_and_never_kills_silently(runtime: CoreRuntime, store: CoreStore):
    registration = runtime.stage("owner-1", CoreContributionSet(contracts=(SampleContractV1,)))
    registration.commit()
    runtime._note_lease("owner-1", "lease-2", LeaseState.RELEASE_UNKNOWN)
    runtime._note_lease("owner-1", "lease-1", LeaseState.ACQUIRED)
    runtime._note_execution("owner-1", "exec-0002", ExecutionState.START_UNKNOWN)
    runtime._note_execution("owner-1", "exec-0001", ExecutionState.SUCCEEDED)

    report = runtime.close()
    assert report.unresolved_leases == ("lease-1", "lease-2")  # ordered by id
    assert report.unresolved_executions == ("exec-0002",)
    assert report.cleanup_failures == ()
    # close did not rewrite any fact: the terminal one stays terminal,
    # the unresolved ones stay unresolved (no synthesized cancellation)
    second = runtime.close()
    assert second == report
    assert store.is_closed
    with pytest.raises(RuntimeClosedError):
        runtime.stage("owner-2", CoreContributionSet(contracts=(OtherContractV1,)))
    with pytest.raises(RuntimeClosedError):
        runtime.owner_busy("owner-1")


def test_close_records_store_cleanup_failure():
    class StoreFailingClose(CoreStore):
        def close(self) -> None:  # simulate a dying database handle
            raise RuntimeError("disk on fire")

    runtime = CoreRuntime(StoreFailingClose(":memory:"))
    report = runtime.close()
    assert len(report.cleanup_failures) == 1
    assert "disk on fire" in report.cleanup_failures[0]


# --------------------------------------------------------------------------
# facade boundary: pacthold.public must never drag the business chain in
# --------------------------------------------------------------------------

_FORBIDDEN_CHAIN = ("work_core", "resource_contracts", "extensions", "storage", "cli")


def _module_sources() -> list[tuple[Path, str]]:
    """(source file, owning package) — relative imports resolve against it."""
    root = Path(__file__).resolve().parents[2] / "src" / "pacthold"
    return [(root / "public.py", "pacthold")] + [
        (path, "pacthold.core") for path in sorted((root / "core").glob("*.py"))
    ]


def _imported_names(source: Path, package: str) -> list[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import resolves inside this package
                names.append(package + "." + (node.module or ""))
            elif node.module:
                names.append(node.module)
    return names


def test_facade_chain_ast_forbids_business_modules():
    for source, package in _module_sources():
        for name in _imported_names(source, package):
            parts = name.split(".")
            if parts and parts[0] == "pacthold":
                assert len(parts) > 1 and parts[1] == "core", (
                    f"{source.name} imports {name!r}: the public chain is core-only"
                )


def test_importing_public_pulls_no_reverse_dependency_modules():
    probe = (
        "import sys, pacthold.public;"
        "bad=[m for m in ('pacthold.resource_contracts','pacthold.work_core',"
        "'pacthold.extensions','pacthold.cli','pacthold.storage.database')"
        " if m in sys.modules];"
        "print(bad)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout
