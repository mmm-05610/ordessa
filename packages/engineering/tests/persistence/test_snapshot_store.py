"""SQLite snapshot-store acceptance using only synthetic, empty catalogs.

These tests exercise the real EngineeringLibrary connection and snapshot
adapter. The test catalog below is an explicit synthetic fixture, not a
production capability authority.
"""
from __future__ import annotations

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader

import hashlib
import json
import shutil
import sqlite3
import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from ordessa_engineering.methods.definitions.models import StoredProgram, CompiledProgram, ProgramBindings, StoredSourceBundle, StoredSnapshot, CapturedResource, SourceBundle, ResourceBytes

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite import engineering_library as library_module
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models.identity import method_digest
from ordessa_engineering.methods.compilation.encoding import (
    program_to_canonical, program_plan_digest, compiled_program_from_canonical,
    stored_program_from_canonical, program_documents, program_skills,
)
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.methods.definitions.models import (
    BlobRef, CompilationCapabilities, MethodRef, MethodSource,
)
from ordessa_engineering.methods.definitions.models.compiled import StoredProgram
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method


class _SyntheticEmptyCatalog:
    """Fixture-only catalog with no capabilities; never a host adapter."""

    __test__ = False

    def read_current(self) -> CompilationCapabilities:
        return CompilationCapabilities((), "synthetic-empty-catalog", "host")


def _compile(root: Path, *, entry: str = "done", method_id: str = "test.snapshot"):
    root.mkdir(parents=True, exist_ok=True)
    workflow = {
        "schema_version": 1,
        "entry": entry,
        "steps": [{"id": entry, "kind": "stop", "outcome": "finished"}],
        "stop_outcomes": ["finished"],
        "wait_kinds": [],
    }
    workflow_bytes = json.dumps(workflow, separators=(",", ":")).encode("utf-8")
    (root / "workflow.yaml").write_bytes(workflow_bytes)
    manifest = {
        "schema_version": 1,
        "method_id": method_id,
        "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1",
        "entry": {"resource": "workflow.main"},
        "resources": [{
            "id": "workflow.main",
            "kind": "workflow",
            "path": "workflow.yaml",
            "media_type": "application/yaml",
            "sha256": hashlib.sha256(workflow_bytes).hexdigest(),
        }],
        "requires": [],
    }
    (root / "method.yaml").write_text(json.dumps(manifest), encoding="utf-8")

    loaded = load_method(MethodSource(root), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    compiled = compile_method(loaded.value, CompilationCapabilities(()), "test.compiler/1")
    assert compiled.ok and compiled.value is not None, compiled.error
    return compiled.value


def _new_library(path: Path, library_id: str = "test.library") -> EngineeringLibrary:
    return EngineeringLibrary.create(path.resolve(), library_id=library_id, schema_version=3)


def _freeze(store: SQLiteSnapshotStore, compiled):
    result = freeze_method(
        compiled, store, store, capability_catalog=_SyntheticEmptyCatalog(),
    )
    assert result.ok and result.value is not None, result.error
    return result.value


def _assert_method_failure(call, expected_code: str) -> None:
    with pytest.raises(MethodFailure) as caught:
        call()
    assert caught.value.error.code == expected_code


def test_sqlite_snapshot_survives_source_removal_reopen_and_dto_mutation(tmp_path: Path) -> None:
    library_path = tmp_path / "library.sqlite"
    source_root = tmp_path / "method-source"
    compiled = _compile(source_root)

    library = _new_library(library_path)
    store = SQLiteSnapshotStore(library)
    frozen = _freeze(store, compiled)
    assert _freeze(store, compiled).ref == frozen.ref  # same release is idempotent

    # The returned values are mutable DTOs; mutating them must not alter the
    # canonical bytes or BLOBs committed by the real adapter.
    program_to_canonical(frozen.snapshot.program)["workflow"]["entry"] = "caller-tampered"
    shutil.rmtree(source_root)
    library.close()

    reopened = EngineeringLibrary.open(library_path.resolve(), library_id="test.library")
    reopened_store = SQLiteSnapshotStore(reopened)
    restored = reopened_store.get(frozen.ref)
    assert program_to_canonical(restored.program)["workflow"]["entry"] == "done"
    assert reopened_store.read_blob(restored.manifest_ref)
    resource = restored.resources[0]
    assert reopened_store.read_blob(resource.blob_ref) == json.dumps(
        {"schema_version": 1, "entry": "done", "steps": [{"id": "done", "kind": "stop", "outcome": "finished"}],
         "stop_outcomes": ["finished"], "wait_kinds": []}, separators=(",", ":")
    ).encode("utf-8")

    program_to_canonical(restored.program)["workflow"]["entry"] = "second-caller-tamper"
    assert program_to_canonical(reopened_store.get(frozen.ref).program)["workflow"]["entry"] == "done"
    reopened.close()


def test_blob_reuse_bad_digest_foreign_reference_and_stored_blob_tamper(tmp_path: Path) -> None:
    library = _new_library(tmp_path / "primary.sqlite", "primary.library")
    store = SQLiteSnapshotStore(library)
    body = b"stable blob"
    digest = hashlib.sha256(body).hexdigest()
    first = store.put_blob(digest, "application/octet-stream", body)
    assert store.put_blob(digest, "application/octet-stream", body) == first
    assert store.read_blob(first) == body

    _assert_method_failure(
        lambda: store.put_blob("0" * 64, "application/octet-stream", body),
        "SNAPSHOT_BLOB_INVALID",
    )

    foreign_library = _new_library(tmp_path / "foreign.sqlite", "foreign.library")
    foreign_ref = SQLiteSnapshotStore(foreign_library).put_blob(
        digest, "application/octet-stream", body,
    )
    _assert_method_failure(lambda: store.read_blob(foreign_ref), "SNAPSHOT_BLOB_REF_INVALID")
    _assert_method_failure(
        lambda: store.read_blob(replace(first, byte_length=True)),
        "SNAPSHOT_BLOB_REF_INVALID",
    )
    _assert_method_failure(
        lambda: store.read_blob(replace(first, storage_object_id=first.storage_object_id + ":foreign")),
        "SNAPSHOT_BLOB_REF_INVALID",
    )
    _assert_method_failure(
        lambda: store.read_blob(replace(first, byte_length=first.byte_length + 1)),
        "SNAPSHOT_BLOB_CORRUPT",
    )
    _assert_method_failure(
        lambda: store.get(MethodRef("test.snapshot", "1.0.0", True, "0" * 64)),
        "SNAPSHOT_REF_INVALID",
    )

    # Keep the schema valid while corrupting the actual stored bytes.
    with library.transaction() as connection:
        connection.execute("UPDATE eng_method_blobs SET body=? WHERE digest=?", (b"tampered!!!", digest))
    _assert_method_failure(lambda: store.read_blob(first), "SNAPSHOT_BLOB_CORRUPT")
    foreign_library.close()
    library.close()


def test_oversized_blob_read_is_bounded_and_rejected(tmp_path: Path) -> None:
    library = _new_library(tmp_path / "large-blob.sqlite", "large-blob.library")
    store = SQLiteSnapshotStore(library)
    size = 17 * 1024 * 1024
    digest = "a" * 64
    # A plausible bounded reference must not cause a corrupt oversized stored
    # body to be materialized in full before the metadata mismatch is rejected.
    ref = BlobRef(digest, 1, "application/octet-stream", store._object_id(digest))
    with library.transaction() as connection:
        connection.execute(
            "INSERT INTO eng_method_blobs(digest, byte_length, body) VALUES (?, ?, zeroblob(?))",
            (digest, size, size),
        )

    statements = []
    library._connection.set_trace_callback(statements.append)
    try:
        _assert_method_failure(lambda: store.read_blob(ref), "SNAPSHOT_BLOB_CORRUPT")
    finally:
        library._connection.set_trace_callback(None)
    query = next(item.lower() for item in statements if "from eng_method_blobs" in item.lower())
    assert "case when typeof(body)='blob' and length(body)<=16777216" in query
    assert "then body else null end" in query
    assert "select byte_length, body" not in query
    library.close()


def test_oversized_canonical_snapshot_read_is_bounded_and_rejected(tmp_path: Path) -> None:
    library = _new_library(tmp_path / "large-snapshot.sqlite", "large-snapshot.library")
    store = SQLiteSnapshotStore(library)
    compiled = _compile(tmp_path / "method-source")
    frozen = _freeze(store, compiled)
    size = 17 * 1024 * 1024
    with library.transaction() as connection:
        connection.execute(
            "UPDATE eng_method_snapshots SET canonical_bytes=zeroblob(?) WHERE snapshot_digest=?",
            (size, frozen.ref.snapshot_digest),
        )

    statements = []
    library._connection.set_trace_callback(statements.append)
    try:
        _assert_method_failure(lambda: store.get(frozen.ref), "SNAPSHOT_CONTENT_CORRUPT")
    finally:
        library._connection.set_trace_callback(None)
    query = next(item.lower() for item in statements if "join eng_method_snapshots" in item.lower())
    assert "substr(s.canonical_bytes, 1, 16777217)" in query
    assert "select s.canonical_bytes" not in query
    library.close()


def test_duplicate_manifest_diagnostic_does_not_echo_sensitive_key(tmp_path: Path) -> None:
    library = _new_library(tmp_path / "duplicate-manifest.sqlite", "duplicate-manifest.library")
    store = SQLiteSnapshotStore(library)
    compiled = _compile(tmp_path / "method-source")
    valid = _freeze(store, compiled).snapshot
    sensitive_key = "synthetic-private-key-7f4a91"
    duplicate_manifest = (
        f"{sensitive_key}: first\n{sensitive_key}: second\n"
    ).encode("utf-8")
    manifest_ref = store.put_blob(
        hashlib.sha256(duplicate_manifest).hexdigest(), "application/yaml", duplicate_manifest,
    )
    digest = method_digest("method-snapshot", {
        "schema_version": valid.identity.schema_version,
        "method_id": valid.identity.method_id,
        "release_version": valid.identity.release_version,
        "manifest_sha256": manifest_ref.digest,
        "resource_digests": [
            {"id": item.resource_id, "sha256": item.digest}
            for item in sorted(valid.resources, key=lambda item: item.resource_id)
        ],
        "required_capabilities": program_to_canonical(valid.program)["capability_bindings"],
        "compiler_version": valid.compiler_version,
        "compiled_plan_digest": {"algorithm": "sha256", "hex": program_plan_digest(valid.program)},
    })
    malformed = replace(valid, source_bundle=replace(valid.source_bundle, manifest_ref=manifest_ref), snapshot_digest=digest)

    with pytest.raises(MethodFailure) as caught:
        store.publish(malformed)
    assert caught.value.error.code == "DUPLICATE_KEY"
    assert sensitive_key not in caught.value.error.message
    assert sensitive_key not in (caught.value.error.path or "")
    assert sensitive_key not in (caught.value.error.pointer or "")
    library.close()


class _BarrierStore:
    def __init__(self, store: SQLiteSnapshotStore, barrier: threading.Barrier) -> None:
        self._store = store
        self._barrier = barrier

    def __getattr__(self, name):
        return getattr(self._store, name)

    def publish(self, snapshot):
        self._barrier.wait(timeout=15)
        return self._store.publish(snapshot)


def test_same_release_race_on_independent_connections_has_one_atomic_winner(tmp_path: Path) -> None:
    library_path = tmp_path / "race.sqlite"
    setup = _new_library(library_path, "race.library")
    setup.close()
    compiled_values = (
        _compile(tmp_path / "method-a", entry="done"),
        _compile(tmp_path / "method-b", entry="finish"),
    )
    barrier = threading.Barrier(2)
    outcomes = [None, None]
    unexpected = []

    def publish(index: int) -> None:
        library = None
        try:
            # Each contender opens its own validated SQLite connection inside
            # its worker thread; both pass the preflight before publishing.
            library = EngineeringLibrary.open(library_path.resolve(), library_id="race.library")
            store = SQLiteSnapshotStore(library)
            outcomes[index] = freeze_method(
                compiled_values[index], _BarrierStore(store, barrier),
                _BarrierStore(store, barrier), capability_catalog=_SyntheticEmptyCatalog(),
            )
        except BaseException as exc:  # retain unexpected race failures as test failures
            unexpected.append(exc)
        finally:
            if library is not None:
                library.close()

    workers = [threading.Thread(target=publish, args=(index,)) for index in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
    assert all(not worker.is_alive() for worker in workers), "publication race did not finish"
    assert not unexpected, unexpected

    successes = [item for item in outcomes if item is not None and item.ok]
    failures = [item for item in outcomes if item is not None and not item.ok]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].error is not None
    assert failures[0].error.code == "RELEASE_IDENTITY_CONFLICT"

    check = EngineeringLibrary.open(library_path.resolve(), library_id="race.library")
    with check._read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM eng_method_releases").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM eng_method_snapshots").fetchone()[0] == 1
    check.close()


def test_recomputed_compiled_and_snapshot_digests_do_not_forge_source(tmp_path: Path) -> None:
    source_library = _new_library(tmp_path / "source.sqlite", "source.library")
    source_store = SQLiteSnapshotStore(source_library)
    source_compiled = _compile(tmp_path / "method-source")
    valid = _freeze(source_store, source_compiled).snapshot

    target_library = _new_library(tmp_path / "target.sqlite", "target.library")
    target_store = SQLiteSnapshotStore(target_library)
    manifest_ref = target_store.put_blob(
        valid.manifest_ref.digest, valid.manifest_ref.media_type,
        source_store.read_blob(valid.manifest_ref),
    )
    target_resources = tuple(replace(
        resource,
        blob_ref=target_store.put_blob(
            resource.digest, resource.media_type, source_store.read_blob(resource.blob_ref),
        ),
    ) for resource in valid.resources)

    forged_program = deepcopy(program_to_canonical(valid.program))
    forged_program["workflow"]["entry"] = "forged-entry"
    forged_plan_digest = method_digest("compiled-method-program", forged_program)
    forged_snapshot_digest = method_digest("method-snapshot", {
        "schema_version": valid.identity.schema_version,
        "method_id": valid.identity.method_id,
        "release_version": valid.identity.release_version,
        "manifest_sha256": manifest_ref.digest,
        "resource_digests": [
            {"id": item.resource_id, "sha256": item.digest}
            for item in sorted(target_resources, key=lambda item: item.resource_id)
        ],
        "required_capabilities": forged_program["capability_bindings"],
        "compiler_version": valid.compiler_version,
        "compiled_plan_digest": {"algorithm": "sha256", "hex": forged_plan_digest},
    })
    forged = replace(valid,
        source_bundle=replace(valid.source_bundle, manifest_ref=manifest_ref, resources=target_resources),
        program=compiled_program_from_canonical(forged_program, valid.program.bindings),
        snapshot_digest=forged_snapshot_digest,
    )
    _assert_method_failure(lambda: target_store.publish(forged), "SNAPSHOT_SOURCE_MISMATCH")
    with target_library._read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM eng_method_snapshots").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM eng_method_releases").fetchone()[0] == 0
    target_library.close()
    source_library.close()


def test_publish_failure_after_snapshot_insert_rolls_back_release_and_snapshot(tmp_path: Path) -> None:
    library = _new_library(tmp_path / "rollback.sqlite", "rollback.library")
    store = SQLiteSnapshotStore(library)
    compiled = _compile(tmp_path / "method-source")

    def deny_release_insert(action, arg1, arg2, database, trigger):
        if action == sqlite3.SQLITE_INSERT and arg1 == "eng_method_releases":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    # SQLite authorizer fault-injection is connection-local and does not alter
    # the strict schema. The adapter inserts the snapshot first, then failure
    # at the release insert must roll both rows back in its one transaction.
    library._connection.set_authorizer(deny_release_insert)
    failed = freeze_method(
        compiled, store, store, capability_catalog=_SyntheticEmptyCatalog(),
    )
    assert not failed.ok and failed.error is not None
    assert failed.error.code == "SNAPSHOT_STORAGE_UNKNOWN"
    assert library._closed is True

    # The adapter closes an uncertain connection. Reconciliation always uses
    # a newly validated handle; completed blob stages may remain by design.
    reopened = EngineeringLibrary.open(library.path, library_id="rollback.library")
    with reopened._read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM eng_method_snapshots").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM eng_method_releases").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM eng_method_blobs").fetchone()[0] >= 1
    reopened.close()
    library.close()


class _CommitLostReplyStore:
    def __init__(self, store: SQLiteSnapshotStore) -> None:
        self._store = store
        self.publish_calls = 0

    def __getattr__(self, name):
        return getattr(self._store, name)

    def publish(self, snapshot):
        self.publish_calls += 1
        self._store.library._connection.lose_commit_reply = True
        return self._store.publish(snapshot)


@pytest.mark.parametrize("failure_kind", ["sqlite", "runtime"])
def test_commit_lost_reply_is_unknown_then_reopen_reconciles_without_retry(
    tmp_path: Path, monkeypatch, failure_kind: str,
) -> None:
    library_path = tmp_path / "lost-reply.sqlite"
    initial = _new_library(library_path, "lost-reply.library")
    initial.close()

    base_connection = library_module._LibraryConnection

    class CommitLostReplyConnection(base_connection):
        def commit(self):
            result = super().commit()
            if getattr(self, "lose_commit_reply", False):
                self.lose_commit_reply = False
                if failure_kind == "runtime":
                    raise RuntimeError("synthetic COMMIT reply lost")
                raise sqlite3.OperationalError("synthetic COMMIT reply lost")
            return result

    monkeypatch.setattr(library_module, "_LibraryConnection", CommitLostReplyConnection)
    library = EngineeringLibrary.open(library_path.resolve(), library_id="lost-reply.library")
    store = SQLiteSnapshotStore(library)
    wrapped = _CommitLostReplyStore(store)
    compiled = _compile(tmp_path / "method-source")

    result = freeze_method(
        compiled, wrapped, wrapped, capability_catalog=_SyntheticEmptyCatalog(),
    )
    assert not result.ok and result.error is not None
    assert result.error.code == "SNAPSHOT_STORAGE_UNKNOWN"
    assert wrapped.publish_calls == 1  # no automatic resend after an uncertain commit
    assert library._closed is True

    reopened = EngineeringLibrary.open(library_path.resolve(), library_id="lost-reply.library")
    reconciler = SQLiteSnapshotStore(reopened)
    digest = reconciler.get_digest(
        compiled.identity.method_id, compiled.identity.release_version,
    )
    assert digest is not None
    ref = MethodRef(
        compiled.identity.method_id,
        compiled.identity.release_version,
        compiled.identity.schema_version,
        digest,
    )
    durable = reconciler.get(ref)
    assert durable.snapshot_digest == digest
    assert program_to_canonical(durable.program)["workflow"]["entry"] == "done"
    with reopened._read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM eng_method_releases").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM eng_method_snapshots").fetchone()[0] == 1
    reopened.close()
    library.close()


def test_valid_published_snapshot_remains_readable_after_schema4_upgrade_and_business_write(tmp_path):
    from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema3
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.domain.artifacts.models import Artifact
    from ordessa_engineering.domain.common.models.identity import (Scope)
    path = tmp_path / "upgraded-snapshot.sqlite"
    library = _new_library(path)
    store = SQLiteSnapshotStore(library)
    frozen = _freeze(store, _compile(tmp_path / "published-method"))
    before = store.get(frozen.ref)
    blob_bytes = {resource.blob_ref: store.read_blob(resource.blob_ref) for resource in before.resources}
    receipt = migrate_schema3(library, backup_path=tmp_path / "published-backup.sqlite")
    assert receipt.target_version == 4 and receipt.applied
    upgraded = SQLiteSnapshotStore(library)
    assert upgraded.get(frozen.ref) == before
    with SQLiteUoWFactory(library).begin(Scope("realm", "project")) as uow:
        uow.engineering.create(Artifact(uow.scope, "new-artifact", "plan", "2026-10-09T12:00:00.000000Z"))
        uow.commit()
    library.close()
    reopened = EngineeringLibrary.open(path, library_id="test.library")
    try:
        restored = SQLiteSnapshotStore(reopened)
        assert restored.get(frozen.ref) == before
        assert {ref: restored.read_blob(ref) for ref in blob_bytes} == blob_bytes
    finally:
        reopened.close()


def test_historical_program1_reads_through_explicit_store_materialization(tmp_path):
    from ordessa_engineering.adapters.persistence.sqlite.historical_method_program import reconstruct_historical_program_v1
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_codec import encode_snapshot, decode_snapshot
    from ordessa_engineering.methods.definitions.models import LoadedMethod, MethodSource, StoredSnapshot, MethodRef
    from pathlib import Path

    database = tmp_path / "historical-source.sqlite"
    library = _new_library(database)
    store = SQLiteSnapshotStore(library)
    compiled = _compile(tmp_path / "historical-source")
    published = _freeze(store, compiled).snapshot
    historical = stored_program_from_canonical(reconstruct_historical_program_v1(
        LoadedMethod(MethodSource(Path(".")), compiled.source_bundle, compiled.parsed_source), compiled.compiler_version))
    payload = {
        "schema_version": published.identity.schema_version,
        "method_id": published.identity.method_id, "release_version": published.identity.release_version,
        "manifest_sha256": published.manifest_ref.digest,
        "resource_digests": [{"id": r.resource_id, "sha256": r.digest} for r in sorted(published.resources, key=lambda r: r.resource_id)],
        "required_capabilities": program_to_canonical(historical)["capability_bindings"],
        "compiler_version": historical.compiler_version,
        "compiled_plan_digest": {"algorithm": "sha256", "hex": program_plan_digest(historical)},
    }
    digest = method_digest("method-snapshot", payload)
    raw = encode_snapshot(StoredSnapshot(published.source_bundle, historical, digest))
    decoded = decode_snapshot(raw)
    assert type(decoded) is StoredSnapshot
    assert decoded.program.schema_version == 1
    assert "schema_resources" not in program_to_canonical(decoded.program)
    library.close()
    # Explicit synthetic historical database fixture, not a runtime migration.
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO eng_method_snapshots VALUES (?, ?)", (digest, raw))
        connection.execute("UPDATE eng_method_releases SET snapshot_digest=?", (digest,))
    reopened = EngineeringLibrary.open(database.resolve(), library_id="test.library")
    restored = SQLiteSnapshotStore(reopened).get(MethodRef(published.identity.method_id, published.identity.release_version, 1, digest))
    assert restored.program.schema_version == 1
    assert encode_snapshot(restored) == raw
    with pytest.raises(ValueError, match="historical document bindings unavailable"):
        _ = program_documents(restored.program)
    with pytest.raises(ValueError, match="historical skill roles unavailable"):
        _ = program_skills(restored.program)
    _assert_method_failure(lambda: SQLiteSnapshotStore(reopened).publish(restored), "HISTORICAL_SNAPSHOT_READ_ONLY")
    reopened.close()


@pytest.mark.parametrize("broken_bytes, expected_code", [
    (b"schema_version: 1\nschema_version: 1\n", "DUPLICATE_KEY"),
    (b"entry: *forbidden_alias\n", "YAML_ALIAS_OR_ANCHOR"),
    (b"steps: [\n", "METHOD_PARSE_ERROR"),
])
def test_stored_resource_parse_failure_stops_before_next_blob_read(tmp_path, monkeypatch, broken_bytes, expected_code):
    from ordessa_engineering.adapters.persistence.sqlite import snapshot_store as module
    from ordessa_engineering.methods.definitions.models import ResourceSnapshot

    library = _new_library(tmp_path / "read-order.sqlite")
    try:
        store = SQLiteSnapshotStore(library)
        compiled = _compile(tmp_path / "method-source")
        snapshot = _freeze(store, compiled).snapshot
        first = snapshot.resources[0]
        bad_ref = store.put_blob(hashlib.sha256(broken_bytes).hexdigest(), first.media_type, broken_bytes)
        later_bytes = b"later captured skill"
        later_ref = store.put_blob(hashlib.sha256(later_bytes).hexdigest(), "text/plain", later_bytes)
        later = ResourceSnapshot("z.later", "later.txt", later_ref)
        manifest = json.loads(compiled.source_bundle.manifest_bytes)
        manifest["resources"][0]["sha256"] = bad_ref.digest
        manifest["resources"].append({"id": later.resource_id, "kind": "skill",
            "path": later.logical_path, "media_type": later.media_type, "sha256": later.digest})
        raw_manifest = json.dumps(manifest, separators=(",", ":")).encode()
        manifest_ref = store.put_blob(hashlib.sha256(raw_manifest).hexdigest(), "application/yaml", raw_manifest)
        injected = replace(snapshot, source_bundle=replace(snapshot.source_bundle,
            manifest_ref=manifest_ref, resources=(replace(first, blob_ref=bad_ref), later)))
        observed_reads = []
        original_read = module.read_snapshot_blob

        def tracked_read(connection, authority_id, ref):
            observed_reads.append(ref.storage_object_id)
            if ref.storage_object_id == later_ref.storage_object_id:
                raise AssertionError("a later resource was read after the first resource syntax failed")
            return original_read(connection, authority_id, ref)

        monkeypatch.setattr(module, "read_snapshot_blob", tracked_read)
        # The original caller transaction and real stored BLOBs remain the authority.
        with library.transaction() as connection:
            with pytest.raises(MethodFailure) as caught:
                module.verify_snapshot_source(connection, library.library_id, injected)
        assert caught.value.error.code == expected_code
        assert observed_reads == [manifest_ref.storage_object_id, bad_ref.storage_object_id]
        assert later_ref.storage_object_id not in observed_reads
    finally:
        library.close()
