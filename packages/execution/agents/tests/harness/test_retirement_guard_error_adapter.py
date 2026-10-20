"""Typed Harness boundary over the original Unit retirement read guard.

Only temporary original SQLite rows are used; no Unit runtime or provider runs.
"""
import sqlite3

import pytest

from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_execution_agents.harness.providers.registry import CatalogUnavailable, HarnessAdmission
from ordessa_units.errors import UnitGuaranteeUnavailable, UnitOperationUnknown
from test_registry_retained_guarantees import _owner, _stage, _declaration, _close


def _rows(store):
    with store.transaction() as connection:
        return tuple(connection.iterdump())


@pytest.mark.parametrize("state", ["active", "unknown"])
def test_harness_refusal_keeps_original_sql_usage_and_catalog_draining(tmp_path, state):
    context, catalog, _materials, store = _owner(tmp_path)
    admitted, = _stage(catalog, _declaration()).commit()
    catalog.drain("host-brand", 4)
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO env_usages(usage_id,environment,state,rights,holder_ref,target_ref,revision) "
            "VALUES(?,?,?,?,?,?,?)",
            ("original-held", "catalog-regression", state, '["use"]',
             '{"kind":"operation","operationRef":"original"}',
             safe_json(admitted.provider_ref), 1),
        )
    before = _rows(store)
    try:
        with pytest.raises(CatalogUnavailable, match="Usage remains held") as caught:
            catalog.retire("host-brand", 4)
        assert type(caught.value.__cause__) is UnitGuaranteeUnavailable
        assert caught.value.code == caught.value.__cause__.code == "GUARANTEE_UNAVAILABLE"
        assert _rows(store) == before
        assert store.unresolved_provider_usages("catalog-regression", "host-brand", 4) == ("original-held",)
        assert HarnessAdmission(context).describe_for_cleanup(
            admitted.descriptor.definition_ref, admitted.provider_ref) == admitted
        # The Material/Unit-facing guard still has its original exception.
        with pytest.raises(UnitGuaranteeUnavailable, match="Usage remains held"):
            with context.provider_retirement_guard("host-brand", 4):
                raise AssertionError("held original Usage must prevent entry")
        assert _rows(store) == before
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["sqlite", "unknown"])
def test_harness_guard_does_not_translate_catalog_body_or_source_errors(tmp_path, monkeypatch, failure):
    context, catalog, materials, store = _owner(tmp_path)
    before = _rows(store)
    body_error = UnitGuaranteeUnavailable("controlled body error")
    try:
        with pytest.raises(UnitGuaranteeUnavailable) as caught:
            with context.harness_provider_retirement_guard("host-brand", 4):
                raise body_error
        assert caught.value is body_error
        assert _rows(store) == before
        source_error = (sqlite3.OperationalError("controlled source failure")
                        if failure == "sqlite" else UnitOperationUnknown("controlled unresolved source"))
        def unavailable_source(*_args):
            raise source_error
        with monkeypatch.context() as patch:
            patch.setattr(store, "unresolved_provider_usages", unavailable_source)
            with pytest.raises(type(source_error)) as caught:
                with context.harness_provider_retirement_guard("host-brand", 4):
                    raise AssertionError("failed source must prevent entry")
            assert caught.value is source_error
        assert _rows(store) == before
    finally:
        _close(context, catalog, materials, store)
