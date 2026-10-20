"""Actual authored declaration publication; no production grants or execution."""
from pathlib import Path

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.api.method_publication import publish_method_declaration
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.methods import load_method, read_method_definition, compile_method
from ordessa_engineering.methods.definitions.models import MethodRef, MethodSource

from test_method_control_admission import context


CANDIDATE = Path(__file__).resolve().parents[4] / 'methods/incremental-engineering/candidates/2.7.0'


def test_actual_27_declaration_publishes_and_reopens_without_workflow_or_project_control(tmp_path):
    loaded = load_method(MethodSource(CANDIDATE, 'method.json'), FileResourceReader())
    assert loaded.ok, loaded.error
    declared = read_method_definition(loaded.value)
    assert declared.ok, declared.error
    execution = compile_method(loaded.value, object(), 'unavailable-schema2-compiler')
    assert not execution.ok and execution.error.code == 'METHOD_EXECUTION_UNSUPPORTED'

    path = (tmp_path / 'declaration.sqlite').resolve()
    library = EngineeringLibrary.create(path, library_id='declaration-publication', schema_version=16)
    try:
        store = SQLiteSnapshotStore(library)
        published = publish_method_declaration(loaded.value, store)
        assert published.ok, published.error
        ref = published.value
        assert ref.snapshot_digest.hex == declared.value.method_ref.snapshot_digest
        exact = MethodRef(ref.method_id, ref.release_version, ref.schema_version, ref.snapshot_digest.hex)
        assert store.get_declaration(exact) == declared.value
        assert publish_method_declaration(loaded.value, store) == published
        controls = SQLiteMethodControl(SQLiteUoWFactory(library), store)
        with pytest.raises(ApplicationError, match='METHOD_CONTROL_UNAVAILABLE'):
            with controls.guard(context('uncontrolled-declaration'), ref):
                pytest.fail('publication must not mint project control')
    finally:
        library.close()

    reopened = EngineeringLibrary.open(path, library_id='declaration-publication')
    try:
        assert SQLiteSnapshotStore(reopened).get_declaration(exact) == declared.value
        # This exact pin is a declaration, never a fabricated compiled workflow.
        from ordessa_engineering.methods.definitions.errors import MethodFailure
        with pytest.raises(MethodFailure):
            SQLiteSnapshotStore(reopened).get(exact)
    finally:
        reopened.close()


def test_public_declaration_publication_rejects_arbitrary_projection(tmp_path):
    library = EngineeringLibrary.create((tmp_path / 'invalid.sqlite').resolve(),
                                        library_id='invalid-declaration', schema_version=16)
    try:
        store = SQLiteSnapshotStore(library)
        result = publish_method_declaration(object(), store)
        assert not result.ok
        assert store.get_digest('ordessa.incremental-engineering', '2.7.0') is None
    finally:
        library.close()
