"""Asset records and per-Profile bindings (records.py).

Ported from `plugins/assets/src/ordessa_assets/server/records.py`
@ 752f148b1b, keeping the legacy read-then-write binding shape and the
camelCase wire views (wire-compat.md §4 red lines; legacy-inventory.md §B.2).

Row IDs, table names and digest spellings are the legacy ones
(`server_assets`, `server_profile_assets`) so the disk story survives the
migration unchanged — and this module uses **only the columns those tables
already have**; it never adds or requires a schema change (AGENTS.md rule 5).

Two things the legacy module did not enforce, both required of the Skills
domain here:

* **Other kinds are foreign rows.** plan.md 原有 Assets-Skill 迁移: 旧表其他
  kind 由迁移账指定旧业务所有者，不能由 Skills 清空. Every write this module
  issues is guarded to `kind='skill'` in SQL itself (not just in Python), so
  an `mcp`/`command`/`plugin` row can be neither written nor deleted here, and
  a binding to a non-Skill asset is neither listed nor removed.
  verification.md G01 counter-example 「非 Skill 行被修改」.
* **The new CAS guard.** data-model.md §内容与版本: 更新已启用范围时明确挑选
  目标修订并写 CAS/操作键；重试不能重复升级. `expected_version` +
  `operation_key` are accepted on the binding writes and delegated to an
  injected :class:`BindingCasPort`; the CAS table itself belongs to the
  assignments slice (T05), so it is a port, never a column of `server_assets`.
  Without a port injected the legacy read-then-write shape is used verbatim
  (review-record MINOR: the legacy two-phase TOCTOU is accepted as-is).

  The accepted-as-is shape stays reachable ONLY for deliberate in-process
  library callers; three facts make that safe and are pinned by tests:
  (1) no wire method routes to `bind`/`update_binding` at all — the wire
  binding writes are `skills.assignmentsUpsert/Remove`, which go through
  :class:`...assignments.store.AssignmentStore` and its own CAS ledger
  (pin: `tests/test_binding_cas.py::
  test_the_unguarded_records_writes_are_unreachable_from_the_wire`);
  (2) presenting `expectedVersion`/`operationKey` without a port is a typed
  refusal (`BINDING_CAS_UNAVAILABLE`), never a silent downgrade;
  (3) a replayed legacy `update_binding` whose logical change is already in
  the row is a NO-OP — it returns the current view without a second write,
  so "重试不能重复升级" holds on this path too (pin: `tests/
  test_binding_cas.py::test_a_replayed_legacy_update_is_a_no_op_not_a_second_upgrade`).
  A per-call mandatory opt-in kwarg would change the legacy call shape that
  wire-compat.md §4 red-lines (review-record MINOR accepts it verbatim), so
  the explicitness lives in these pins, not in a new required parameter.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, runtime_checkable
from uuid import uuid4

from pacthold_runtime_compat.storage import Database

from ..api.errors import AssetDomainError, BindingError
from ..api.identity import ASSET_KINDS

_ASSET_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")

#: The only kind this domain may publish; the other `ASSET_KINDS` values stay
#: with their old business owners (see module docstring).
SKILL_KIND = "skill"

#: `server_profile_assets` rows whose asset is a Skill — the guard every
#: binding write is filtered through, expressed in SQL rather than in Python.
_SKILL_ASSET_SQL = (
    "EXISTS (SELECT 1 FROM server_assets a "
    "WHERE a.id=server_profile_assets.asset_id AND a.kind=?)")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def opaque_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def asset_view(row: Any) -> dict[str, Any]:
    """The wire-facing catalogue shape (no content, no host paths)."""
    return {
        "assetId": row["id"],
        "kind": row["kind"],
        "name": row["name"],
        "description": row["description"],
        "latestRevision": int(row["latest_revision"]),
        "digest": row["digest"],
        "source": row["source"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


@runtime_checkable
class BindingCasPort(Protocol):
    """Row-version + operation-key ledger for the guarded binding writes.

    The Skills content library owns the asset rows; the *versions* a compare
    -and-set write needs do not live in `server_assets`/`server_profile_assets`
    (shared schema, C0 review needed — AGENTS.md rule 5), so the assignments
    slice (plan.md T05) supplies this port and owns its table. Implementation
    requirements:

    * `current_version` returns the monotonic version of one
      `(profile_id, asset_id)` pair, `0` when it has never been written.
    * `replay` returns a previously settled result for an operation key, or
      `None` when the key is new — this is what makes a retry of a
      "publish a new revision and move one binding" flow upgrade once.
    * `settle` records the outcome of a write that was applied.
    """

    def current_version(self, profile_id: str, asset_id: str) -> int: ...

    def replay(self, operation_key: str) -> Mapping[str, Any] | None: ...

    def settle(self, *, operation_key: str, profile_id: str, asset_id: str,
               version: int, result: Mapping[str, Any]) -> None: ...


class AssetRecords:
    def __init__(self, database: Database, cas: BindingCasPort | None = None) -> None:
        self.database = database
        self.cas = cas

    def publish(
        self, *, kind: str, name: str, revision: int, digest: str,
        description: str | None = None, source: str | None = None,
        asset_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Register one installed revision, creating the asset row on first use.

        The digest is required: an asset without a digest could not be
        verified when it is projected. Publishing never touches bindings.
        """
        if kind not in ASSET_KINDS or not name or not digest.startswith("sha256:"):
            raise AssetDomainError(
                "ASSET_INVALID", "an asset needs a kind, a name and a digest")
        if kind != SKILL_KIND:
            # Owned by another domain's migration account; this module may not
            # write it even when asked to.
            raise AssetDomainError(
                "ASSET_KIND_NOT_SKILL",
                f"kind {kind!r} is not owned by the skills domain")
        if revision < 1:
            raise AssetDomainError("ASSET_INVALID", "revision must be >= 1")
        timestamp = now()
        with self.database.transaction() as conn:
            row = None
            if asset_id is not None:
                if _ASSET_ID.fullmatch(asset_id) is None:
                    raise AssetDomainError(
                        "ASSET_INVALID", "asset_id must be a lowercase slug")
                row = conn.execute(
                    "SELECT * FROM server_assets WHERE id=? AND kind=?",
                    (asset_id, SKILL_KIND)).fetchone()
                if row is None and conn.execute(
                        "SELECT 1 FROM server_assets WHERE id=?",
                        (asset_id,)).fetchone() is not None:
                    raise AssetDomainError(
                        "ASSET_KIND_NOT_SKILL",
                        "that asset id belongs to another kind", detail=asset_id)
            if row is None:
                if asset_id is None:
                    asset_id = opaque_id("asset")
                conn.execute(
                    "INSERT INTO server_assets(id,kind,name,description,latest_revision,"
                    "digest,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (asset_id, SKILL_KIND, name, description, revision, digest, source,
                     timestamp, timestamp))
            else:
                # `AND kind=?` in SQL: a concurrent rewrite of this id into
                # another kind can never be clobbered from here.
                moved = conn.execute(
                    "UPDATE server_assets SET kind=?,name=?,description=?,latest_revision=?,"
                    "digest=?,source=COALESCE(?,source),updated_at=? WHERE id=? AND kind=?",
                    (SKILL_KIND, name, description, revision, digest, source, timestamp,
                     asset_id, SKILL_KIND))
                if moved.rowcount != 1:
                    raise AssetDomainError(
                        "ASSET_KIND_NOT_SKILL",
                        "that asset id belongs to another kind", detail=asset_id)
            return "published", self._view(conn, asset_id)

    def get(self, asset_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT * FROM server_assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise AssetDomainError("ASSET_NOT_FOUND", "Asset was not found")
        return dict(row)

    def list(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        """Catalogue rows; `kind=None` keeps the legacy all-kinds listing."""
        with self.database.read() as conn:
            if kind is None:
                rows = conn.execute(
                    "SELECT * FROM server_assets ORDER BY kind,name,id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM server_assets WHERE kind=? ORDER BY kind,name,id",
                    (kind,)).fetchall()
        return [dict(row) for row in rows]

    def bind(self, *, profile_id: str, asset_id: str, revision: int | None = None,
             enabled: bool = True, expected_version: int | None = None,
             operation_key: str | None = None) -> dict[str, Any]:
        """Bind a Skill to a Profile, pinning an explicit revision.

        Omitted revision pins the latest published one *at bind time*; once
        pinned, nothing but an explicit update moves it (D1).

        `expected_version`/`operation_key` route the write through the
        injected :class:`BindingCasPort`; without one they are a typed
        refusal rather than a silent downgrade to the unguarded shape.
        """
        guard = self._cas_guard(
            profile_id=profile_id, asset_id=asset_id,
            expected_version=expected_version, operation_key=operation_key)
        if guard is not None:
            return guard
        with self.database.read() as conn:
            asset = conn.execute(
                "SELECT * FROM server_assets WHERE id=? AND kind=?",
                (asset_id, SKILL_KIND)).fetchone()
        if asset is None:
            raise BindingError("ASSET_NOT_FOUND", "Asset was not found")
        chosen = int(asset["latest_revision"]) if revision is None else revision
        if chosen <= 0 or chosen > int(asset["latest_revision"]):
            raise BindingError("ASSET_REVISION_UNKNOWN", "that revision is not published")
        timestamp = now()
        with self.database.transaction() as conn:
            if conn.execute(
                    "SELECT 1 FROM server_profiles WHERE id=?",
                    (profile_id,)).fetchone() is None:
                raise BindingError("PROFILE_NOT_FOUND", "Profile was not found")
            # Re-checked against the table inside the write transaction: this
            # module only ever creates a binding row for a `kind='skill'`
            # asset, whatever the caller's id happens to point at.
            if conn.execute(
                    "SELECT 1 FROM server_assets WHERE id=? AND kind=?",
                    (asset_id, SKILL_KIND)).fetchone() is None:
                raise BindingError("ASSET_NOT_FOUND", "Asset was not found")
            conn.execute(
                "INSERT INTO server_profile_assets(profile_id,asset_id,revision,enabled,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(profile_id,asset_id) DO UPDATE SET revision=?,enabled=?,"
                "updated_at=? WHERE " + _SKILL_ASSET_SQL,
                (profile_id, asset_id, chosen, 1 if enabled else 0, timestamp, timestamp,
                 chosen, 1 if enabled else 0, timestamp, SKILL_KIND))
            result = self._binding_view(conn, profile_id, asset_id)
        self._cas_settle(
            profile_id=profile_id, asset_id=asset_id,
            expected_version=expected_version, operation_key=operation_key,
            result=result)
        return result

    def update_binding(self, *, profile_id: str, asset_id: str, revision: int,
                       enabled: bool | None = None,
                       expected_version: int | None = None,
                       operation_key: str | None = None) -> dict[str, Any]:
        """The explicit "update to this version" act (D1's upgrade path).

        With an injected :class:`BindingCasPort` the operation key replays
        settled results and a stale `expected_version` is refused. Without
        one this is the LEGACY-COMPAT call shape (review-record MINOR,
        wire-compat.md §4): reachable only from in-process library code —
        no wire method routes here — CAS args without a port are refused
        (`BINDING_CAS_UNAVAILABLE`) and a replay of a change the row
        already holds is a no-op, never a second upgrade.
        """
        guard = self._cas_guard(
            profile_id=profile_id, asset_id=asset_id,
            expected_version=expected_version, operation_key=operation_key)
        if guard is not None:
            return guard
        with self.database.read() as conn:
            asset = conn.execute(
                "SELECT latest_revision, kind FROM server_assets WHERE id=?",
                (asset_id,)).fetchone()
            binding = conn.execute(
                "SELECT * FROM server_profile_assets WHERE profile_id=? AND asset_id=?",
                (profile_id, asset_id)).fetchone()
        if asset is None:
            raise BindingError("ASSET_NOT_FOUND", "Asset was not found")
        if str(asset["kind"]) != SKILL_KIND:
            raise BindingError("ASSET_KIND_NOT_SKILL",
                               "that binding belongs to another kind")
        if binding is None:
            raise BindingError("BINDING_NOT_FOUND", "that binding does not exist")
        if revision <= 0 or revision > int(asset["latest_revision"]):
            raise BindingError("ASSET_REVISION_UNKNOWN", "that revision is not published")
        enabled_value = int(binding["enabled"]) if enabled is None else \
            (1 if enabled else 0)
        if self.cas is None and int(binding["revision"]) == revision \
                and int(binding["enabled"]) == enabled_value:
            # Replay guard on the legacy (port-less) shape: the logical
            # change is already in the row, so a repeated update is a NO-OP
            # — no second write, no second timestamp bump (data-model.md:
            # 重试不能重复升级). With a port the operation key settles and
            # replays through `_cas_guard` above instead; that shape is
            # untouched here.
            with self.database.read() as conn:
                return self._binding_view(conn, profile_id, asset_id)
        timestamp = now()
        with self.database.transaction() as conn:
            moved = conn.execute(
                "UPDATE server_profile_assets SET revision=?,enabled=?,updated_at=? "
                f"WHERE profile_id=? AND asset_id=? AND asset_id IN "
                f"(SELECT id FROM server_assets WHERE kind=?)",
                (revision, enabled_value, timestamp, profile_id, asset_id, SKILL_KIND))
            if moved.rowcount != 1:
                raise BindingError("BINDING_NOT_FOUND", "that binding does not exist")
            result = self._binding_view(conn, profile_id, asset_id)
        self._cas_settle(
            profile_id=profile_id, asset_id=asset_id,
            expected_version=expected_version, operation_key=operation_key,
            result=result)
        return result

    def unbind(self, *, profile_id: str, asset_id: str) -> None:
        with self.database.transaction() as conn:
            removed = conn.execute(
                "DELETE FROM server_profile_assets WHERE profile_id=? AND asset_id=? "
                f"AND {_SKILL_ASSET_SQL}",
                (profile_id, asset_id, SKILL_KIND))
            if removed.rowcount != 1:
                raise BindingError("BINDING_NOT_FOUND", "that binding does not exist")

    def bindings(self, profile_id: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            rows = conn.execute(
                "SELECT b.*,a.kind,a.name,a.digest FROM server_profile_assets b "
                "JOIN server_assets a ON a.id=b.asset_id WHERE b.profile_id=? "
                "AND a.kind=? "
                + ("AND b.enabled=1 " if enabled_only else "")
                + "ORDER BY a.kind,a.name",
                (profile_id, SKILL_KIND)).fetchall()
        return [self._binding_row(row) for row in rows]

    def _cas_guard(self, *, profile_id: str, asset_id: str,
                   expected_version: int | None,
                   operation_key: str | None) -> dict[str, Any] | None:
        """Resolve a CAS-guarded write before it reaches the legacy shape.

        Returns the replayed result when an operation key was already
        settled (a retry must not upgrade twice), `None` to continue.
        """
        if expected_version is None and operation_key is None:
            return None
        if self.cas is None:
            raise BindingError(
                "BINDING_CAS_UNAVAILABLE",
                "expectedVersion/operationKey need a binding CAS port")
        if operation_key is not None:
            replayed = self.cas.replay(operation_key)
            if replayed is not None:
                return dict(replayed)
        if expected_version is not None:
            current = self.cas.current_version(profile_id, asset_id)
            if current != expected_version:
                raise BindingError(
                    "BINDING_VERSION_CONFLICT",
                    f"the binding is at version {current}, not {expected_version}",
                    detail=f"{profile_id}/{asset_id}")
        return None

    def _cas_settle(self, *, profile_id: str, asset_id: str,
                    expected_version: int | None, operation_key: str | None,
                    result: Mapping[str, Any]) -> None:
        if operation_key is None or self.cas is None:
            return
        version = self.cas.current_version(profile_id, asset_id)
        self.cas.settle(operation_key=operation_key, profile_id=profile_id,
                        asset_id=asset_id, version=version + 1, result=dict(result))

    def _view(self, conn, asset_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM server_assets WHERE id=?", (asset_id,)).fetchone()
        return {
            "asset_id": row["id"],
            "kind": row["kind"],
            "name": row["name"],
            "description": row["description"],
            "latest_revision": int(row["latest_revision"]),
            "digest": row["digest"],
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _binding_view(self, conn, profile_id: str, asset_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT b.*,a.kind,a.name,a.digest FROM server_profile_assets b "
            "JOIN server_assets a ON a.id=b.asset_id "
            "WHERE b.profile_id=? AND b.asset_id=?",
            (profile_id, asset_id)).fetchone()
        return self._binding_row(row)

    @staticmethod
    def _binding_row(row: Any) -> dict[str, Any]:
        return {
            "assetId": row["asset_id"],
            "kind": row["kind"],
            "name": row["name"],
            "revision": int(row["revision"]),
            "digest": row["digest"],
            "enabled": bool(row["enabled"]),
        }
