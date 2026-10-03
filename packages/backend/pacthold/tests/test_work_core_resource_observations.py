"""Structured ResourceObservation ledger: model, persistence, and invariants."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import ClassVar

import pytest

from pacthold.work_core import ExecutionStartReceipt, ExecutionStartRequest
from pacthold.work_core.errors import InvalidResourceObservation, WorkCoreError
from pacthold.work_core.models import Ref, RefType
from pacthold.work_core.projection import ExecutionProjection, Freshness, Outcome, Phase
from pacthold.work_core.registry import ExtensionRegistry, ProviderDescriptor
from pacthold.work_core.repository import CoreRepository
from pacthold.work_core.resource_observations import (
    ResourceObservation,
    ResourceObservationCoverage,
    ResourceObservationKind,
    ResourceObservationResult,
    ResourceObserverRole,
)
from pacthold.work_core.services import ExecutionService, WorkService

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


# specs/010 T009: the kernel registry starts empty; this local stand-in keeps
# the historical contract id (protocol, not display name) so the observation
# ledger semantics stay pinned unchanged without importing the relocated
# product contract package (``pacthold_runtime_compat.resource_contracts``).
@dataclass(frozen=True)
class WorkspaceV1:
    contract_id: ClassVar[str] = "agent-box.workspace@1"

    path: str = ""
    source_digest: str = ""


@dataclass(frozen=True)
class FragmentV1:
    """Second contract so several same-contract inputs can be addressed."""

    contract_id: ClassVar[str] = "test.fragment@1"

    body: str = "x"


class FragmentResourceProvider:
    supported_contract_ids = frozenset(
        {WorkspaceV1.contract_id, FragmentV1.contract_id}
    )

    def resolve(self, contract_id, ref):
        if contract_id == FragmentV1.contract_id:
            return FragmentV1(body=ref.native_id)
        return WorkspaceV1.__new__(WorkspaceV1)


class DispatchExecutionProvider:
    def descriptor(self):
        return ProviderDescriptor("fake-execution", "Fake Execution", "test")

    def capabilities(self):
        return {"start": "supported", "observe": "supported"}

    def input_limits(self):
        return {
            WorkspaceV1.contract_id: (1, 1),
            FragmentV1.contract_id: (0, 2),
        }

    def start(self, request):
        assert isinstance(request, ExecutionStartRequest)
        return ExecutionStartReceipt(
            request.execution_id, request.dispatch_id, request.inputs_digest
        )

    def observe(self, native_ref):
        return native_ref


def _observation(ref, *, contract_id=WorkspaceV1.contract_id, **overrides):
    values = dict(
        contract_id=contract_id,
        ref=ref,
        kind=ResourceObservationKind.READ_BACK,
        result=ResourceObservationResult.MATCH,
        observer_role=ResourceObserverRole.RESOURCE_PROVIDER,
        observer_id="git-worktree",
        observed_at=NOW,
        coverage=ResourceObservationCoverage.COMPLETE,
        detail="tracked HEAD/tree at finish",
    )
    values.update(overrides)
    return ResourceObservation(**values)


def _setup(tmp_agent_box_home, *, inputs=None):
    repo = CoreRepository()
    work = WorkService(repo).create_work("structured observations")
    service = ExecutionService(repo)
    execution = service.create_execution(
        work.id, "fake-execution", responsibility_intent="observe frozen inputs"
    )
    registry = ExtensionRegistry()
    registry.register_contract(WorkspaceV1)
    registry.register_contract(FragmentV1)
    registry.register_execution_provider(DispatchExecutionProvider())
    registry.register_resource_provider("fake-resource", FragmentResourceProvider())
    if inputs is None:
        inputs = (
            (WorkspaceV1.contract_id, Ref(RefType.WORKSPACE, "fake-resource", "workspace-1")),
        )
    service.dispatch_execution(execution.id, inputs, registry, "dispatch-1")
    return repo, service, execution, registry


# ── construction validation ──────────────────────────────────────────


def test_observation_rejects_invalid_construction():
    ref = Ref(RefType.WORKSPACE, "fake-resource", "workspace-1")
    with pytest.raises(InvalidResourceObservation, match="contract_id"):
        _observation(ref, contract_id="")
    with pytest.raises(InvalidResourceObservation, match="contract_id"):
        _observation(ref, contract_id="not-versioned")
    with pytest.raises(InvalidResourceObservation, match="Ref"):
        ResourceObservation(
            contract_id=WorkspaceV1.contract_id,
            ref="not-a-ref",
            kind=ResourceObservationKind.READ_BACK,
            result=ResourceObservationResult.MATCH,
            observer_role=ResourceObserverRole.RESOURCE_PROVIDER,
            observer_id="git-worktree",
            observed_at=NOW,
            coverage=ResourceObservationCoverage.UNKNOWN,
        )
    with pytest.raises(InvalidResourceObservation, match="observer_id"):
        _observation(ref, observer_id="  ")
    with pytest.raises(InvalidResourceObservation, match="observer_id"):
        _observation(ref, observer_id="x" * 65)
    with pytest.raises(InvalidResourceObservation, match="observed_at"):
        _observation(ref, observed_at="2026-08-27")
    with pytest.raises(InvalidResourceObservation, match="detail"):
        _observation(ref, detail="y" * 257)
    with pytest.raises(InvalidResourceObservation, match="ArtifactRef"):
        _observation(ref, evidence_ref=Ref(RefType.WORKSPACE, "fake-resource", "e"))
    with pytest.raises(InvalidResourceObservation, match="observation surface"):
        _observation(ref, coverage=ResourceObservationCoverage.PARTIAL, detail=None)


# ── frozen input association ─────────────────────────────────────────


def test_observation_must_address_frozen_input_association(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    created = service.record_resource_observations(
        execution.id, (_observation(frozen_ref),)
    )
    assert created[0][1] is True

    stranger = Ref(RefType.WORKSPACE, "fake-resource", "never-frozen")
    with pytest.raises(ValueError, match="frozen INPUT"):
        service.record_resource_observations(execution.id, (_observation(stranger),))


def test_multiple_same_contract_inputs_are_addressed_separately(tmp_agent_box_home):
    prompt_a = Ref(RefType.ARTIFACT, "fake-resource", "prompt-a")
    prompt_b = Ref(RefType.ARTIFACT, "fake-resource", "prompt-b")
    inputs = (
        (FragmentV1.contract_id, prompt_a),
        (FragmentV1.contract_id, prompt_b),
        (WorkspaceV1.contract_id, Ref(RefType.WORKSPACE, "fake-resource", "workspace-1")),
    )
    repo, service, execution, _ = _setup(tmp_agent_box_home, inputs=inputs)
    service.record_resource_observations(
        execution.id,
        (
            _observation(prompt_a, contract_id=FragmentV1.contract_id, detail="fragment a projected"),
            _observation(prompt_b, contract_id=FragmentV1.contract_id, result=ResourceObservationResult.UNKNOWN, coverage=ResourceObservationCoverage.UNKNOWN, observer_id="codex"),
        ),
    )
    # prompt-b cannot claim prompt-a's observation: wrong native_id fails.
    unobserved = repo.list_unobserved_inputs(execution.id)
    assert (FragmentV1.contract_id, prompt_a) not in unobserved
    assert (FragmentV1.contract_id, prompt_b) not in unobserved
    assert (WorkspaceV1.contract_id, Ref(RefType.WORKSPACE, "fake-resource", "workspace-1")) in unobserved


def test_apply_observation_is_atomic_when_an_observation_is_invalid(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    native = Ref(RefType.SESSION, "fake-execution", "thread-9")
    before_events = len(repo.list_events(execution.id))
    with pytest.raises(ValueError, match="frozen INPUT"):
        service.apply_observation(
            execution.id,
            ExecutionProjection(Phase.ACTIVE, None, True, Freshness.OBSERVED, NOW),
            native_refs=(native,),
            resource_observations=(
                _observation(native, contract_id=WorkspaceV1.contract_id),
            ),
        )
    # Nothing half-applies: an invalid observation rejects the whole batch.
    assert not any(ref.native_id == "thread-9" for ref in repo.list_refs(execution.id))
    assert len(repo.list_events(execution.id)) == before_events


# ── append-only, idempotency, multi-observer ────────────────────────


def test_duplicate_observation_digest_is_idempotent(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    observation = _observation(frozen_ref)
    first = service.record_resource_observations(execution.id, (observation,))
    second = service.record_resource_observations(execution.id, (observation,))
    assert first[0][1] is True
    assert second[0][1] is False
    assert first[0][0] == second[0][0]
    assert len(repo.list_resource_observations(execution.id)) == 1


def test_module_has_no_update_or_delete_for_observation_rows(tmp_agent_box_home):
    import inspect
    from pacthold.work_core import repository as repository_module

    source = inspect.getsource(repository_module)
    assert "UPDATE core_resource_observations" not in source
    assert "DELETE FROM core_resource_observations" not in source


def test_conflicting_observers_coexist_without_resolution(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    service.record_resource_observations(
        execution.id,
        (
            _observation(
                frozen_ref,
                kind=ResourceObservationKind.PROJECTED,
                result=ResourceObservationResult.MATCH,
                observer_role=ResourceObserverRole.EXECUTION_PROVIDER,
                observer_id="fake-execution",
                coverage=ResourceObservationCoverage.UNKNOWN,
                detail=None,
            ),
            _observation(
                frozen_ref,
                result=ResourceObservationResult.MISMATCH,
                observer_role=ResourceObserverRole.HOST_OBSERVER,
                observer_id="host-snapshot",
                detail="tracked HEAD/tree at finish",
            ),
        ),
    )
    observations = repo.list_resource_observations(execution.id)
    assert [item.result for item in observations] == ["match", "mismatch"]
    assert [item.observer_role for item in observations] == [
        "execution_provider",
        "host_observer",
    ]


def test_unknown_and_unverifiable_are_first_class_results(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    service.record_resource_observations(
        execution.id,
        (
            _observation(
                frozen_ref,
                result=ResourceObservationResult.UNKNOWN,
                coverage=ResourceObservationCoverage.UNKNOWN,
                detail="queryable but not yet checked",
            ),
            _observation(
                frozen_ref,
                kind=ResourceObservationKind.CONSUMPTION_REPORTED,
                result=ResourceObservationResult.UNVERIFIABLE,
                observer_role=ResourceObserverRole.EXECUTION_PROVIDER,
                observer_id="fake-execution",
                coverage=ResourceObservationCoverage.UNKNOWN,
                detail="no observation surface exists",
            ),
        ),
    )
    results = {item.result for item in repo.list_resource_observations(execution.id)}
    assert results == {"unknown", "unverifiable"}


# ── terminal monotonic interplay ────────────────────────────────────


def test_late_observation_on_terminal_execution_keeps_outcome_sealed(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    terminal = ExecutionProjection(
        Phase.TERMINAL,
        Outcome.SUCCEEDED,
        False,
        Freshness.OBSERVED,
        datetime.now(timezone.utc),
    )
    from pacthold.work_core.finalization import ExecutionFinalizationRequest
    sealed = repo.get_execution(execution.id)
    service.apply_finalization(ExecutionFinalizationRequest(execution.id, "finish-late", terminal))
    sealed = repo.get_execution(execution.id)
    late_ref = Ref(RefType.ARTIFACT, "fake-resource", "sha256:" + "a" * 64)
    service.record_resource_observations(
        execution.id,
        (
            _observation(
                frozen_ref,
                observed_at=NOW + timedelta(hours=3),
                evidence_ref=late_ref,
            ),
        ),
    )
    after = repo.get_execution(execution.id)
    assert after.projection.phase is Phase.TERMINAL
    assert after.projection.outcome is Outcome.SUCCEEDED
    assert after.version == sealed.version
    assert len(repo.list_resource_observations(execution.id)) == 1


# ── evidence_ref metadata round-trip (migration 008) ────────────────


def test_evidence_ref_metadata_round_trips_completely(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    evidence = Ref(
        RefType.ARTIFACT,
        "fake-resource",
        "sha256:" + "b" * 64,
        uri="file:///evidence/proof.json",
        metadata={"kind": "read-back", "tool": "git", "commit": "abc123"},
    )
    service.record_resource_observations(
        execution.id, (_observation(frozen_ref, evidence_ref=evidence),)
    )
    stored = repo.list_resource_observations(execution.id)
    assert len(stored) == 1
    # The full ArtifactRef — including metadata — survives the round trip.
    assert stored[0].evidence_ref == evidence


def test_evidence_metadata_differences_produce_different_digests(tmp_agent_box_home):
    repo = CoreRepository()
    base = dict(
        contract_id=WorkspaceV1.contract_id,
        ref=Ref(RefType.WORKSPACE, "fake-resource", "workspace-1"),
        kind=ResourceObservationKind.READ_BACK,
        result=ResourceObservationResult.MATCH,
        observer_role=ResourceObserverRole.RESOURCE_PROVIDER,
        observer_id="git-worktree",
        observed_at=NOW,
        coverage=ResourceObservationCoverage.COMPLETE,
        detail="tracked HEAD/tree at finish",
    )
    one = ResourceObservation(
        **base,
        evidence_ref=Ref(
            RefType.ARTIFACT, "fake-resource", "artifact-1", metadata={"tool": "git"}
        ),
    )
    two = ResourceObservation(
        **base,
        evidence_ref=Ref(
            RefType.ARTIFACT, "fake-resource", "artifact-1", metadata={"tool": "fs"}
        ),
    )
    assert repo.observation_digest("exec_1", one) != repo.observation_digest(
        "exec_1", two
    )


def test_empty_evidence_metadata_keeps_legacy_digest_algorithm():
    """Pre-008 observations must stay digest-compatible.

    The payload below is the pre-008 digest body: evidence metadata was not
    part of it.  An evidence ref without metadata must produce exactly that
    digest today, so historical rows never collide or diverge.
    """
    import hashlib
    import json

    observation = ResourceObservation(
        contract_id=WorkspaceV1.contract_id,
        ref=Ref(RefType.WORKSPACE, "fake-resource", "workspace-1"),
        kind=ResourceObservationKind.READ_BACK,
        result=ResourceObservationResult.MATCH,
        observer_role=ResourceObserverRole.RESOURCE_PROVIDER,
        observer_id="git-worktree",
        observed_at=NOW,
        coverage=ResourceObservationCoverage.COMPLETE,
        evidence_ref=Ref(RefType.ARTIFACT, "fake-resource", "artifact-1"),
        detail="tracked HEAD/tree at finish",
    )
    legacy_payload = {
        "execution_id": "exec_1",
        "contract_id": observation.contract_id,
        "ref": {
            "type": observation.ref.type.value,
            "provider": observation.ref.provider,
            "native_id": observation.ref.native_id,
            "uri": observation.ref.uri,
            "metadata": dict(observation.ref.metadata),
        },
        "kind": observation.kind.value,
        "result": observation.result.value,
        "observer_role": observation.observer_role.value,
        "observer_id": observation.observer_id.strip(),
        "observed_at": observation.observed_at.isoformat(),
        "coverage": observation.coverage.value,
        "evidence": {
            "type": observation.evidence_ref.type.value,
            "provider": observation.evidence_ref.provider,
            "native_id": observation.evidence_ref.native_id,
            "uri": observation.evidence_ref.uri,
        },
        "detail": observation.detail,
    }
    legacy_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            legacy_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert CoreRepository.observation_digest("exec_1", observation) == legacy_digest


# ── batch append atomicity ──────────────────────────────────────────


def test_repository_batch_append_rolls_back_on_late_invalid_entry(tmp_agent_box_home):
    """A frozen-association failure anywhere in the batch rejects it all."""
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    valid = _observation(frozen_ref)
    stranger = _observation(
        Ref(RefType.WORKSPACE, "fake-resource", "never-frozen"),
    )
    with pytest.raises(WorkCoreError, match="frozen INPUT"):
        repo.record_resource_observations(execution.id, (valid, stranger))
    # The first (valid) observation must not have been committed.
    assert repo.list_resource_observations(execution.id) == ()


def test_repository_batch_append_rolls_back_mid_transaction(
    tmp_agent_box_home, monkeypatch
):
    """A failure after the first INSERT still removes the first row.

    The fault is injected between the two batch writes to prove the whole
    batch shares one SQLite transaction: the first observation is inserted,
    the second write fails, and rollback leaves the ledger empty.
    """
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    observations = (
        _observation(frozen_ref),
        _observation(frozen_ref, observer_id="second-observer"),
    )
    original = CoreRepository.observation_digest
    calls = {"count": 0}

    def flaky_digest(execution_id, observation):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("simulated mid-batch database failure")
        return original(execution_id, observation)

    monkeypatch.setattr(CoreRepository, "observation_digest", staticmethod(flaky_digest))
    with pytest.raises(RuntimeError, match="mid-batch"):
        repo.record_resource_observations(execution.id, observations)
    assert repo.list_resource_observations(execution.id) == ()


def test_batch_append_is_idempotent_for_duplicates_within_one_batch(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    observation = _observation(frozen_ref)
    results = repo.record_resource_observations(
        execution.id, (observation, observation)
    )
    assert [created for _, created in results] == [True, False]
    assert results[0][0] == results[1][0]
    assert len(repo.list_resource_observations(execution.id)) == 1


def test_service_batch_rejection_leaves_no_partial_writes(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    stranger = Ref(RefType.WORKSPACE, "fake-resource", "never-frozen")
    with pytest.raises(ValueError, match="frozen INPUT"):
        service.record_resource_observations(
            execution.id,
            (_observation(frozen_ref), _observation(stranger)),
        )
    assert repo.list_resource_observations(execution.id) == ()


def test_empty_batch_append_is_a_no_op(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    assert repo.record_resource_observations(execution.id, ()) == ()
    assert service.record_resource_observations(execution.id, ()) == ()
    assert repo.list_resource_observations(execution.id) == ()


# ── legacy compatibility ────────────────────────────────────────────


def test_legacy_resource_states_still_work_and_stay_separate(tmp_agent_box_home):
    repo, service, execution, _ = _setup(tmp_agent_box_home)
    frozen_ref = repo.list_input_refs(execution.id)[0][1]
    service.apply_observation(
        execution.id,
        ExecutionProjection(Phase.ACTIVE, None, True, Freshness.OBSERVED, NOW),
        resource_states=((frozen_ref, "provider-reported:projected"),),
    )
    # Legacy strings do not become structured observations.
    assert repo.list_resource_observations(execution.id) == ()
    events = [
        event
        for event in repo.list_events(execution.id)
        if event.data.get("observation_kind") == "resource"
    ]
    assert events and events[0].data["resource_state"] == "provider-reported:projected"
    # ...and the input still counts as unobserved for the typed ledger.
    assert repo.list_unobserved_inputs(execution.id) == (
        (WorkspaceV1.contract_id, frozen_ref),
    )
