"""Canonical Work dispatch assembly over the real schema-17 Engineering owners.

The released 2.7.2 Work/package/review chain, SQLite factory, method guard,
source materials, blob store and approval use cases are real. Records, query,
transport and selection are explicitly controlled test peers; this module
does not start a Unit or establish production transport/permission authority.
"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.assembly import bind_execution_dispatch
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.owner_operations import EngineeringOwnerOperations
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.common.models.values import Digest
from test_work_package_approval_flow_v2 import build_work_package_approval


ENVIRONMENT = EnvironmentRef("assembly-test-environment", "assembly-test-profile",
    Digest("sha256", "c" * 64))


class _Records:
    def acp_turn_query_digest(self, *_args):
        raise AssertionError("binding must not query Records")

    def query_acp_turn(self, *_args, **_kwargs):
        raise AssertionError("binding must not query Records")


class _Execution:
    def __init__(self, records, query_factory):
        self.records = records
        self.query_factory = query_factory

    def freeze_input(self, *_args):
        raise AssertionError("binding must not dispatch")

    def query_digest(self, *_args):
        raise AssertionError("binding must not dispatch")

    @contextmanager
    def guard_effect_handoff(self, *_args, **_kwargs):
        raise AssertionError("binding must not suspend an admission")
        yield

    def send(self, *_args, **_kwargs):
        raise AssertionError("binding must not dispatch")

    def capture(self, *_args):
        raise AssertionError("binding must not reconcile")


class _Selection:
    work_scope_ready = True

    @contextmanager
    def guard_work_selection(self, *_args):
        yield SimpleNamespace(source="controlled-test-only")

    @contextmanager
    def guard_work_scope(self, *_args):
        yield


@contextmanager
def _fixture(tmp_path, monkeypatch):
    with build_work_package_approval(tmp_path, environment_ref=ENVIRONMENT) as fixture:
        service = fixture["service"]
        records = _Records()
        query_factory = lambda _binding: (_ for _ in ()).throw(
            AssertionError("binding must not create a query invocation"))
        # This is the explicit selection point for controlled transport
        # adapters. These assignments happen before binding, on the exact
        # service that already owns the fixture's persisted Work and Grant.
        service._execution_records = records
        service._execution_query_factory = query_factory
        access = service._access

        @contextmanager
        def handoff(*_args, **_kwargs):
            yield

        @contextmanager
        def consume(*_args, **_kwargs):
            yield

        monkeypatch.setattr(access, "handoff_effect_write", handoff, raising=False)
        monkeypatch.setattr(access, "consume_effect_write", consume, raising=False)
        dependencies = {
            "execution": _Execution(records, query_factory),
            "selection": _Selection(),
            # These old read-only peers are intentionally absent. The declared
            # Work path resolves only through method_guard/source_materials.
            "source_snapshots": None,
            "history_sources": None,
        }
        yield fixture, service, dependencies, records, query_factory


def test_binding_uses_one_real_schema17_owner_graph_without_method_run_chain(tmp_path, monkeypatch):
    with _fixture(tmp_path, monkeypatch) as (fixture, service, deps, records, query_factory):
        owner = bind_execution_dispatch(service, **deps)

        assert type(owner) is EngineeringOwnerOperations
        assert service._execution_dispatch is owner
        assert owner.factory is service._factory is fixture["factory"]
        assert owner.access is service._access
        assert owner.packages is service._packages
        assert owner.submissions is service._submission_reports
        assert owner.records is records is service._execution_records
        assert owner.blobs is service._blobs is fixture["env"].blobs
        assert owner.packages.approvals is owner.submissions.approvals
        assert owner.packages.approvals is service._packages.approvals
        assert owner.dispatch.factory is fixture["factory"]
        assert owner.dispatch.access is service._access
        assert owner.dispatch.approvals is owner.packages.approvals
        assert owner.dispatch.execution is deps["execution"]
        assert owner.dispatch.execution.records is records
        assert owner.dispatch.execution.query_factory is query_factory
        assert owner.dispatch.method_guard is fixture["env"].controls
        assert owner.dispatch.source_materials is fixture["env"].materials
        assert owner.dispatch.method_runs is None
        assert owner.dispatch.registry_loader is None
        assert getattr(owner.submissions, "method_runs", None) is None
        assert getattr(service._work, "bindings", None) is None
        assert owner.dispatch.source_snapshots is None
        assert owner.dispatch.history_sources is None


@pytest.mark.parametrize("missing", ["selection", "guard_work_selection", "guard_work_scope"])
def test_missing_real_work_selection_authority_refuses_without_partial_binding(
        tmp_path, monkeypatch, missing):
    with _fixture(tmp_path, monkeypatch) as (_fixture_value, service, deps, *_):
        if missing == "selection":
            deps["selection"] = None
        else:
            setattr(deps["selection"], missing, None)
        with pytest.raises(ApplicationError):
            bind_execution_dispatch(service, **deps)
        assert service._execution_dispatch is None


@pytest.mark.parametrize("mutation", ["records", "query_factory"])
def test_foreign_execution_reader_refuses_without_partial_binding(tmp_path, monkeypatch, mutation):
    with _fixture(tmp_path, monkeypatch) as (_fixture_value, service, deps, *_):
        if mutation == "records":
            deps["execution"].records = object()
        else:
            deps["execution"].query_factory = lambda _binding: None
        with pytest.raises(ApplicationError, match="DISPATCH_OWNER_BINDING_MISMATCH"):
            bind_execution_dispatch(service, **deps)
        assert service._execution_dispatch is None


@pytest.mark.parametrize("mutation", ["foreign_factory", "missing_method"])
def test_foreign_or_missing_original_method_guard_refuses(tmp_path, monkeypatch, mutation):
    with _fixture(tmp_path, monkeypatch) as (_fixture_value, service, deps, *_):
        if mutation == "foreign_factory":
            service._method_guard = SimpleNamespace(factory=object(), guard=lambda *_: None,
                resource_ref=lambda *_: None, read_resource=lambda *_: None)
        else:
            service._method_guard = None
        with pytest.raises(ApplicationError, match="DISPATCH_OWNER_BINDING_MISMATCH"):
            bind_execution_dispatch(service, **deps)
        assert service._execution_dispatch is None


@pytest.mark.parametrize("mutation", ["foreign_factory", "missing_material"])
def test_foreign_or_missing_original_source_materials_refuse(tmp_path, monkeypatch, mutation):
    with _fixture(tmp_path, monkeypatch) as (_fixture_value, service, deps, *_):
        if mutation == "foreign_factory":
            service._source_materials = SimpleNamespace(factory=object(), read=lambda *_: None)
        else:
            service._source_materials = None
        with pytest.raises(ApplicationError, match="DISPATCH_OWNER_BINDING_MISMATCH"):
            bind_execution_dispatch(service, **deps)
        assert service._execution_dispatch is None


@pytest.mark.parametrize("missing", ["handoff_effect_write", "consume_effect_write", "guard_effect_handoff"])
def test_missing_effect_handoff_port_refuses_before_binding(tmp_path, monkeypatch, missing):
    with _fixture(tmp_path, monkeypatch) as (_fixture_value, service, deps, *_):
        target = deps["execution"] if missing == "guard_effect_handoff" else service._access
        setattr(target, missing, None)
        with pytest.raises(ApplicationError):
            bind_execution_dispatch(service, **deps)
        assert service._execution_dispatch is None


def test_duplicate_binding_and_non_service_dto_refuse(tmp_path, monkeypatch):
    with _fixture(tmp_path, monkeypatch) as (_fixture_value, service, deps, *_):
        with pytest.raises(ApplicationError, match="DISPATCH_AUTHORITY_MISMATCH"):
            bind_execution_dispatch(SimpleNamespace(**service.__dict__), **deps)
        owner = bind_execution_dispatch(service, **deps)
        with pytest.raises(ApplicationError, match="DISPATCH_ALREADY_BOUND"):
            bind_execution_dispatch(service, **deps)
        assert service._execution_dispatch is owner
