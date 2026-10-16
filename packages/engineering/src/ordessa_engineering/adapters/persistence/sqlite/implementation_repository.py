"""Immutable RepositoryBaseline and ImplementationPackage records in the active UoW."""
from dataclasses import asdict
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.mechanisms.codec import canonical_value
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from ordessa_engineering.domain.changes.repository_baseline import RepositoryBaseline
from ordessa_engineering.domain.changes.repository_baseline_codec import (
    MAX_REPOSITORY_BASELINE_BYTES, decode_repository_baseline, encode_repository_baseline,
)
from ordessa_engineering.domain.packages.models import ImplementationPackage
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.packages.codec import decode_package, encode_package
from .blob_bytes import read_bytes, BlobBytesError
from .implementation_schema import IMPLEMENTATION_SCHEMA_VERSION
from .dispatch_schema import WORK_DISPATCH_SCHEMA_VERSION
from .submission_schema import SUBMISSION_SCHEMA_VERSION, SUBMISSION_DDL, IMPLEMENTATION_APPLY_DDL
from .dispatch_schema import DISPATCH_SCHEMA_VERSION, DISPATCH_DDL
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION

_BASELINE_BYTES = ("CASE WHEN typeof(canonical_bytes)='blob' AND "
                   "length(canonical_bytes) BETWEEN 1 AND 2097152 "
                   "THEN canonical_bytes ELSE NULL END")
_PACKAGE_BYTES = ("CASE WHEN typeof(canonical_bytes)='blob' AND "
                  "length(canonical_bytes) BETWEEN 1 AND 2097152 "
                  "THEN canonical_bytes ELSE NULL END")


def _decode(function, raw):
    try:
        return function(raw)
    except (ReferenceError, ValueError, TypeError, KeyError, AttributeError,
            RecursionError, OverflowError):
        raise ApplicationError('RECORD_CORRUPT') from None


def _body_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _ref_bytes(ref) -> bytes:
    return canonical_bytes(asdict(ref))


class SQLiteImplementationRepository:
    """Insert-only closed records using the caller's original _RepositoryAccess."""

    def __init__(self, access):
        self.access = access

    def _check(self, *, write=False):
        self.access.check_active()
        if type(self.access.scope) is not Scope:
            raise ApplicationError('SCOPE_MISMATCH')
        row = self.access.execute(
            'SELECT schema_version FROM library_meta WHERE singleton=1').fetchone()
        if row is None or row[0] not in (IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
            raise ApplicationError('IMPLEMENTATION_SCHEMA_REQUIRED')
        if write:
            self.access.require_write()
        return self.access.scope.realm_id, self.access.scope.project_id

    @staticmethod
    def _baseline_key(ref):
        return (ref.realm_id, ref.project_id, ref.repository_id, ref.vcs,
                ref.commit_id or '', ref.tree_digest.hex,
                '' if ref.dirty_overlay_digest is None else ref.dirty_overlay_digest.hex)

    def read_blob(self, ref):
        self._check()
        try:
            return read_bytes(self.access, self.access.authority_id, ref)
        except BlobBytesError as exc:
            raise ApplicationError('IMPLEMENTATION_BLOB_' + exc.code) from exc

    def _verify_files(self, record):
        total = 0
        for file in record.files:
            total += len(self.read_blob(file.blob_ref))
            if total > 16 * 1024 * 1024:
                raise ApplicationError('REPOSITORY_BYTES_BOUND_EXCEEDED')

    def create_repository_baseline(self, record: RepositoryBaseline) -> RepositorySnapshotRef:
        prefix = self._check(write=True)
        if type(record) is not RepositoryBaseline or record.ref.realm_id != prefix[0] or record.ref.project_id != prefix[1]:
            raise ApplicationError('INVALID_ARGUMENT')
        if record.ref.vcs != 'none' or record.ref.dirty_overlay_digest is not None:
            raise ApplicationError('REPOSITORY_CHECKOUT_SOURCE_UNAVAILABLE')
        raw = encode_repository_baseline(record)
        if len(raw) > MAX_REPOSITORY_BASELINE_BYTES or decode_repository_baseline(raw) != record:
            raise ApplicationError('INVALID_ARGUMENT')
        self._verify_files(record)
        ref = record.ref
        key = self._baseline_key(ref)
        existing = self.access.execute(
            'SELECT ref_bytes,body_digest,' + _BASELINE_BYTES +
            ' FROM eng_repository_baselines WHERE realm_id=? AND project_id=? AND repository_id=? AND vcs=? AND commit_key=? AND tree_digest=? AND overlay_key=?',
            key).fetchone()
        encoded_ref = _ref_bytes(ref)
        body_digest = _body_digest(raw)
        if existing is not None:
            if existing[0] != encoded_ref or existing[1] != body_digest or existing[2] != raw:
                raise ApplicationError('REPOSITORY_BASELINE_IDENTITY_CONFLICT')
            self._decode_baseline_row(key, existing)
            return ref
        self.access.execute(
            'INSERT INTO eng_repository_baselines VALUES (?,?,?,?,?,?,?,?,?,?)',
            key + (encoded_ref, body_digest, raw))
        return ref

    def _decode_baseline_row(self, key, row):
        raw = row[2]
        if type(row[0]) is not bytes or type(row[1]) is not str or type(raw) is not bytes or row[1] != _body_digest(raw):
            raise ApplicationError('RECORD_CORRUPT')
        record = _decode(decode_repository_baseline, raw)
        if (record.ref != self._ref_from_baseline_key(key)
                or _ref_bytes(record.ref) != row[0]
                or encode_repository_baseline(record) != raw):
            raise ApplicationError('RECORD_CORRUPT')
        self._verify_files(record)
        return record

    @staticmethod
    def _ref_from_baseline_key(key):
        realm_id, project_id, repository_id, vcs, commit_key, tree_digest, overlay_key = key
        return RepositorySnapshotRef(realm_id, project_id, repository_id, vcs,
            commit_key or None, Digest('sha256', tree_digest),
            None if not overlay_key else Digest('sha256', overlay_key))

    def resolve_repository_baseline(self, ref: RepositorySnapshotRef) -> RepositoryBaseline:
        prefix = self._check()
        if type(ref) is not RepositorySnapshotRef:
            raise ApplicationError('INVALID_ARGUMENT')
        if (ref.realm_id, ref.project_id) != prefix:
            raise ApplicationError('SCOPE_MISMATCH')
        key = self._baseline_key(ref)
        row = self.access.execute(
            'SELECT ref_bytes,body_digest,' + _BASELINE_BYTES +
            ' FROM eng_repository_baselines WHERE realm_id=? AND project_id=? AND repository_id=? AND vcs=? AND commit_key=? AND tree_digest=? AND overlay_key=?',
            key).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        return self._decode_baseline_row(key, row)

    def create_package(self, record: ImplementationPackage) -> ImplementationPackageRef:
        prefix = self._check(write=True)
        if type(record) is not ImplementationPackage or (record.scope.realm_id, record.scope.project_id) != prefix:
            raise ApplicationError('INVALID_ARGUMENT')
        raw = encode_package(record)
        if type(raw) is not bytes or not 1 <= len(raw) <= 2097152 or decode_package(raw) != record:
            raise ApplicationError('INVALID_ARGUMENT')
        ref = record.ref
        existing = self.access.execute(
            'SELECT digest,' + _PACKAGE_BYTES +
            ' FROM eng_packages WHERE realm_id=? AND project_id=? AND package_id=?',
            prefix + (record.package_id,)).fetchone()
        if existing is not None:
            if existing[0] != ref.digest.hex or existing[1] != raw:
                raise ApplicationError('PACKAGE_IDENTITY_CONFLICT')
            self._decode_package_row(prefix + (record.package_id,), existing, ref)
            return ref
        self.access.execute('INSERT INTO eng_packages VALUES (?,?,?,?,?)',
            prefix + (record.package_id, ref.digest.hex, raw))
        return ref

    def _decode_package_row(self, key, row, requested_ref=None):
        raw = row[1]
        if type(row[0]) is not str or type(raw) is not bytes:
            raise ApplicationError('RECORD_CORRUPT')
        record = _decode(decode_package, raw)
        if (record.ref.digest.hex != row[0]
                or (record.scope.realm_id, record.scope.project_id, record.package_id) != key
                or requested_ref is not None and record.ref != requested_ref
                or encode_package(record) != raw):
            raise ApplicationError('RECORD_CORRUPT')
        return record

    def resolve_package(self, ref: ImplementationPackageRef) -> ImplementationPackage:
        prefix = self._check()
        if type(ref) is not ImplementationPackageRef:
            raise ApplicationError('INVALID_ARGUMENT')
        if (ref.realm_id, ref.project_id) != prefix:
            raise ApplicationError('SCOPE_MISMATCH')
        key = prefix + (ref.package_id,)
        row = self.access.execute(
            'SELECT digest,' + _PACKAGE_BYTES +
            ' FROM eng_packages WHERE realm_id=? AND project_id=? AND package_id=?', key).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        return self._decode_package_row(key, row, ref)
