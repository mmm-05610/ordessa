"""Explicit-path SQLite authority for immutable source and generated materials."""
from __future__ import annotations

from ordessa_engineering.domain.artifacts.library_material_codec import material_ref_to_dict, material_ref_from_dict
from contextlib import contextmanager
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import sqlite3

from ordessa_infrastructure.database import SQLiteOptions, create_connection
import stat
import threading
import tempfile
from typing import Any, Iterator, Mapping

from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.domain.artifacts.library_materials import MaterialRef
from ordessa_engineering.domain.artifacts.library_material_codec import canonical_json, content_digest
from .schema import SNAPSHOT_DDL, SNAPSHOT_SCHEMA_VERSION
from .application_schema import APPLICATION_DDL, APPLICATION_SCHEMA_VERSION
from .review_schema import REVIEW_DDL, REVIEW_SCHEMA_VERSION
from .material_schema import MATERIAL_DDL, MATERIAL_SCHEMA_VERSION
from .proposal_schema import PROPOSAL_DDL, PROPOSAL_SCHEMA_VERSION
from .authorization_schema import AUTHORIZATION_DDL, AUTHORIZATION_SCHEMA_VERSION
from .apply_schema import APPLY_SCHEMA_VERSION, APPLY_DDL
from .method_schema import METHOD_SCHEMA_VERSION, METHOD_DDL
from .implementation_schema import IMPLEMENTATION_SCHEMA_VERSION, IMPLEMENTATION_DDL, IMPLEMENTATION_TABLES
from .submission_schema import SUBMISSION_SCHEMA_VERSION, SUBMISSION_DDL, IMPLEMENTATION_APPLY_DDL
from .dispatch_schema import (DISPATCH_SCHEMA_VERSION, DISPATCH_DDL,
                              WORK_DISPATCH_SCHEMA_VERSION, WORK_DISPATCH_DDL)
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION, ACCEPTANCE_DDL, ACCEPTANCE_LEDGER_DDL
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_DDL
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION, EXTERNAL_RECORD_DDL


SCHEMA_VERSION = 2
_LIBRARY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,191}$")
IMPORTABLE_KINDS = frozenset({
    "did", "decision", "source-fact", "source-map", "standards-profile",
    "proposal", "conversation-summary", "method", "review-policy",
})
GENERATED_KINDS = frozenset({
    "source-review", "standard-review", "summary-fidelity", "review-judgement",
    "review-selection", "decision-run", "acceptance", "application-receipt", "step-receipt",
    "package", "package-review", "package-export-refusal", "package-export-uncertain",
    "implementation-run",
})

_SCHEMA = """
CREATE TABLE library_meta (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  library_id TEXT NOT NULL,
  schema_version INTEGER NOT NULL
);
CREATE TABLE materials (
  kind TEXT NOT NULL,
  stable_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  digest TEXT NOT NULL,
  body_json TEXT NOT NULL,
  generated INTEGER NOT NULL CHECK (generated IN (0, 1)),
  PRIMARY KEY (kind, stable_id, revision),
  UNIQUE (kind, stable_id, digest)
);
CREATE TABLE heads (
  kind TEXT NOT NULL,
  stable_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  digest TEXT NOT NULL,
  PRIMARY KEY (kind, stable_id),
  FOREIGN KEY (kind, stable_id, revision)
    REFERENCES materials(kind, stable_id, revision)
);
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  method_ref_json TEXT NOT NULL,
  registry_ref_json TEXT NOT NULL,
  input_json TEXT NOT NULL,
  status TEXT NOT NULL,
  cursor INTEGER NOT NULL,
  wait_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE step_log (
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  ordinal INTEGER NOT NULL,
  step_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  status TEXT NOT NULL,
  receipt_ref_json TEXT NOT NULL,
  PRIMARY KEY (run_id, ordinal)
);
CREATE TABLE idempotency (
  operation_id TEXT PRIMARY KEY,
  payload_digest TEXT NOT NULL,
  receipt_ref_json TEXT NOT NULL
);
"""


def _sql_tokens(sql: str | None) -> tuple[str, ...] | None:
    if sql is None:
        return None
    tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]", sql)
    if tokens and tokens[-1] == ";":
        tokens.pop()
    return tuple(token if token.startswith(("'", '"')) else token.casefold() for token in tokens)


def _schema_signature(connection: sqlite3.Connection) -> tuple:
    objects = tuple(connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"))
    definitions = tuple((kind, name, table, _sql_tokens(sql)) for kind, name, table, sql in objects)
    tables = []
    for kind, name, _, _ in objects:
        if kind != "table":
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        indexes = tuple(connection.execute(f"PRAGMA index_list({quoted})"))
        index_columns = []
        for index in indexes:
            index_name = '"' + index[1].replace('"', '""') + '"'
            index_columns.append((index, tuple(connection.execute(f"PRAGMA index_xinfo({index_name})"))))
        tables.append((name, tuple(connection.execute(f"PRAGMA table_xinfo({quoted})")),
                       tuple(connection.execute(f"PRAGMA foreign_key_list({quoted})")),
                       tuple(index_columns)))
    return definitions, tuple(tables)


@lru_cache(maxsize=8)
def _expected_schema_signature(version: int = SCHEMA_VERSION) -> tuple:
    # This temporary in-memory connection derives schema2 from its original DDL.
    # It is a comparison fixture, not another persistence authority. SQL tokens
    # ignore layout/case; logically different DDL requires an explicit migration.
    reference = create_connection(SQLiteOptions(location=":memory:"))
    try:
        reference.executescript(_SCHEMA)
        if version in (SNAPSHOT_SCHEMA_VERSION, APPLICATION_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION,
                          WORK_DISPATCH_SCHEMA_VERSION):
            reference.executescript(SNAPSHOT_DDL)
            if version in (APPLICATION_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                reference.executescript(APPLICATION_DDL)
                if version in (REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                    reference.executescript(REVIEW_DDL)
                    if version in (MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                        reference.executescript(MATERIAL_DDL)
                        if version in (PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                            reference.executescript(PROPOSAL_DDL)
                            if version in (AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                reference.executescript(AUTHORIZATION_DDL)
                                if version in (APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                    reference.executescript(ACCEPTANCE_LEDGER_DDL if version in (ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION) else IMPLEMENTATION_APPLY_DDL if version in (SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION) else APPLY_DDL)
                                    if version in (METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                        reference.executescript(METHOD_DDL)
                                        if version in (IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                            reference.executescript(IMPLEMENTATION_DDL)
                                            if version in (SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                reference.executescript(SUBMISSION_DDL)
                                                if version == DISPATCH_SCHEMA_VERSION:
                                                    reference.executescript(DISPATCH_DDL)
                                                if version in (ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                    reference.executescript(DISPATCH_DDL)
                                                    reference.executescript(ACCEPTANCE_DDL)
                                                    if version in (REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                        reference.executescript(REVIEWER_ASSIGNMENT_DDL)
                                                    if version in (EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                        reference.executescript(EXTERNAL_RECORD_DDL)
        elif version != SCHEMA_VERSION:
            raise EngineeringError("library_identity_or_schema_mismatch")
        if version == WORK_DISPATCH_SCHEMA_VERSION:
            # The comparison fixture must build the declared-Work relation too,
            # or a correctly migrated library would look like a mismatch.
            reference.executescript(WORK_DISPATCH_DDL)
        return _schema_signature(reference)
    finally:
        reference.close()


class _LibraryConnection(sqlite3.Connection):
    """Carry the preflight identity pin, not a claim about SQLite's native FD."""


class EngineeringLibrary:
    """One explicit authority under a trusted directory/process boundary.

    Standard sqlite3 opens by pathname. The identity guards detect observed
    replacements, but do not exclude malicious same-UID/OS ABA replacements or
    attest SQLite's actual FD. WAL and recovery sidecars require another reader
    design and are deliberately unavailable here; never use immutable=1 to hide
    live WAL state.
    """

    def __init__(self, path: Path, connection: sqlite3.Connection,
                 library_id: str):
        identity = getattr(connection, "_ordessa_identity", None)
        if (identity is None or getattr(connection, "_ordessa_path", None) != path
                or getattr(connection, "_ordessa_library_id", None) != library_id):
            raise EngineeringError("library_connection_unvalidated")
        if self._file_identity(path) != identity:
            raise EngineeringError("library_replaced_during_open")
        self.path = path
        self.library_id = library_id
        self._connection = connection
        self._lock = threading.RLock()
        self._identity = identity
        self._closed = False
        self._schema_version = connection._ordessa_schema_version

    @staticmethod
    def _file_identity(path: Path) -> tuple[int, int]:
        ancestor = path
        while ancestor.parent != ancestor:
            try:
                ancestor_info = ancestor.lstat()
            except FileNotFoundError:
                ancestor = ancestor.parent
                continue
            if stat.S_ISLNK(ancestor_info.st_mode):
                raise EngineeringError("library_path_unsafe")
            ancestor = ancestor.parent
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise EngineeringError("library_path_unsafe")
        return info.st_dev, info.st_ino

    @classmethod
    def create(cls, path: str | Path, *, library_id: str,
               schema_version: int = SCHEMA_VERSION) -> "EngineeringLibrary":
        selected = Path(path)
        if type(schema_version) is not int or schema_version not in (SCHEMA_VERSION, SNAPSHOT_SCHEMA_VERSION, APPLICATION_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
            raise EngineeringError("library_schema_version_unsupported")
        if not selected.is_absolute():
            raise EngineeringError("library_path_must_be_absolute")
        if type(library_id) is not str or not _LIBRARY_ID.fullmatch(library_id):
            raise EngineeringError("library_id_invalid")
        if selected.exists() or selected.is_symlink():
            raise EngineeringError("library_already_exists")
        ancestor = selected.parent
        while True:
            try:
                info = ancestor.lstat()
            except FileNotFoundError:
                if ancestor.parent == ancestor:
                    raise EngineeringError("library_parent_missing")
                ancestor = ancestor.parent
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise EngineeringError("library_parent_unsafe")
            break
        selected.parent.mkdir(parents=True, exist_ok=True)
        cls._validate_directory_chain(selected.parent)
        cls._reject_sidecars(selected)
        # Only private staging is cleaned on failure. Once linked into place a
        # complete database is retained even if the subsequent open fails.
        with tempfile.TemporaryDirectory(prefix=".ordessa-library-", dir=selected.parent) as staging:
            stage_root = Path(staging)
            os.chmod(stage_root, 0o700)
            staged = stage_root / "library.sqlite"
            descriptor = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(descriptor)
            connection = create_connection(SQLiteOptions(location=staged, isolation_level=None))
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.executescript(_SCHEMA)
                if schema_version in (SNAPSHOT_SCHEMA_VERSION, APPLICATION_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                    connection.executescript(SNAPSHOT_DDL)
                    if schema_version in (APPLICATION_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                        connection.executescript(APPLICATION_DDL)
                        if schema_version in (REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                            connection.executescript(REVIEW_DDL)
                            if schema_version in (MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                connection.execute("PRAGMA foreign_keys=OFF")
                                connection.executescript(MATERIAL_DDL)
                                if schema_version in (PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                    connection.executescript(PROPOSAL_DDL)
                                    if schema_version in (AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                        connection.executescript(AUTHORIZATION_DDL)
                                        if schema_version in (APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                            connection.executescript(ACCEPTANCE_LEDGER_DDL if schema_version in (ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION) else IMPLEMENTATION_APPLY_DDL if schema_version in (SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION) else APPLY_DDL)
                                            if schema_version in (METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                connection.executescript(METHOD_DDL)
                                                if schema_version in (IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                    connection.executescript(IMPLEMENTATION_DDL)
                                                    if schema_version in (SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                        connection.executescript(SUBMISSION_DDL)
                                                        if schema_version == DISPATCH_SCHEMA_VERSION:
                                                            connection.executescript(DISPATCH_DDL)
                                                        if schema_version in (ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                            connection.executescript(DISPATCH_DDL)
                                                            connection.executescript(ACCEPTANCE_DDL)
                                                            if schema_version in (REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                                connection.executescript(REVIEWER_ASSIGNMENT_DDL)
                                                            if schema_version in (EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                                                                connection.executescript(EXTERNAL_RECORD_DDL)
                                                            if schema_version == WORK_DISPATCH_SCHEMA_VERSION:
                                                                # The declared-Work relation is part of this version's
                                                                # schema, so a fresh library at this version carries it.
                                                                connection.executescript(WORK_DISPATCH_DDL)
                                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                                    raise EngineeringError("library_identity_or_schema_mismatch")
                                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("INSERT INTO library_meta VALUES (1, ?, ?)",
                                   (library_id, schema_version))
                connection.execute(f"PRAGMA user_version={schema_version}")
                cls._validate_schema(connection, library_id)
            finally:
                connection.close()
            cls._validate_directory_chain(selected.parent)
            cls._reject_sidecars(selected)
            try:
                os.link(staged, selected, follow_symlinks=False)
            except FileExistsError as exc:
                raise EngineeringError("library_already_exists") from exc
            staged.unlink()
        try:
            return cls.open(selected, library_id=library_id)
        except BaseException as exc:
            raise EngineeringError("library_created_open_failed") from exc

    @staticmethod
    def _validate_directory_chain(path: Path) -> None:
        current = path
        while True:
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise EngineeringError("library_parent_unsafe")
            if current.parent == current:
                break
            current = current.parent

    @classmethod
    def open(cls, path: str | Path, *, library_id: str) -> "EngineeringLibrary":
        selected = Path(path)
        if not selected.is_absolute():
            raise EngineeringError("library_path_must_be_absolute")
        identity = cls._file_identity(selected)
        cls._preflight_storage(selected, identity)
        uri = selected.as_uri() + "?mode=ro"
        probe = None
        try:
            probe = create_connection(SQLiteOptions(location=uri, uri=True))
            probe.execute("BEGIN")
            cls._validate_schema(probe, library_id)
        except sqlite3.Error as exc:
            raise EngineeringError("foreign_or_invalid_library") from exc
        finally:
            if probe is not None:
                probe.close()
        if cls._file_identity(selected) != identity:
            raise EngineeringError("library_replaced_during_open")
        cls._preflight_storage(selected, identity)
        connection = sqlite3.connect(selected.as_uri() + "?mode=rw", uri=True,
                                     isolation_level=None, check_same_thread=False,
                                     factory=_LibraryConnection)
        try:
            cls._preflight_storage(selected, identity)
            connection.execute("BEGIN")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            cls._validate_schema(connection, library_id, version)
            cls._preflight_storage(selected, identity, expected_version=version)
            connection.rollback()
            connection.execute("PRAGMA foreign_keys=ON")
            connection._ordessa_identity = identity
            connection._ordessa_path = selected
            connection._ordessa_library_id = library_id
            connection._ordessa_schema_version = version
            return cls(selected, connection, library_id)
        except BaseException:
            connection.close()
            raise

    @staticmethod
    def _reject_sidecars(path: Path, *, allow_journal: bool = False) -> None:
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                info = Path(str(path) + suffix).lstat()
            except FileNotFoundError:
                continue
            if allow_journal and suffix == "-journal" and stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                continue  # The active owned rollback transaction may have a journal.
            raise EngineeringError("library_sidecar_preflight_unavailable")

    @classmethod
    def _preflight_storage(cls, path: Path, identity: tuple[int, int], *, allow_journal: bool = False,
                           expected_version: int | None = None) -> None:
        cls._reject_sidecars(path, allow_journal=allow_journal)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        nonblocking = getattr(os, "O_NONBLOCK", None)
        if nofollow is None or nonblocking is None:
            raise EngineeringError("library_safe_open_unavailable")
        descriptor = os.open(path, os.O_RDONLY | nofollow | nonblocking)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != identity):
                raise EngineeringError("library_replaced_during_open")
            header = os.read(descriptor, 100)
        finally:
            os.close(descriptor)
        if len(header) != 100 or header[:16] != b"SQLite format 3\x00":
            raise EngineeringError("foreign_or_invalid_library")
        if header[18:20] != b"\x01\x01":
            raise EngineeringError("library_wal_preflight_unavailable")
        version = int.from_bytes(header[60:64], "big")
        if version not in (SCHEMA_VERSION, SNAPSHOT_SCHEMA_VERSION, APPLICATION_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION) or (expected_version is not None and version != expected_version):
            raise EngineeringError("library_identity_or_schema_mismatch")
        if cls._file_identity(path) != identity:
            raise EngineeringError("library_replaced_during_open")
        cls._reject_sidecars(path, allow_journal=allow_journal)

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection, library_id: str,
                         expected_version: int | None = None) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if (version not in (SCHEMA_VERSION, SNAPSHOT_SCHEMA_VERSION, APPLICATION_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION)
                or (expected_version is not None and version != expected_version)
                or _schema_signature(connection) != _expected_schema_signature(version)):
            raise EngineeringError("library_identity_or_schema_mismatch")
        row = connection.execute(
            "SELECT library_id, schema_version FROM library_meta WHERE singleton=1").fetchone()
        if row != (library_id, version):
            raise EngineeringError("library_identity_or_schema_mismatch")

    @property
    def schema_version(self) -> int:
        """The explicitly created/pinned library schema version."""
        return self._schema_version

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def _check_identity(self) -> None:
        if self._closed:
            raise EngineeringError("library_closed")
        if self._file_identity(self.path) != self._identity:
            raise EngineeringError("library_replaced")

    def _check_bound_state(self, *, allow_journal: bool = False) -> None:
        self._check_identity()
        self._preflight_storage(self.path, self._identity, allow_journal=allow_journal,
                                expected_version=self._schema_version)
        self._validate_schema(self._connection, self.library_id, self._schema_version)

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            # Existing validated connections may wait for another legitimate
            # rollback-mode writer. New open still refuses all sidecars; this
            # permission is not a no-side-effect hot-journal recovery guarantee.
            self._check_bound_state(allow_journal=True)
            yield self._connection

    def _rollback_failure(self, original: BaseException) -> None:
        try:
            self._connection.rollback()
        except BaseException as rollback_error:
            close_error = None
            try:
                self._connection.close()
            except BaseException as exc:
                close_error = exc
            self._closed = True
            error = EngineeringError("library_rollback_failed")
            error.rollback_error = rollback_error
            error.close_error = close_error
            raise error from original

    @staticmethod
    def _invalidates_connection(error: BaseException) -> bool:
        if isinstance(error, EngineeringError):
            return error.code in {
                "library_replaced", "library_replaced_during_open", "library_path_unsafe",
                "library_parent_unsafe", "foreign_or_invalid_library",
                "library_identity_or_schema_mismatch", "library_sidecar_preflight_unavailable",
                "library_wal_preflight_unavailable", "library_safe_open_unavailable", "library_closed",
            }
        code = getattr(error, "sqlite_errorcode", None)
        return isinstance(code, int) and (code & 0xFF) in {
            sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_IOERR,
        }

    @contextmanager
    def transaction(self, *, nonblocking: bool = False) -> Iterator[sqlite3.Connection]:
        """Original transaction authority, with a fail-fast effect-cut acquisition.

        The ordinary transaction path retains its historical wait semantics.
        Effect acquisition never blocks the async SDK loop on a library lock or
        another SQLite writer. It does not create another connection or ledger.
        """
        acquired = self._lock.acquire(blocking=not nonblocking)
        if not acquired:
            raise EngineeringError("library_effect_busy")
        previous_timeout = None
        try:
            if nonblocking:
                if self._connection.in_transaction:
                    raise EngineeringError("library_effect_busy")
                previous_timeout = self._connection.execute("PRAGMA busy_timeout").fetchone()[0]
                self._connection.execute("PRAGMA busy_timeout=0")
            self._check_bound_state(allow_journal=True)
            if self._connection.in_transaction:
                raise EngineeringError("library_transaction_nested")
            commit_attempted = False
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._check_bound_state(allow_journal=True)
                yield self._connection
                self._check_bound_state(allow_journal=True)
                commit_attempted = True
                self._connection.commit()
            except BaseException as exc:
                self._rollback_failure(exc)
                if commit_attempted:
                    self.close()
                    raise EngineeringError("library_commit_unknown") from exc
                if self._invalidates_connection(exc):
                    self.close()
                if (nonblocking and isinstance(exc, sqlite3.OperationalError)
                        and getattr(exc, 'sqlite_errorcode', None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)):
                    raise EngineeringError("library_effect_busy") from exc
                raise
        except sqlite3.OperationalError as exc:
            if (nonblocking and getattr(exc, 'sqlite_errorcode', None)
                    in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)):
                raise EngineeringError("library_effect_busy") from exc
            raise
        finally:
            try:
                if previous_timeout is not None and not self._closed:
                    self._connection.execute("PRAGMA busy_timeout=" + str(int(previous_timeout)))
            finally:
                self._lock.release()

    @staticmethod
    def _row_ref(library_id: str, row: tuple[Any, ...]) -> MaterialRef:
        return MaterialRef(library_id, row[0], row[1], row[2], row[3])

    def _write_material(self, connection: sqlite3.Connection, *, kind: str,
                        stable_id: str, revision: int, body: Any,
                        generated: bool) -> MaterialRef:
        if kind == 'work-context' and not getattr(connection, '_ordessa_work_context_write', False):
            raise EngineeringError('work_context_write_unauthorized')
        body_json = canonical_json(body)
        digest = content_digest(body)
        connection.execute(
            "INSERT INTO materials VALUES (?, ?, ?, ?, ?, ?)",
            (kind, stable_id, revision, digest, body_json, int(generated)))
        connection.execute(
            "INSERT INTO heads VALUES (?, ?, ?, ?) ON CONFLICT(kind, stable_id) "
            "DO UPDATE SET revision=excluded.revision, digest=excluded.digest",
            (kind, stable_id, revision, digest))
        return MaterialRef(self.library_id, kind, stable_id, revision, digest)

    def import_material(self, *, kind: str, stable_id: str, body: Any,
                        expected_head: MaterialRef | None = None) -> MaterialRef:
        if kind == "skill-bundle":
            raise EngineeringError("material_kind_retired")
        if kind in GENERATED_KINDS or kind not in IMPORTABLE_KINDS:
            raise EngineeringError("generated_material_cannot_be_imported")
        canonical_json(body)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT revision, digest FROM heads WHERE kind=? AND stable_id=?",
                (kind, stable_id)).fetchone()
            if row is None:
                if expected_head is not None:
                    raise EngineeringError("expected_head_missing")
                revision = 1
            else:
                if kind == "did":
                    raise EngineeringError("did_revision_requires_apply")
                current = MaterialRef(self.library_id, kind, stable_id, row[0], row[1])
                if expected_head != current:
                    raise EngineeringError("head_conflict")
                revision = row[0] + 1
            return self._write_material(connection, kind=kind, stable_id=stable_id,
                                         revision=revision, body=body, generated=False)

    def _create_generated(self, connection: sqlite3.Connection, *, kind: str,
                          stable_id: str, body: Any) -> MaterialRef:
        if kind == "implementation-run" and self._schema_version not in (DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
            raise EngineeringError("implementation_run_requires_dispatch_schema")
        if kind not in GENERATED_KINDS:
            raise EngineeringError("not_a_generated_kind")
        row = connection.execute(
            "SELECT revision FROM heads WHERE kind=? AND stable_id=?",
            (kind, stable_id)).fetchone()
        revision = 1 if row is None else row[0] + 1
        return self._write_material(connection, kind=kind, stable_id=stable_id,
                                     revision=revision, body=body, generated=True)

    def read(self, ref: MaterialRef) -> Any:
        if not isinstance(ref, MaterialRef) or ref.library_id != self.library_id:
            raise EngineeringError("cross_library_reference")
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT digest, body_json FROM materials "
                "WHERE kind=? AND stable_id=? AND revision=?",
                (ref.kind, ref.stable_id, ref.revision)).fetchone()
            if row is None or row[0] != ref.digest:
                raise EngineeringError("material_reference_unresolved")
            body = json.loads(row[1])
            if content_digest(body) != ref.digest:
                raise EngineeringError("material_digest_mismatch")
            return body

    def require_current(self, connection: sqlite3.Connection,
                        ref: MaterialRef) -> None:
        if not isinstance(ref, MaterialRef) or ref.library_id != self.library_id:
            raise EngineeringError("cross_library_reference")
        with self._read_connection() as owned_connection:
            if connection is not owned_connection or not connection.in_transaction:
                raise EngineeringError("library_transaction_connection_mismatch")
            row = connection.execute(
                "SELECT revision, digest FROM heads WHERE kind=? AND stable_id=?",
                (ref.kind, ref.stable_id)).fetchone()
            if row != (ref.revision, ref.digest):
                raise EngineeringError("stale_material_reference")
            self.read(ref)

    def head(self, kind: str, stable_id: str) -> MaterialRef | None:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT revision, digest FROM heads WHERE kind=? AND stable_id=?",
                (kind, stable_id)).fetchone()
            if row is None:
                return None
            return MaterialRef(self.library_id, kind, stable_id, row[0], row[1])

    def start_run(self, run_id: str, *, method_ref: MaterialRef,
                  registry_ref: Mapping[str, Any], inputs: Mapping[str, Any], now: str,
                  expected_refs: tuple[MaterialRef, ...]) -> None:
        if (not isinstance(method_ref, MaterialRef) or method_ref.kind != "method"
                or method_ref.library_id != self.library_id):
            raise EngineeringError("run_method_ref")
        dependencies = tuple(expected_refs)
        if any(not isinstance(ref, MaterialRef) for ref in dependencies):
            raise EngineeringError("run_dependency_ref")
        with self.transaction() as connection:
            self.require_current(connection, method_ref)
            # The selected dependencies and the new run are admitted together.
            # Pre-BEGIN head observations cannot authorise this insertion.
            for ref in dependencies:
                self.require_current(connection, ref)
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, 'RUNNING', 0, NULL, ?, ?)",
                (run_id, canonical_json(material_ref_to_dict(method_ref)), canonical_json(registry_ref),
                 canonical_json(inputs), now, now))

    def run_row(self, run_id: str) -> dict[str, Any]:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT method_ref_json, registry_ref_json, input_json, status, cursor, wait_reason, created_at, updated_at "
                "FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise EngineeringError("run_not_found")
            return {"method_ref": material_ref_from_dict(json.loads(row[0])),
                    "registry_ref": json.loads(row[1]), "inputs": json.loads(row[2]),
                    "status": row[3], "cursor": row[4], "wait_reason": row[5],
                    "created_at": row[6], "updated_at": row[7]}

    def step_rows(self, run_id: str) -> list[dict[str, Any]]:
        with self._read_connection() as connection:
            from .step_rows import read_step_rows
            return read_step_rows(connection,run_id)

    def lookup_idempotency(self, operation_id: str, payload_hash: str) -> MaterialRef | None:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT payload_digest, receipt_ref_json FROM idempotency WHERE operation_id=?",
                (operation_id,)).fetchone()
            if row is None:
                return None
            if row[0] != payload_hash:
                raise EngineeringError("idempotency_conflict")
            return material_ref_from_dict(json.loads(row[1]))
