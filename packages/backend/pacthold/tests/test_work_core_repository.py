from datetime import datetime, timezone

import pytest

from pacthold.work_core.events import CoreEvent, EventType
from pacthold.work_core.models import Execution, Ref, RefType, Work, WorkLifecycle
from pacthold.work_core.projection import ExecutionProjection, Freshness, Phase
from pacthold.work_core.repository import (
    ConcurrencyConflict,
    CoreRepository,
    RefRelation,
    WorkNotFound,
)


NOW = datetime(2026, 8, 21, tzinfo=timezone.utc)


def event(event_id, kind, subject, data=None):
    return CoreEvent(event_id, kind, subject, NOW, data or {})


def test_persists_work_execution_refs_events_and_reloads(tmp_agent_box_home):
    repo = CoreRepository()
    work = repo.create_work(Work("work_1", "test", WorkLifecycle.OPEN, NOW, NOW), event("evt_1", EventType.WORK_CREATED, "work_1"))
    projection = ExecutionProjection(Phase.ACTIVE, None, True, Freshness.OBSERVED, NOW)
    execution = repo.create_execution(
        Execution("exec_1", work.id, "external-executor", projection, NOW),
        event(
            "evt_2",
            EventType.EXECUTION_CREATED,
            "exec_1",
            {
                "provider": "external-executor",
                "responsibility_intent": "run an exact coding attempt",
            },
        ),
    )
    repo.attach_ref(execution.id, RefRelation.NATIVE, Ref(RefType.SESSION, "external-executor", "session-1"), event("evt_3", EventType.NATIVE_REF_DISCOVERED, execution.id))
    assert repo.get_execution(execution.id).projection.resumable_now is True
    assert repo.list_refs(execution.id)[0].native_id == "session-1"
    assert [item.type for item in repo.list_events(execution.id)] == [EventType.EXECUTION_CREATED, EventType.NATIVE_REF_DISCOVERED]


def test_list_executions_isolated_and_stably_sorted_by_created_at_then_id(tmp_agent_box_home):
    repo = CoreRepository()
    first_work = repo.create_work(
        Work("work_1", "first", WorkLifecycle.OPEN, NOW, NOW),
        event("evt_work_1", EventType.WORK_CREATED, "work_1"),
    )
    second_work = repo.create_work(
        Work("work_2", "second", WorkLifecycle.OPEN, NOW, NOW),
        event("evt_work_2", EventType.WORK_CREATED, "work_2"),
    )

    def create(execution_id, work_id, created_at):
        projection = ExecutionProjection(
            Phase.UNKNOWN, None, None, Freshness.STALE, created_at
        )
        return repo.create_execution(
            Execution(execution_id, work_id, "fake", projection, created_at),
            CoreEvent(
                f"evt_{execution_id}",
                EventType.EXECUTION_CREATED,
                execution_id,
                created_at,
                {"provider": "fake", "responsibility_intent": execution_id},
            ),
        )

    tied = datetime(2026, 8, 22, tzinfo=timezone.utc)
    create("z-last-tie", first_work.id, tied)
    create("a-first-tie", first_work.id, tied)
    create("older", first_work.id, datetime(2026, 8, 21, tzinfo=timezone.utc))
    create("other-work", second_work.id, tied)

    assert [item.id for item in repo.list_executions(first_work.id)] == [
        "older",
        "a-first-tie",
        "z-last-tie",
    ]
    assert [item.id for item in repo.list_executions(second_work.id)] == ["other-work"]


def test_list_executions_empty_work_returns_empty_tuple(tmp_agent_box_home):
    repo = CoreRepository()
    repo.create_work(
        Work("empty", "no executions", WorkLifecycle.OPEN, NOW, NOW),
        event("evt_empty", EventType.WORK_CREATED, "empty"),
    )

    assert repo.list_executions("empty") == ()


def test_list_executions_missing_work_raises_work_not_found(tmp_agent_box_home):
    with pytest.raises(WorkNotFound, match="missing"):
        CoreRepository().list_executions("missing")


def test_optimistic_version_rejects_stale_projection_update(tmp_agent_box_home):
    repo = CoreRepository()
    repo.create_work(Work("work_1", "test", WorkLifecycle.OPEN, NOW, NOW), event("evt_1", EventType.WORK_CREATED, "work_1"))
    current = repo.create_execution(
        Execution("exec_1", "work_1", "fake", ExecutionProjection(Phase.ACTIVE, None, False, Freshness.OBSERVED, NOW), NOW),
        event(
            "evt_2",
            EventType.EXECUTION_CREATED,
            "exec_1",
            {
                "provider": "fake",
                "responsibility_intent": "observe optimistic concurrency",
            },
        ),
    )
    repo.update_projection(current, expected_version=0, event=event("evt_3", EventType.EXECUTION_PROJECTION_CHANGED, "exec_1"))
    with pytest.raises(ConcurrencyConflict):
        repo.update_projection(current, expected_version=0, event=event("evt_4", EventType.EXECUTION_PROJECTION_CHANGED, "exec_1"))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"provider": "fake"}, "responsibility_intent is required"),
        (
            {"provider": "other", "responsibility_intent": "review the change"},
            "provider must match",
        ),
        (
            {"provider": "fake", "responsibility_intent": "  review the change  "},
            "must be normalized",
        ),
    ],
)
def test_execution_created_event_must_match_execution(data, message, tmp_agent_box_home):
    repo = CoreRepository()
    repo.create_work(
        Work("work_1", "test", WorkLifecycle.OPEN, NOW, NOW),
        event("evt_1", EventType.WORK_CREATED, "work_1"),
    )
    execution = Execution(
        "exec_1",
        "work_1",
        "fake",
        ExecutionProjection(Phase.ACTIVE, None, False, Freshness.OBSERVED, NOW),
        NOW,
    )

    with pytest.raises(ValueError, match=message):
        repo.create_execution(
            execution,
            event("evt_2", EventType.EXECUTION_CREATED, "exec_1", data),
        )
