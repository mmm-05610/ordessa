"""Original-SQLite Work review journal mechanics; admission is a test peer.

These tests cover request identity, same-UoW correlation and journal replay only.
The synthetic admission port does not qualify the production method's missing
phase-to-subject mapping, reviewer authority, or a complete Work review flow.
"""
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WORK_CONTRACT, WorkReviewSelector
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import SQLiteWorkReviewBindings

from test_review_usecases import (
    LIBRARY_ID, SyntheticAccess, _context, _create_source, _plan, _scope,
)


class SyntheticWorkAdmission:
    """Controlled port peer; it is not a production Work/reviewer authority."""
    def __init__(self, library):
        self.library = library
        self.check_calls = 0
        self.reject_stale = False

    @contextmanager
    def guard_plan(self, context, plan, *, work_selector=None):
        assert work_selector is not None
        yield object()

    def check_work_review_current(self, uow, context, plan, selector):
        self.check_calls += 1
        assert self.library._connection.in_transaction
        if self.reject_stale:
            raise ApplicationError('WORK_REVIEW_SELECTOR_STALE')
        try:
            uow.reviews.get_plan(plan.review_id)
        except ApplicationError as exc:
            if exc.code != 'NOT_FOUND':
                raise
        else:
            raise ApplicationError('WORK_REVIEW_PLAN_ALREADY_BOUND')
        return {'row': {'synthetic_mechanics_peer': True}, 'attempt': selector.attempt,
                'next_step_ordinal': selector.expected_next_step_ordinal}

    def work_review_result(self, context, plan, selector, entry, *, request, work_facts):
        assert entry.state == 'pending'
        assert request['state'] == 'requested'
        assert set(work_facts) == {'row', 'attempt', 'next_step_ordinal'}
        return {
            'work_review': {
                'selector': asdict(selector), 'plan_digest': asdict(plan.plan_digest),
                'review_id': plan.review_id,
                'command': {'key': asdict(entry.key), 'operation_id': entry.operation_id},
            },
            'work_bindings': work_facts,
        }


@pytest.fixture
def review_work(tmp_path):
    library = EngineeringLibrary.create(
        (tmp_path / 'work-review-journal.sqlite').resolve(),
        library_id=LIBRARY_ID + '.work-review-journal87', schema_version=6)
    factory = SQLiteUoWFactory(library)
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject, 'work-review-journal-plan')
    admission = SyntheticWorkAdmission(library)
    service = ReviewUseCases(factory, SyntheticAccess(), admission)
    selector = WorkReviewSelector(scope, 'controlled-run', plan.requirement.method_ref,
        plan.requirement.phase_key, 1, subject, subject,
        plan.requirement.criterion_set_ref.digest, 1)
    try:
        yield {'library': library, 'factory': factory, 'scope': scope, 'plan': plan,
               'service': service, 'admission': admission, 'selector': selector}
    finally:
        library.close()


def _request(env, request_id, *, selector=None, plan=None):
    selected_plan = plan or env['plan']
    context = _context(env['scope'], request_id)
    result = env['service'].request({'plan': asdict(selected_plan)}, context,
        work_selector=selector or env['selector'])
    return context, result


def test_request_persists_same_transaction_work_facts_and_exact_terminal_proof(review_work):
    env = review_work
    context, result = _request(env, 'work-review-request')
    assert result.status == 'completed'
    assert env['admission'].check_calls == 1
    with env['factory'].begin(env['scope'], 'read') as uow:
        command = uow.commands.get(context.key)
    assert command is not None
    from ordessa_engineering.domain.common.mechanisms.codec import canonical_value
    value = canonical_value(command.result_bytes)
    assert set(value) == {'request', 'work_review', 'work_bindings'}
    assert value['work_review']['selector'] == asdict(env['selector'])
    assert value['work_review']['plan_digest'] == asdict(env['plan'].plan_digest)
    assert value['work_review']['command']['key'] == asdict(command.key)
    assert value['work_bindings']['attempt'] == 1
    assert value['work_bindings']['next_step_ordinal'] == 1
    reader = object.__new__(SQLiteWorkReviewBindings)
    reader.factory = env['factory']
    recovered = reader.read_request_correlation(context, env['plan'])
    assert recovered.key == command.key
    assert recovered.operation == 'engineering.reviews.request'


def test_same_key_replays_original_result_but_selector_change_conflicts(review_work):
    env = review_work
    context, first = _request(env, 'work-review-replay')
    _, replay = _request(env, 'work-review-replay')
    assert replay == first
    assert env['admission'].check_calls == 1
    changed = replace(env['selector'], run_id='different-controlled-run')
    with pytest.raises(ApplicationError, match='REQUEST_IDENTITY_CONFLICT'):
        _request(env, 'work-review-replay', selector=changed)


def test_existing_plan_cannot_be_rebound_to_a_second_work_selector(review_work):
    env = review_work
    _request(env, 'work-review-first-work')
    bindings = object.__new__(SQLiteWorkReviewBindings)
    with env['factory'].begin(env['scope'], 'read') as uow:
        with pytest.raises(ApplicationError, match='WORK_REVIEW_PLAN_ALREADY_BOUND'):
            bindings.check_work_review_current(
                uow, _context(env['scope'], 'second-work'), env['plan'],
                replace(env['selector'], run_id='second-controlled-run'))


def test_same_uow_selector_refusal_leaves_no_plan_or_success_proof(review_work):
    env = review_work
    env['admission'].reject_stale = True
    context, result = _request(env, 'work-review-stale')
    assert result.status == 'rejected'
    assert result.result == {'code': 'WORK_REVIEW_SELECTOR_STALE'}
    with env['factory'].begin(env['scope'], 'read') as uow:
        with pytest.raises(ApplicationError, match='NOT_FOUND'):
            uow.reviews.get_plan(env['plan'].review_id)
        assert uow.commands.find_completed_review_request(
            env['scope'], review_id=env['plan'].review_id,
            plan_digest=env['plan'].plan_digest) is None


def test_review_selection_requires_an_actual_work_run(review_work):
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore

    env = review_work
    snapshots = SQLiteSnapshotStore(env['library'])
    controls = SQLiteMethodControl(env['factory'], snapshots)
    bindings = SQLiteWorkReviewBindings(env['factory'], controls,
        scope=env['scope'], blobs=SQLiteBlobStore(env['library']))
    with pytest.raises(ApplicationError, match='WORK_BINDING_INVALID'):
        bindings.review_selection(_context(env['scope'], 'missing-work-run'),
            run_id='controlled-run', review_id='review',
            subject_ref=env['selector'].subject_ref)


@pytest.mark.parametrize('order', ('review-wait-stop', 'wait-stop-review'))
def test_current_review_and_exact_compiled_review_gate_successor_are_allowed_but_later_cursor_is_not(
        review_work, monkeypatch, order):
    from ordessa_engineering.methods.definitions.models.compiled import (
        OperationNode, OutcomeBinding, OutcomeMap, StopNode, TransitionTarget,
        WaitNode, WorkflowSpec,
    )

    env = review_work
    selector = env['selector']
    review = OperationNode(id=selector.phase_key, kind='operation',
        operation='engineering.reviews.request',
        outcomes=OutcomeMap(entries=(OutcomeBinding(outcome='completed',
            target=TransitionTarget(next='await-review')),)))
    wait = WaitNode(id='await-review', kind='wait',
        event='engineering.work.current_condition', next='finished')
    stop = StopNode(id='finished', kind='stop', outcome='finished')
    nodes = (review, wait, stop) if order == 'review-wait-stop' else (wait, stop, review)
    workflow = WorkflowSpec(schema_version=1, entry=review.id,
        steps=nodes, stop_outcomes=('finished',), wait_kinds=(),
        workflow_id='journal87-route')
    snapshot = SimpleNamespace(program=SimpleNamespace(workflow=workflow))
    reader = object.__new__(SQLiteWorkReviewBindings)
    reader.scope = env['scope']
    # This isolated routing fixture supplies the canonical Work binding marker
    # consumed by the real current-method guard. Journal/run persistence remains
    # controlled below; this does not claim a production Work admission flow.
    saved_row = {'cursor': nodes.index(review), 'inputs': {
        'work_contract': WORK_CONTRACT,
        'scope': asdict(env['scope']),
        'method_ref': asdict(selector.method_ref),
        'compiled_plan_digest': 'fixture:compiled-plan',
        'slots': {
            'work_inputs': asdict(selector.input_ref),
            'subject': asdict(selector.subject_ref),
        },
    }}
    current_row = dict(saved_row)
    monkeypatch.setattr(reader, '_historical_row', lambda context, plan: (selector, saved_row))
    monkeypatch.setattr(reader, '_run_row', lambda context, run_id: current_row)
    monkeypatch.setattr(reader, '_snapshot', lambda context, method_ref: nullcontext(snapshot))
    reader._policy = lambda snapshot: {'input_document_slot': 'work_inputs', 'waits': {
        wait.id: {'family': 'review_gate', 'phase_key': selector.phase_key}}}
    request = SimpleNamespace(review_id=env['plan'].review_id,
                               state='requested', version=1, fence=1)
    class ReviewReadUow:
        def __init__(self, selected_request):
            self.reviews = SimpleNamespace(get_request=lambda _review_id: selected_request)
    reader.factory = SimpleNamespace(
        begin=lambda *_args, **_kwargs: nullcontext(ReviewReadUow(request)))
    reader._work_values = lambda *_args, **_kwargs: None
    progression_calls = []
    monkeypatch.setattr(
        'ordessa_engineering.adapters.method_work.SQLitePersistedMethodWorkSource._input_progression_in_uow',
        staticmethod(lambda _uow, _snapshot, _policy, previous, current, *, run_id:
            progression_calls.append((previous, current, run_id)) or None))
    context = _context(env['scope'], 'compiled-route-check')

    current_row['cursor'] = nodes.index(review)
    reader.guard_current_request(context, env['plan'], request)
    current_row['cursor'] = nodes.index(wait)
    reader.guard_current_request(context, env['plan'], request)
    current_row['cursor'] = nodes.index(stop)
    with pytest.raises(ApplicationError, match='WORK_REVIEW_STALE'):
        reader.guard_current_request(context, env['plan'], request)
    assert len(progression_calls) == 2
    assert all(previous == current == selector.input_ref
               for previous, current, _run_id in progression_calls)
