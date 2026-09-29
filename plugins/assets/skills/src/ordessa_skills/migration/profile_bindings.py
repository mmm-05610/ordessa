"""Dry-run-first migration of legacy Profile skill bindings (tasks.md T07).

Scope of this module (docs/design/skills-v2/data-model.md §存储升级;
verification.md G08/G09):

    `server_profile_assets` 现有固定修订绑定保留；把它转成 Profile
    `enable(revision)` 的迁移必须有字节/ID 样本和回滚验证。

The Profile facet `assets.skills` itself (contracts.md §Profile / Workspace /
Settings: per Skill `inherit | enable(revision) | disable`, Profile 专用内容
只保存引用) has **no published storage yet** — its read/write seam is the
open request §G3 of `specs/011-q1-skills/api-requests.md` (Z1). What is
implementable now, and what this module ships, is the *migration engine*:
plan / apply / verify / rollback over the tables this package already owns,
in an **additive/parallel** shape:

* `plan()` is strictly read-only. It classifies every legacy binding row
  (`migrate | skip | refuse:<reason>`) and digests the outcome.
* `apply()` writes only into `skill_assignments` — a domain table owned by
  :mod:`ordessa_skills.assignments.store` — through the public
  :class:`~ordessa_skills.assignments.store.AssignmentStore` API, so the
  store's own guards (kind='skill' SQL guard, RevisionGate approval check,
  UNIQUE layer index, operation-key idempotency ledger) all apply to the
  migrated rows exactly as to user writes. `server_profile_assets` rows are
  **byte-identical afterwards**: the old table stays authoritative history
  until Z1 publishes the real facet and the retirement ledger (C0,
  docs/migration/) takes it over — the switch of authority is NOT performed
  here.
* The migrated rows live in a partitioned evidence namespace:
  ``principal = "profile:<profileId>"``, ``scope_kind = user_global``,
  ``harness_key = "*"``. The resolver filters rows by
  (server_scope, principal), so this namespace never leaks into any live
  principal's assignment chain (G07) while still being resolvable verbatim
  as the Profile layer's `enable(revision) / disable` entries — which is
  what :func:`verify` and the G08 equivalence test consume. When Z1's facet
  lands, this namespace's rows are moved to the facet storage by the
  integration wave; nothing outside this module depends on the encoding.
* G08's three counter-examples are enforced, not hoped for:
  固定版变追最新 — an `enabled=1` binding only ever maps to
  ``enable(pinned revision)``; an uninstalled/unapproved pin is classified
  ``refuse:revision_unapproved`` and NEVER resolved up or down to another
  revision (:meth:`plan` never guesses);
  已禁用项变启用 — ``enabled=0`` maps to ``disable`` and nothing else;
  迁移重跑双写 — the same operation key with the same plan identity (the
  ledger's recorded planDigest AND serverScope) replays with zero effect;
  a *different* plan presented under a settled key is refused
  ``MIGRATION_PLAN_STALE``, never reported as a replay of a write it never
  made; a *different* key re-apply finds every layer already at the plan
  intent and writes nothing (the UNIQUE layer index makes a second
  logical row impossible anyway).
* User-data safety (AGENTS.md rule 5; plan.md 原有 Assets-Skill 迁移: 数据
  变更先在合成数据根…dry-run…若需要修改真实用户数据，另给备份/恢复和用户
  确认): what is actually ENFORCED here is only a path-shape rule —
  :func:`apply` and :func:`rollback` refuse any data root that does not
  resolve underneath ``tempfile.gettempdir()`` unless the caller passes
  ``allow_user_data=True``. That flag is an **unverified caller
  assertion**: the module validates no backup/rollback evidence and no
  user confirmation record when it is set; collecting that evidence for
  real roots remains an out-of-band (human) duty the flag stands for,
  not something this code checks.

G09 note: this file proves the **rollback half** of T07's evidence (exact
removal of one operation plus byte-identity of the legacy table). G09's own
cell (会话覆盖下一次提交生效) needs Z1's session item-override mechanism
(§G3(b)) and stays blocked; the session-override *mapping* tests already in
test_assignments_tristate_g06.py cover only the injected-port shape.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pacthold_runtime_compat.storage import Database

from ..api.errors import AssetDomainError
from ..assignments.model import (
    ANY_HARNESS,
    DECISION_DISABLE,
    DECISION_ENABLE,
    SCOPE_USER_GLOBAL,
)
from ..assignments.ports import ProfileSkillEntry, RevisionGate
from ..assignments.store import (
    ASSIGNMENTS_TABLE,
    OPERATIONS_TABLE,
    AssignmentScope,
    AssignmentStore,
)
from ..library.records import SKILL_KIND

#: Plan classifications, verbatim of the shape ``migrate | skip | refuse:*``
#: required by the T07 work order.
CLASSIFY_MIGRATE = "migrate"
SKIP_FOREIGN_KIND = "skip:foreign_kind"
SKIP_ALREADY_MIGRATED = "skip:already_migrated"
REFUSE_UNAPPROVED = "refuse:revision_unapproved"
REFUSE_NO_GATE = "refuse:no_approval_gate"
REFUSE_PROFILE_UNKNOWN = "refuse:profile_unknown"

#: Placeholder data-domain identity until §G5's serverScope injection lands
#: (api-requests.md: serverScope = 该 Server 数据根实例身份). A plan stamps
#: it into every entry, so a plan built under one scope can only be applied
#: under that scope.
DEFAULT_SERVER_SCOPE = "srv:migration-placeholder"


class MigrationError(AssetDomainError):
    """One migration operation was refused (codes registered here, once:
    ``MIGRATION_INVALID_OPERATION_KEY``, ``MIGRATION_PLAN_STALE``,
    ``MIGRATION_PLAN_HAS_REFUSALS``,
    ``MIGRATION_USER_DATA_CONFIRMATION_REQUIRED``,
    ``MIGRATION_OPERATION_UNKNOWN``, ``MIGRATION_VERIFY_MISMATCH``,
    ``MIGRATION_ROLLBACK_ROW_DRIFT``).
    """


def profile_principal(profile_id: str) -> str:
    """The partitioned evidence principal for one Profile's migrated facet
    rows — see module docstring for why this is the Profile layer's own
    namespace and not any live user's."""
    return f"profile:{profile_id}"


# -- plan ----------------------------------------------------------------------


@dataclass(frozen=True)
class MigrationEntry:
    """One classified legacy binding row and its intended target entry."""

    profile_id: str
    asset_id: str
    kind: str
    source_revision: int
    source_enabled: int
    classification: str
    target_decision: str | None
    target_revision: int | None
    #: the legacy row's mutable identity at plan time: "revision|enabled".
    #: apply() re-reads it and refuses when it moved (version guard).
    source_signature: str
    #: row_version of the intended target layer at plan time (0 == absent,
    #: i.e. "creation intent" in the store's CAS vocabulary).
    layer_version: int

    def view(self) -> dict[str, Any]:
        return {
            "profileId": self.profile_id,
            "assetId": self.asset_id,
            "kind": self.kind,
            "sourceRevision": self.source_revision,
            "sourceEnabled": self.source_enabled,
            "classification": self.classification,
            "target": None if self.target_decision is None else {
                "decision": self.target_decision,
                "revision": self.target_revision,
            },
            "sourceSignature": self.source_signature,
            "layerVersion": self.layer_version,
        }


@dataclass(frozen=True)
class MigrationPlan:
    server_scope: str
    profile_filter: str | None
    entries: tuple[MigrationEntry, ...]
    digest: str

    @property
    def migratable(self) -> tuple[MigrationEntry, ...]:
        return tuple(e for e in self.entries
                     if e.classification == CLASSIFY_MIGRATE)

    @property
    def refused(self) -> tuple[MigrationEntry, ...]:
        return tuple(e for e in self.entries
                     if e.classification.startswith("refuse"))

    def view(self) -> dict[str, Any]:
        return {
            "serverScope": self.server_scope,
            "profileFilter": self.profile_filter,
            "digest": self.digest,
            "entries": [e.view() for e in self.entries],
        }


def _digest_of(server_scope: str, profile_filter: str | None,
               entries: tuple[MigrationEntry, ...]) -> str:
    """Identity of a plan: the partition it was built to write (server
    scope + profile filter) is part of the digest, so two plans over the
    same rows but different partitions never share an identity — and a
    settled operation can recognise "this incoming plan is NOT the one I
    applied"."""
    payload = json.dumps({
        "serverScope": server_scope,
        "profileFilter": profile_filter,
        "entries": [e.view() for e in entries],
    }, sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _binding_rows(database: Database, profile_id: str | None) -> list[Any]:
    """Every legacy binding joined to its asset kind — foreign kinds stay
    visible here precisely so they can be classified ``skip`` and proven
    untouched; they are never migrated, never written, never removed."""
    sql = ("SELECT b.profile_id AS profile_id, b.asset_id AS asset_id,"
           " b.revision AS revision, b.enabled AS enabled,"
           " a.kind AS kind, a.latest_revision AS latest_revision"
           " FROM server_profile_assets b"
           " JOIN server_assets a ON a.id = b.asset_id")
    params: tuple = ()
    if profile_id is not None:
        sql += " WHERE b.profile_id = ?"
        params = (profile_id,)
    sql += " ORDER BY b.profile_id, b.asset_id"
    with database.read() as conn:
        return [dict(row) for row in conn.execute(sql, params)]


def _known_profiles(database: Database) -> set[str]:
    with database.read() as conn:
        return {str(row["id"]) for row in
                conn.execute("SELECT id FROM server_profiles")}


def _layer_state(database: Database, *, server_scope: str, profile_id: str,
                 asset_id: str) -> tuple[int, str | None, int | None]:
    """(row_version, decision, revision) of the intended target layer — a
    raw read; plan() must never touch the store's schema-creating API."""
    with database.read() as conn:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (ASSIGNMENTS_TABLE,)).fetchone()
        if present is None:
            return 0, None, None
        row = conn.execute(
            f"SELECT row_version, decision, revision FROM {ASSIGNMENTS_TABLE}"
            " WHERE server_scope=? AND principal=? AND scope_kind=?"
            " AND scope_id='' AND harness_key=? AND asset_id=?",
            (server_scope, profile_principal(profile_id), SCOPE_USER_GLOBAL,
             ANY_HARNESS, asset_id)).fetchone()
    if row is None:
        return 0, None, None
    return int(row["row_version"]), str(row["decision"]), \
        None if row["revision"] is None else int(row["revision"])


def plan(database: Database, *, profile_id: str | None = None,
         server_scope: str = DEFAULT_SERVER_SCOPE,
         approvals: RevisionGate | None = None) -> MigrationPlan:
    """Read-only migration plan over `server_profile_assets` (T07 dry-run).

    Per-row classification (never a silent rewrite of intent):

    * asset kind != 'skill'            -> ``skip:foreign_kind``
    * enabled=0                          -> ``migrate`` to ``disable``
      (counter-example 2: a disabled item must not become enabled)
    * enabled=1, pinned revision passes the RevisionGate (installed,
      digest-verified, approved) -> ``migrate`` to ``enable(revision)``
      pinned at exactly that revision (counter-example 1: never re-pointed
      at "latest")
    * enabled=1, gate refuses          -> ``refuse:revision_unapproved``
      with the gate's code as detail — NOT resolved up or down
    * enabled=1 without an injected gate -> ``refuse:no_approval_gate``
      (不可用不以静默过滤达成成功: no gate means no guess)
    * the binding's profile row is absent   -> ``refuse:profile_unknown``
    * target layer already holds exactly the intent -> ``skip:already_migrated``
      (this is what a re-run of the plan after an apply reports)

    This function opens read transactions only; it writes nothing, ever.
    """
    known_profiles = _known_profiles(database)
    entries: list[MigrationEntry] = []
    for row in _binding_rows(database, profile_id):
        asset_id = str(row["asset_id"])
        pid = str(row["profile_id"])
        revision = int(row["revision"])
        enabled = int(row["enabled"])
        kind = str(row["kind"])
        signature = f"{revision}|{enabled}"

        if kind != SKILL_KIND:
            # Foreign kinds stay with their old business owners (plan.md
            # 原有 Assets-Skill 迁移); Skills neither writes, removes nor
            # even probes a target layer for them.
            entries.append(MigrationEntry(
                pid, asset_id, kind, revision, enabled, SKIP_FOREIGN_KIND,
                None, None, signature, 0))
            continue

        def refuse(reason: str) -> None:
            entries.append(MigrationEntry(
                pid, asset_id, kind, revision, enabled, reason,
                None, None, signature,
                _layer_state(database, server_scope=server_scope,
                             profile_id=pid, asset_id=asset_id)[0]))

        if pid not in known_profiles:
            refuse(REFUSE_PROFILE_UNKNOWN)
            continue
        if enabled == 0:
            # counter-example 2: a disabled item migrates to a pure
            # `disable` row — it can never become an enable.
            decision: str = DECISION_DISABLE
            target_revision: int | None = None
        elif approvals is None:
            refuse(REFUSE_NO_GATE)
            continue
        else:
            try:
                approvals.assert_usable_for_assignment(asset_id, revision)
            except AssetDomainError:
                # counter-example 1: an uninstalled/unapproved pinned
                # revision is refused with a type — never resolved to
                # "latest", never downgraded to the last approved one.
                refuse(REFUSE_UNAPPROVED)
                continue
            decision, target_revision = DECISION_ENABLE, revision

        layer_version, current_decision, current_revision = _layer_state(
            database, server_scope=server_scope, profile_id=pid,
            asset_id=asset_id)
        classification = (
            SKIP_ALREADY_MIGRATED
            if (current_decision == decision and
                current_revision == target_revision)
            else CLASSIFY_MIGRATE)
        entries.append(MigrationEntry(
            pid, asset_id, kind, revision, enabled, classification,
            decision, target_revision, signature, layer_version))

    frozen = tuple(entries)
    return MigrationPlan(server_scope=server_scope, profile_filter=profile_id,
                         entries=frozen,
                         digest=_digest_of(server_scope, profile_id, frozen))


# -- user-data guard ------------------------------------------------------------


def _is_synthetic_root(database: Database) -> bool:
    """True only when the root is a path that resolves STRICTLY under
    ``tempfile.gettempdir()`` (the temp dir itself is not synthetic).
    This is a path-shape probe, nothing more: it reads no backup evidence
    and cannot tell a synthetic root from a user root someone symlinked
    into /tmp."""
    root = Path(str(getattr(database, "data_root", ""))).resolve()
    tmp = Path(tempfile.gettempdir()).resolve()
    return bool(str(root)) and root != tmp and tmp in root.parents


def _require_writable_root(database: Database, *, allow_user_data: bool
                           ) -> None:
    """apply/rollback refuse any data root outside
    ``tempfile.gettempdir()`` unless ``allow_user_data=True``.

    What is enforced is exactly that path rule. ``allow_user_data=True``
    is an UNVERIFIED caller assertion — this module validates no backup
    evidence, no rollback evidence and no user-confirmation record when
    the flag is set; it merely stops second-guessing the caller's claim
    that those (out-of-band, AGENTS.md rule 5) prerequisites exist for
    this root."""
    if allow_user_data or _is_synthetic_root(database):
        return
    raise MigrationError(
        "MIGRATION_USER_DATA_CONFIRMATION_REQUIRED",
        "the data root is not under the system temp dir; the default "
        "refusal is a path-shape rule only, and running the migration "
        "against a real user root additionally requires the documented "
        "backup/rollback evidence and explicit user confirmation "
        "(AGENTS.md rule 5; plan.md 原有 Assets-Skill 迁移) — collected "
        "out-of-band and asserted, not verified, by allow_user_data=True",
        detail=str(getattr(database, "data_root", "")))


# -- apply ----------------------------------------------------------------------


def apply(database: Database, plan: MigrationPlan, *, operation_key: str,
          expected_row_version: int | None = None,
          approvals: RevisionGate | None = None,
          allow_user_data: bool = False) -> dict[str, Any]:
    """Write the plan's ``migrate`` entries into the assignments domain
    tables, idempotently, leaving `server_profile_assets` byte-identical.

    Guards, in order:

    1. synthetic-root guard (see :func:`_require_writable_root`);
    2. **replay** — the master ``operation_key`` already settled in
       ``skill_assignment_operations`` returns the recorded result and
       applies nothing again (counter-example 3, same-key half; the store's
       per-row sub keys carry the same ledger semantics for row writes).
       A replay is only recognised when the stored ``planDigest`` AND
       ``serverScope`` equal the incoming plan's: the same operation key
       under a *different* plan or data partition is NOT a replay — it is
       a second, never-applied write wearing an old identity, and is
       refused with ``MIGRATION_PLAN_STALE``;
    3. plan integrity — the scope, partition and entry views must re-hash
       to the plan digest (a tampered or mutated document is refused);
    4. refusals — a plan containing ``refuse:*`` rows is refused outright
       (``MIGRATION_PLAN_HAS_REFUSALS``); nothing is migrated "except the
       bad ones" behind the operator's back;
    5. **version guard** — each skill row's legacy signature and target
       layer version are re-read; a concurrent change to *either* is
       ``MIGRATION_PLAN_STALE`` unless the layer already holds exactly the
       plan intent, in which case the row is skipped (no second write —
       counter-example 3, different-key half). When
       ``expected_row_version`` is supplied it must additionally equal the
       current target row_version (explicit CAS), enforced again inside the
       store's own ``ASSIGNMENT_VERSION_CONFLICT`` check.

    Every write goes through :meth:`AssignmentStore.upsert`, so the
    kind='skill' SQL guard and the approval gate re-apply at write time.
    """
    if not operation_key:
        raise MigrationError(
            "MIGRATION_INVALID_OPERATION_KEY",
            "apply needs a non-empty operation key for idempotency")
    _require_writable_root(database, allow_user_data=allow_user_data)

    settled = _ledger_get(database, operation_key)
    if settled is not None:
        if (str(settled.get("planDigest") or "") != plan.digest
                or str(settled.get("serverScope") or "") != plan.server_scope):
            # The key is settled for a DIFFERENT plan/partition: replaying
            # it would report the incoming plan as applied although nothing
            # of it was ever written (MAJOR-1 counter-example).
            raise MigrationError(
                "MIGRATION_PLAN_STALE",
                "operation key is already settled for another plan "
                "(plan digest or server scope mismatch); the incoming plan "
                "was NOT applied — rebuild it under the settled plan's own "
                "scope, or use a fresh operation key",
                detail=f"{operation_key}: settled "
                       f"{settled.get('serverScope')!r}/"
                       f"{settled.get('planDigest')} != incoming "
                       f"{plan.server_scope!r}/{plan.digest}")
        settled = dict(settled)
        settled["replayed"] = True
        return settled

    if _digest_of(plan.server_scope, plan.profile_filter, plan.entries) \
            != plan.digest:
        raise MigrationError(
            "MIGRATION_PLAN_STALE",
            "the plan document does not match its own digest; rebuild it "
            "with plan() before applying", detail=plan.digest)
    if plan.refused:
        raise MigrationError(
            "MIGRATION_PLAN_HAS_REFUSALS",
            "the plan contains refused rows; resolve the underlying "
            "install/approval state (never by silently picking another "
            "revision) and re-plan",
            detail=", ".join(f"{e.profile_id}/{e.asset_id}:{e.classification}"
                             for e in plan.refused))

    signatures = _legacy_signatures(database)
    divergences: list[str] = []
    writes: list[tuple[int, MigrationEntry]] = []
    skipped: list[str] = []
    for index, entry in enumerate(plan.entries):
        if entry.kind != SKILL_KIND:
            continue  # foreign rows: not touched, not even re-read for state
        if signatures.get(f"{entry.profile_id}|{entry.asset_id}") != \
                entry.source_signature:
            divergences.append(
                f"legacy binding {entry.profile_id}/{entry.asset_id} moved "
                "since the plan was built")
            continue
        if entry.classification != CLASSIFY_MIGRATE:
            continue  # skip:already_migrated / skip:foreign_kind — write nothing
        row_version, decision, revision = _layer_state(
            database, server_scope=plan.server_scope, profile_id=entry.profile_id,
            asset_id=entry.asset_id)
        intent_met = (decision == entry.target_decision and
                      revision == entry.target_revision)
        if intent_met and (expected_row_version is None or
                           row_version == expected_row_version):
            skipped.append(f"{entry.profile_id}/{entry.asset_id}")
            continue
        if row_version != entry.layer_version or (
                expected_row_version is not None
                and row_version != expected_row_version):
            divergences.append(
                f"target layer {entry.profile_id}/{entry.asset_id} is at "
                f"version {row_version}, not the planned "
                f"{entry.layer_version}"
                + (f"/{expected_row_version} explicit"
                   if expected_row_version is not None else ""))
            continue
        writes.append((index, entry))
    if divergences:
        raise MigrationError(
            "MIGRATION_PLAN_STALE",
            "concurrent change detected between plan and apply; rebuild the "
            "plan", detail="; ".join(divergences))

    targets: list[dict[str, Any]] = []
    written_views: list[dict[str, Any]] = []
    stores: dict[str, AssignmentStore] = {}

    def store_for(profile_id: str) -> AssignmentStore:
        if profile_id not in stores:
            stores[profile_id] = AssignmentStore(
                database,
                scope=AssignmentScope(server_scope=plan.server_scope,
                                      principal=profile_principal(profile_id)),
                approvals=approvals)
        return stores[profile_id]

    if plan.entries:
        store_for(plan.entries[0].profile_id).ensure_schema()
    else:
        _ensure_schema_once(database, plan.server_scope)

    for index, entry in writes:
        sub_key = f"{operation_key}:{index:04d}"
        result = store_for(entry.profile_id).upsert(
            scope_kind=SCOPE_USER_GLOBAL, scope_id="", harness_id=None,
            asset_id=entry.asset_id, decision=str(entry.target_decision),
            revision=entry.target_revision,
            expected_version=(entry.layer_version if expected_row_version
                              is None else expected_row_version),
            operation_key=sub_key)
        written_views.append(result)
        targets.append({
            "profileId": entry.profile_id,
            "assetId": entry.asset_id,
            "serverScope": plan.server_scope,
            "principal": profile_principal(entry.profile_id),
            "scopeKind": SCOPE_USER_GLOBAL,
            "scopeId": "",
            "harnessKey": ANY_HARNESS,
            "subOperationKey": sub_key,
        })

    outcome = {
        "operationKey": operation_key,
        "planDigest": plan.digest,
        "serverScope": plan.server_scope,
        "written": written_views,
        "targets": targets,
        "skippedAlreadyMigrated": skipped,
        "replayed": False,
    }
    _ledger_settle(database, operation_key, outcome)
    return outcome


def _legacy_signatures(database: Database) -> dict[str, str]:
    rows = _binding_rows(database, None)
    return {f"{r['profile_id']}|{r['asset_id']}":
            f"{int(r['revision'])}|{int(r['enabled'])}"
            for r in rows if str(r["kind"]) == SKILL_KIND}


def _ledger_get(database: Database, operation_key: str) -> dict | None:
    with database.read() as conn:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (OPERATIONS_TABLE,)).fetchone()
        if present is None:
            return None
        row = conn.execute(
            f"SELECT result_json FROM {OPERATIONS_TABLE} WHERE operation_key=?",
            (operation_key,)).fetchone()
    return json.loads(row["result_json"]) if row else None


def _ledger_settle(database: Database, operation_key: str,
                   result: dict[str, Any]) -> None:
    from datetime import datetime, timezone
    with database.transaction() as conn:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {OPERATIONS_TABLE} ("
            "operation_key TEXT PRIMARY KEY, result_json TEXT NOT NULL,"
            "settled_at TEXT NOT NULL)")
        conn.execute(
            f"INSERT OR REPLACE INTO {OPERATIONS_TABLE}"
            "(operation_key,result_json,settled_at) VALUES (?,?,?)",
            (operation_key, json.dumps(result, sort_keys=True),
             datetime.now(timezone.utc).isoformat()))


def _ensure_schema_once(database: Database, server_scope: str) -> None:
    store = AssignmentStore(
        database, scope=AssignmentScope(server_scope=server_scope,
                                        principal=profile_principal("")))
    store.ensure_schema()


# -- verify ---------------------------------------------------------------------


def _namespace_rows(database: Database, *, server_scope: str,
                    profile_id: str) -> list[Any]:
    with database.read() as conn:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (ASSIGNMENTS_TABLE,)).fetchone()
        if present is None:
            return []
        return [dict(row) for row in conn.execute(
            f"SELECT * FROM {ASSIGNMENTS_TABLE}"
            " WHERE server_scope=? AND principal=?"
            " ORDER BY asset_id",
            (server_scope, profile_principal(profile_id)))]


def profile_skill_entries(database: Database, *, server_scope: str,
                          profile_id: str) -> tuple[ProfileSkillEntry, ...]:
    """Read the migrated evidence namespace back as Profile-layer entries —
    the exact shape ``assignments.ports.ProfileLayerPort.skill_entries``
    must yield when Z1's facet lands. The G08 equivalence test resolves
    these through the real six-layer resolver."""
    return tuple(
        ProfileSkillEntry(
            row["asset_id"], str(row["decision"]),
            None if row["revision"] is None else int(row["revision"]))
        for row in _namespace_rows(database, server_scope=server_scope,
                                   profile_id=profile_id))


def verify(database: Database, plan: MigrationPlan) -> dict[str, Any]:
    """Forward+backward mapping check between legacy bindings and the
    migrated entries (G08 正向「老 Profile 绑定迁 enable(revision)，结果
    相同」).

    * forward: every ``migrate`` entry's intent must be present in the
      evidence namespace with the same decision AND the same pinned
      revision; every ``refuse:*`` entry must have NO row (a refusal that
      got written anyway is a violation, not a warning);
    * backward: every row in the namespace of the plan's profiles must map
      to a legacy `skill` binding whose state agrees with it
      (enable(rev) <-> enabled=1 & same revision; disable <-> enabled=0);
    * equivalence: the effective skill set (assetId, revision) the plan's
      migratable ``enable`` rows imply equals what the namespace actually
      resolves to — assetIds AND pinned revisions, exactly.

    Raises the typed ``MIGRATION_VERIFY_MISMATCH`` on any divergence;
    returns the evidence summary otherwise.
    """
    violations: list[str] = []
    profiles = sorted({e.profile_id for e in plan.entries
                       if e.classification != SKIP_FOREIGN_KIND})
    namespace: dict[str, dict[str, Any]] = {}
    for pid in profiles:
        rows = {row["asset_id"]: row for row in _namespace_rows(
            database, server_scope=plan.server_scope, profile_id=pid)}
        namespace[pid] = rows

    legacy_expected: set[tuple[str, int]] = set()
    legacy_disabled: set[str] = set()
    for entry in plan.entries:
        if entry.classification == CLASSIFY_MIGRATE:
            row = namespace.get(entry.profile_id, {}).get(entry.asset_id)
            if row is None:
                violations.append(
                    f"{entry.profile_id}/{entry.asset_id}: planned "
                    f"{entry.target_decision} is missing")
            elif (row["decision"] != entry.target_decision or
                  (None if row["revision"] is None else int(row["revision"]))
                  != entry.target_revision):
                violations.append(
                    f"{entry.profile_id}/{entry.asset_id}: stored row is "
                    f"{row['decision']}/{row['revision']}, planned "
                    f"{entry.target_decision}/{entry.target_revision}")
            if entry.target_decision == DECISION_ENABLE:
                legacy_expected.add((entry.asset_id, entry.target_revision))
            else:
                legacy_disabled.add(entry.asset_id)
        elif entry.classification.startswith("refuse"):
            if entry.asset_id in namespace.get(entry.profile_id, {}):
                violations.append(
                    f"{entry.profile_id}/{entry.asset_id}: a refused binding "
                    "was written anyway")

    migrated_effective: set[tuple[str, int]] = set()
    for pid, rows in namespace.items():
        for asset_id, row in rows.items():
            decision = str(row["decision"])
            revision = None if row["revision"] is None else int(row["revision"])
            legacy = _legacy_signatures(database).get(f"{pid}|{asset_id}")
            if legacy is None:
                violations.append(
                    f"{pid}/{asset_id}: namespace row maps to no legacy "
                    "skill binding (backward mapping broken)")
                continue
            pinned, enabled = (int(part) for part in legacy.split("|"))
            if decision == DECISION_ENABLE:
                migrated_effective.add((asset_id, int(revision)))
                if enabled != 1 or revision != pinned:
                    violations.append(
                        f"{pid}/{asset_id}: enable({revision}) does not "
                        f"correspond to the legacy pin {pinned}/enabled={enabled}")
            elif enabled != 0:
                violations.append(
                    f"{pid}/{asset_id}: disable row while the legacy binding "
                    f"is enabled=1")

    if migrated_effective != legacy_expected:
        violations.append(
            "effective-set divergence: legacy-implied "
            f"{sorted(legacy_expected)} != migrated {sorted(migrated_effective)}")
    if violations:
        raise MigrationError(
            "MIGRATION_VERIFY_MISMATCH",
            "the migrated entries do not round-trip the legacy bindings",
            detail="; ".join(violations))
    return {
        "equivalent": True,
        "planDigest": plan.digest,
        "legacyEffectiveSkills": sorted(
            [list(item) for item in legacy_expected]),
        "migratedEffectiveSkills": sorted(
            [list(item) for item in migrated_effective]),
        "migratedDisabled": sorted(legacy_disabled),
        "refused": [f"{e.profile_id}/{e.asset_id}:{e.classification}"
                    for e in plan.refused],
    }


# -- rollback --------------------------------------------------------------------


def _row_state_at(database: Database, *, server_scope: str, principal: str,
                  scope_kind: str, scope_id: str, harness_key: str,
                  asset_id: str) -> dict[str, Any] | None:
    """Raw read of one assignment row at full layer coordinates —
    (row_version, decision, revision), or None when absent / table
    missing. Rollback's drift probe must not depend on the store's
    schema guard: the table exists whenever there are targets to remove,
    and a missing table reads as "row gone"."""
    with database.read() as conn:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (ASSIGNMENTS_TABLE,)).fetchone()
        if present is None:
            return None
        row = conn.execute(
            f"SELECT row_version, decision, revision FROM {ASSIGNMENTS_TABLE}"
            " WHERE server_scope=? AND principal=? AND scope_kind=?"
            " AND scope_id=? AND harness_key=? AND asset_id=?",
            (server_scope, principal, scope_kind, scope_id, harness_key,
             asset_id)).fetchone()
    if row is None:
        return None
    return {"row_version": int(row["row_version"]),
            "decision": str(row["decision"]),
            "revision": None if row["revision"] is None
            else int(row["revision"])}


def _written_index(written: list[dict[str, Any]]) -> dict[tuple, dict]:
    """The ledger's recorded post-write views indexed by the same layer
    coordinates the targets carry (a view's harnessId None == ANY)."""
    return {
        (str(w["serverScope"]), str(w["principal"]), str(w["scopeKind"]),
         str(w["scopeId"]),
         ANY_HARNESS if w.get("harnessId") is None else str(w["harnessId"]),
         str(w["assetId"])): w
        for w in written}


def rollback(database: Database, operation_key: str, *,
             allow_user_data: bool = False) -> dict[str, Any]:
    """Remove exactly the rows one applied operation wrote — and nothing
    else — but ONLY while every written row still stands as recorded.
    The legacy `server_profile_assets` table was never written by
    apply, so rollback of the additive layer leaves it byte-identical
    (proven with row-byte samples in test_migration_rollback_g09.py).

    Drift guard (the MINOR that read as data loss): before deleting, each
    target row is re-read and its decision/revision/row_version compared
    against the ``written`` view the ledger recorded at apply time. Any
    divergence — a user who edited a migrated assignment after the
    apply, a row that is already gone, a ledger whose written/target
    lists no longer pair up — refuses the whole rollback with
    ``MIGRATION_ROLLBACK_ROW_DRIFT`` and writes NOTHING (the probe runs
    to completion before the first delete, so a 3-row operation with one
    drifted row loses zero rows, not two). Rolling back after the drift
    is resolved is the operator's decision; silently deleting the edit
    while claiming "revert" is not.

    The master and sub operation-ledger keys of the rolled-back operation
    are cleared with its rows, so the same operation key may legitimately
    be re-run afterwards against a rebuilt plan; other operations' ledger
    rows and assignment rows are untouched.
    """
    _require_writable_root(database, allow_user_data=allow_user_data)
    settled = _ledger_get(database, operation_key)
    if settled is None:
        raise MigrationError(
            "MIGRATION_OPERATION_UNKNOWN",
            "no settled migration operation carries that key in this data "
            "root (a rolled-back key is cleared and reports unknown)",
            detail=operation_key)
    targets = list(settled.get("targets") or [])
    written_index = _written_index(list(settled.get("written") or []))

    divergences: list[str] = []
    probe: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for target in targets:
        coordinates = (str(target["serverScope"]), str(target["principal"]),
                       str(target["scopeKind"]), str(target["scopeId"]),
                       str(target["harnessKey"]), str(target["assetId"]))
        recorded = written_index.get(coordinates)
        if recorded is None:
            divergences.append(
                f"{target['principal']}/{target['assetId']}: ledger target "
                "has no paired written-view evidence to revert against")
            continue
        current = _row_state_at(
            database, server_scope=coordinates[0], principal=coordinates[1],
            scope_kind=coordinates[2], scope_id=coordinates[3],
            harness_key=coordinates[4], asset_id=coordinates[5])
        if current is None:
            divergences.append(
                f"{target['principal']}/{target['assetId']}: row is already "
                "gone; the ledger no longer describes this data root")
            continue
        if (current["decision"] != str(recorded["decision"])
                or current["revision"] != recorded["revision"]
                or current["row_version"] != int(recorded["rowVersion"])):
            divergences.append(
                f"{target['principal']}/{target['assetId']}: row moved to "
                f"{current['decision']}/{current['revision']}/v"
                f"{current['row_version']}, not the applied "
                f"{recorded['decision']}/{recorded['revision']}/v"
                f"{recorded['rowVersion']}")
            continue
        probe.append((target, recorded))
    if divergences:
        raise MigrationError(
            "MIGRATION_ROLLBACK_ROW_DRIFT",
            "a migrated row changed since the operation applied it; "
            "refusing to delete an edit the migration did not make (zero "
            "rows removed, ledger untouched) — resolve the drifted row "
            "first, then roll back",
            detail="; ".join(divergences))

    for target, _recorded in probe:
        store = AssignmentStore(
            database, scope=AssignmentScope(server_scope=target["serverScope"],
                                            principal=target["principal"]))
        store.remove(scope_kind=target["scopeKind"],
                     scope_id=target["scopeId"],
                     harness_id=(None if target["harnessKey"] == ANY_HARNESS
                                 else target["harnessKey"]),
                     asset_id=target["assetId"])
    keys = [operation_key] + [t["subOperationKey"] for t in targets]
    with database.transaction() as conn:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {OPERATIONS_TABLE} ("
            "operation_key TEXT PRIMARY KEY, result_json TEXT NOT NULL,"
            "settled_at TEXT NOT NULL)")
        conn.execute(
            f"DELETE FROM {OPERATIONS_TABLE} WHERE operation_key IN "
            f"({','.join('?' * len(keys))})", tuple(keys))
    return {"rolledBackOperationKey": operation_key,
            "removedRows": len(targets), "ledgerKeysCleared": len(keys)}


__all__ = [
    "CLASSIFY_MIGRATE", "DEFAULT_SERVER_SCOPE", "MigrationEntry",
    "MigrationError", "MigrationPlan", "REFUSE_NO_GATE",
    "REFUSE_PROFILE_UNKNOWN", "REFUSE_UNAPPROVED",
    "SKIP_ALREADY_MIGRATED", "SKIP_FOREIGN_KIND", "apply", "plan",
    "profile_principal", "profile_skill_entries", "rollback", "verify",
]
