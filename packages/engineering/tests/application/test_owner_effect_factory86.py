"""The native adapter accepts only the canonical Engineering owner bundle.

The fixture uses the original SQLite/service binder, while Records and live
Unit ports are explicit non-effecting test peers. These checks do not qualify
native execution or production Product assembly.
"""
from copy import copy
from types import SimpleNamespace

import pytest

from test_execution_dispatch_assembly import _fixture
from test_method_control_admission import context
from ordessa_engineering.adapters.native_records import (
    engineering_effect_write_guard_factory,
)
from ordessa_engineering.application.assembly import bind_execution_dispatch
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import (
    ImplementationDispatch,
)


def test_factory_unwraps_exact_canonical_owner_without_effects(tmp_path, monkeypatch):
    with _fixture(tmp_path, monkeypatch) as (
        _fixture_value, service, dependencies, records, _query_factory
    ):
        owner = bind_execution_dispatch(service, **dependencies)
        ctx = context("effect-factory-86")

        fixed = engineering_effect_write_guard_factory(owner, ctx, records, owner.blobs)

        # The adapter internally passes the canonical owner's exact original
        # dispatcher to the existing fixed factory. Construction performs no
        # Records query, native call, action consumption, or journal write.
        assert fixed.dispatch_owner is owner.dispatch
        assert service._execution_dispatch is owner
        with pytest.raises(ApplicationError, match="DISPATCH_EFFECT_HANDOFF_UNAVAILABLE"):
            fixed({}, "execution-op-fixture", "sha256:" + "0" * 64, {})

        # Construction does not bind or cache a CommandContext. The actual context
        # is supplied and checked for each effect handoff.
        unbound_context_factory = engineering_effect_write_guard_factory(
            owner, None, records, owner.blobs,
        )
        assert unbound_context_factory.dispatch_owner is owner.dispatch
        with pytest.raises(ApplicationError, match="DISPATCH_EFFECT_HANDOFF_UNAVAILABLE"):
            unbound_context_factory({}, "execution-op-fixture", "sha256:" + "0" * 64, {})


@pytest.mark.parametrize("foreign", ["records", "blobs"])
def test_factory_rejects_foreign_original_source_objects(tmp_path, monkeypatch, foreign):
    with _fixture(tmp_path, monkeypatch) as (
        _fixture_value, service, dependencies, records, _query_factory
    ):
        owner = bind_execution_dispatch(service, **dependencies)
        ctx = context("effect-factory-86-foreign-" + foreign)
        other = object()

        args = (other, owner.blobs) if foreign == "records" else (records, other)
        with pytest.raises(ApplicationError, match="RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED"):
            engineering_effect_write_guard_factory(owner, ctx, *args)


def test_factory_rejects_foreign_dispatch_access_even_on_owner_type(tmp_path, monkeypatch):
    with _fixture(tmp_path, monkeypatch) as (
        _fixture_value, service, dependencies, records, _query_factory
    ):
        owner = bind_execution_dispatch(service, **dependencies)
        foreign_owner = copy(owner)
        original_dispatch = owner.dispatch
        foreign_owner.dispatch = ImplementationDispatch(
            owner.factory,
            SimpleNamespace(handoff_effect_write=lambda *a, **k: None,
                            consume_effect_write=lambda *a, **k: None),
            approval_usecases=original_dispatch.approvals,
            execution=original_dispatch.execution,
            selection=original_dispatch.selection,
            blobs=owner.blobs,
            registry_loader=original_dispatch.registry_loader,
            source_snapshots=original_dispatch.source_snapshots,
            history_sources=original_dispatch.history_sources,
            method_runs=original_dispatch.method_runs,
        )

        with pytest.raises(ApplicationError, match="RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED"):
            engineering_effect_write_guard_factory(
                foreign_owner, context("effect-factory-86-access"), records, owner.blobs,
            )


def test_factory_keeps_exact_original_dispatch_route_and_refuses_incomplete_owner(
    tmp_path, monkeypatch
):
    with _fixture(tmp_path, monkeypatch) as (
        _fixture_value, service, dependencies, records, _query_factory
    ):
        owner = bind_execution_dispatch(service, **dependencies)
        ctx = context("effect-factory-86-unbound")

        # Existing trusted callers that already hold the original exact
        # ImplementationDispatch keep using the same fixed factory.
        fixed = engineering_effect_write_guard_factory(owner.dispatch, ctx, records, owner.blobs)
        assert fixed.dispatch_owner is owner.dispatch
        with pytest.raises(ApplicationError, match="DISPATCH_EFFECT_HANDOFF_UNAVAILABLE"):
            fixed({}, "execution-op-fixture", "sha256:" + "0" * 64, {})

        with pytest.raises(ApplicationError, match="RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED"):
            engineering_effect_write_guard_factory(SimpleNamespace(dispatch=owner.dispatch), ctx,
                                                   records, owner.blobs)

        incomplete = copy(owner)
        incomplete.access = None
        with pytest.raises(ApplicationError, match="RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED"):
            engineering_effect_write_guard_factory(incomplete, ctx, records, owner.blobs)
