"""Withdrawn compiled result-routing route, kept as an explicit record.

The previous suite asserted that an accepted result routed to a stop outcome
finished as SLICE_DONE without spending a loop round, and inspected the
persisted step receipt, round counter and cursor the compiled program produced.
Those invariants belong to the withdrawn compiled route: creating and advancing
a compiled run is no longer an advertised Service operation, and this stage keeps
the persisted rows for reading only. The retired assertions are recorded here
rather than silently dropped or weakened:

  * accepted-result routing stops with the declared outcome (`SLICE_DONE`);
  * loop rounds are consumed only where the compiled workflow declares them;
  * one step receipt is written per recorded command step;
  * the receipt carries the stop and result outcomes it was routed by.

Re-establishing them needs a real declarative replacement for compiled step and
result routing, which is not in this stage's scope.
"""
import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from test_method_work import call, env, query, seed_historical_run

WITHDRAWN = (
    'engineering.work.bind_inputs',
    'engineering.work.record_command_step',
    'engineering.work.record_dispatch_step',
    'engineering.runs.resume',
    'engineering.runs.cancel',
)


def test_compiled_create_and_advance_routes_are_withdrawn(env):
    """No advertised route reaches the compiled create/advance lifecycle."""
    e = env
    advertised = set(type(e['facade']).supported_commands)
    for operation in WITHDRAWN:
        assert operation not in advertised
        with pytest.raises(ApplicationError) as refused:
            call(e, operation, {'run_id': 'accepted-route-run'}, 'withdrawn-' + operation)
        assert refused.value.code == 'OPERATION_UNAVAILABLE'


def test_historical_compiled_row_stays_readable_and_unadvanced(env):
    """A seeded historical row can still be read, and nothing advances it."""
    e = env
    seed_historical_run(e, 'historical-only-run')
    listed = query(e, 'engineering.runs.list', {'limit': 8}, 'historical-list')
    assert [row['run_id'] for row in listed['runs']] == ['historical-only-run']
    assert listed['runs'][0]['status'] == 'WAITING_FOR_CONDITION'
    assert listed['runs'][0]['execution'] == {'availability': 'unavailable'}
    for operation in WITHDRAWN:
        with pytest.raises(ApplicationError) as refused:
            call(e, operation, {'run_id': 'historical-only-run'}, 'advance-' + operation)
        assert refused.value.code == 'OPERATION_UNAVAILABLE'
    final = e['lib'].run_row('historical-only-run')
    assert final['status'] == 'WAITING_FOR_CONDITION'
    assert not e['lib'].step_rows('historical-only-run')
