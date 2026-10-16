"""Canonical dispatch assembly retains the original Engineering owner graph.

The SQLite factory, method-control and blob source are real. Execution
Records/query, selection, source snapshot and history ports are explicit
synthetic adapters; these tests qualify the seam, not native dispatch authority.
"""
from types import SimpleNamespace

import pytest

from test_invariant_checks import invariant_source
from test_proposal_usecases import SyntheticAccess
from ordessa_engineering.application.assembly import bind_execution_dispatch
from ordessa_engineering.application.api import EngineeringService
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.owner_operations import EngineeringOwnerOperations
from ordessa_engineering.application.assembly import build_method_run_bindings


class _Records:
    @staticmethod
    def acp_turn_query_digest(*args):
        raise AssertionError('binding does not read Records')

    def query_acp_turn(self, *args, **kwargs):
        raise AssertionError('binding does not read Records')


class _Execution:
    def __init__(self, records, query_factory):
        self.records = records
        self.query_factory = query_factory

    def freeze_input(self, *args):
        raise AssertionError('binding does not dispatch')

    def query_digest(self, *args):
        raise AssertionError('binding does not dispatch')

    def guard_effect_handoff(self, *args, **kwargs):
        raise AssertionError('binding does not suspend an admission')

    def send(self, *args, **kwargs):
        raise AssertionError('binding does not dispatch')

    def capture(self, *args):
        raise AssertionError('binding does not reconcile')


class _WorkSource:
    def __init__(self, factory):
        self.factory = factory

    def guard_start(self, *args):
        raise AssertionError('binding does not start Work')

    def guard_condition(self, *args):
        raise AssertionError('binding does not resume Work')

    def guard_step_completion(self, *args):
        raise AssertionError('binding does not advance a Work step')


class _Access(SyntheticAccess):
    def handoff_effect_write(self, *args, **kwargs):
        raise AssertionError('binding does not suspend an admission')

    def consume_effect_write(self, *args, **kwargs):
        raise AssertionError('binding does not consume an admission')


class _Selection:
    def guard_selection(self, *args):
        raise AssertionError('binding does not select a native Unit')


class _Snapshots:
    def guard_commit_snapshot(self, *args):
        raise AssertionError('binding does not read native snapshots')


class _History:
    def guard_history_read(self, *args):
        raise AssertionError('binding does not read native history')


def _fixture(source):
    records = _Records()
    query_factory = lambda binding: (_ for _ in ()).throw(AssertionError('not invoked'))
    bindings = build_method_run_bindings(source.factory, method_control=source.methods,
        work_condition_source=_WorkSource(source.factory), registry_loader=lambda: object())
    service = EngineeringService(
        source.factory,
        _Access(),
        blobs=source.blobs,
        current_wait_bindings=bindings,
        execution_records=records,
        execution_query_factory=query_factory,
    )
    dependencies = dict(
        execution=_Execution(records, query_factory),
        selection=_Selection(),
        source_snapshots=_Snapshots(),
        history_sources=_History(),
    )
    return service, dependencies, records, query_factory, bindings


def test_bind_returns_canonical_owner_operations_over_original_service_objects(invariant_source):
    source, *_ = invariant_source
    service, dependencies, records, query_factory, bindings = _fixture(source)

    owner = bind_execution_dispatch(service, **dependencies)

    assert type(owner) is EngineeringOwnerOperations
    assert service._execution_dispatch is owner
    assert owner.factory is service._factory is source.factory
    assert owner.access is service._access
    assert owner.packages is service._packages
    assert owner.submissions is service._submission_reports
    assert owner.records is records is service._execution_records
    assert owner.blobs is service._blobs is source.blobs
    assert owner.packages.approvals is owner.submissions.approvals
    assert owner.submissions.method_runs is bindings is service._work.bindings
    assert owner.dispatch.factory is source.factory
    assert owner.dispatch.access is service._access
    assert owner.dispatch.approvals is owner.packages.approvals
    assert owner.dispatch.execution is dependencies['execution']
    assert owner.dispatch.execution.query_factory is query_factory
    assert owner.dispatch.method_runs is bindings
    assert owner.dispatch.registry_loader is bindings.registry_loader


@pytest.mark.parametrize('port', ['selection', 'source_snapshots', 'history_sources'])
def test_missing_native_guard_port_refuses_without_partial_binding(invariant_source, port):
    source, *_ = invariant_source
    service, dependencies, *_ = _fixture(source)
    dependencies[port] = None
    with pytest.raises(ApplicationError):
        bind_execution_dispatch(service, **dependencies)
    assert service._execution_dispatch is None


@pytest.mark.parametrize('mutation', ['records', 'query_factory'])
def test_foreign_execution_reader_refuses_without_partial_binding(invariant_source, mutation):
    source, *_ = invariant_source
    service, dependencies, *_ = _fixture(source)
    if mutation == 'records':
        dependencies['execution'].records = object()
    else:
        dependencies['execution'].query_factory = lambda _binding: None
    with pytest.raises(ApplicationError, match='DISPATCH_OWNER_BINDING_MISMATCH'):
        bind_execution_dispatch(service, **dependencies)
    assert service._execution_dispatch is None


def test_foreign_method_factory_and_already_bound_service_refuse(invariant_source):
    source, *_ = invariant_source
    service, dependencies, *_ = _fixture(source)
    service._work.bindings.methods = SimpleNamespace(factory=object())
    with pytest.raises(ApplicationError, match='DISPATCH_OWNER_BINDING_MISMATCH'):
        bind_execution_dispatch(service, **dependencies)
    assert service._execution_dispatch is None

    bound_service, bound_dependencies, *_ = _fixture(source)
    bound_service._execution_dispatch = SimpleNamespace(execute=lambda *args: None)
    with pytest.raises(ApplicationError, match='DISPATCH_ALREADY_BOUND'):
        bind_execution_dispatch(bound_service, **bound_dependencies)
    assert bound_service._execution_dispatch.execute is not None


@pytest.mark.parametrize('mutation', ['foreign_factory', 'missing_guard'])
def test_foreign_or_incomplete_work_source_refuses(invariant_source, mutation):
    source, *_ = invariant_source
    service, dependencies, *_ = _fixture(source)
    work_source = service._work.bindings.source
    if mutation == 'foreign_factory':
        work_source.factory = object()
    else:
        work_source.guard_condition = None
    with pytest.raises(ApplicationError):
        bind_execution_dispatch(service, **dependencies)
    assert service._execution_dispatch is None


def test_non_service_dto_cannot_be_bound(invariant_source):
    source, *_ = invariant_source
    service, dependencies, *_ = _fixture(source)
    with pytest.raises(ApplicationError, match='DISPATCH_AUTHORITY_MISMATCH'):
        bind_execution_dispatch(SimpleNamespace(**service.__dict__), **dependencies)


@pytest.mark.parametrize('missing', ['handoff_effect_write', 'consume_effect_write', 'guard_effect_handoff'])
def test_missing_native_handoff_port_refuses_before_binding(invariant_source, missing):
    source, *_ = invariant_source
    service, dependencies, *_ = _fixture(source)
    target = dependencies['execution'] if missing == 'guard_effect_handoff' else service._access
    setattr(target, missing, None)
    with pytest.raises(ApplicationError):
        bind_execution_dispatch(service, **dependencies)
    assert service._execution_dispatch is None
