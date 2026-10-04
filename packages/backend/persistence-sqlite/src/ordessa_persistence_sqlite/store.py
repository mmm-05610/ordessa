"""SQLite implementation of the frozen ``StorePort`` (spec 026 order 005).

Scope discipline (compat-retirement §2 storage row): the CONNECTION and
TRANSACTION mechanism moves here; the product business DDL (server_profiles,
server_sessions, … PRODUCT_SCHEMA_VERSION=21) does NOT — the archived
history stays sealed in its own migrations and is only ever opened read-only
(see :mod:`ordessa_persistence_sqlite.legacy_read`).

C2 rules implemented here:

* same data root admits ONE effectful writer — a second ``open`` on a live
  root refuses; lease loss/timeout alone never proves the old writer dead,
  so recovery is an explicit evidence-backed release, not a timeout grab;
* request keys are claimed atomically with their digest; a spent key replays
  its stored receipt for the same digest and refuses a different one;
* response slots are consumed exactly once per (control_id, delivery_revision);
* receipts are append-only rows; current facts are revised, never rewritten.
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

from ordessa_environment_api import IdentityMismatchError
from ordessa_environment_api.identity import RequestKey
from ordessa_environment_api.domain import DomainWrite, DomainRevisionConflict
from ordessa_environment_api.errors import GuaranteeUnavailableError, UnknownResultError
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

    def __init__(self, store: "SqliteStorePort", cursor: sqlite3.Cursor) -> None:
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

    def __init__(self, store: "SqliteStorePort") -> None:
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
CREATE TABLE IF NOT EXISTS env_objects (
    environment TEXT NOT NULL,
    owner_instance TEXT NOT NULL,
    owner_generation INTEGER NOT NULL,
    object_id TEXT NOT NULL,
    state TEXT NOT NULL,
    historical INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (environment, owner_instance, owner_generation, object_id)
);
CREATE TABLE IF NOT EXISTS env_usages (
    usage_id TEXT PRIMARY KEY,
    environment TEXT NOT NULL,
    object_env TEXT,
    state TEXT NOT NULL,
    rights TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS env_response_slots (
    control_id TEXT NOT NULL,
    delivery_revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    PRIMARY KEY (control_id, delivery_revision)
);
CREATE TABLE IF NOT EXISTS env_relations (
    relation_id TEXT NOT NULL,
    source_entity TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (relation_id, source_entity, source_revision)
);
-- E5 change reservations (T005-11): durable admission tickets. Process death,
-- close/reopen or TTL never auto-releases one; only an explicit executed
-- release deletes its row (CREATE TABLE IF NOT EXISTS keeps this idempotent
-- for databases created before this table existed).
CREATE TABLE IF NOT EXISTS env_change_reservations (
    reservation_id TEXT PRIMARY KEY,
    target_entity TEXT NOT NULL,
    expected_revision TEXT NOT NULL,
    change_kind TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    refused_relations TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS env_key_tombstones (
    key_id TEXT PRIMARY KEY,
    retired_at REAL NOT NULL
);
"""


class WriterLockHeldError(RuntimeError):
    """Another live writer owns this data root (C2 same-root exclusivity)."""

    code = "WRITER_LOCK_HELD"


class SqliteStorePort(OperationRecordsMixin):
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
        self._acquire_writer_lock(allow_takeover=allow_takeover)

    @_serialized
    def _ensure_operation_columns(self) -> None:
        """Add named-step storage without changing old request/Usage identity."""
        additions = {
            "env_requests": {"operation_json": "TEXT", "operation_revision": "INTEGER NOT NULL DEFAULT 0",
                             "operation_intent_digest": "TEXT"},
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
        cur = self._conn.execute("SELECT owner_token FROM env_writer_lock WHERE id=1")
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO env_writer_lock (id, owner_token, acquired_at) VALUES (1, ?, ?)",
                (self._token, time.time()),
            )
            self._conn.commit()
            return
        if row["owner_token"] == self._token:
            return
        if not allow_takeover:
            raise WriterLockHeldError(
                f"data root {self._path} is owned by writer {row['owner_token']!r}; "
                "lease age never proves that writer dead — release explicitly or "
                "open with allow_takeover only with failure evidence"
            )
        # explicit evidence-backed takeover: record the previous owner's facts
        self._conn.execute(
            "UPDATE env_writer_lock SET owner_token=?, acquired_at=? WHERE id=1",
            (self._token, time.time()),
        )
        self._conn.commit()

    @_serialized
    def release_writer(self) -> None:
        self._conn.execute("DELETE FROM env_writer_lock WHERE id=1 AND owner_token=?",
                           (self._token,))
        self._conn.commit()

    @_serialized
    def close(self) -> None:
        try:
            self.release_writer()
        finally:
            self._conn.close()

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
    def claim_dispatch(self, key: RequestKey, digest: str) -> bool:
        """Atomically claim effect dispatch for one complete RequestKey.

        ``True`` grants the one dispatch claim. A same-digest existing row is
        already spent and returns ``False``; a changed digest is a conflict.
        The initial row is committed as possibly-dispatched/unknown before a
        caller can enter native code, so recovery can never infer permission
        to send again from a missing final receipt.
        """
        identity = (key.environment_namespace, key.principal_scope, key.request_id)
        unknown_receipt = json.dumps({
            "delivery": "issue_possible", "issued_revision": "rev-0",
            "safe_summary": {"recovery": "dispatch-claimed"}, "sequences": None,
        }, sort_keys=True)
        unknown_current = json.dumps({
            "outcome": "unknown", "revision": 0, "conflicts": [], "obligations": [],
        }, sort_keys=True)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT digest FROM env_requests WHERE environment=? AND principal=? AND request_id=?",
                identity,
            ).fetchone()
            if row is not None:
                self._conn.rollback()
                if row["digest"] != digest:
                    raise KeyConflictError(
                        f"request key {key.request_id} is spent with a different digest"
                    )
                return False
            self._conn.execute(
                "INSERT INTO env_requests "
                "(environment, principal, request_id, digest, spent, receipt, current, dispatch_state) "
                "VALUES (?, ?, ?, ?, 1, ?, ?, 'possibly-dispatched')",
                (*identity, digest, unknown_receipt, unknown_current),
            )
            self._conn.commit()
            return True
        except BaseException:
            if self._conn.in_transaction:
                self._conn.rollback()
            raise

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

    @_serialized
    def record_dispatch_result(self, key: RequestKey, receipt: Mapping[str, Any],
                               current: Mapping[str, Any]) -> bool:
        """Persist the final known/unknown result only for its exact request."""
        state = str(current.get("outcome", "unknown"))
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE env_requests SET receipt=?, current=?, dispatch_state=? "
                "WHERE environment=? AND principal=? AND request_id=? "
                "AND dispatch_state='possibly-dispatched'",
                (json.dumps(dict(receipt), sort_keys=True),
                 json.dumps(dict(current), sort_keys=True), state,
                 key.environment_namespace, key.principal_scope, key.request_id),
            )
            return cursor.rowcount == 1

    def commit_activity(self, activity_id: str, receipt: Mapping[str, Any]) -> None:
        self.append_receipt(activity_id, receipt)

    def _reject_scoped_activity_mutation(self, activity_id: str) -> None:
        """Bare activity ids cannot overwrite full scoped durable results."""
        rows = self._conn.execute(
            "SELECT operation_json,receipt FROM env_requests WHERE request_id=?", (activity_id,),
        ).fetchall()
        for row in rows:
            if row["operation_json"] is not None:
                raise GuaranteeUnavailableError("bare activity mutation cannot change a scoped operation")
            try:
                receipt = json.loads(row["receipt"]) if row["receipt"] else None
            except (TypeError, ValueError):
                raise GuaranteeUnavailableError("bare activity mutation cannot replace an unreadable receipt") from None
            if isinstance(receipt, dict) and "domain_result" in receipt:
                raise GuaranteeUnavailableError("bare activity mutation cannot change a scoped domain result")

    @_serialized
    def append_receipt(self, activity_id: str, receipt: Mapping[str, Any]) -> None:
        with self._operation_transaction():
            self._reject_scoped_activity_mutation(activity_id)
            self._conn.execute(
                "UPDATE env_requests SET receipt=? WHERE request_id=?",
                (json.dumps(dict(receipt), sort_keys=True), activity_id),
            )
            if self._conn.execute("SELECT changes()").fetchone()[0] == 0:
                self._conn.execute(
                    "INSERT INTO env_requests (environment, principal, request_id, digest, spent, receipt) "
                    "VALUES ('', '', ?, '', 1, ?)",
                    (activity_id, json.dumps(dict(receipt), sort_keys=True)),
                )

    @_serialized
    def read_current(self, activity_id: str) -> Mapping[str, Any] | None:
        row = self._conn.execute(
            "SELECT current FROM env_requests WHERE request_id=?", (activity_id,)
        ).fetchone()
        return json.loads(row["current"]) if row and row["current"] else None

    @_serialized
    def revise_current(self, activity_id: str, current: Mapping[str, Any]) -> None:
        """Current facts are REVISED, never overwritten silently (V2-3)."""
        with self._operation_transaction():
            self._reject_scoped_activity_mutation(activity_id)
            self._conn.execute(
                "UPDATE env_requests SET current=? WHERE request_id=?",
                (json.dumps(dict(current), sort_keys=True), activity_id),
            )

    @_serialized
    def lookup_history(self, activity_id: str) -> Mapping[str, Any] | None:
        row = self._conn.execute(
            "SELECT receipt, current FROM env_requests WHERE request_id=?", (activity_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "receipt": json.loads(row["receipt"]) if row["receipt"] else None,
            "current": json.loads(row["current"]) if row["current"] else None,
        }

    @_serialized
    def claim_response_slot(self, control_id: str, delivery_revision: int) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO env_response_slots (control_id, delivery_revision, state) "
                "VALUES (?, ?, 'claimed')",
                (control_id, delivery_revision),
            )
            if cur.rowcount == 0:
                row = self._conn.execute(
                    "SELECT state FROM env_response_slots WHERE control_id=? AND delivery_revision=?",
                    (control_id, delivery_revision),
                ).fetchone()
                if row and row["state"] == "free":
                    self._conn.execute(
                        "UPDATE env_response_slots SET state='claimed' "
                        "WHERE control_id=? AND delivery_revision=?",
                        (control_id, delivery_revision),
                    )
                    return True
                return False  # already spent — one effectful answer per slot
            return True

    @_serialized
    def commit_creation_and_usage(
        self, activity_id: str, objects: Mapping[str, Any], usages: Mapping[str, Any]
    ) -> None:
        """V3-1: objects + usages + receipt in ONE transaction."""
        with self._operation_transaction():
            self._reject_scoped_activity_mutation(activity_id)
            env_row = self._conn.execute(
                "SELECT environment FROM env_requests WHERE request_id=?", (activity_id,)
            ).fetchone()
            environment = env_row["environment"] if env_row else ""
            for usage_id in usages:
                row = self._conn.execute("SELECT holder_ref FROM env_usages WHERE usage_id=?", (usage_id,)).fetchone()
                if row is not None and row["holder_ref"] is not None:
                    raise GuaranteeUnavailableError("legacy creation cannot replace a scoped Usage holder")
            for ref, state in objects.items():
                env, inst, gen, oid = _split_object(ref)
                self._conn.execute(
                    "INSERT OR REPLACE INTO env_objects "
                    "(environment, owner_instance, owner_generation, object_id, state) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (env, inst, gen, oid, state),
                )
            for usage_id, state in usages.items():
                self._conn.execute(
                    "INSERT OR REPLACE INTO env_usages (usage_id, environment, state, rights) "
                    "VALUES (?, ?, ?, 'use')",
                    (usage_id, environment, state),
                )
            self._conn.execute(
                "UPDATE env_requests SET receipt=COALESCE(receipt, ?) WHERE request_id=?",
                (json.dumps({"creation": True}, sort_keys=True), activity_id),
            )

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


def _split_object(ref: str) -> tuple[str, str, int, str]:
    parts = ref.split(":", 3)
    if len(parts) != 4:
        raise ValueError(f"object ref must be env:instance:generation:object, got {ref!r}")
    return parts[0], parts[1], int(parts[2]), parts[3]


class KeyConflictError(IdentityMismatchError):
    """Same request key, different digest — never a re-dispatch."""

    code = "KEY_CONFLICT"
