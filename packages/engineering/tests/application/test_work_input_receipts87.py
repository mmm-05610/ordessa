"""Work input selections are journaled with their original CAS observation."""
from contextlib import contextmanager
from dataclasses import asdict

import pytest

from test_method_work import env, call, _context
from ordessa_engineering.application.contracts.method_work import WorkSeed
from ordessa_engineering.application.contracts.commands import ReadSet
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.orchestration.method_runs import _loop_round
from ordessa_engineering.methods.definitions.models.compiled import (
    LoopSpec, OperationNode, OutcomeBinding, OutcomeMap, StopNode,
    TransitionTarget, WaitNode, WorkflowSpec,
)
from types import SimpleNamespace


def _parameters(e, run_id):
    with e['factory'].begin(e['scope'], 'read') as uow:
        row = uow.workflow.run_row(run_id)
        ordinal = uow.workflow.next_step_ordinal(run_id)
    return {'run_id': run_id, 'input_ref': asdict(e['ref']),
            'expected_row_digest': asdict(run_wait_row_digest(row)),
            'expected_next_step_ordinal': ordinal}


@contextmanager
def _selected(e, context, snapshot, view, input_ref):
    assert input_ref == e['ref']
    assert view['run_id'] in {'work-a', 'work-b'}
    with e['factory'].begin(e['scope'], 'read') as uow:
        assert uow.engineering.resolve_revision(input_ref).ref == input_ref
    yield WorkSeed({'initial': {'selected_ref': asdict(input_ref)}}, ReadSet(e['scope'], ()))


def test_loop_round_uses_compiled_backedge_body_not_only_endpoints():
    def operation(step_id, target):
        return OperationNode(id=step_id, kind='operation', operation='engineering.fixture',
            outcomes=OutcomeMap(entries=(OutcomeBinding(outcome='completed', target=target),)))

    workflow = WorkflowSpec(schema_version=1, entry='prefix',
        steps=(operation('prefix', TransitionTarget(next='head')),
            operation('head', TransitionTarget(next='body')),
            WaitNode(id='body', kind='wait', event='fixture.event', next='tail'),
            OperationNode(id='tail', kind='operation', operation='engineering.fixture',
                outcomes=OutcomeMap(entries=(
                    OutcomeBinding(outcome='again', target=TransitionTarget(next='body')),
                    OutcomeBinding(outcome='done', target=TransitionTarget(stop='finished'))))),
            StopNode(id='finished', kind='stop', outcome='finished'),
            StopNode(id='exhausted', kind='stop', outcome='exhausted')),
        stop_outcomes=('finished', 'exhausted'), wait_kinds=('fixture.event',),
        loops=(LoopSpec(loop_id='repeat', from_step='tail', to_step='body',
                        max_rounds=3, on_exhausted='exhausted'),))
    program = SimpleNamespace(workflow=workflow)
    row = {'inputs': {'rounds': {'repeat': 2}}}
    assert _loop_round(program, row, 'body') == 2
    assert _loop_round(program, row, 'tail') == 2
    assert _loop_round(program, row, 'head') == 1


def test_bind_inputs_records_exact_two_run_cas_and_survives_reopen(env):
    e = env
    e['source'].guard_inputs = lambda *args: _selected(e, *args)
    for run_id in ('work-a', 'work-b'):
        started = call(e, 'engineering.work.start', {'run_id': run_id}, f'start-{run_id}')
        assert started.result['run_id'] == run_id

    results = {}
    for run_id in ('work-a', 'work-b'):
        parameters = _parameters(e, run_id)
        before = parameters['expected_row_digest']
        request_id = f'bind-{run_id}'
        result = call(e, 'engineering.work.bind_inputs', parameters, request_id)
        results[run_id] = result
        with e['factory'].begin(e['scope'], 'read') as uow:
            row = uow.workflow.run_row(run_id)
            after = run_wait_row_digest(row)
            journal = uow.commands.get(_context(e['scope'], request_id).key)
            assert journal is not None and journal.state == 'completed'
            assert journal.result_bytes == result.result_bytes
            assert row['status'] == 'WAITING_FOR_CONDITION' and row['cursor'] == 0
            assert uow.workflow.next_step_ordinal(run_id) == 0
        expected_observation = record_digest('engineering-work-input-selection', {
            'run_id': run_id, 'input_ref': asdict(e['ref']),
            'method_ref': asdict(e['method']), 'node_id': 'seed',
            'round': 1, 'ordinal': 0,
            'before': before, 'after': asdict(after)})
        assert result.result == {
            'run_id': run_id, 'status': 'WAITING_FOR_CONDITION', 'cursor': 0,
            'input_slots': ['initial'], 'dispatched': False,
            'input_ref': asdict(e['ref']), 'method_ref': asdict(e['method']),
            'node': 'seed', 'round': 1, 'ordinal': 0,
            'before_after_digest': asdict(expected_observation)}
        assert call(e, 'engineering.work.bind_inputs', parameters, request_id) == result
        with pytest.raises(ApplicationError, match='RUN_WAIT_CHANGED'):
            call(e, 'engineering.work.bind_inputs', parameters, f'stale-{run_id}')

    # Reopen the same original SQLite library and verify both the selected
    # slots and terminal command journal are still the authoritative facts.
    e['lib'].close()
    reopened = EngineeringLibrary.open((e['tmp_path'] / 'work.sqlite').resolve(),
                                       library_id='work-fixture')
    e['lib'] = reopened
    e['factory'] = SQLiteUoWFactory(reopened)
    with e['factory'].begin(e['scope'], 'read') as uow:
        for run_id in ('work-a', 'work-b'):
            row = uow.workflow.run_row(run_id)
            assert row['inputs']['slots']['initial'] == {
                'selected_ref': asdict(e['ref'])}
            assert uow.workflow.next_step_ordinal(run_id) == 0
        for run_id, result in results.items():
            journal = uow.commands.get(_context(e['scope'], f'bind-{run_id}').key)
            assert journal is not None and journal.result_bytes == result.result_bytes
    reopened.close()
