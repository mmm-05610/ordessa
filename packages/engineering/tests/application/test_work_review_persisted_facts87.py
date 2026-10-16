"""Real Work-row CAS/history with a synthetic plan admission, not a method policy.

The original Work fixture executes its real start/resume and SQLite journal.
Its method is deliberately not a production review method. Only the new
transaction/proof port is qualified here; production target mapping refuses.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace

import pytest

from test_method_work import env, call, query, resume_params, _context
from test_review_usecases import _plan, _create_source
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.review_sources import SQLiteWorkReviewBindings
from ordessa_engineering.application.contracts.method_work import WorkReviewSelector
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.domain.reviews.models import ReviewPlan


class PlanAdmissionPeer:
    """Explicit test oracle for policy; real source owns CAS and frozen facts."""
    def __init__(self, reader, on_guard=None):
        self.reader, self.on_guard = reader, on_guard

    @contextmanager
    def guard_plan(self, context, plan, *, work_selector):
        if self.on_guard is not None:
            self.on_guard()
        yield

    def check_work_review_current(self, *args):
        return self.reader.check_work_review_current(*args)

    def work_review_result(self, *args, **kwargs):
        return self.reader.work_review_result(*args, **kwargs)


def setup(e):
    call(e, 'engineering.work.start', {'run_id': 'work'}, 'start')
    ready = query(e, 'engineering.work.current_condition', {'run_id': 'work'})
    call(e, 'engineering.runs.resume', resume_params(ready), 'resume')
    with e['factory'].begin(e['scope'], 'read') as uow:
        row = uow.workflow.run_row('work')
        ordinal = uow.workflow.next_step_ordinal('work')
    prototype = _plan(e['scope'], e['ref'], 'fact-plan87')
    requirement = replace(prototype.requirement, method_ref=e['method'], phase_key='capture')
    plan = ReviewPlan(prototype.review_id, requirement, prototype.check_policies,
                      prototype.aggregation_policy, prototype.reviewer_requirements)
    selector = WorkReviewSelector(e['scope'], 'work', e['method'], 'capture', 1,
        e['ref'], e['ref'], run_wait_row_digest(row), ordinal)
    reader = SQLiteWorkReviewBindings(e['factory'], e['controls'], scope=e['scope'],
        blobs=SQLiteBlobStore(e['lib']))
    return reader, plan, selector, row


def test_real_row_changes_do_not_replace_frozen_request_facts_and_reopen_replays(env):
    e = env
    reader, plan, selector, before = setup(e)
    context = _context(e['scope'], 'review-facts')
    owner = ReviewUseCases(e['factory'], e['access'], PlanAdmissionPeer(reader))
    result = owner.request({'plan': asdict(plan)}, context, work_selector=selector)
    assert result.status == 'completed'
    recovered_selector, frozen = reader._historical_row(context, plan)
    assert recovered_selector == selector
    assert {k:v for k,v in frozen.items() if k != 'run_id'} == before

    replacement_ref = _create_source(e['factory'], e['scope'])
    with e['factory'].begin(e['scope']) as uow:
        current = uow.workflow.run_row('work')
        updated = {**current['inputs'], 'slots': {
            **current['inputs']['slots'], 'artifact_ref': asdict(replacement_ref)}}
        uow.workflow.replace_run_inputs(run_id='work', expected_inputs=current['inputs'], inputs=updated)
        uow.workflow.update_run(run_id='work', status='WAITING_FOR_CONDITION', cursor=2,
                               wait_reason='result', now=context.received_at)
        uow.commit()
    assert reader._historical_row(context, plan) == (recovered_selector, frozen)
    assert owner.request({'plan': asdict(plan)}, context, work_selector=selector) == result

    e['lib'].close()
    reopened = EngineeringLibrary.open((e['tmp_path'] / 'work.sqlite').resolve(), library_id='work-fixture')
    e['lib'] = reopened
    factory = SQLiteUoWFactory(reopened)
    historical = SQLiteWorkReviewBindings(factory, SQLiteMethodControl(factory, SQLiteSnapshotStore(reopened)),
        scope=e['scope'], blobs=SQLiteBlobStore(reopened))
    assert historical._historical_row(context, plan) == (recovered_selector, frozen)
    replay_owner = ReviewUseCases(factory, e['access'], PlanAdmissionPeer(historical))
    assert replay_owner.request({'plan': asdict(plan)}, context, work_selector=selector) == result


def test_real_row_change_after_admission_before_write_refuses_without_plan_or_proof(env):
    e = env
    reader, plan, selector, before = setup(e)
    context = _context(e['scope'], 'stale-real-row')

    def race():
        with e['factory'].begin(e['scope']) as uow:
            uow.workflow.update_run(run_id='work', status='WAITING_FOR_CONDITION', cursor=2,
                                   wait_reason='result', now=context.received_at)
            uow.commit()

    owner = ReviewUseCases(e['factory'], e['access'], PlanAdmissionPeer(reader, race))
    rejected = owner.request({'plan': asdict(plan)}, context, work_selector=selector)
    assert rejected.status == 'rejected'
    assert rejected.result == {'code': 'WORK_REVIEW_SELECTOR_STALE'}
    with e['factory'].begin(e['scope'], 'read') as uow:
        with pytest.raises(ApplicationError, match='NOT_FOUND'):
            uow.reviews.get_plan(plan.review_id)
        assert uow.commands.find_completed_review_request(e['scope'], review_id=plan.review_id,
                                                        plan_digest=plan.plan_digest) is None
