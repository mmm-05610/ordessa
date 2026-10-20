"""Generated schema-2 documents remain readable through the exact package."""
import hashlib
from dataclasses import replace

import pytest
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.implementation_repository import (
    SQLiteImplementationRepository)
from ordessa_engineering.adapters.persistence.sqlite.package_document_materials import (
    PackageDocumentMaterials)
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import (
    SQLiteEngineeringUoW, SQLiteUoWFactory)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.provenance import VersionCapture
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.codec import decode_package_ref

from test_real_source_chain import SCOPE, close_chain, context
from test_itemized_source_chain import build_itemized_chain
from test_work_invoke_generation import (
    _Transport, _command_payload, _command_status, _invoke_generation,
    _prepared_output)
from test_real_source_chain import run_full_chain
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema16
from work_step_access_fixture import enable_controlled_work_steps


@pytest.fixture(autouse=True)
def controlled_work_step_admission(monkeypatch):
    enable_controlled_work_steps(monkeypatch)


_EXPECTED = {
    "spec": b"# Spec\nA bounded generated specification.\n",
    "plan": b"# Plan\nApply the approved source change.\n",
    "tasks": b"# Tasks\n- [ ] Verify the change.\n",
}


def _package_ref(business):
    return decode_package_ref(business["package_ref"])


def _assert_package_not_registered(env, package_id):
    with env.library._read_connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM eng_packages WHERE realm_id=? AND project_id=? AND package_id=?",
            (SCOPE.realm_id, SCOPE.project_id, package_id),
        ).fetchone()
    assert row is None


def _generation_case(tmp_path):
    env = build_itemized_chain(tmp_path)
    migrate_schema16(env.library,
                     backup_path=(tmp_path / "schema16.backup.sqlite").resolve())
    chain = run_full_chain(env)
    captured = _prepared_output(env, chain.review_ref, chain.successor)
    blob = env.blobs.put_verified(
        captured, Digest("sha256", hashlib.sha256(captured).hexdigest()),
        "application/json")
    transport = _Transport(blob, blobs=env.blobs)
    env.service.attach_declared_generation_handles(
        blobs=env.blobs, execution=transport,
        unit_ref_resolver=lambda context, binding, profile_ref: {
            "environmentNamespace": "env", "unitId": "unit-1",
            "ownerProviderRef": {"provider": "local"}, "sourceRevision": "rev-1"})
    return env, chain, transport


def test_generated_documents_survive_reopen_and_read_from_registered_package(tmp_path):
    env, chain, transport = _generation_case(tmp_path)
    try:
        result = _invoke_generation(env, chain, transport)
        payload = _command_payload(result)
        assert _command_status(result) == "completed", payload
        step = next(item for item in payload["steps"]
                    if item.get("business", {}).get("package_ref"))
        package_ref = _package_ref(step["business"])
        path = env.library.path
        env.library.close()

        reopened = EngineeringLibrary.open(path, library_id="local-source-chain")
        factory = SQLiteUoWFactory(reopened)
        blobs = SQLiteBlobStore(reopened)
        try:
            with factory.begin(SCOPE, "read") as uow:
                package = uow.implementation.resolve_package(package_ref)
            materials = PackageDocumentMaterials(
                factory, blobs, scope=SCOPE, package_ref=package_ref)
            assert {doc.role for doc in package.payload.documents} == set(_EXPECTED)
            for document in package.payload.documents:
                assert materials.read(context("generated-document-read"),
                                      document.source_ref) == _EXPECTED[document.role]
        finally:
            reopened.close()
    finally:
        close_chain(env)


def test_package_document_reader_rejects_foreign_scope_refs_and_unregistered_package(tmp_path):
    env, chain, transport = _generation_case(tmp_path)
    try:
        result = _invoke_generation(env, chain, transport)
        payload = _command_payload(result)
        assert _command_status(result) == "completed", payload
        step = next(item for item in payload["steps"]
                    if item.get("business", {}).get("package_ref"))
        business = step["business"]
        package_ref = _package_ref(business)
        with env.factory.begin(SCOPE, "read") as uow:
            package = uow.implementation.resolve_package(package_ref)
        source_ref = next(doc.source_ref for doc in package.payload.documents
                          if doc.role == "spec")
        reader = PackageDocumentMaterials(env.factory, env.blobs,
                                          scope=SCOPE, package_ref=package_ref)

        changed_capture = VersionCapture(
            source_ref.capture.upstream_version,
            Digest("sha256", "0" * 64))
        changed_ref = replace(source_ref, capture=changed_capture)
        with pytest.raises(ApplicationError, match="SOURCE_VERSION_MISMATCH"):
            reader.read(context("tampered-generated-document"), changed_ref)

        unknown_ref = replace(source_ref, source_id="unknown-generated-document")
        with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
            reader.read(context("unknown-generated-document"), unknown_ref)

        foreign_scope = Scope(SCOPE.realm_id, "other-project")
        with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
            reader.read(replace(context("foreign-generated-document"),
                                scope=foreign_scope), source_ref)

        unregistered = replace(package_ref, package_id="unregistered-package")
        missing_reader = PackageDocumentMaterials(
            env.factory, env.blobs, scope=SCOPE, package_ref=unregistered)
        with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
            missing_reader.read(context("unregistered-generated-document"), source_ref)
    finally:
        close_chain(env)


def test_package_reader_only_normalizes_missing_package_errors(tmp_path, monkeypatch):
    env, chain, transport = _generation_case(tmp_path)
    try:
        result = _invoke_generation(env, chain, transport)
        payload = _command_payload(result)
        assert _command_status(result) == "completed", payload
        step = next(item for item in payload["steps"]
                    if item.get("business", {}).get("package_ref"))
        package_ref = _package_ref(step["business"])
        with env.factory.begin(SCOPE, "read") as uow:
            package = uow.implementation.resolve_package(package_ref)
        source_ref = package.payload.documents[0].source_ref
        reader = PackageDocumentMaterials(env.factory, env.blobs,
                                          scope=SCOPE, package_ref=package_ref)

        for repository_error, expected_error in (
                ("NOT_FOUND", "SOURCE_UNAVAILABLE"),
                ("SCOPE_MISMATCH", "SCOPE_MISMATCH"),
                ("STORAGE_UNAVAILABLE", "STORAGE_UNAVAILABLE")):
            def fail_resolve(_repository, _ref, code=repository_error):
                raise ApplicationError(code)

            monkeypatch.setattr(SQLiteImplementationRepository,
                                "resolve_package", fail_resolve)
            with pytest.raises(ApplicationError) as raised:
                reader.read(context("package-reader-error-" + repository_error), source_ref)
            assert raised.value.code == expected_error
    finally:
        close_chain(env)


def test_archive_write_failure_does_not_register_readable_package(tmp_path, monkeypatch):
    env, chain, transport = _generation_case(tmp_path)
    try:
        original_put = env.blobs.put_verified

        def fail_first_document_archive(raw_bytes, digest, media_type):
            if raw_bytes == _EXPECTED["spec"] and media_type == "text/markdown":
                raise OSError("injected archive write failure")
            return original_put(raw_bytes, digest, media_type)

        monkeypatch.setattr(env.blobs, "put_verified", fail_first_document_archive)
        with pytest.raises(ApplicationError) as raised:
            _invoke_generation(env, chain, transport)
        assert raised.value.code == "WORK_ACTION_GENERATION_DOCUMENT_ARCHIVE_UNAVAILABLE"
        assert transport.sends == 1
        _assert_package_not_registered(env, "generated-package-1")
    finally:
        close_chain(env)


def test_package_commit_failure_rolls_back_readable_package(tmp_path, monkeypatch):
    env, chain, transport = _generation_case(tmp_path)
    try:
        package_transaction = {}
        original_create = SQLiteImplementationRepository.create_package

        def capture_package_ref(repository, record):
            ref = original_create(repository, record)
            package_transaction["connection"] = repository.access._connection
            package_transaction["ref"] = ref
            package_transaction["source_ref"] = next(
                document.source_ref for document in record.payload.documents
                if document.role == "spec")
            return ref

        original_finish = SQLiteEngineeringUoW._finish

        def fail_package_commit(uow, error=None):
            if (error is None and package_transaction
                    and uow._access._connection is package_transaction["connection"]):
                # Run the normal rollback branch so this injected failure is a
                # definite non-commit, then surface a storage refusal.
                original_finish(uow, RuntimeError("injected package commit failure"))
                raise ApplicationError("STORAGE_UNAVAILABLE")
            return original_finish(uow, error)

        monkeypatch.setattr(SQLiteImplementationRepository,
                            "create_package", capture_package_ref)
        monkeypatch.setattr(SQLiteEngineeringUoW, "_finish", fail_package_commit)
        with pytest.raises(ApplicationError) as raised:
            _invoke_generation(env, chain, transport)
        assert raised.value.code == "STORAGE_UNAVAILABLE"
        package_ref = package_transaction["ref"]
        with env.factory.begin(SCOPE, "read") as uow:
            with pytest.raises(ApplicationError) as missing:
                uow.implementation.resolve_package(package_ref)
        assert missing.value.code == "NOT_FOUND"
        reader = PackageDocumentMaterials(env.factory, env.blobs,
                                          scope=SCOPE, package_ref=package_ref)
        with pytest.raises(ApplicationError, match="SOURCE_UNAVAILABLE"):
            reader.read(context("rolled-back-generated-document"),
                        package_transaction["source_ref"])
    finally:
        close_chain(env)
