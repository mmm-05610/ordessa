"""Blob bytes remain on the original EngineeringLibrary authority."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite.blob_bytes import (
    MAX_BLOB_BYTES, BlobBytesError, read_bytes,
)
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.models import Artifact
from ordessa_engineering.domain.common.models.refs import (BlobRef as DomainBlobRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.methods.definitions.models import BlobRef as MethodBlobRef


CREATED_AT = "2026-10-09T12:00:00.000000Z"
SCOPE = Scope("realm-blob", "project-blob")


def _library(path: Path, library_id: str, schema_version: int = 5) -> EngineeringLibrary:
    return EngineeringLibrary.create(path.resolve(), library_id=library_id,
                                     schema_version=schema_version)


def _digest(raw: bytes) -> Digest:
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


def _to_method_ref(ref: DomainBlobRef) -> MethodBlobRef:
    return MethodBlobRef(ref.digest.hex, ref.byte_length, ref.media_type, ref.storage_object_id)


def _to_domain_ref(ref: MethodBlobRef) -> DomainBlobRef:
    return DomainBlobRef(Digest("sha256", ref.digest), ref.byte_length,
                         ref.media_type, ref.storage_object_id)


def _assert_application_failure(call, code: str) -> None:
    with pytest.raises(ApplicationError) as caught:
        call()
    assert caught.value.code == code


def _assert_method_failure(call, code: str) -> None:
    with pytest.raises(MethodFailure) as caught:
        call()
    assert caught.value.error.code == code


@pytest.mark.parametrize("schema_version", (3, 5))
def test_blob_store_and_snapshot_store_share_the_library_blob_table(
    tmp_path: Path, schema_version: int,
) -> None:
    library = _library(tmp_path / f"shared-v{schema_version}.sqlite",
                       f"blob.shared.v{schema_version}", schema_version)
    blobs = SQLiteBlobStore(library)
    snapshots = SQLiteSnapshotStore(library)
    assert blobs.library is library and snapshots.library is library
    assert blobs.authority_id == library.library_id
    raw = b"one authority, one content-addressed row"
    digest = _digest(raw)

    ref = blobs.put_verified(raw, digest, "application/octet-stream")
    assert blobs.put_verified(raw, digest, "application/octet-stream") == ref
    assert snapshots.read_blob(_to_method_ref(ref)) == raw
    method_ref = snapshots.put_blob(digest.hex, "application/octet-stream", raw)
    assert _to_domain_ref(method_ref) == ref
    assert blobs.read_verified(_to_domain_ref(method_ref)) == raw
    with library._read_connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM eng_method_blobs WHERE digest=?", (digest.hex,),
        ).fetchone()[0] == 1
    library.close()


def test_bad_digest_and_foreign_library_locator_are_rejected(tmp_path: Path) -> None:
    primary = _library(tmp_path / "primary.sqlite", "blob.primary", 5)
    primary_blobs = SQLiteBlobStore(primary)
    primary_snapshots = SQLiteSnapshotStore(primary)
    raw = b"verified bytes"
    digest = _digest(raw)
    primary_ref = primary_blobs.put_verified(raw, digest, "text/plain")
    primary_method_ref = primary_snapshots.put_blob(digest.hex, "text/plain", raw)

    _assert_application_failure(
        lambda: primary_blobs.put_verified(raw, Digest("sha256", "0" * 64), "text/plain"),
        "BLOB_INVALID",
    )
    _assert_method_failure(
        lambda: primary_snapshots.put_blob("0" * 64, "text/plain", raw),
        "SNAPSHOT_BLOB_INVALID",
    )

    foreign = _library(tmp_path / "foreign.sqlite", "blob.foreign", 5)
    foreign_blobs = SQLiteBlobStore(foreign)
    foreign_snapshots = SQLiteSnapshotStore(foreign)
    _assert_application_failure(lambda: foreign_blobs.read_verified(primary_ref), "BLOB_REF_INVALID")
    _assert_method_failure(lambda: foreign_snapshots.read_blob(primary_method_ref), "SNAPSHOT_BLOB_REF_INVALID")
    assert primary_snapshots.read_blob(primary_method_ref) == raw
    primary.close()
    foreign.close()


def test_missing_and_corrupted_rows_fail_closed_through_both_readers(tmp_path: Path) -> None:
    library = _library(tmp_path / "corrupt.sqlite", "blob.corrupt", 5)
    blobs = SQLiteBlobStore(library)
    snapshots = SQLiteSnapshotStore(library)
    corrupted_body = b"persistent body"
    corrupted_ref = blobs.put_verified(corrupted_body, _digest(corrupted_body), "text/plain")
    missing_body = b"row will be removed"
    missing_ref = blobs.put_verified(missing_body, _digest(missing_body), "text/plain")

    with library.transaction() as connection:
        connection.execute("UPDATE eng_method_blobs SET body=? WHERE digest=?",
                           (b"altered payload", corrupted_ref.digest.hex))
        connection.execute("DELETE FROM eng_method_blobs WHERE digest=?", (missing_ref.digest.hex,))

    _assert_application_failure(lambda: blobs.read_verified(corrupted_ref), "BLOB_CORRUPT")
    _assert_method_failure(lambda: snapshots.read_blob(_to_method_ref(corrupted_ref)), "SNAPSHOT_BLOB_CORRUPT")
    _assert_application_failure(
        lambda: blobs.put_verified(corrupted_body, _digest(corrupted_body), "text/plain"),
        "BLOB_CORRUPT",
    )
    _assert_method_failure(
        lambda: snapshots.put_blob(corrupted_ref.digest.hex, "text/plain", corrupted_body),
        "SNAPSHOT_BLOB_CORRUPT",
    )
    _assert_application_failure(lambda: blobs.read_verified(missing_ref), "BLOB_NOT_FOUND")
    _assert_method_failure(lambda: snapshots.read_blob(_to_method_ref(missing_ref)), "SNAPSHOT_BLOB_NOT_FOUND")
    library.close()


def test_blob_bytes_are_reopenable_and_original_library_serializes_cross_thread_reads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reopen-thread.sqlite"
    library = _library(path, "blob.reopen", 5)
    store = SQLiteBlobStore(library)
    raw = b"reopen exact body"
    ref = store.put_verified(raw, _digest(raw), "application/octet-stream")

    outcomes: list[object] = []
    worker = threading.Thread(target=lambda: outcomes.append(store.read_verified(ref)))
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive(), "EngineeringLibrary RLock should serialize this read"
    assert outcomes == [raw]
    library.close()

    reopened = EngineeringLibrary.open(path.resolve(), library_id="blob.reopen")
    reopened_store = SQLiteBlobStore(reopened)
    assert reopened_store.read_verified(ref) == raw
    assert SQLiteSnapshotStore(reopened).read_blob(_to_method_ref(ref)) == raw
    reopened.close()


def test_blob_port_needs_existing_library_and_rejects_unsupported_schema(tmp_path: Path) -> None:
    _assert_application_failure(lambda: SQLiteBlobStore(object()), "BLOB_AUTHORITY_REQUIRED")
    _assert_method_failure(lambda: SQLiteSnapshotStore(object()), "SNAPSHOT_AUTHORITY_REQUIRED")

    legacy = _library(tmp_path / "schema2.sqlite", "blob.legacy", 2)
    _assert_application_failure(lambda: SQLiteBlobStore(legacy), "BLOB_SCHEMA_REQUIRED")
    legacy.close()


def test_nested_blob_io_refuses_business_uow_without_poisoning_it(tmp_path: Path) -> None:
    library = _library(tmp_path / "nested.sqlite", "blob.nested", 5)
    store = SQLiteBlobStore(library)
    raw = b"outside the business transaction"
    ref = store.put_verified(raw, _digest(raw), "text/plain")
    factory = SQLiteUoWFactory(library)

    with factory.begin(SCOPE, "write") as uow:
        _assert_application_failure(lambda: store.read_verified(ref), "BLOB_IO_IN_BUSINESS_TX")
        _assert_application_failure(
            lambda: store.put_verified(raw + b"-next", _digest(raw + b"-next"), "text/plain"),
            "BLOB_IO_IN_BUSINESS_TX",
        )
        assert library._connection.in_transaction
        uow.engineering.create(Artifact(SCOPE, "after-nested-refusal", "specification", CREATED_AT))
        uow.commit()

    with factory.begin(SCOPE, "read") as uow:
        assert uow.engineering.get_artifact("after-nested-refusal").artifact_id == "after-nested-refusal"
        uow.commit()
    library.close()


def test_sql_bounds_blob_extraction_before_python_receives_body(tmp_path: Path) -> None:
    library = _library(tmp_path / "bounded-read.sqlite", "blob.bounded", 5)
    store = SQLiteBlobStore(library)
    raw = b"tiny body; no oversized fixture needed"
    ref = store.put_verified(raw, _digest(raw), "application/octet-stream")
    observed_sql: list[str] = []
    observed_parameters: list[tuple] = []
    observed_body: list[object] = []

    class CursorProbe:
        def __init__(self, cursor):
            self.cursor = cursor

        def fetchone(self):
            row = self.cursor.fetchone()
            if row is not None:
                observed_body.append(row[3])
            return row

    class ConnectionProbe:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, parameters=()):
            observed_sql.append(sql)
            observed_parameters.append(tuple(parameters))
            # Exercise the SQL CASE's rejecting branch with a tiny real row;
            # production code supplies MAX_BLOB_BYTES instead of zero.
            bounded_parameters = (0, parameters[1])
            return CursorProbe(self.connection.execute(sql, bounded_parameters))

    with library._read_connection() as connection:
        with pytest.raises(BlobBytesError) as rejected:
            read_bytes(ConnectionProbe(connection), library.library_id, ref)
    assert rejected.value.code == "CORRUPT"
    assert observed_sql and "CASE WHEN typeof(body)='blob' AND length(body)<=?" in observed_sql[0]
    assert observed_parameters == [(MAX_BLOB_BYTES, ref.digest.hex)]
    assert observed_body == [None]
    library.close()
