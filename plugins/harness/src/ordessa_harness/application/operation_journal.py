"""T08 durable reservation and result ledger; no native effects are executed.

The authenticated service must supply ``principal`` and verify submission
permits before calling reserve. A journal row is written and committed before
any external effect. A crash after reservation remains Unknown; reopening,
querying and reconciling never rerun the effect.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from ordessa_harness_api import (
    ApplicationTarget, Confirmed, ErrorCode, NotFound, OperationRecord, Plan,
    Refused, Unknown,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ACTIVE = ("applying", "verifying", "unknown")


class JournalError(ValueError):
    """Malformed journal input or impossible transition."""


@dataclass(frozen=True)
class FenceObservation:
    target: ApplicationTarget
    desired_digest: str
    before_revision: str
    native_version_ref: str
    provider_generation: int
    authorization_revision: str
    secret_ref_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, ApplicationTarget):
            raise JournalError("fence target required")
        if type(self.provider_generation) is not int or self.provider_generation < 0:
            raise JournalError("invalid provider generation")
        if any(not isinstance(value, str) or not value for value in (
            self.desired_digest, self.before_revision, self.native_version_ref,
            self.authorization_revision, self.secret_ref_revision,
        )):
            raise JournalError("invalid fence revision")

    @classmethod
    def from_plan(cls, plan: Plan) -> FenceObservation:
        return cls(plan.target, plan.desired_digest, plan.before_revision,
                   plan.native_version_ref, plan.provider_generation,
                   plan.authorization_revision, plan.secret_ref_revision)


@dataclass(frozen=True)
class NativeActivationReceipt:
    """Evidence issued by the native owner for one reserved operation.

    It is never synthesized from a file readback. The service checks it against
    the reserved target and the manifest bound before native activation.
    """
    operation_id: str
    target: ApplicationTarget
    manifest_digest: str
    native_session_identity: str
    applied_revision: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, ApplicationTarget) or not _DIGEST.fullmatch(self.manifest_digest):
            raise JournalError("native receipt target or manifest invalid")
        if any(not isinstance(value, str) or not value for value in (
            self.operation_id, self.native_session_identity, self.applied_revision, self.evidence_ref,
        )):
            raise JournalError("native receipt identity incomplete")


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _target(target: ApplicationTarget) -> str:
    return _json(asdict(target))


def _now(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise JournalError("timezone-aware now required")
    return now.astimezone(timezone.utc)


def _expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JournalError("invalid plan expiry") from exc
    return _now(parsed)


def _fingerprint(plan_json: str) -> str:
    return hashlib.sha256(plan_json.encode("utf-8")).hexdigest()


def _unknown(operation_id: str, phase: str = "applying") -> Unknown:
    return Unknown(operation_id, phase, (), ("external effects and native state require reconciliation",), "reconcile")


class OperationJournal:
    """One SQLite journal rooted in the Harness plugin's private storage.

    An operation is scoped by authenticated principal + complete target + key.
    The active unique index serializes all keys for one server/session/channel,
    including Unknown rows after a restart. The caller retains the right to
    report Confirmed only after independent native verification.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.parent.is_dir():
            raise JournalError("journal parent must be provisioned by the product")
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY, principal TEXT NOT NULL,
                    plan_json TEXT NOT NULL, fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY, principal TEXT NOT NULL,
                    server_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL, runtime_generation INTEGER NOT NULL,
                    operation_key TEXT NOT NULL, plan_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, state TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    UNIQUE(principal, server_id, session_id, channel_id,
                           runtime_generation, operation_key),
                    FOREIGN KEY(plan_id) REFERENCES plans(plan_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_session_operation
                ON operations(server_id, session_id, channel_id)
                WHERE state IN ('applying', 'verifying', 'unknown');
                CREATE TABLE IF NOT EXISTS native_evidence (
                    operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id),
                    manifest_digest TEXT NOT NULL,
                    receipt_json TEXT
                );
                CREATE TABLE IF NOT EXISTS native_verifications (
                    operation_id TEXT PRIMARY KEY REFERENCES operations(operation_id),
                    readback_evidence_ref TEXT NOT NULL
                );
            """)

    def register_plan(self, principal: str, plan: Plan) -> None:
        if not isinstance(principal, str) or not principal.strip() or not isinstance(plan, Plan):
            raise JournalError("authenticated principal and Plan required")
        if not _DIGEST.fullmatch(plan.desired_digest):
            raise JournalError("desired digest must be sha256 hex")
        _expiry(plan.expires_at_utc)
        encoded = _json(asdict(plan))
        fingerprint = _fingerprint(encoded)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT principal, fingerprint FROM plans WHERE plan_id=?", (plan.plan_id,)).fetchone()
            if row is not None:
                if row["principal"] != principal or row["fingerprint"] != fingerprint:
                    raise JournalError("plan id already bound to different principal or content")
                db.commit()
                return
            db.execute("INSERT INTO plans VALUES (?,?,?,?)", (plan.plan_id, principal, encoded, fingerprint))
            db.commit()

    @staticmethod
    def _result(db: sqlite3.Connection, row: sqlite3.Row):
        data = json.loads(row["result_json"])
        if row["state"] == "confirmed":
            receipt = db.execute("SELECT receipt_json FROM native_evidence WHERE operation_id=?",
                                 (row["operation_id"],)).fetchone()
            verification = db.execute("SELECT readback_evidence_ref FROM native_verifications WHERE operation_id=?",
                                      (row["operation_id"],)).fetchone()
            # Existing databases may contain legacy confirmations made from
            # matching bytes alone. Keep their physical row and one-use fence,
            # but do not publish a confirmation unsupported by both proofs.
            if (receipt is None or receipt["receipt_json"] is None or verification is None or
                    verification["readback_evidence_ref"] != data["verification_evidence_ref"]):
                return Unknown(row["operation_id"], "verifying", (),
                               ("legacy confirmation lacks operation-bound native/readback evidence",),
                               "reconcile")
            owner = json.loads(receipt["receipt_json"])
            if (owner["operation_id"] != row["operation_id"] or
                    owner["native_session_identity"] != data["native_session_identity"] or
                    owner["applied_revision"] != data["applied_revision"] or
                    owner["target"] != asdict(ApplicationTarget(
                        row["server_id"], row["session_id"], row["channel_id"], row["runtime_generation"]))):
                return Unknown(row["operation_id"], "verifying", (),
                               ("legacy confirmation differs from native owner evidence",), "reconcile")
            return Confirmed(data["operation_id"], data["applied_revision"],
                             data["native_session_identity"], data["runtime_generation"],
                             data["verification_evidence_ref"], tuple(data["resource_changes"]))
        if row["state"] == "refused":
            return Refused(ErrorCode(data["code"]), tuple(data["diagnostics"]),
                           data["original_state_preserved"], data["operation_id"])
        return Unknown(data["operation_id"], data["phase"],
                       tuple(data["observed_effects"]), tuple(data["pending_checks"]),
                       data["allowed_next_action"])

    @classmethod
    def _record(cls, db: sqlite3.Connection, row: sqlite3.Row) -> OperationRecord:
        return OperationRecord(row["operation_id"], row["operation_key"],
                               ApplicationTarget(row["server_id"], row["session_id"],
                                                 row["channel_id"], row["runtime_generation"]),
                               cls._result(db, row))

    def reserve(self, principal: str, plan_id: str, operation_key: str,
                observed: FenceObservation, *, now: datetime) -> OperationRecord | Refused:
        """Commit the applying row before any caller may perform an effect."""
        return self.reserve_new(principal, plan_id, operation_key, observed, now=now)[0]

    def reserve_new(self, principal: str, plan_id: str, operation_key: str,
                    observed: FenceObservation, *, now: datetime) -> tuple[OperationRecord | Refused, bool]:
        """Return (row, newly_reserved) so only one caller may execute effects."""
        if not isinstance(principal, str) or not principal.strip() or not isinstance(operation_key, str) or not operation_key.strip():
            raise JournalError("principal and operation key required")
        if not isinstance(observed, FenceObservation):
            raise JournalError("fence observation required")
        current = _now(now)
        target = observed.target
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            plan_row = db.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
            if plan_row is None or plan_row["principal"] != principal:
                return Refused(ErrorCode.AUTHORIZATION_REFUSED, ("plan unavailable to principal",), True), False
            plan_data = json.loads(plan_row["plan_json"])
            planned_target = ApplicationTarget(**plan_data["target"])
            existing = db.execute("""SELECT * FROM operations WHERE principal=? AND server_id=?
                AND session_id=? AND channel_id=? AND runtime_generation=? AND operation_key=?""",
                (principal, target.server_id, target.session_id, target.channel_id,
                 target.runtime_generation, operation_key)).fetchone()
            if existing is not None:
                if existing["fingerprint"] != plan_row["fingerprint"]:
                    return Refused(ErrorCode.TARGET_CONFLICT, ("idempotency key bound to different plan",), True), False
                return self._record(db, existing), False
            expected = FenceObservation(planned_target, plan_data["desired_digest"],
                                        plan_data["before_revision"], plan_data["native_version_ref"],
                                        plan_data["provider_generation"], plan_data["authorization_revision"],
                                        plan_data["secret_ref_revision"])
            if observed != expected or current >= _expiry(plan_data["expires_at_utc"]):
                return Refused(ErrorCode.STALE_PLAN, ("plan fence or expiry changed",), True), False
            # Legacy rows remain physically confirmed for data compatibility,
            # but a confirmation with no operation-bound evidence projects as
            # Unknown. It must retain the session fence for a different key.
            older = db.execute("""SELECT * FROM operations WHERE server_id=? AND session_id=?
                AND channel_id=? AND state='confirmed'""",
                (target.server_id, target.session_id, target.channel_id)).fetchall()
            if any(isinstance(self._result(db, prior), Unknown) for prior in older):
                return Refused(ErrorCode.BUSY, ("legacy native effect requires reconciliation",), True), False
            operation_id = f"op-{uuid4().hex}"
            result = _unknown(operation_id)
            try:
                db.execute("""INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (operation_id, principal, target.server_id, target.session_id,
                     target.channel_id, target.runtime_generation, operation_key,
                     plan_id, plan_row["fingerprint"], "applying", _json(asdict(result))))
            except sqlite3.IntegrityError as exc:
                if "one_active_session_operation" in str(exc) or "operations.server_id" in str(exc):
                    return Refused(ErrorCode.BUSY, ("another operation owns the session",), True), False
                raise
            db.commit()
            return OperationRecord(operation_id, operation_key, target, result), True

    def query(self, principal: str, target: ApplicationTarget, operation_key: str) -> OperationRecord | NotFound:
        with self._connect() as db:
            row = db.execute("""SELECT * FROM operations WHERE principal=? AND server_id=?
                AND session_id=? AND channel_id=? AND runtime_generation=? AND operation_key=?""",
                (principal, target.server_id, target.session_id, target.channel_id,
                 target.runtime_generation, operation_key)).fetchone()
            return self._record(db, row) if row is not None else NotFound(operation_key)

    def existing_for_plan(self, principal: str, plan: Plan, operation_key: str) -> OperationRecord | Refused | NotFound:
        """Read an earlier reservation before reevaluating mutable native fences."""
        with self._connect() as db:
            row = db.execute("""SELECT * FROM operations WHERE principal=? AND server_id=?
                AND session_id=? AND channel_id=? AND runtime_generation=? AND operation_key=?""",
                (principal, plan.target.server_id, plan.target.session_id, plan.target.channel_id,
                 plan.target.runtime_generation, operation_key)).fetchone()
            if row is None:
                return NotFound(operation_key)
            if row["fingerprint"] != _fingerprint(_json(asdict(plan))):
                return Refused(ErrorCode.TARGET_CONFLICT, ("idempotency key bound to different plan",), True)
            return self._record(db, row)

    def reconcile(self, principal: str, target: ApplicationTarget, operation_key: str):
        """Read-only until a native observer supplies independent evidence."""
        record = self.query(principal, target, operation_key)
        return record.result if isinstance(record, OperationRecord) else record

    def bind_native_manifest(self, principal: str, target: ApplicationTarget,
                             operation_id: str, manifest_digest: str) -> None:
        """Durably fix the published generation manifest before native activation."""
        if not isinstance(manifest_digest, str) or not _DIGEST.fullmatch(manifest_digest):
            raise JournalError("invalid generation manifest digest")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM operations WHERE operation_id=? AND principal=?",
                             (operation_id, principal)).fetchone()
            if row is None or self._record(db, row).target != target or row["state"] != "applying":
                raise JournalError("operation not available for native manifest")
            prior = db.execute("SELECT manifest_digest FROM native_evidence WHERE operation_id=?",
                               (operation_id,)).fetchone()
            if prior is not None and prior["manifest_digest"] != manifest_digest:
                raise JournalError("native manifest is immutable")
            db.execute("INSERT OR IGNORE INTO native_evidence VALUES (?,?,NULL)",
                       (operation_id, manifest_digest))
            db.commit()

    def record_native_receipt(self, principal: str, target: ApplicationTarget,
                              receipt: NativeActivationReceipt) -> None:
        """Persist owner evidence; an old operation with no receipt stays Unknown."""
        if not isinstance(receipt, NativeActivationReceipt) or receipt.target != target:
            raise JournalError("native receipt target mismatch")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM operations WHERE operation_id=? AND principal=?",
                             (receipt.operation_id, principal)).fetchone()
            evidence = db.execute("SELECT * FROM native_evidence WHERE operation_id=?",
                                  (receipt.operation_id,)).fetchone()
            if (row is None or self._record(db, row).target != target or row["state"] not in _ACTIVE or
                    evidence is None or evidence["manifest_digest"] != receipt.manifest_digest):
                raise JournalError("native receipt does not match reserved operation/manifest")
            encoded = _json(asdict(receipt))
            if evidence["receipt_json"] is not None and evidence["receipt_json"] != encoded:
                raise JournalError("native receipt is immutable")
            db.execute("UPDATE native_evidence SET receipt_json=? WHERE operation_id=?",
                       (encoded, receipt.operation_id))
            # Query/reconcile expose that an effect was acknowledged while
            # remaining Unknown until separate readback verification completes.
            if row["state"] != "confirmed":
                unknown = Unknown(receipt.operation_id, "verifying",
                                  (f"native-receipt:{receipt.evidence_ref}",),
                                  ("native readback and adapter verification",), "reconcile")
                self._persist_result(db, receipt.operation_id, "verifying", unknown)
            db.commit()

    def record_native_verification(self, principal: str, target: ApplicationTarget,
                                   operation_id: str, readback_evidence_ref: str) -> None:
        """Persist independent readback proof after adapter Match and before Confirmed."""
        if not isinstance(readback_evidence_ref, str) or not readback_evidence_ref:
            raise JournalError("readback verification evidence required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM operations WHERE operation_id=? AND principal=?",
                             (operation_id, principal)).fetchone()
            evidence = db.execute("SELECT receipt_json FROM native_evidence WHERE operation_id=?",
                                  (operation_id,)).fetchone()
            if (row is None or self._record(db, row).target != target or row["state"] not in _ACTIVE or
                    evidence is None or evidence["receipt_json"] is None):
                raise JournalError("readback verification lacks reserved native receipt")
            if json.loads(evidence["receipt_json"])["evidence_ref"] == readback_evidence_ref:
                raise JournalError("readback and activation evidence must be distinct")
            prior = db.execute("SELECT readback_evidence_ref FROM native_verifications WHERE operation_id=?",
                               (operation_id,)).fetchone()
            if prior is not None and prior["readback_evidence_ref"] != readback_evidence_ref:
                raise JournalError("readback verification evidence is immutable")
            db.execute("INSERT OR IGNORE INTO native_verifications VALUES (?,?)",
                       (operation_id, readback_evidence_ref))
            db.commit()

    def _persist_result(self, db: sqlite3.Connection, operation_id: str,
                        state: str, result: Confirmed | Unknown) -> None:
        db.execute("UPDATE operations SET state=?, result_json=? WHERE operation_id=?",
                   (state, _json(asdict(result)), operation_id))

    def record_result(self, principal: str, target: ApplicationTarget,
                      operation_id: str, result: Confirmed | Unknown) -> OperationRecord:
        """Persist a caller-observed outcome; DB failure leaves prior Unknown."""
        if not isinstance(result, (Confirmed, Unknown)) or result.operation_id != operation_id:
            raise JournalError("result identity mismatch")
        if isinstance(result, Confirmed) and result.runtime_generation != target.runtime_generation:
            raise JournalError("confirmed runtime generation mismatch")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM operations WHERE operation_id=? AND principal=?",
                             (operation_id, principal)).fetchone()
            if row is None or self._record(db, row).target != target:
                raise JournalError("operation unavailable to principal/target")
            if row["state"] == "confirmed":
                receipt_row = db.execute("SELECT receipt_json FROM native_evidence WHERE operation_id=?",
                                         (operation_id,)).fetchone()
                verification_row = db.execute("SELECT readback_evidence_ref FROM native_verifications WHERE operation_id=?",
                                              (operation_id,)).fetchone()
                if (receipt_row is None or receipt_row["receipt_json"] is None or verification_row is None):
                    raise JournalError("confirmed outcome lacks native receipt/readback evidence")
                if self._result(db, row) != result:
                    raise JournalError("confirmed outcome is immutable")
                return self._record(db, row)
            if row["state"] not in _ACTIVE:
                raise JournalError("operation cannot transition")
            if isinstance(result, Confirmed):
                evidence = db.execute("SELECT receipt_json FROM native_evidence WHERE operation_id=?",
                                      (operation_id,)).fetchone()
                if evidence is None or evidence["receipt_json"] is None:
                    raise JournalError("confirmed result requires native owner receipt")
                verification = db.execute("SELECT readback_evidence_ref FROM native_verifications WHERE operation_id=?",
                                          (operation_id,)).fetchone()
                if verification is None or verification["readback_evidence_ref"] != result.verification_evidence_ref:
                    raise JournalError("confirmed result requires matching readback verification evidence")
                receipt_data = json.loads(evidence["receipt_json"])
                receipt = NativeActivationReceipt(**{
                    **receipt_data, "target": ApplicationTarget(**receipt_data["target"]),
                })
                if (receipt.target != target or receipt.operation_id != operation_id or
                        receipt.native_session_identity != result.native_session_identity or
                        receipt.applied_revision != result.applied_revision):
                    raise JournalError("confirmed result differs from native owner receipt")
            state = "confirmed" if isinstance(result, Confirmed) else "unknown"
            self._persist_result(db, operation_id, state, result)
            db.commit()
            return OperationRecord(operation_id, row["operation_key"], target, result)
