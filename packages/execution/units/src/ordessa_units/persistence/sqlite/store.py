"""Original Unit operation/Usage and Agent domain rows on one SQLite connection.

Historical SQL names and current CAS/unknown semantics are retained. No arbitrary
Object, capability dispatch, response-slot or global-reference APIs. This is a
source candidate; old physical files retire after consumers switch and tests.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from functools import wraps
from threading import RLock
from typing import Any, Mapping

from ordessa_execution_api.environment import IdentityMismatchError
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import (
    DomainWrite,
    DomainRevisionConflict,
)
from ordessa_execution_api.environment.errors import GuaranteeUnavailableError, UnknownResultError
from ordessa_execution_api.environment.staged_operations import STAGED_OPERATION_STORE_VERSION
from .operation_records import OperationRecordsMixin

SCHEMA_VERSION = 1


def _serialized(method):
    """Serialize access to this StorePort's shared SQLite connection."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


class _SerializedCursor:
    """Cursor facade that serializes fetches with connection operations."""

    __slots__ = ("_store", "_cursor")

    def __init__(self, store: "SqliteUnitStore", cursor: sqlite3.Cursor) -> None:
        self._store = store
        self._cursor = cursor

    def __getattr__(self, name):
        with self._store._lock:
            value = getattr(self._cursor, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            with self._store._lock:
                result = getattr(self._cursor, name)(*args, **kwargs)
                return (_SerializedCursor(self._store, result)
                        if isinstance(result, sqlite3.Cursor) else result)
        return call


class _SerializedConnectionView:
    """Connection facade preserving `with store.transaction() as conn`.

    The store lock spans the whole context manager body and is used around
    direct connection/cursor calls too. This prevents callers using the
    protocol's transaction escape hatch from interleaving with adapter claims
    on the same `check_same_thread=False` SQLite connection.
    """

    __slots__ = ("_store", "_entered")

    def __init__(self, store: "SqliteUnitStore") -> None:
        self._store = store
        self._entered = False

    def __enter__(self):
        self._store._lock.acquire()
        self._entered = True
        try:
            return self._store._conn.__enter__()
        except BaseException:
            self._entered = False
            self._store._lock.release()
            raise

    def __exit__(self, exc_type, exc, tb):
        if not self._entered:
            self._store._lock.acquire()
        try:
            return self._store._conn.__exit__(exc_type, exc, tb)
        finally:
            self._entered = False
            self._store._lock.release()

    @property
    def row_factory(self):
        """Mirror sqlite3's mutable row factory under the store lock."""
        with self._store._lock:
            return self._store._conn.row_factory

    @row_factory.setter
    def row_factory(self, factory):
        with self._store._lock:
            self._store._conn.row_factory = factory

    def __getattr__(self, name):
        with self._store._lock:
            value = getattr(self._store._conn, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            with self._store._lock:
                result = getattr(self._store._conn, name)(*args, **kwargs)
                return (_SerializedCursor(self._store, result)
                        if isinstance(result, sqlite3.Cursor) else result)
        return call

_SCHEMA = """
CREATE TABLE IF NOT EXISTS env_domain_records (
    environment TEXT NOT NULL,
    namespace TEXT NOT NULL,
    record_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    payload TEXT NOT NULL,
    PRIMARY KEY (environment, namespace, record_id)
);
CREATE TABLE IF NOT EXISTS env_request_steps (
    environment TEXT NOT NULL,
    principal TEXT NOT NULL,
    request_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    intent_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    outcome TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    result_digest TEXT,
    PRIMARY KEY(environment, principal, request_id, step_id),
    FOREIGN KEY(environment, principal, request_id)
      REFERENCES env_requests(environment, principal, request_id)
);
CREATE TABLE IF NOT EXISTS env_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS env_writer_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    owner_token TEXT NOT NULL,
    acquired_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS env_requests (
    environment TEXT NOT NULL,
    principal TEXT NOT NULL,
    request_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    spent INTEGER NOT NULL DEFAULT 1,
    receipt TEXT,
    current TEXT,
    dispatch_state TEXT NOT NULL DEFAULT 'legacy',
    PRIMARY KEY (environment, principal, request_id)
);
CREATE TABLE IF NOT EXISTS env_usages (
    usage_id TEXT PRIMARY KEY,
    environment TEXT NOT NULL,
    object_env TEXT,
    state TEXT NOT NULL,
    rights TEXT NOT NULL
);
-- E5 change reservations (T005-11): durable admission tickets. Process death,
-- close/reopen or TTL never auto-releases one; only an explicit executed
-- release deletes its row (CREATE TABLE IF NOT EXISTS keeps this idempotent
-- for databases created before this table existed).
CREATE TABLE IF NOT EXISTS env_key_tombstones (
    key_id TEXT PRIMARY KEY,
    retired_at REAL NOT NULL
);
"""


class WriterLockHeldError(RuntimeError):
    """Another live writer owns this data root (C2 same-root exclusivity)."""

    code = "WRITER_LOCK_HELD"


class SqliteUnitStore(OperationRecordsMixin):
    """One SQLite file implementing StorePort for one environment root."""

    def __init__(self, path: Path | str, *, writer_token: str | None = None,
                 allow_takeover: bool = False) -> None:
        self._lock = RLock()
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._token = writer_token or f"writer-{uuid.uuid4().hex}"
        self._conn = sqlite3.connect(str(self._path), timeout=10.0,
                                     check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._ensure_dispatch_state_column()
        self._ensure_operation_columns()
        self._writer_release_confirmed = False
        self._connection_closed = False
        self._acquire_writer_lock(allow_takeover=allow_takeover)

    @property
    def staged_operation_contract_version(self) -> str:
        return STAGED_OPERATION_STORE_VERSION

    @_serialized
    def _ensure_operation_columns(self) -> None:
        """Add named-step storage without changing old request/Usage identity."""
        additions = {
            "env_requests": {"operation_json": "TEXT", "operation_revision": "INTEGER NOT NULL DEFAULT 0",
                             "operation_intent_digest": "TEXT", "staged_operation_json": "TEXT"},
            "env_usages": {"holder_ref": "TEXT", "target_ref": "TEXT",
                           "revision": "INTEGER NOT NULL DEFAULT 0", "payload": "TEXT"},
            "env_request_steps": {"evidence_digest": "TEXT"},
        }
        with self._conn:
            for table, declarations in additions.items():
                columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(" + table + ")")}
                for name, declaration in declarations.items():
                    if name not in columns:
                        self._conn.execute("ALTER TABLE " + table + " ADD COLUMN " + name + " " + declaration)

    @_serialized
    def _ensure_dispatch_state_column(self) -> None:
        """Add the closeout state to databases created by schema version 1.

        Existing request rows become ``legacy`` and therefore remain spent;
        they are never mistaken for a newly claimed dispatch.
        """
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(env_requests)")}
        if "dispatch_state" not in columns:
            self._conn.execute(
                "ALTER TABLE env_requests ADD COLUMN dispatch_state TEXT NOT NULL DEFAULT 'legacy'"
            )
            self._conn.commit()

    # -- lifecycle -----------------------------------------------------------

    @_serialized
    def _acquire_writer_lock(self, *, allow_takeover: bool) -> None:
        # The product must first validate its original Host OS-root proof.
        # This transaction fences the exact SQL marker seen at admission;
        # no lease age, timeout, request state, or Usage is changed.
        if self._conn.in_transaction:
            raise GuaranteeUnavailableError("writer acquisition cannot nest in another transaction")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO env_writer_lock (id, owner_token, acquired_at) VALUES (1, ?, ?)",
                    (self._token, time.time()),
                )
            elif row["owner_token"] == self._token:
                pass
            elif not allow_takeover:
                raise WriterLockHeldError(
                    f"data root {self._path} is owned by writer {row['owner_token']!r}; "
                    "lease age never proves that writer dead — release explicitly or "
                    "open with allow_takeover only with failure evidence"
                )
            else:
                old = row["owner_token"]
                if not isinstance(old, str) or not old:
                    raise GuaranteeUnavailableError("previous SQL writer marker is malformed")
                changed = self._conn.execute(
                    "UPDATE env_writer_lock SET owner_token=?, acquired_at=? "
                    "WHERE id=1 AND owner_token=?",
                    (self._token, time.time(), old),
                )
                if changed.rowcount != 1:
                    raise GuaranteeUnavailableError("previous SQL writer marker changed during takeover")
            self._conn.commit()
        except BaseException:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise

    @_serialized
    def release_writer(self) -> None:
        """Release only the exact original SQL writer after a committed CAS.

        A failed DELETE/commit leaves the connection and OS root owner in
        place for inspection or retry. A missing/mismatched row is not proof
        that this call successfully released it: a lost commit reply is
        ambiguous and requires explicit ownership reconciliation.
        """
        if self._writer_release_confirmed:
            return
        if self._connection_closed or self._conn.in_transaction:
            raise GuaranteeUnavailableError("writer release state is not comparable")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone()
            if row is None or row["owner_token"] != self._token:
                raise GuaranteeUnavailableError(
                    "original SQL writer lock is absent or belongs to another owner")
            deleted = self._conn.execute(
                "DELETE FROM env_writer_lock WHERE id=1 AND owner_token=?",
                (self._token,))
            if deleted.rowcount != 1:
                raise GuaranteeUnavailableError("writer release CAS did not match")
            self._conn.commit()
        except BaseException:
            if self._conn.in_transaction:
                try:
                    self._conn.rollback()
                except BaseException as rollback_error:
                    raise GuaranteeUnavailableError(
                        "writer release and rollback outcomes are unknown") from rollback_error
            raise
        self._writer_release_confirmed = True

    @_serialized
    def close(self) -> None:
        """Close only after exact SQL writer release is confirmed.

        If release fails, retain the original connection so a retry can
        compare and release the same token. If connection close itself fails
        after a confirmed release, retry only the connection close.
        """
        if self._connection_closed:
            return
        self.release_writer()
        self._conn.close()
        self._connection_closed = True

    @_serialized
    def inspect_and_close(self, inspector):
        """Run one read-only inspection and close under this Store's RLock.

        Every SqliteUnitStore method, including Unit step recording, uses this
        same lock. The inspector must read from this StorePort and must not
        perform effects. If inspection fails, the writer remains open. The
        successful return is the inspector's result; close errors propagate
        rather than manufacturing a report. This is a storage serialization
        boundary, not a new report authority or a second connection.
        """
        if not callable(inspector):
            raise TypeError("read-only store inspector required")
        result = inspector()
        self.close()
        return result

    @property
    def writer_token(self) -> str:
        return self._token

    @property
    @_serialized
    def schema_version(self) -> int:
        row = self._conn.execute(
            "SELECT value FROM env_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT OR REPLACE INTO env_meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
            return SCHEMA_VERSION
        return int(row["value"])

    def check_future_schema(self) -> None:
        version = self.schema_version
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema {version} is newer than this code ({SCHEMA_VERSION}); "
                "refusing to write (read-only downgrade is not a migration)"
            )

    # -- StorePort (E1) --------------------------------------------------------

    def transaction(self) -> Any:
        """Return a serialized connection view for the frozen StorePort API."""
        return _SerializedConnectionView(self)

    @_serialized
    def read_domain(self, environment: str, namespace: str,
                    record_id: str) -> Mapping[str, Any] | None:
        row = self._conn.execute(
            "SELECT record_id, revision, payload FROM env_domain_records "
            "WHERE environment=? AND namespace=? AND record_id=?",
            (environment, namespace, record_id),
        ).fetchone()
        return self._domain_record(row) if row is not None else None

    @staticmethod
    def _domain_record(row) -> Mapping[str, Any]:
        try:
            value = json.loads(row["payload"])
            if not isinstance(value, dict):
                raise ValueError("domain record is not an object")
            return {"record_id": row["record_id"], "revision": row["revision"], "value": value}
        except (TypeError, ValueError, RecursionError):
            raise GuaranteeUnavailableError("stored domain record is unreadable") from None

    @_serialized
    def list_domain(self, environment: str,
                    namespace: str) -> tuple[Mapping[str, Any], ...]:
        rows = self._conn.execute(
            "SELECT record_id, revision, payload FROM env_domain_records "
            "WHERE environment=? AND namespace=? ORDER BY record_id",
            (environment, namespace),
        ).fetchall()
        return tuple(self._domain_record(row) for row in rows)

    @staticmethod
    def _domain_result(existing, digest: str) -> Mapping[str, Any]:
        if existing["digest"] != digest:
            raise KeyConflictError("request key is spent with a different digest")
        try:
            receipt = json.loads(existing["receipt"]) if existing["receipt"] else None
            current = json.loads(existing["current"]) if existing["current"] else None
        except (TypeError, ValueError) as exc:
            raise UnknownResultError("stored domain result is unreadable") from exc
        if (existing["dispatch_state"] != "concluded" or not isinstance(current, dict)
                or current.get("outcome") != "concluded" or not isinstance(receipt, dict)
                or not isinstance(receipt.get("domain_result"), dict)):
            raise UnknownResultError("spent request has no complete concluded domain result")
        return receipt["domain_result"]

    @_serialized
    def read_domain_result(self, request: RequestKey,
                           digest: str) -> Mapping[str, Any] | None:
        existing = self._conn.execute(
            "SELECT digest, dispatch_state, receipt, current FROM env_requests "
            "WHERE environment=? AND principal=? AND request_id=?",
            (request.environment_namespace, request.principal_scope, request.request_id),
        ).fetchone()
        return self._domain_result(existing, digest) if existing is not None else None

    @_serialized
    def commit_domain_change(self, request: RequestKey, digest: str,
                             writes: tuple[DomainWrite, ...],
                             result: Mapping[str, Any]) -> Mapping[str, Any]:
        """CAS domain rows and the existing request result in one transaction.

        This data-only operation never enters a provider or dispatch callback.
        A spent uncertain request remains spent, even without a domain result.
        """
        if self._conn.in_transaction:
            raise GuaranteeUnavailableError("domain commit cannot nest inside an open transaction")
        identities = [(write.namespace, write.record_id) for write in writes]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate domain record in one change")
        payloads = [json.dumps(dict(write.value), sort_keys=True, allow_nan=False)
                    for write in writes]
        result_json = json.dumps(dict(result), sort_keys=True, allow_nan=False)
        receipt_json = json.dumps({"delivery": "acknowledged", "domain_result":
                                   json.loads(result_json)}, sort_keys=True, allow_nan=False)
        current_json = json.dumps({"outcome": "concluded", "revision": 1,
                                   "conflicts": [], "obligations": []}, sort_keys=True)
        identity = (request.environment_namespace, request.principal_scope, request.request_id)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            existing = self._conn.execute(
                "SELECT digest, dispatch_state, receipt, current FROM env_requests "
                "WHERE environment=? AND principal=? AND request_id=?", identity,
            ).fetchone()
            if existing is not None:
                replay = self._domain_result(existing, digest)
                self._conn.rollback()
                return replay
            for write, payload in zip(writes, payloads):
                row = self._conn.execute(
                    "SELECT revision FROM env_domain_records "
                    "WHERE environment=? AND namespace=? AND record_id=?",
                    (request.environment_namespace, write.namespace, write.record_id),
                ).fetchone()
                actual = row["revision"] if row is not None else 0
                if actual != write.expected_revision:
                    raise DomainRevisionConflict("domain record revision does not match")
                if row is None:
                    self._conn.execute(
                        "INSERT INTO env_domain_records(environment, namespace, record_id, revision, payload) "
                        "VALUES (?, ?, ?, 1, ?)",
                        (request.environment_namespace, write.namespace, write.record_id, payload),
                    )
                else:
                    self._conn.execute(
                        "UPDATE env_domain_records SET revision=?, payload=? "
                        "WHERE environment=? AND namespace=? AND record_id=? AND revision=?",
                        (actual + 1, payload, request.environment_namespace, write.namespace,
                         write.record_id, actual),
                    )
            self._conn.execute(
                "INSERT INTO env_requests(environment, principal, request_id, digest, spent, "
                "receipt, current, dispatch_state) VALUES (?, ?, ?, ?, 1, ?, ?, 'concluded')",
                (*identity, digest, receipt_json, current_json),
            )
            self._conn.commit()
            return json.loads(result_json)
        except BaseException:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise

    @_serialized
    def reserve_request(self, key: RequestKey, digest: str) -> bool:
        """Atomically claim a request key; True when newly claimed.

        A spent key returns True only for the SAME digest (the caller replays
        the stored receipt); a different digest raises IdentityMismatchError
        semantics via False-with-conflict marker ``KeyConflictError``."""
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO env_requests (environment, principal, request_id, digest, spent) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (key.environment_namespace, key.principal_scope, key.request_id, digest),
                )
            return True
        except sqlite3.IntegrityError:
            row = self._conn.execute(
                "SELECT digest FROM env_requests WHERE environment=? AND principal=? AND request_id=?",
                (key.environment_namespace, key.principal_scope, key.request_id),
            ).fetchone()
            if row is None:
                raise
            if row["digest"] != digest:
                raise KeyConflictError(
                    f"request key {key.request_id} is spent with a different digest"
                )
            return True  # same digest → replay path; caller reads the receipt


    @_serialized
    def read_request(self, key: RequestKey) -> Mapping[str, Any] | None:
        """Read a request by its full environment/principal/request identity."""
        row = self._conn.execute(
            "SELECT digest, receipt, current, dispatch_state FROM env_requests "
            "WHERE environment=? AND principal=? AND request_id=?",
            (key.environment_namespace, key.principal_scope, key.request_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "digest": row["digest"],
            "state": row["dispatch_state"],
            "receipt": json.loads(row["receipt"]) if row["receipt"] else None,
            "current": json.loads(row["current"]) if row["current"] else None,
        }










    # -- tombstones (C2 §密钥与墓碑) -------------------------------------------

    @_serialized
    def record_key_tombstone(self, key_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO env_key_tombstones (key_id, retired_at) VALUES (?, ?)",
                (key_id, time.time()),
            )

    @_serialized
    def has_key_tombstone(self, key_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM env_key_tombstones WHERE key_id=?", (key_id,)
        ).fetchone() is not None



    @_serialized
    def pending_operations(self, environment_namespace):
        rows = self._conn.execute("SELECT principal,request_id FROM env_requests WHERE environment=? AND operation_json IS NOT NULL", (environment_namespace,)).fetchall()
        pending = []
        for row in rows:
            request = RequestKey(environment_namespace, row['principal'], row['request_id'])
            record = self.read_operation(request)
            # The original query owner reserves an authorization recipe, not
            # an effect. Preserve its reserved row; never invent a terminal
            # result. Any actual step claim makes this conservative exclusion
            # unavailable, even when its kind says query.
            intent = record.intent
            if (intent.kind == 'unit-acp-query' and len(intent.steps) == 1
                    and intent.steps[0].step_id == 'read'
                    and isinstance(intent.context_ref.get('acpTurnRead'), Mapping)
                    and set(intent.context_ref['acpTurnRead']) == {
                        'unitRef', 'operationRef', 'expectedPromptInputDigest'}
                    and self._conn.execute(
                        'SELECT 1 FROM env_request_steps WHERE environment=? AND principal=? AND request_id=?',
                        (environment_namespace, row['principal'], row['request_id'])).fetchone() is None):
                continue
            if record.status not in ('published', 'refused', 'cancelled'):
                pending.append(record)
        return tuple(pending)

    @_serialized
    def pending_unclassified_requests(self, environment_namespace):
        """Old spent requests without a recipe cannot be proved harmless."""
        return tuple({'environmentNamespace': environment_namespace,
                      'principalScope': row['principal'], 'requestId': row['request_id']}
                     for row in self._conn.execute(
                         "SELECT principal,request_id FROM env_requests WHERE environment=? "
                         "AND operation_json IS NULL AND dispatch_state!='concluded' "
                         "ORDER BY principal,request_id", (environment_namespace,)))

    @_serialized
    def pending_usage_ids(self, environment_namespace):
        return tuple(row['usage_id'] for row in self._conn.execute(
            "SELECT usage_id FROM env_usages WHERE environment=? AND state IN ('active','unknown') ORDER BY usage_id", (environment_namespace,)))


class KeyConflictError(IdentityMismatchError):
    """Same request key, different digest — never a re-dispatch."""

    code = "KEY_CONFLICT"
