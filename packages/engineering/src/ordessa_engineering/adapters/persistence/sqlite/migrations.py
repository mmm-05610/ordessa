"""Explicit schema2->3, schema3->4 and schema4->5 migrations on the original authority, with no overwrite.

Only a trusted directory/process deployment is supported by the underlying
Library. This does not attest SQLite's native FD or recover WAL/hot journals.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3

from ordessa_infrastructure.database import SQLiteOptions, create_connection
import stat
import tempfile
import time

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from .engineering_library import EngineeringLibrary, SCHEMA_VERSION
from .schema import SNAPSHOT_DDL, SNAPSHOT_SCHEMA_VERSION
from .application_schema import APPLICATION_DDL, APPLICATION_SCHEMA_VERSION
from .review_schema import REVIEW_DDL, REVIEW_SCHEMA_VERSION, REVIEW_TABLES
from .material_schema import MATERIAL_DDL, MATERIAL_SCHEMA_VERSION
from .proposal_schema import PROPOSAL_DDL, PROPOSAL_SCHEMA_VERSION, PROPOSAL_TABLES
from .authorization_schema import AUTHORIZATION_DDL, AUTHORIZATION_SCHEMA_VERSION, AUTHORIZATION_TABLES
from .apply_schema import APPLY_DDL, APPLY_SCHEMA_VERSION, APPLY_TABLES
from .method_schema import METHOD_SCHEMA_VERSION, METHOD_DDL, METHOD_TABLES
from .implementation_schema import IMPLEMENTATION_SCHEMA_VERSION, IMPLEMENTATION_DDL, IMPLEMENTATION_TABLES

from .submission_schema import SUBMISSION_SCHEMA_VERSION, SUBMISSION_TABLES, MIGRATION11_DDL
from .dispatch_schema import DISPATCH_SCHEMA_VERSION, DISPATCH_DDL
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION, ACCEPTANCE_TABLES, ACCEPTANCE_MIGRATION_DDL

_OLD_TABLES = ('library_meta', 'materials', 'heads', 'runs', 'step_log', 'idempotency')
_SNAPSHOT_TABLES = ('eng_method_blobs', 'eng_method_snapshots', 'eng_method_releases', 'eng_schema_migrations')
_APPLICATION_TABLES = ('eng_artifacts', 'eng_artifact_revisions', 'eng_revision_parents', 'eng_commands')


@dataclass(frozen=True)
class MigrationReceipt:
    applied: bool
    source_digest: str
    backup_sha256: str
    backup_path: str
    target_version: int = SNAPSHOT_SCHEMA_VERSION


def _rows(connection, source_version):
    tables = (_OLD_TABLES + (_SNAPSHOT_TABLES if source_version >= 3 else ())
              + (_APPLICATION_TABLES if source_version >= 4 else ())
              + (REVIEW_TABLES if source_version >= 5 else ())
              + (PROPOSAL_TABLES if source_version >= 7 else ())
              + (AUTHORIZATION_TABLES if source_version >= 8 else ())
              + (APPLY_TABLES if source_version >= 9 else ())
              + (METHOD_TABLES if source_version >= 10 else ())
              + (IMPLEMENTATION_TABLES if source_version >= 11 else ())
              + (SUBMISSION_TABLES if source_version >= 12 else ())
              + (ACCEPTANCE_TABLES if source_version >= ACCEPTANCE_SCHEMA_VERSION else ()))
    def cell(value):
        if isinstance(value, bytes):
            return {"byte_length": len(value), "sha256": hashlib.sha256(value).hexdigest()}
        return value
    return {name: sorted([[cell(value) for value in row] for row in
                          connection.execute(('SELECT run_id,ordinal,step_id,operation,attempt,status,receipt_ref_json FROM step_log' if name == 'step_log' and source_version < DISPATCH_SCHEMA_VERSION else 'SELECT * FROM ' + name))], key=canonical_bytes)
            for name in tables}


def _source_digest(connection, source_version=SCHEMA_VERSION):
    return hashlib.sha256(canonical_bytes(_rows(connection, source_version))).hexdigest()


def _check_backup(path, library_id, source_version=SCHEMA_VERSION):
    identity = EngineeringLibrary._file_identity(path)
    EngineeringLibrary._preflight_storage(path, identity, expected_version=source_version)
    connection = create_connection(SQLiteOptions(location=path.as_uri() + '?mode=ro', uri=True))
    try:
        connection.execute('BEGIN')
        EngineeringLibrary._validate_schema(connection, library_id, source_version)
        logical_digest = _source_digest(connection, source_version)
        # Keep SQLite's read lock while hashing the same regular file through
        # a bounded nofollow descriptor. A legitimate writer cannot commit
        # between the logical receipt and the physical backup receipt.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or (metadata.st_dev, metadata.st_ino) != identity[:2]):
                raise EngineeringError('migration_backup_replaced')
            hasher = hashlib.sha256()
            while chunk := os.read(fd, 65536):
                hasher.update(chunk)
            raw_digest = hasher.hexdigest()
        finally:
            os.close(fd)
        EngineeringLibrary._preflight_storage(path, identity, expected_version=source_version)
        if EngineeringLibrary._file_identity(path) != identity:
            raise EngineeringError('migration_backup_replaced')
    finally:
        connection.close()
    return logical_digest, raw_digest


def _sync_backup(path, source_version=SCHEMA_VERSION):
    # The backup filename must be durable before the source schema commits.
    # SQLite syncs its pages; publishing with link also needs a directory sync.
    identity = EngineeringLibrary._file_identity(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_dev, info.st_ino) != identity):
            raise EngineeringError('migration_backup_replaced')
        os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(path.parent, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    EngineeringLibrary._preflight_storage(path, identity, expected_version=source_version)


def migrate_schema2(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    return _migrate(library, backup_path=backup_path, source_version=SCHEMA_VERSION,
                    target_version=SNAPSHOT_SCHEMA_VERSION, ddl=SNAPSHOT_DDL)


def migrate_schema3(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit method-store->application schema migration, never on open."""
    return _migrate(library, backup_path=backup_path, source_version=SNAPSHOT_SCHEMA_VERSION,
                    target_version=APPLICATION_SCHEMA_VERSION, ddl=APPLICATION_DDL)


def migrate_schema4(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit same-authority review upgrade; no auto migration on open."""
    return _migrate(library, backup_path=backup_path, source_version=APPLICATION_SCHEMA_VERSION,
                    target_version=REVIEW_SCHEMA_VERSION, ddl=REVIEW_DDL)


def migrate_schema5(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit material upgrade; historical bytes are copied unchanged."""
    return _migrate(library, backup_path=backup_path, source_version=REVIEW_SCHEMA_VERSION,
                    target_version=MATERIAL_SCHEMA_VERSION, ddl=MATERIAL_DDL)


def migrate_schema6(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit additive Proposal upgrade; no real data or auto-open upgrade."""
    return _migrate(library, backup_path=backup_path, source_version=MATERIAL_SCHEMA_VERSION,
                    target_version=PROPOSAL_SCHEMA_VERSION, ddl=PROPOSAL_DDL)


def migrate_schema7(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit additive authorization upgrade; never runs during open."""
    return _migrate(library, backup_path=backup_path, source_version=PROPOSAL_SCHEMA_VERSION,
                    target_version=AUTHORIZATION_SCHEMA_VERSION, ddl=AUTHORIZATION_DDL)


def migrate_schema8(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit additive action budget/apply upgrade; no automatic migration."""
    return _migrate(library, backup_path=backup_path, source_version=AUTHORIZATION_SCHEMA_VERSION,
                    target_version=APPLY_SCHEMA_VERSION, ddl=APPLY_DDL)


def migrate_schema9(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit additive MethodControl upgrade; never modifies a real DB implicitly."""
    return _migrate(library, backup_path=backup_path, source_version=APPLY_SCHEMA_VERSION,
                    target_version=METHOD_SCHEMA_VERSION, ddl=METHOD_DDL)


def migrate_schema10(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit additive baseline/package schema11; never performed by open."""
    return _migrate(library, backup_path=backup_path, source_version=METHOD_SCHEMA_VERSION,
                    target_version=IMPLEMENTATION_SCHEMA_VERSION, ddl=IMPLEMENTATION_DDL)



def migrate_schema11(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit original action-ledger upgrade + Submission schema12; never on open."""
    return _migrate(library, backup_path=backup_path, source_version=IMPLEMENTATION_SCHEMA_VERSION,
                    target_version=SUBMISSION_SCHEMA_VERSION, ddl=MIGRATION11_DDL)


def migrate_schema12(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicit additive original step binding schema13; never performed by open."""
    return _migrate(library, backup_path=backup_path, source_version=SUBMISSION_SCHEMA_VERSION,
                    target_version=DISPATCH_SCHEMA_VERSION, ddl=DISPATCH_DDL)


def migrate_schema13(library: EngineeringLibrary, *, backup_path: Path) -> MigrationReceipt:
    """Explicitly widen the original action ledger and add acceptance receipts."""
    return _migrate(library, backup_path=backup_path, source_version=DISPATCH_SCHEMA_VERSION,
                    target_version=ACCEPTANCE_SCHEMA_VERSION, ddl=ACCEPTANCE_MIGRATION_DDL)


def _set_foreign_keys(connection, enabled):
    # SQLite ignores this pragma inside a transaction. Verify the actual value.
    if connection.in_transaction:
        raise EngineeringError('migration_foreign_keys_transaction')
    connection.execute('PRAGMA foreign_keys=' + ('ON' if enabled else 'OFF'))
    if connection.execute('PRAGMA foreign_keys').fetchone() != (int(enabled),):
        raise EngineeringError('migration_foreign_keys_unconfirmed')


def _statements(ddl):
    # Complete SQLite statements retain trigger BEGIN/END bodies; executescript
    # would implicitly commit and destroy the required all-or-nothing upgrade.
    pending = ""
    for line in ddl.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ""
    if pending.strip():
        raise EngineeringError('migration_ddl_incomplete')


def _migrate(library, *, backup_path, source_version, target_version, ddl):
    """Caller explicitly selects its owned DB and backup; no implicit migration."""
    if not isinstance(library, EngineeringLibrary):
        raise EngineeringError('migration_authority_required')
    selected = Path(backup_path)
    if not selected.is_absolute() or selected == library.path:
        raise EngineeringError('migration_backup_path_invalid')
    EngineeringLibrary._validate_directory_chain(selected.parent)
    with library._lock:
        library._check_bound_state()
        connection = library._connection
        if connection.in_transaction:
            raise EngineeringError('library_transaction_nested')
        if library._schema_version >= target_version:
            row = connection.execute(
                'SELECT source_digest, backup_sha256, backup_path FROM eng_schema_migrations WHERE target_version=?',
                (target_version,)).fetchone()
            if row is None or row[2] != str(selected):
                raise EngineeringError('migration_receipt_unavailable')
            if _check_backup(selected, library.library_id, source_version) != row[:2]:
                raise EngineeringError('migration_backup_changed')
            return MigrationReceipt(False, *row, target_version=target_version)

        if library._schema_version != source_version:
            raise EngineeringError('migration_source_version_required')
        try:
            connection.execute('BEGIN')
            before = _source_digest(connection, source_version)
            if selected.exists() or selected.is_symlink():
                if EngineeringLibrary._file_identity(selected) == library._identity:
                    raise EngineeringError('migration_backup_path_invalid')
                backed_up, backup_digest = _check_backup(selected, library.library_id, source_version)
                if backed_up != before:
                    raise EngineeringError('migration_backup_conflict')
            else:
                EngineeringLibrary._reject_sidecars(selected)
                with tempfile.TemporaryDirectory(prefix='.ordessa-migration-', dir=selected.parent) as stage:
                    staged = Path(stage) / 'backup.sqlite'
                    fd = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(fd)
                    target = create_connection(SQLiteOptions(location=staged))
                    try:
                        deadline = time.monotonic() + 15
                        def progress(status, remaining, total):
                            if time.monotonic() >= deadline:
                                raise EngineeringError('migration_backup_timeout')
                        connection.backup(target, pages=256, progress=progress, sleep=0.05)
                    finally:
                        target.close()
                    backed_up, backup_digest = _check_backup(staged, library.library_id, source_version)
                    if backed_up != before:
                        raise EngineeringError('migration_backup_mismatch')
                    EngineeringLibrary._validate_directory_chain(selected.parent)
                    os.link(staged, selected, follow_symlinks=False)
                    staged.unlink()
            if EngineeringLibrary._file_identity(selected) == library._identity:
                raise EngineeringError('migration_backup_path_invalid')
            if source_version == SCHEMA_VERSION:
                _sync_backup(selected)
            else:
                _sync_backup(selected, source_version)
        except BaseException as exc:
            library._rollback_failure(exc)
            raise
        else:
            try:
                connection.rollback()  # Release the consistent read snapshot.
            except BaseException as exc:
                # _rollback_failure closes a connection whose rollback cannot
                # be confirmed, and preserves the original failure as cause.
                library._rollback_failure(exc)
                library.close()
                raise

        # A concurrent legitimate writer may have run after the backup snapshot.
        # Recheck the full old state under the original SQLite write lock.
        commit_started = False
        backup_guard = create_connection(SQLiteOptions(location=selected.as_uri() + '?mode=ro', uri=True))
        try:
            # Retain the backup's SQLite read lock through the source commit,
            # so a legitimate SQLite writer cannot alter the recovery copy
            # after its logical/physical receipt was checked.
            backup_guard.execute('BEGIN')
            EngineeringLibrary._validate_schema(backup_guard, library.library_id, source_version)
            if _check_backup(selected, library.library_id, source_version) != (before, backup_digest):
                raise EngineeringError('migration_backup_changed')
            if target_version in (MATERIAL_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION):
                _set_foreign_keys(connection, False)
            connection.execute('BEGIN IMMEDIATE')
            library._check_bound_state(allow_journal=True)
            if _source_digest(connection, source_version) != before:
                raise EngineeringError('migration_source_changed')
            for statement in _statements(ddl):
                connection.execute(statement)
            connection.execute('UPDATE library_meta SET schema_version=? WHERE singleton=1',
                               (target_version,))
            connection.execute('PRAGMA user_version=' + str(target_version))
            connection.execute('INSERT INTO eng_schema_migrations VALUES (?, ?, ?, ?)',
                               (target_version, before, backup_digest, str(selected)))
            if target_version in (MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION) and connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise EngineeringError('migration_foreign_keys_invalid')
            EngineeringLibrary._validate_schema(connection, library.library_id, target_version)
            if _source_digest_after(connection, source_version, target_version) != before:
                raise EngineeringError('migration_legacy_data_changed')
            library._check_identity()
            EngineeringLibrary._preflight_storage(library.path, library._identity,
                allow_journal=True)
            commit_started = True
            connection.commit()
            if target_version in (MATERIAL_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION):
                _set_foreign_keys(connection, True)
            library._schema_version = target_version
            connection._ordessa_schema_version = target_version
            library._check_bound_state()
        except BaseException as exc:
            library._rollback_failure(exc)
            # If COMMIT lost its result, do not retry on this connection. The
            # durable migration row and explicit backup allow later inspection.
            library.close()
            if target_version in (MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION) and commit_started:
                raise EngineeringError('migration_commit_unknown') from exc
            raise
        finally:
            backup_guard.close()
        return MigrationReceipt(True, before, backup_digest, str(selected), target_version=target_version)


def _source_digest_after(connection, source_version, target_version):
    rows = _rows(connection, source_version)
    rows['library_meta'][0][2] = source_version
    if source_version >= SNAPSHOT_SCHEMA_VERSION:
        # Remove only this upgrade's receipt; all prior receipt bytes remain
        # in the preservation comparison.
        rows['eng_schema_migrations'] = [row for row in rows['eng_schema_migrations']
                                         if row[0] != target_version]
    return hashlib.sha256(canonical_bytes(rows)).hexdigest()
