"""`PolicyRepository` - persisted ceilings and intents in SEPARATE stores (FR-01).

The administrator ceiling lives in its own table and is only writable from a
trusted-source provenance: construction goes through `PolicyCeiling`, which
already refuses an unsigned or low-scope record, and the store re-checks
`is_trusted` before writing, so a ceiling arriving through the ordinary
profile/settings path cannot land even if a caller built the object some other
way. Intents are a different table with different rules; an intent record has
no ceiling vocabulary at all, which is what keeps "the lower layer raised the
upper bound" unrepresentable.

Every revision is kept (`...@N` history rows are never overwritten), so a
mid-flight tightening is detectable by comparing the digest a fact was decided
under with the digest currently in force. A third, derived table keeps the
legacy import's review findings (flag-only, never authority); the raw-record
readers at the bottom exist for the read-only describe projection, which
validates each field itself so an unverified provenance can be REPORTED with
its source without any enforcement path ever reading through it.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Sequence

from ordessa_permissions_api import PermissionIntent, PolicyCeiling, PolicyRefusal

from ._store import ApprovalDatabase, now_stamp

__all__ = ["PolicyRepository"]

_CEILINGS_TABLE = "permissions_policy_ceilings"
_INTENTS_TABLE = "permissions_policy_intents"
_REVIEWS_TABLE = "permissions_policy_reviews"
_CEILINGS_DDL = (
    f"CREATE TABLE IF NOT EXISTS {_CEILINGS_TABLE} ("
    "policy_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK (revision >= 1),"
    " record_json TEXT NOT NULL, stored_at TEXT NOT NULL,"
    f" PRIMARY KEY(policy_id, revision))"
)
_INTENTS_DDL = (
    f"CREATE TABLE IF NOT EXISTS {_INTENTS_TABLE} ("
    "intent_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK (revision >= 1),"
    " record_json TEXT NOT NULL, stored_at TEXT NOT NULL,"
    f" PRIMARY KEY(intent_id, revision))"
)
#: Derived review findings of the legacy import (T012): which stored entry of
#: which source still needs a human ruling, and why. Not an authority record:
#: it can only flag, never import; `permissions.policy.describe` reads it so
#: the Settings region shows the same findings the importer produced.
_REVIEWS_DDL = (
    f"CREATE TABLE IF NOT EXISTS {_REVIEWS_TABLE} ("
    "source TEXT NOT NULL, entry_index INTEGER, reason TEXT NOT NULL,"
    " finding_digest TEXT NOT NULL, seq INTEGER NOT NULL,"
    f" PRIMARY KEY(source, finding_digest))"
)
#: The review reason is a diagnostic, not a payload: single-line safe text,
#: the admission port's own bound (`_refusal_reason` caps at 240).
_REASON_MAX = 240
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _review_reason(value: Any) -> str:
    text = value if isinstance(value, str) else str(value)
    return _CONTROL_CHARS.sub("?", text)[:_REASON_MAX]


def _ceiling_record(ceiling: PolicyCeiling) -> dict[str, Any]:
    def entries(items) -> list[dict[str, Any]]:
        rendered: list[dict[str, Any]] = []
        for entry in items:
            item: dict[str, Any] = {"key": entry.tool.key, "action": entry.action}
            if entry.target is not None:
                item["pattern"] = entry.target.pattern
            rendered.append(item)
        return rendered
    return {
        "policyId": ceiling.policy_id, "scope": ceiling.scope.value,
        "revision": ceiling.revision, "source": ceiling.source.value,
        "signed": ceiling.signed, "deny": entries(ceiling.hard_denies),
        "requireApproval": entries(ceiling.require_approval),
        "maximumExposure": ceiling.maximum_exposure.value,
        "effectiveFrom": ceiling.effective_from.isoformat(),
    }


def _intent_record(intent: PermissionIntent) -> dict[str, Any]:
    def rule_record(rule) -> dict[str, Any]:
        record: dict[str, Any] = {
            "key": rule.tool.key, "action": rule.action.value,
            "priority": rule.priority, "scope": rule.scope.value,
        }
        if rule.target is not None:
            record["pattern"] = rule.target.pattern
        if rule.authorization is not None:
            authority = rule.authorization
            record["authorization"] = {
                "issuer": authority.issuer, "subject": authority.subject,
                "target": authority.target,
                "ceilingRevision": authority.ceiling_revision,
                "verified": True,
                "expiresAt": authority.expires_at.isoformat(),
            }
        return record

    record: dict[str, Any] = {
        "intentId": intent.intent_id, "revision": intent.revision,
        "harnessId": intent.harness_id, "scope": intent.scope.value,
        "rules": [rule_record(rule) for rule in intent.rules],
    }
    if intent.desired_mode is not None:
        # The stored spelling is the bare brand-native mode name
        # (`intents.from_record` re-declares it against this intent's own
        # harness id); `BrandMode` has no `.value` - naming the mode is the
        # whole record.
        record["desiredMode"] = intent.desired_mode.name
    return record


class PolicyRepository:
    """Two stores, one per authority layer; neither can write the other."""

    def __init__(self, database: ApprovalDatabase) -> None:
        self.database = database

    def ensure_schema(self) -> None:
        with self.database.transaction() as conn:
            conn.execute(_CEILINGS_DDL)
            conn.execute(_INTENTS_DDL)
            conn.execute(_REVIEWS_DDL)

    @staticmethod
    def store_tables() -> dict[str, str]:
        return {"ceilings": _CEILINGS_TABLE, "intents": _INTENTS_TABLE,
                "reviews": _REVIEWS_TABLE}

    # -- ceilings (trusted-source provenance only) ---------------------------------

    def store_ceiling_record(self, raw: dict[str, Any]) -> PolicyCeiling:
        return self.store_ceiling(PolicyCeiling.from_record(raw))

    def store_ceiling(self, ceiling: PolicyCeiling) -> PolicyCeiling:
        if not isinstance(ceiling, PolicyCeiling):
            raise PolicyRefusal("PERMISSION_CEILING_INVALID",
                               source="policies.store_ceiling",
                               target=type(ceiling).__name__)
        if not ceiling.is_trusted:
            # Defence in depth: even a hand-built object without provenance
            # never reaches the table.
            raise PolicyRefusal("POLICY_SCOPE_UNVERIFIED",
                                source="policies.store_ceiling (provenance)",
                                target=ceiling.policy_id)
        record = _ceiling_record(ceiling)
        self._insert(_CEILINGS_TABLE, "policy_id", ceiling.policy_id,
                     ceiling.revision, record,
                     error_code="PERMISSION_CEILING_INVALID")
        return ceiling

    def ceiling(self, policy_id: str, revision: int) -> PolicyCeiling | None:
        raw = self._fetch(_CEILINGS_TABLE, "policy_id", policy_id, revision)
        return None if raw is None else PolicyCeiling.from_record(raw)

    def ceilings_current(self) -> tuple[PolicyCeiling, ...]:
        rows = self._latest(_CEILINGS_TABLE, "policy_id")
        built: list[PolicyCeiling] = []
        for row in rows:
            raw = self._fetch(_CEILINGS_TABLE, "policy_id", row["id"], row["revision"])
            if raw is not None:
                built.append(PolicyCeiling.from_record(raw))
        return tuple(built)

    def ceiling_history(self, policy_id: str) -> tuple[PolicyCeiling, ...]:
        return tuple(PolicyCeiling.from_record(raw)
                     for raw in self._history(_CEILINGS_TABLE, "policy_id", policy_id))

    # -- intents (configuration layer; can only narrow) -------------------------------

    def store_intent_record(self, raw: dict[str, Any]) -> PermissionIntent:
        return self.store_intent(PermissionIntent.from_record(raw))

    def store_intent(self, intent: PermissionIntent) -> PermissionIntent:
        if not isinstance(intent, PermissionIntent):
            raise PolicyRefusal("PERMISSION_INTENT_INVALID", source="policies.store_intent",
                                target=type(intent).__name__)
        self._insert(_INTENTS_TABLE, "intent_id", intent.intent_id, intent.revision,
                     _intent_record(intent), error_code="PERMISSION_INTENT_INVALID")
        return intent

    def intent(self, intent_id: str, revision: int) -> PermissionIntent | None:
        raw = self._fetch(_INTENTS_TABLE, "intent_id", intent_id, revision)
        return None if raw is None else PermissionIntent.from_record(raw)

    def intent_current(self, intent_id: str) -> PermissionIntent | None:
        latest = self._latest_one(_INTENTS_TABLE, "intent_id", intent_id)
        return None if latest is None else self.intent(intent_id, latest)

    def intent_history(self, intent_id: str) -> tuple[PermissionIntent, ...]:
        return tuple(PermissionIntent.from_record(raw)
                     for raw in self._history(_INTENTS_TABLE, "intent_id", intent_id))

    # -- raw current revisions (the describe projection's read surface) ---------------
    # These hand back the stored records WITHOUT the authority round-trip: the
    # `permissions.policy.describe` projection validates them field by field so
    # an unverified provenance can be REPORTED with its source. No enforcement
    # path reads through here.

    def ceilings_current_records(self) -> list[dict[str, Any]]:
        built: list[dict[str, Any]] = []
        for row in self._latest(_CEILINGS_TABLE, "policy_id"):
            raw = self._fetch(_CEILINGS_TABLE, "policy_id", row["id"], row["revision"])
            if raw is not None:
                built.append(raw)
        return built

    def intents_current_records(self) -> list[dict[str, Any]]:
        built: list[dict[str, Any]] = []
        for row in self._latest(_INTENTS_TABLE, "intent_id"):
            raw = self._fetch(_INTENTS_TABLE, "intent_id", row["id"], row["revision"])
            if raw is not None:
                built.append(raw)
        return built

    # -- legacy-import review findings (derived, flag-only; never authority) ----------

    def record_review_findings(self, source: str, findings: Iterable[Any]) -> int:
        """Replace the stored findings of one source with the given ones.

        `findings` is a sequence of `(entry_index | None, reason)` pairs. The
        reason is bounded single-line safe text on the way in - a finding is a
        pointer for a human, not a carrier for stored payloads.
        """
        rows: list[tuple[Any, ...]] = []
        seen: set[str] = set()
        for seq, (entry_index, reason) in enumerate(findings):
            text = _review_reason(reason)
            index = None if entry_index is None else int(entry_index)
            digest = hashlib.sha256(json.dumps([index, text], sort_keys=True)
                                   .encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            rows.append((source, index, text, digest, seq))
        with self.database.transaction() as conn:
            conn.execute(f"DELETE FROM {_REVIEWS_TABLE} WHERE source=?", (source,))
            for row in rows:
                conn.execute(
                    f"INSERT INTO {_REVIEWS_TABLE}"
                    "(source,entry_index,reason,finding_digest,seq) VALUES (?,?,?,?,?)",
                    row)
        return len(rows)

    def review_findings(self) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            rows = conn.execute(
                f"SELECT source, entry_index, reason FROM {_REVIEWS_TABLE}"
                " ORDER BY source, seq, finding_digest").fetchall()
        return [{"source": row["source"],
                 "index": None if row["entry_index"] is None else int(row["entry_index"]),
                 "reason": row["reason"]} for row in rows]

    # -- shared storage plumbing -------------------------------------------------------

    def _insert(self, table: str, id_column: str, record_id: str, revision: int,
                record: dict[str, Any], *, error_code: str) -> None:
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self.database.transaction() as conn:
            rows = conn.execute(
                f"SELECT revision, record_json FROM {table} WHERE {id_column}=?",
                (record_id,)).fetchall()
            stored = {int(row["revision"]) for row in rows}
            if stored and revision < max(stored):
                raise PolicyRefusal(error_code, source=f"policies.{table}",
                                    target="revision may not move backwards")
            if revision in stored:
                existing = next(row["record_json"] for row in rows
                                if int(row["revision"]) == revision)
                if existing != payload:
                    raise PolicyRefusal(error_code, source=f"policies.{table}",
                                        target=f"revision {revision} already holds"
                                               " a different record")
                return  # idempotent re-store of the identical revision
            conn.execute(
                f"INSERT INTO {table}({id_column},revision,record_json,stored_at)"
                " VALUES (?,?,?,?)",
                (record_id, revision, payload, now_stamp()),
            )

    def _fetch(self, table: str, id_column: str, record_id: str,
               revision: int) -> dict[str, Any] | None:
        with self.database.read() as conn:
            row = conn.execute(
                f"SELECT record_json FROM {table} WHERE {id_column}=? AND revision=?",
                (record_id, revision)).fetchone()
        return None if row is None else json.loads(row["record_json"])

    def _latest_one(self, table: str, id_column: str, record_id: str) -> int | None:
        with self.database.read() as conn:
            row = conn.execute(
                f"SELECT MAX(revision) FROM {table} WHERE {id_column}=?",
                (record_id,)).fetchone()
        return None if row is None or row[0] is None else int(row[0])

    def _latest(self, table: str, id_column: str) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            rows = conn.execute(
                f"SELECT {id_column} AS id, MAX(revision) AS revision FROM {table}"
                f" GROUP BY {id_column} ORDER BY {id_column}").fetchall()
        return [{"id": row["id"], "revision": int(row["revision"])} for row in rows]

    def _history(self, table: str, id_column: str, record_id: str) -> list[dict]:
        with self.database.read() as conn:
            rows = conn.execute(
                f"SELECT record_json FROM {table} WHERE {id_column}=?"
                " ORDER BY revision ASC", (record_id,)).fetchall()
        return [json.loads(row["record_json"]) for row in rows]
