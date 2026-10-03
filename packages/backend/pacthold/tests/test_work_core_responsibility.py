import pytest

from pacthold.work_core import db
from pacthold.work_core.events import EventType
from pacthold.work_core.repository import CoreRepository
from pacthold.work_core.services import ExecutionService, WorkService


def test_creation_event_is_the_authoritative_responsibility_record(tmp_agent_box_home):
    repo = CoreRepository()
    work = WorkService(repo).create_work("broad multi-session configuration work")
    execution = ExecutionService(repo).create_execution(
        work.id,
        "fake",
        responsibility_intent="  repair concurrent overlay contamination  ",
    )

    assert not hasattr(execution, "objective")
    assert not hasattr(execution, "responsibility_intent")
    created = next(
        event
        for event in repo.list_events(execution.id)
        if event.type is EventType.EXECUTION_CREATED
    )
    assert created.data == {
        "provider": "fake",
        "responsibility_intent": "repair concurrent overlay contamination",
    }
    assert (
        CoreRepository().get_execution_responsibility_intent(execution.id)
        == "repair concurrent overlay contamination"
    )


def test_responsibility_is_required_and_not_inferred_from_work(tmp_agent_box_home):
    repo = CoreRepository()
    work = WorkService(repo).create_work("work objective must not be inherited")

    with pytest.raises(ValueError, match="responsibility_intent is required"):
        ExecutionService(repo).create_execution(
            work.id,
            "fake",
            responsibility_intent="   ",
        )

    assert db.get_conn().execute("SELECT COUNT(*) FROM core_executions").fetchone()[0] == 0


def test_same_work_can_have_distinct_execution_responsibilities(tmp_agent_box_home):
    repo = CoreRepository()
    work = WorkService(repo).create_work("build the plugin")
    service = ExecutionService(repo)
    review = service.create_execution(
        work.id,
        "fake",
        responsibility_intent="independently review credential handling",
    )
    ci = service.create_execution(
        work.id,
        "fake",
        responsibility_intent="run exact-commit CI",
    )

    assert repo.get_execution_responsibility_intent(review.id) == "independently review credential handling"
    assert repo.get_execution_responsibility_intent(ci.id) == "run exact-commit CI"
    assert repo.get_work(work.id).objective == "build the plugin"


def test_legacy_execution_created_event_without_responsibility_is_readable(tmp_agent_box_home):
    repo = CoreRepository()
    work = WorkService(repo).create_work("legacy work")
    execution = ExecutionService(repo).create_execution(
        work.id,
        "fake",
        responsibility_intent="temporary value used to create the row",
    )
    db.get_conn().execute(
        "UPDATE core_events SET data_json = ? WHERE subject_id = ? AND type = ?",
        ('{"provider": "fake"}', execution.id, EventType.EXECUTION_CREATED.value),
    )
    db.get_conn().commit()

    assert CoreRepository().get_execution_responsibility_intent(execution.id) is None
