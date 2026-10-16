from contextlib import contextmanager

import pytest

from ordessa_engineering.application.assembly import build_method_run_bindings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_runs import MethodRunBindings


class Factory:
    def begin(self, *_args, **_kwargs):
        raise AssertionError("builder must not begin a transaction")


class MethodControl:
    def __init__(self, factory):
        self.factory = factory

    @contextmanager
    def guard_method(self, *_args, **_kwargs):
        yield None

    @contextmanager
    def guard_selected(self, *_args, **_kwargs):
        yield None


class WorkSource:
    def __init__(self, factory):
        self.factory = factory

    @contextmanager
    def guard_start(self, *_args, **_kwargs):
        yield None

    @contextmanager
    def guard_condition(self, *_args, **_kwargs):
        yield None

    @contextmanager
    def guard_step_completion(self, *_args, **_kwargs):
        yield None


def test_builder_returns_the_existing_binding_without_calling_loader():
    factory = Factory()
    methods = MethodControl(factory)
    source = WorkSource(factory)
    calls = []

    def registry_loader():
        calls.append("called")
        return {"registry_id": "selected", "revision": 1, "registry_digest": "sha256:abc"}

    result = build_method_run_bindings(
        factory,
        method_control=methods,
        work_condition_source=source,
        registry_loader=registry_loader,
    )

    assert build_method_run_bindings.__annotations__["return"] is MethodRunBindings
    assert result.__class__ is MethodRunBindings
    assert result.factory is factory
    assert result.methods is methods
    assert result.source is source
    assert result.registry_loader is registry_loader
    assert calls == []


def test_builder_rejects_factory_without_original_uow_entry():
    class NoBegin:
        pass

    factory = NoBegin()
    with pytest.raises(ApplicationError, match="PERSISTENCE_AUTHORITY_UNAVAILABLE"):
        build_method_run_bindings(
            factory,
            method_control=MethodControl(factory),
            work_condition_source=WorkSource(factory),
            registry_loader=lambda: {},
        )


def test_builder_rejects_method_control_from_another_factory():
    factory = Factory()
    with pytest.raises(ApplicationError, match="METHOD_AUTHORITY_MISMATCH"):
        build_method_run_bindings(
            factory,
            method_control=MethodControl(Factory()),
            work_condition_source=WorkSource(factory),
            registry_loader=lambda: {},
        )


def test_builder_rejects_method_control_missing_original_guards():
    factory = Factory()

    class IncompleteMethodControl:
        def __init__(self):
            self.factory = factory

        def guard_method(self, *_args, **_kwargs):
            pass

    with pytest.raises(ApplicationError, match="METHOD_AUTHORITY_MISMATCH"):
        build_method_run_bindings(
            factory,
            method_control=IncompleteMethodControl(),
            work_condition_source=WorkSource(factory),
            registry_loader=lambda: {},
        )


def test_builder_rejects_source_bound_to_another_factory():
    factory = Factory()
    with pytest.raises(ApplicationError, match="WORK_SOURCE_AUTHORITY_MISMATCH"):
        build_method_run_bindings(
            factory,
            method_control=MethodControl(factory),
            work_condition_source=WorkSource(Factory()),
            registry_loader=lambda: {},
        )


def test_builder_rejects_missing_work_source_guard():
    factory = Factory()

    class IncompleteWorkSource:
        def __init__(self):
            self.factory = factory

        def guard_start(self, *_args, **_kwargs):
            pass

        def guard_condition(self, *_args, **_kwargs):
            pass

    with pytest.raises(ApplicationError, match="WORK_SOURCE_AUTHORITY_UNAVAILABLE"):
        build_method_run_bindings(
            factory,
            method_control=MethodControl(factory),
            work_condition_source=IncompleteWorkSource(),
            registry_loader=lambda: {},
        )


def test_builder_rejects_noncallable_registry_loader_without_invoking_source():
    factory = Factory()
    with pytest.raises(ApplicationError, match="OPERATION_REGISTRY_UNAVAILABLE"):
        build_method_run_bindings(
            factory,
            method_control=MethodControl(factory),
            work_condition_source=WorkSource(factory),
            registry_loader={"registry_id": "untrusted"},
        )


def test_builder_rejects_missing_work_source():
    factory = Factory()
    with pytest.raises(ApplicationError, match="WORK_SOURCE_AUTHORITY_UNAVAILABLE"):
        build_method_run_bindings(
            factory,
            method_control=MethodControl(factory),
            work_condition_source=None,
            registry_loader=lambda: {},
        )
