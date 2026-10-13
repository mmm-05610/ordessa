"""MethodRun survives closing its original SQLite connection.

These tests use the real EngineeringLibrary, frozen snapshot, selected method,
control row, UoW and command journal. The WorkConditionSource below is an
explicit fixture authority recreated after reopening and contains no reference
to the closed library. It is not production admission or execution authority.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.contracts.commands import ReadSet
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WorkWaitSelection
from ordessa_engineering.application.contracts.run_waits import BoundRunWait
from ordessa_engineering.application.orchestration.method_runs import MethodRunBindings
from test_method_work import env
from test_review_usecases import _context


class _ReopenedWorkConditionSource:
    """Small trusted fixture; deliberately has no old Library/factory closure."""
    def __init__(self, scope, artifact_ref):
        self.scope = scope
        self.artifact_ref = artifact_ref

    @contextmanager
    def guard_condition(self, context, snapshot, node, view):
        condition = BoundRunWait(
            self.scope, view['run_id'], view['row_digest'],
            view['next_step_ordinal'], 'object_exists', (self.artifact_ref,))
        yield WorkWaitSelection(condition, {'artifact_ref': asdict(self.artifact_ref)})

    @contextmanager
    def guard_step_completion(self, context, snapshot, node, view):
        yield ReadSet(self.scope, ())


def _reopened_service(e, registry):
    path = e['lib'].path
    library_id = e['lib'].library_id
    e['lib'].close()
    lib = EngineeringLibrary.open(path, library_id=library_id)
    factory = SQLiteUoWFactory(lib)
    snapshots = SQLiteSnapshotStore(lib)
    methods = SQLiteMethodControl(factory, snapshots)
    source = _ReopenedWorkConditionSource(e['scope'], e['ref'])
    bindings = MethodRunBindings(factory, methods, source, lambda: registry)
    facade = EngineeringService(factory, e['access'], current_wait_bindings=bindings)
    return lib, factory, snapshots, methods, source, facade


def _query(facade, e, request_id='reopen-condition'):
    return asyncio.run(facade.query('engineering.work.current_condition',
        {'run_id': 'work'}, _context(e['scope'], request_id)))


def _resume(facade, e, state, request_id='reopen-resume'):
    params = {'run_id': 'work', 'expected_row_digest': state['row_digest'],
        'expected_condition_digest': state['condition_digest'],
        'expected_next_step_ordinal': state['next_step_ordinal']}
    return asyncio.run(facade.execute('engineering.runs.resume', params,
        _context(e['scope'], request_id)))


def _current_identity(e):
    with e['factory'].begin(e['scope'], 'read') as uow:
        selected = uow.methods.selected()
        control = uow.methods.control(e['method'])
        row = uow.workflow.run_row('work')
        ordinal = uow.workflow.next_step_ordinal('work')
        steps = uow.workflow.step_rows('work')
    return selected, control, row, ordinal, steps


def test_method_run_wait_resumes_after_original_library_close_and_reopen(env):
    e = env
    asyncio.run(e['facade'].execute('engineering.work.start', {'run_id': 'work'},
        _context(e['scope'], 'reopen-start')))
    prior = _query(e['facade'], e, 'pre-close-condition')
    selected_before, control_before, row_before, ordinal_before, steps_before = _current_identity(e)
    old_path, old_id = e['lib'].path, e['lib'].library_id

    lib, factory, snapshots, methods, source, facade = _reopened_service(e, e['registry'])
    e.update(lib=lib, factory=factory, snapshots=snapshots, controls=methods,
             source=source, bindings=None, facade=facade)
    try:
        exact_snapshot = methods.read_snapshot(e['method'])
        assert (exact_snapshot.ref.method_id, exact_snapshot.ref.release_version,
                exact_snapshot.ref.schema_version, exact_snapshot.ref.snapshot_digest) == (
                    e['method'].method_id, e['method'].release_version,
                    e['method'].schema_version, e['method'].snapshot_digest.hex)
        selected_after, control_after, row_after, ordinal_after, steps_after = _current_identity(e)
        assert selected_after == selected_before
        assert control_after == control_before
        assert row_after == row_before
        assert ordinal_after == ordinal_before
        assert steps_after == steps_before
        assert old_path == lib.path and old_id == lib.library_id

        resumed = _resume(facade, e, prior)
        assert resumed.status == 'completed'
        assert resumed.result['dispatched'] is False
        recovered = lib.run_row('work')
        assert recovered['status'] == 'RUNNING'
        assert recovered['cursor'] == 1
        rows = lib.step_rows('work')
        assert rows == steps_before == []
    finally:
        lib.close()


def test_registry_identity_drift_after_reopen_refuses_query_and_resume_without_writes(env):
    e = env
    asyncio.run(e['facade'].execute('engineering.work.start', {'run_id': 'work'},
        _context(e['scope'], 'drift-start')))
    prior = _query(e['facade'], e, 'pre-drift-condition')
    _, _, row_before, ordinal_before, steps_before = _current_identity(e)
    changed_registry = {'registry_id': 'different-registry', 'revision': 2,
                        'registry_digest': 'sha256:' + 'd' * 64}

    lib, factory, snapshots, methods, source, facade = _reopened_service(e, changed_registry)
    e.update(lib=lib, factory=factory, snapshots=snapshots, controls=methods,
             source=source, bindings=None, facade=facade)
    try:
        with pytest.raises(ApplicationError, match='METHOD_CAPABILITY_CHANGED'):
            _query(facade, e, 'drift-query')
        with pytest.raises(ApplicationError, match='METHOD_CAPABILITY_CHANGED'):
            _resume(facade, e, prior, 'drift-resume')
        with factory.begin(e['scope'], 'read') as uow:
            row_after = uow.workflow.run_row('work')
            ordinal_after = uow.workflow.next_step_ordinal('work')
            steps_after = uow.workflow.step_rows('work')
            assert uow.commands.get(_context(e['scope'], 'drift-resume').key) is None
        assert row_after == row_before
        assert ordinal_after == ordinal_before
        assert steps_after == steps_before
        assert lib.step_rows('work') == []
    finally:
        lib.close()
