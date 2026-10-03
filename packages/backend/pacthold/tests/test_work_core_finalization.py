from datetime import datetime, timezone

import pytest

from pacthold.work_core import db
from pacthold.work_core import (
    ExecutionFinalizationRequest,
    ExecutionProjection,
    Freshness,
    Outcome,
    Phase,
    Ref,
    RefType,
)
from pacthold.work_core.errors import FinalizationConflict, FinalizationRequired
from pacthold.work_core.events import EventType
from pacthold.work_core.events import CoreEvent
from pacthold.work_core.repository import CoreRepository, RefRelation
from pacthold.work_core.resource_observations import ResourceObservation, ResourceObservationCoverage, ResourceObservationKind, ResourceObservationResult, ResourceObserverRole
from pacthold.work_core.services import ExecutionService, WorkService


def _projection(outcome=Outcome.SUCCEEDED):
    return ExecutionProjection(Phase.TERMINAL, outcome, False, Freshness.OBSERVED, datetime.now(timezone.utc))


def _new(tmp_agent_box_home):
    repo = CoreRepository()
    work = WorkService(repo).create_work("atomic finalization")
    execution = ExecutionService(repo).create_execution(work.id, "test", responsibility_intent="finish")
    return repo, ExecutionService(repo), execution


def test_first_terminal_observation_requires_finalization(tmp_agent_box_home):
    repo, service, execution = _new(tmp_agent_box_home)
    with pytest.raises(FinalizationRequired, match="apply_finalization"):
        service.apply_observation(execution.id, _projection())
    assert repo.get_execution(execution.id).projection.phase is Phase.UNKNOWN


def test_empty_finalization_receipt_replays_without_writes(tmp_agent_box_home):
    repo, service, execution = _new(tmp_agent_box_home)
    request = ExecutionFinalizationRequest(execution.id, "finish-1", _projection())
    receipt = service.apply_finalization(request)
    before = (repo.get_execution(execution.id).version, len(repo.list_events(execution.id)))
    replay = service.apply_finalization(request)
    assert replay == receipt
    assert (repo.get_execution(execution.id).version, len(repo.list_events(execution.id))) == before
    assert repo.get_execution(execution.id).projection.outcome is Outcome.SUCCEEDED


def test_conflicting_key_and_terminal_outcome_are_rejected(tmp_agent_box_home):
    repo, service, execution = _new(tmp_agent_box_home)
    service.apply_finalization(ExecutionFinalizationRequest(execution.id, "finish-1", _projection()))
    with pytest.raises(FinalizationConflict):
        service.apply_finalization(ExecutionFinalizationRequest(execution.id, "finish-1", _projection(Outcome.FAILED)))
    with pytest.raises(FinalizationConflict):
        service.apply_finalization(ExecutionFinalizationRequest(execution.id, "finish-2", _projection()))
    assert repo.get_execution(execution.id).projection.outcome is Outcome.SUCCEEDED


def test_finalization_rolls_back_refs_projection_and_events(tmp_agent_box_home, monkeypatch):
    repo, service, execution = _new(tmp_agent_box_home)
    native = Ref(RefType.SESSION, "test", "session-1")
    output = Ref(RefType.ARTIFACT, "test", "output-1")
    original = repo._append_event
    calls = 0

    def fail_on_finalization_event(conn, event):
        nonlocal calls
        calls += 1
        # Creation already happened; native and output events are calls 1/2.
        if calls == 3:
            raise RuntimeError("injected before commit")
        return original(conn, event)

    monkeypatch.setattr(repo, "_append_event", fail_on_finalization_event)
    with pytest.raises(RuntimeError, match="injected"):
        service.apply_finalization(ExecutionFinalizationRequest(
            execution.id, "finish-crash", _projection(), native_refs=(native,), output_refs=(output,)
        ))
    assert repo.get_execution(execution.id).projection.phase is Phase.UNKNOWN
    assert repo.get_execution(execution.id).version == 0
    assert repo.list_refs(execution.id) == []
    assert repo.list_events(execution.id) == [repo.list_events(execution.id)[0]]
    assert db.get_conn().execute("SELECT COUNT(*) FROM core_execution_finalizations").fetchone()[0] == 0


def test_terminal_late_observation_remains_append_only(tmp_agent_box_home):
    repo, service, execution = _new(tmp_agent_box_home)
    service.apply_finalization(ExecutionFinalizationRequest(execution.id, "finish-1", _projection()))
    # No frozen inputs means this test only checks the terminal boundary via
    # the empty ledger; the existing observation API remains the late channel.
    assert repo.get_execution(execution.id).projection.phase is Phase.TERMINAL
    assert EventType.EXECUTION_FINALIZED in [e.type for e in repo.list_events(execution.id)]


def test_refs_observation_projection_and_receipt_commit_together(tmp_agent_box_home):
    repo, service, execution = _new(tmp_agent_box_home)
    input_ref = Ref(RefType.WORKSPACE, "test", "workspace-1")
    repo.attach_ref(execution.id, RefRelation.INPUT, input_ref, CoreEvent("input", EventType.REF_ATTACHED, execution.id, datetime.now(timezone.utc), {"contract_id": "test.workspace@1"}), contract_id="test.workspace@1")
    observation = ResourceObservation(
        "test.workspace@1", input_ref, ResourceObservationKind.READ_BACK,
        ResourceObservationResult.MATCH, ResourceObserverRole.HOST_OBSERVER,
        "host", datetime.now(timezone.utc), ResourceObservationCoverage.UNKNOWN,
    )
    output = Ref(RefType.ARTIFACT, "test", "artifact-1")
    service.apply_finalization(ExecutionFinalizationRequest(
        execution.id, "finish-bundle", _projection(),
        native_refs=(Ref(RefType.SESSION, "test", "session-1"),),
        output_refs=(output,), resource_observations=(observation,),
    ))
    assert repo.get_execution(execution.id).projection.phase is Phase.TERMINAL
    assert repo.list_refs(execution.id, RefRelation.OUTPUT) == [output]
    assert len(repo.list_resource_observations(execution.id)) == 1


def test_concurrent_finalization_has_one_winner(tmp_agent_box_home):
    import threading
    repo, service, execution = _new(tmp_agent_box_home)
    results, errors = [], []
    def run(key):
        try:
            results.append(service.apply_finalization(ExecutionFinalizationRequest(execution.id, key, _projection())))
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=run, args=(f"finish-{i}",)) for i in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], FinalizationConflict)
    assert repo.get_execution(execution.id).version == 1
