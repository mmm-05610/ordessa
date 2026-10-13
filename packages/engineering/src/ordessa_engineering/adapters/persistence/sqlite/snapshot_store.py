"""Immutable method publication on the sole EngineeringLibrary connection.

Source integrity is checked here; capability admission belongs to the injected
application catalog at freeze_method. This adapter does not invent a catalog.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ordessa_engineering.methods.compilation.compiler import bind_program
from ordessa_engineering.methods.compilation.encoding import program_to_canonical
from ordessa_engineering.application.orchestration.method_snapshot import verify_stored_snapshot_source
from ordessa_engineering.methods.definitions.errors import MethodError, MethodFailure
from ordessa_engineering.methods.definitions.models import (
    BlobRef, LoadedMethod, MethodRef, MethodSnapshot, MethodSource,
    ResourceBytes, CapturedResource, SourceBundle, StoredSnapshot, StoredSourceBundle,
)
from ordessa_engineering.methods.loading.captured import captured_manifest, parse_captured_resource
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from .engineering_library import EngineeringLibrary
from .schema import SNAPSHOT_SCHEMA_VERSION
from .historical_method_program import reconstruct_historical_program_v1
from .application_schema import APPLICATION_SCHEMA_VERSION
from .review_schema import REVIEW_SCHEMA_VERSION
from .material_schema import MATERIAL_SCHEMA_VERSION
from .proposal_schema import PROPOSAL_SCHEMA_VERSION
from .authorization_schema import AUTHORIZATION_SCHEMA_VERSION
from .apply_schema import APPLY_SCHEMA_VERSION, APPLY_DDL
from .method_schema import METHOD_SCHEMA_VERSION, METHOD_DDL
from .implementation_schema import IMPLEMENTATION_SCHEMA_VERSION, IMPLEMENTATION_DDL, IMPLEMENTATION_TABLES
from .submission_schema import SUBMISSION_SCHEMA_VERSION, SUBMISSION_DDL, IMPLEMENTATION_APPLY_DDL
from .dispatch_schema import DISPATCH_SCHEMA_VERSION, DISPATCH_DDL
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .snapshot_codec import decode_snapshot, encode_snapshot
from .blob_bytes import BlobBytesError, object_id, reference_for, read_bytes, put_bytes
from ordessa_engineering.domain.common.models.refs import (BlobRef as DomainBlobRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 16 * 1024 * 1024
_MAX_RESOURCES = 128


def _fail(code: str):
    raise MethodFailure(MethodError(code, "method snapshot storage refused the operation"))


def read_snapshot_blob(connection, authority_id, ref: BlobRef) -> bytes:
    if type(ref) is not BlobRef:
        _fail("SNAPSHOT_BLOB_REF_INVALID")
    try:
        domain_ref = DomainBlobRef(Digest("sha256", ref.digest), ref.byte_length,
                                   ref.media_type, ref.storage_object_id)
    except (ReferenceError, TypeError, ValueError):
        _fail("SNAPSHOT_BLOB_REF_INVALID")
    try:
        return read_bytes(connection, authority_id, domain_ref)
    except BlobBytesError as exc:
        _fail("SNAPSHOT_BLOB_" + exc.code)


def _verify_snapshot_source_bytes(connection, authority_id, snapshot: MethodSnapshot):
    if len(snapshot.resources) > _MAX_RESOURCES:
        _fail("SNAPSHOT_RESOURCE_LIMIT")
    if snapshot.manifest_ref.byte_length > 256 * 1024 or snapshot.manifest_ref.media_type != "application/yaml":
        _fail("SNAPSHOT_MANIFEST_INVALID")
    manifest_bytes = read_snapshot_blob(connection, authority_id, snapshot.manifest_ref)
    manifest = captured_manifest(ResourceBytes("method.yaml", "application/yaml", manifest_bytes))
    declarations = {item["id"]: item for item in manifest["resources"]}
    if len(declarations) != len(snapshot.resources):
        _fail("SNAPSHOT_SOURCE_MISMATCH")
    captured = []
    total = len(manifest_bytes)
    for resource in sorted(snapshot.resources, key=lambda item: item.resource_id):
        declaration = declarations.get(resource.resource_id)
        if (declaration is None or declaration["path"] != resource.logical_path
                or declaration["sha256"] != resource.digest
                or declaration["media_type"] != resource.media_type):
            _fail("SNAPSHOT_SOURCE_MISMATCH")
        total += resource.byte_length
        if resource.byte_length > 2 * 1024 * 1024 or total > _MAX_BYTES:
            _fail("SNAPSHOT_RESOURCE_LIMIT")
        body = read_snapshot_blob(connection, authority_id, resource.blob_ref)
        capture = ResourceBytes(resource.logical_path, resource.media_type, body)
        parse_captured_resource(capture)
        captured.append(CapturedResource(resource.resource_id, capture))
    bundle = SourceBundle(ResourceBytes("method.yaml", "application/yaml", manifest_bytes), tuple(captured))
    return verify_stored_snapshot_source(
        snapshot, bundle,
        historical_reconstructor=reconstruct_historical_program_v1,
    )


def verify_snapshot_source(connection, authority_id, snapshot):
    try:
        return _verify_snapshot_source_bytes(connection, authority_id, snapshot)
    except MethodFailure as exc:
        raise MethodFailure(MethodError(exc.error.code,
            "stored source does not define a valid method snapshot")) from None
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise MethodFailure(MethodError("SNAPSHOT_SOURCE_INVALID",
            "stored source does not define a valid method snapshot")) from exc


def load_snapshot(connection, authority_id, ref, *, budget=None):
    """Resolve the published release and source bytes inside the caller's TX."""
    row = connection.execute(
        'SELECT r.schema_version, r.snapshot_digest, length(s.canonical_bytes), '
        'typeof(s.canonical_bytes), substr(s.canonical_bytes, 1, ?) FROM eng_method_releases r '
        'JOIN eng_method_snapshots s ON s.snapshot_digest=r.snapshot_digest '
        'WHERE r.method_id=? AND r.release_version=?',
        (_MAX_BYTES + 1, ref.method_id, ref.release_version)).fetchone()
    if row is None or row[:2] != (ref.schema_version, ref.snapshot_digest):
        _fail("SNAPSHOT_NOT_FOUND")
    if row[3] != "blob" or not isinstance(row[4], bytes) or row[2] != len(row[4]) or len(row[4]) > _MAX_BYTES:
        _fail("SNAPSHOT_CONTENT_CORRUPT")
    snapshot = decode_snapshot(row[4])
    if (snapshot.identity.method_id, snapshot.identity.release_version,
            snapshot.identity.schema_version, snapshot.snapshot_digest) != (
            ref.method_id, ref.release_version, ref.schema_version, ref.snapshot_digest):
        _fail("SNAPSHOT_CONTENT_CORRUPT")
    if budget is not None:
        budget(snapshot)
    loaded = verify_snapshot_source(connection, authority_id, snapshot)
    return MethodSnapshot(snapshot.source_bundle, bind_program(snapshot.program, loaded), snapshot.snapshot_digest), loaded

class SQLiteSnapshotStore:
    def __init__(self, library: EngineeringLibrary):
        if not isinstance(library, EngineeringLibrary):
            _fail("SNAPSHOT_AUTHORITY_REQUIRED")
        with library._read_connection():
            if library._schema_version not in (SNAPSHOT_SCHEMA_VERSION, APPLICATION_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION):
                _fail("SNAPSHOT_SCHEMA_REQUIRED")
        self.library = library

    @contextmanager
    def _write(self):
        try:
            with self.library.transaction() as connection:
                yield connection
        except MethodFailure:
            raise
        except Exception as exc:
            # A lost commit response must never trigger a blind publication
            # retry. Close, then reopen and query the immutable release key.
            self.library.close()
            raise MethodFailure(MethodError("SNAPSHOT_STORAGE_UNKNOWN",
                "storage result requires explicit reopen and reconciliation")) from exc

    @contextmanager
    def _read(self):
        try:
            with self.library._read_connection() as connection:
                if connection.in_transaction:
                    raise EngineeringError("library_transaction_nested")
                try:
                    connection.execute("BEGIN")
                    yield connection
                    self.library._check_bound_state(allow_journal=True)
                except BaseException as exc:
                    self.library._rollback_failure(exc)
                    raise
                else:
                    try:
                        connection.rollback()
                    except BaseException as exc:
                        self.library._rollback_failure(exc)
                        self.library.close()
                        raise
        except MethodFailure:
            raise
        except Exception as exc:
            self.library.close()
            raise MethodFailure(MethodError("SNAPSHOT_STORAGE_UNAVAILABLE",
                "storage could not provide a verified read")) from exc

    def _object_id(self, digest: str) -> str:
        return object_id(self.library.library_id, digest)

    def put_blob(self, digest: str, media_type: str, raw_bytes: bytes) -> BlobRef:
        try:
            domain_ref = reference_for(self.library.library_id, raw_bytes, Digest("sha256", digest), media_type)
        except (BlobBytesError, ReferenceError, TypeError, ValueError):
            _fail("SNAPSHOT_BLOB_INVALID")
        ref = BlobRef(digest, len(raw_bytes), media_type, domain_ref.storage_object_id)
        with self._write() as connection:
            try:
                put_bytes(connection, self.library.library_id, domain_ref, raw_bytes)
            except BlobBytesError as exc:
                _fail("SNAPSHOT_BLOB_" + exc.code)
        return ref

    def _read_blob(self, connection, ref: BlobRef) -> bytes:
        return read_snapshot_blob(connection, self.library.library_id, ref)

    def read_blob(self, ref: BlobRef) -> bytes:
        with self._read() as connection:
            return self._read_blob(connection, ref)

    def _verify_source(self, connection, snapshot: MethodSnapshot):
        return verify_snapshot_source(connection, self.library.library_id, snapshot)

    def publish(self, snapshot: MethodSnapshot) -> MethodRef:
        if program_to_canonical(snapshot.program).get("schema_version") != 2:
            _fail("HISTORICAL_SNAPSHOT_READ_ONLY")
        encoded = encode_snapshot(snapshot)
        if len(encoded) > _MAX_BYTES:
            _fail("SNAPSHOT_RESOURCE_LIMIT")
        detached = decode_snapshot(encoded)
        identity = detached.identity
        with self._write() as connection:
            self._verify_source(connection, detached)
            previous = connection.execute(
                'SELECT schema_version, snapshot_digest FROM eng_method_releases WHERE method_id=? AND release_version=?',
                (identity.method_id, identity.release_version)).fetchone()
            if previous is not None and previous != (identity.schema_version, detached.snapshot_digest):
                _fail("RELEASE_IDENTITY_CONFLICT")
            row = connection.execute(
                'SELECT length(canonical_bytes), typeof(canonical_bytes), substr(canonical_bytes, 1, ?) '
                'FROM eng_method_snapshots WHERE snapshot_digest=?',
                (_MAX_BYTES + 1, detached.snapshot_digest)).fetchone()
            if row is None:
                connection.execute('INSERT INTO eng_method_snapshots VALUES (?, ?)',
                                   (detached.snapshot_digest, encoded))
            elif row != (len(encoded), "blob", encoded):
                _fail("SNAPSHOT_CONTENT_CONFLICT")
            if previous is None:
                connection.execute('INSERT INTO eng_method_releases VALUES (?, ?, ?, ?)',
                    (identity.method_id, identity.release_version, identity.schema_version, detached.snapshot_digest))
        return MethodRef(identity.method_id, identity.release_version,
                         identity.schema_version, detached.snapshot_digest)

    def get_digest(self, method_id: str, release_version: str) -> str | None:
        if not isinstance(method_id, str) or not method_id or not isinstance(release_version, str) or not release_version:
            _fail("SNAPSHOT_REF_INVALID")
        with self._read() as connection:
            row = connection.execute(
                'SELECT snapshot_digest FROM eng_method_releases WHERE method_id=? AND release_version=?',
                (method_id, release_version)).fetchone()
            return row[0] if row else None

    def get(self, ref: MethodRef) -> MethodSnapshot:
        if (not isinstance(ref, MethodRef) or type(ref.schema_version) is not int
                or ref.schema_version <= 0 or not isinstance(ref.snapshot_digest, str)
                or not _DIGEST.fullmatch(ref.snapshot_digest)
                or not isinstance(ref.method_id, str) or not ref.method_id
                or not isinstance(ref.release_version, str) or not ref.release_version):
            _fail("SNAPSHOT_REF_INVALID")
        with self._read() as connection:
            snapshot, _ = load_snapshot(connection, self.library.library_id, ref)
            return snapshot
