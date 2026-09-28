"""Durable assignment storage (plan.md T05; data-model.md §内容与版本).

The rows live in the product SQLite database (the same pacthold
:class:`~pacthold.storage.Database` the library uses) in a NEW
domain-owned table, ``skill_assignments``, created by *this package's* own
idempotent :meth:`AssignmentStore.ensure_schema`.

**Shared-schema disclosure (register in the migration account):** the
product schema chain in ``packages/pacthold/src/pacthold/storage/
database.py`` is C0-owned and must not be edited from this slice
(AGENTS.md rule 5). ``ensure_schema`` is therefore the temporary host of
this DDL — when C0 integrates the skills domain, the ``skill_assignments``
/ ``skill_assignment_operations`` / ``skill_binding_cas`` tables must move
into the shared migration chain verbatim (same names, same columns), and
this helper retires. Until then, ``CREATE IF NOT EXISTS`` here is the only
place the DDL exists, which keeps the on-disk story stable for rule 5
(new tables, no change to existing identifiers).

Write guards, both required by the data model (更新已启用范围时明确挑选目标
修订并写 CAS/操作键；重试不能重复升级):

* **expectedVersion CAS** — every guarded write compares against the row's
  monotonic ``row_version`` (``0`` = "no row yet", i.e. creation intent);
  a mismatch is the typed refusal ``ASSIGNMENT_VERSION_CONFLICT``.
* **operationKey idempotency** — a settled key replays its recorded
  result and applies nothing again; the replay check and the write share
  one ``BEGIN IMMEDIATE`` transaction, so a retry can never double-upgrade.

The store also satisfies :class:`ordessa_skills.library.records.
BindingCasPort` (:meth:`AssignmentStore.binding_cas`), which records.py
declared as owned by this slice ("the assignments slice (T05) supplies
this port and owns its table"). The Profile binding versions are kept in
``skill_binding_cas`` — deliberately *not* a column of the legacy
``server_profile_assets`` table (shared schema; same disclosure as above).

`enable` writes are gated by the injected :class:`RevisionGate`
(:class:`ordessa_skills.library.revisions.RevisionApprovalStore`
satisfies it): a revision that is not installed+approved is refused with
its own typed code, never filtered (G06 「启用未批准版」).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

from pacthold_runtime_compat.storage import Database

from ..api.identity import ASSET_ID
from ..library.records import SKILL_KIND
from .model import (
    DECISION_DISABLE,
    DECISION_ENABLE,
    AssignmentError,
    SkillAssignment,
)
from .ports import RevisionGate

#: Table names are registered for the migration account; do not rename
#: without a data-compatibility note (AGENTS.md rule 5).
ASSIGNMENTS_TABLE = "skill_assignments"
OPERATIONS_TABLE = "skill_assignment_operations"
BINDING_CAS_TABLE = "skill_binding_cas"

_DDL = (
    f"""CREATE TABLE IF NOT EXISTS {ASSIGNMENTS_TABLE} (
        assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_scope TEXT NOT NULL,
        principal TEXT NOT NULL,
        scope_kind TEXT NOT NULL CHECK (scope_kind IN ('user_global','project')),
        scope_id TEXT NOT NULL,
        harness_key TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('enable','disable')),
        revision INTEGER,
        row_version INTEGER NOT NULL,
        operation_key TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    # 重复同层同 assetId 拒绝 — enforced in SQL, not only in Python.
    f"""CREATE UNIQUE INDEX IF NOT EXISTS {ASSIGNMENTS_TABLE}_layer_unique
        ON {ASSIGNMENTS_TABLE}
        (server_scope, principal, scope_kind, scope_id, harness_key, asset_id)""",
    f"""CREATE TABLE IF NOT EXISTS {OPERATIONS_TABLE} (
        operation_key TEXT PRIMARY KEY,
        result_json TEXT NOT NULL,
        settled_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE IF NOT EXISTS {BINDING_CAS_TABLE} (
        profile_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        PRIMARY KEY (profile_id, asset_id)
    )""",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AssignmentScope:
    """The server-injected data domain of one store instance (api-requests
    §G5: serverScope = 该 Server 数据根实例身份). A client never supplies
    either value; the auth layer constructs the store with them (FR09)."""

    __slots__ = ("server_scope", "principal")

    def __init__(self, *, server_scope: str, principal: str) -> None:
        if not server_scope or not principal:
            raise AssignmentError(
                "ASSIGNMENT_INVALID",
                "server_scope and principal are injected by the auth layer")
        self.server_scope = server_scope
        self.principal = principal


class AssignmentStore:
    def __init__(self, database: Database, *, scope: AssignmentScope,
                 approvals: RevisionGate | None = None) -> None:
        self.database = database
        self.scope = scope
        self.approvals = approvals
        self._schema_ready = False

    # -- schema ---------------------------------------------------------------

    def ensure_schema(self) -> None:
        """Idempotent: creates the domain-owned tables if absent.

        Every statement is ``CREATE ... IF NOT EXISTS``, so repeated calls
        on a live data root are a no-op (the shared migration chain will
        take this DDL over verbatim — see module docstring).
        """
        with self.database.transaction() as conn:
            for statement in _DDL:
                conn.execute(statement)
        self._schema_ready = True

    def _require_schema(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (ASSIGNMENTS_TABLE,)).fetchone()
        if row is None:
            raise AssignmentError(
                "ASSIGNMENT_SCHEMA_UNAVAILABLE",
                "the skill_assignments table is not present; call "
                "ensure_schema() during service wiring")

    # -- reads ------------------------------------------------------------------

    def list(self, *, scope_kind: str | None = None, scope_id: str | None = None,
             harness_key: str | None = None, asset_id: str | None = None
             ) -> list[dict[str, Any]]:
        """assignments/list (contracts.md). Only this data domain's and this
        principal's rows are addressable — the filter is in SQL itself, so a
        cross-server or cross-principal read cannot be shaped by the caller
        (G07 「未授权跨 Server 引用」).

        ``harness_key``: ``'*'`` restricts to any-harness rows, a brand
        token to that brand's rows, ``None`` (default) lists every harness
        scope of the matching layers.
        """
        with self.database.read() as conn:
            self._require_schema(conn)
            sql = (f"SELECT * FROM {ASSIGNMENTS_TABLE} "
                   "WHERE server_scope=? AND principal=?")
            params: list[Any] = [self.scope.server_scope, self.scope.principal]
            if scope_kind is not None:
                sql += " AND scope_kind=?"
                params.append(scope_kind)
            if scope_id is not None:
                sql += " AND scope_id=?"
                params.append(scope_id)
            if harness_key is not None:
                sql += " AND harness_key=?"
                params.append(harness_key)
            if asset_id is not None:
                sql += " AND asset_id=?"
                params.append(asset_id)
            sql += " ORDER BY scope_kind, scope_id, harness_key, asset_id"
            rows = conn.execute(sql, params).fetchall()
        return [SkillAssignment.from_row(row).view() for row in rows]

    def get_layer(self, *, scope_kind: str, scope_id: str = "",
                  harness_id: str | None, asset_id: str) -> SkillAssignment | None:
        """One layer row, or None (= inherit at that layer)."""
        key = SkillAssignment(
            server_scope=self.scope.server_scope, principal=self.scope.principal,
            scope_kind=scope_kind, scope_id=scope_id or "",
            harness_id=harness_id, asset_id=asset_id,
            decision=DECISION_DISABLE).layer_key
        with self.database.read() as conn:
            self._require_schema(conn)
            row = conn.execute(
                f"SELECT * FROM {ASSIGNMENTS_TABLE} WHERE "
                "server_scope=? AND principal=? AND scope_kind=? AND scope_id=?"
                " AND harness_key=? AND asset_id=?",
                key[:4] + (key[4], key[5])).fetchone()
        return SkillAssignment.from_row(row) if row is not None else None

    # -- writes ------------------------------------------------------------------

    def upsert(self, *, scope_kind: str, scope_id: str = "",
               harness_id: str | None = None, asset_id: str,
               decision: str, revision: int | None = None,
               expected_version: int | None = None,
               operation_key: str | None = None) -> dict[str, Any]:
        """assignments/upsert: set (or overwrite) exactly one layer row.

        CAS + idempotency semantics are documented at module level; the
        duplicate rule is the SQL UNIQUE index, and a guarded "create"
        (expectedVersion=0) against an existing row surfaces as the typed
        ``ASSIGNMENT_VERSION_CONFLICT`` instead of an IntegrityError.
        """
        row = SkillAssignment(
            server_scope=self.scope.server_scope, principal=self.scope.principal,
            scope_kind=scope_kind, scope_id=scope_id or "",
            harness_id=harness_id, asset_id=asset_id, decision=decision,
            revision=revision, operation_key=operation_key)
        key = row.layer_key
        timestamp = now()
        with self.database.transaction() as conn:
            self._require_schema(conn)
            replayed = self._replay(conn, operation_key)
            if replayed is not None:
                return replayed
            self._assert_asset_is_a_skill(conn, asset_id)
            if decision == DECISION_ENABLE:
                # ordered after the replay/asset checks so a retry of a
                # settled key never re-walks the filesystem gate, and an
                # unknown asset is refused before any approval lookup.
                self._assert_revision_usable(asset_id, int(revision))
            current = conn.execute(
                f"SELECT row_version FROM {ASSIGNMENTS_TABLE} "
                "WHERE server_scope=? AND principal=? AND scope_kind=?"
                " AND scope_id=? AND harness_key=? AND asset_id=?",
                key).fetchone()
            current_version = int(current["row_version"]) if current else 0
            if expected_version is not None and current_version != expected_version:
                raise AssignmentError(
                    "ASSIGNMENT_VERSION_CONFLICT",
                    f"the assignment layer is at version {current_version}, "
                    f"not {expected_version}", detail=f"{key[3] or key[2]}/{asset_id}")
            if current is None:
                conn.execute(
                    f"INSERT INTO {ASSIGNMENTS_TABLE}(server_scope,principal,"
                    "scope_kind,scope_id,harness_key,asset_id,decision,revision,"
                    "row_version,operation_key,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key[0], key[1], key[2], key[3], key[4], asset_id, decision,
                     revision, 1, operation_key, timestamp, timestamp))
            else:
                conn.execute(
                    f"UPDATE {ASSIGNMENTS_TABLE} SET decision=?, revision=?, "
                    "row_version=?, operation_key=?, updated_at=? WHERE "
                    "server_scope=? AND principal=? AND scope_kind=? AND scope_id=?"
                    " AND harness_key=? AND asset_id=?",
                    (decision, revision, current_version + 1, operation_key,
                     timestamp, *key))
            stored = conn.execute(
                f"SELECT * FROM {ASSIGNMENTS_TABLE} WHERE "
                "server_scope=? AND principal=? AND scope_kind=? AND scope_id=?"
                " AND harness_key=? AND asset_id=?",
                key).fetchone()
            result = SkillAssignment.from_row(stored).view()
            self._settle(conn, operation_key=operation_key, result=result)
        return result

    def remove(self, *, scope_kind: str, scope_id: str = "",
               harness_id: str | None = None, asset_id: str,
               expected_version: int | None = None,
               operation_key: str | None = None) -> dict[str, Any]:
        """assignments/remove: delete one layer row (back to inherit).

        Removing an absent row is the typed ``ASSIGNMENT_NOT_FOUND``, not a
        silent success; the CAS/idempotency guards behave as in upsert.
        """
        row = SkillAssignment(
            server_scope=self.scope.server_scope, principal=self.scope.principal,
            scope_kind=scope_kind, scope_id=scope_id or "",
            harness_id=harness_id, asset_id=asset_id, decision=DECISION_DISABLE)
        key = row.layer_key
        with self.database.transaction() as conn:
            self._require_schema(conn)
            replayed = self._replay(conn, operation_key)
            if replayed is not None:
                return replayed
            current = conn.execute(
                f"SELECT row_version FROM {ASSIGNMENTS_TABLE} "
                "WHERE server_scope=? AND principal=? AND scope_kind=?"
                " AND scope_id=? AND harness_key=? AND asset_id=?",
                key).fetchone()
            if current is None:
                raise AssignmentError(
                    "ASSIGNMENT_NOT_FOUND",
                    "there is no assignment row at that layer to remove",
                    detail=asset_id)
            current_version = int(current["row_version"])
            if expected_version is not None and current_version != expected_version:
                raise AssignmentError(
                    "ASSIGNMENT_VERSION_CONFLICT",
                    f"the assignment layer is at version {current_version}, "
                    f"not {expected_version}", detail=asset_id)
            conn.execute(
                f"DELETE FROM {ASSIGNMENTS_TABLE} WHERE "
                "server_scope=? AND principal=? AND scope_kind=? AND scope_id=?"
                " AND harness_key=? AND asset_id=?",
                key)
            result = {"removed": True, "layerKey": list(key),
                      "previousRowVersion": current_version}
            self._settle(conn, operation_key=operation_key, result=result)
        return result

    # -- enable-gate and asset guard ----------------------------------------------

    def _assert_revision_usable(self, asset_id: str, revision: int) -> None:
        """分配引用版本必须为已经安装、校验并批准的 revision.

        The injected :class:`RevisionGate` raises the library's typed codes
        (``SKILL_ASSET_MISSING`` / ``SKILL_APPROVAL_MISSING`` /
        ``SKILL_APPROVAL_DIGEST_MISMATCH``); without one the guarded write
        is refused outright — a missing gate never degrades to "allow
        anything" (不可用不以静默过滤达成成功).
        """
        if self.approvals is None:
            raise AssignmentError(
                "ASSIGNMENT_SCHEMA_UNAVAILABLE",
                "an enable assignment needs the revision approval gate "
                "(RevisionApprovalStore) injected")
        self.approvals.assert_usable_for_assignment(asset_id, revision)

    def _assert_asset_is_a_skill(self, conn: sqlite3.Connection,
                                 asset_id: str) -> None:
        """Assignments may only reference this domain's own `skill` rows:
        a foreign kind (or unknown id) is a typed refusal and no row is
        created (the G01 non-Skill isolation, extended to the new table).
        """
        if ASSET_ID.fullmatch(asset_id) is None:
            raise AssignmentError(
                "ASSIGNMENT_INVALID", "asset_id must be a lowercase slug")
        asset = conn.execute(
            "SELECT 1 FROM server_assets WHERE id=? AND kind=?",
            (asset_id, SKILL_KIND)).fetchone()
        if asset is None:
            raise AssignmentError(
                "ASSIGNMENT_ASSET_UNKNOWN",
                "only an installed skill asset can be assigned",
                detail=asset_id)

    # -- operation ledger ----------------------------------------------------------

    @staticmethod
    def _replay(conn: sqlite3.Connection,
                operation_key: str | None) -> dict[str, Any] | None:
        if operation_key is None:
            return None
        row = conn.execute(
            f"SELECT result_json FROM {OPERATIONS_TABLE} WHERE operation_key=?",
            (operation_key,)).fetchone()
        return json.loads(row["result_json"]) if row else None

    @staticmethod
    def _settle(conn: sqlite3.Connection, *, operation_key: str | None,
                result: Mapping[str, Any]) -> None:
        if operation_key is None:
            return
        conn.execute(
            f"INSERT OR REPLACE INTO {OPERATIONS_TABLE}"
            "(operation_key,result_json,settled_at) VALUES (?,?,?)",
            (operation_key, json.dumps(dict(result), sort_keys=True), now()))

    # -- BindingCasPort (library/records.py declares this slice its owner) ----------

    def binding_cas(self) -> "AssignmentBindingCas":
        return AssignmentBindingCas(self.database)


class AssignmentBindingCas:
    """The :class:`BindingCasPort` backed by the domain-owned tables.

    records.py's guarded binding writes (``expectedVersion`` /
    ``operationKey`` on :class:`...library.records.AssetRecords.bind /
    update_binding`) consult these methods; the version ledger is
    ``skill_binding_cas`` and the replay ledger is the same
    ``skill_assignment_operations`` table, so one operation key settles
    once across the whole skills domain ("publish + move one binding"
    retries upgrade exactly once).
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        self._store = AssignmentStore(
            database, scope=AssignmentScope(
                server_scope="__cas__", principal="__cas__"))

    def ensure_schema(self) -> None:
        self._store.ensure_schema()

    def current_version(self, profile_id: str, asset_id: str) -> int:
        with self.database.read() as conn:
            self._store._require_schema(conn)
            row = conn.execute(
                f"SELECT version FROM {BINDING_CAS_TABLE} "
                "WHERE profile_id=? AND asset_id=?",
                (profile_id, asset_id)).fetchone()
        return int(row["version"]) if row else 0

    def replay(self, operation_key: str) -> Mapping[str, Any] | None:
        with self.database.read() as conn:
            self._store._require_schema(conn)
            return AssignmentStore._replay(conn, operation_key)

    def settle(self, *, operation_key: str, profile_id: str, asset_id: str,
               version: int, result: Mapping[str, Any]) -> None:
        with self.database.transaction() as conn:
            self._store._require_schema(conn)
            conn.execute(
                f"INSERT INTO {BINDING_CAS_TABLE}(profile_id,asset_id,version) "
                "VALUES (?,?,?) ON CONFLICT(profile_id,asset_id) DO UPDATE "
                "SET version=excluded.version",
                (profile_id, asset_id, int(version)))
            AssignmentStore._settle(conn, operation_key=operation_key,
                                    result=result)
