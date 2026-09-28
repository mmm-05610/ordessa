"""`ApprovalFacts` - the single authoritative store for approval facts (T02).

The wire/data identities of the existing authority are kept exactly: the
`server_approvals` table name, its ten original columns (byte-for-byte; new
correlation columns are additive and nullable so legacy inserts still land),
the `open`/`settled`/`invalid` spellings, the `approval.requested` /
`approval.settled` event names written in the same transaction, the CAS on
`version`, and the `decideRequestId` idempotency that answers a replay from
the recorded row instead of deciding twice.

On top of the legacy semantics, this module adds exactly what contracts C1
demands and the old store lacks: native correlation (`nativeRequestId` +
`operationDigest` + policy/ceiling revision + native generation stored with
the fact), a native receipt with an explicit `Unknown` reconcile outcome that
never resolves to allow, and a grant that is bound to the approved operation
digest and spendable exactly once.

Rows here may be read by the old authority during the compat window (the
retirement of that writer is owned elsewhere); the dual-authority test proves
that a row two authorities fight over surfaces as a typed conflict, which is
why exactly one of them may be wired.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from ordessa_permissions_api import (
    AlreadyRecorded,
    ApprovalDecision,
    ApprovalFact,
    ApprovalRequest,
    ApprovalScope,
    ApprovalState,
    ApprovalStateKind,
    InvalidApproval,
    NativeReceipt,
    PolicyRefusal,
    QueriedApproval,
    QueryOutcome,
    QueryUnknown,
    Recorded,
    UnknownApproval,
    approval_id_for,
)

from ._store import ApprovalDatabase, append_session_event, now_stamp, parse_stamp
from .errors import ApprovalNotFound

__all__ = ["ApprovalFacts", "VersionConflict", "OPEN", "SETTLED", "INVALID"]

OPEN = "open"
SETTLED = "settled"
INVALID = "invalid"
TERMINAL_EXECUTION_STATES = frozenset({"completed", "failed", "cancelled", "unknown"})
ACTIVE_EXECUTION_STATES = frozenset({"accepted", "dispatching", "running", "capturing"})

#: The ten columns exactly as the host schema creates them today. Kept as one
#: declaration so `ensure_schema` and the byte-compatibility test share it.
LEGACY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS server_approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES server_sessions(id),
    execution_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    state TEXT NOT NULL,
    decision TEXT,
    scope_json TEXT,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    settled_at TEXT
);
"""
LEGACY_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS server_approvals_by_execution "
    "ON server_approvals(execution_id, created_at)"
)
LEGACY_COLUMNS = (
    "id", "session_id", "execution_id", "version", "state", "decision", "scope_json",
    "request_json", "created_at", "settled_at",
)
#: Additive, nullable: a row written without them stays readable by everyone.
_CORRELATION_COLUMNS: dict[str, str] = {
    "native_request_id": "TEXT",
    "operation_digest": "TEXT",
    "ceiling_revision": "TEXT",
    "policy_revision": "TEXT",
    "native_generation": "TEXT",
}
_RECEIPTS_DDL = (
    "CREATE TABLE IF NOT EXISTS server_approval_native_receipts ("
    "approval_id TEXT NOT NULL, native_request_id TEXT NOT NULL, confirmed INTEGER NOT NULL,"
    " observed_at TEXT, recorded_at TEXT NOT NULL, PRIMARY KEY(approval_id,"
    " native_request_id))"
)
_USAGE_DDL = (
    "CREATE TABLE IF NOT EXISTS server_approval_grant_usage ("
    "approval_id TEXT PRIMARY KEY, operation_digest TEXT NOT NULL, consumed_at TEXT NOT NULL)"
)
_REQUEST_WIRE_FIELDS = (
    "approvalId", "sessionId", "executionId", "nativeRequestId", "operationDigest",
    "toolKey", "target", "ceilingRevision", "policyRevision", "nativeGeneration",
    "requestedAt", "expiresAt", "version",
)

#: Sentinel: the execution fact could not be resolved at all (Unknown, not "no").
_EXECUTION_UNRESOLVED = object()


@dataclass(frozen=True)
class VersionConflict:
    """The typed CAS failure of C1's `decide`: someone moved the row first.

    It is a *conflict*, not a refusal of the user's will: the caller re-reads
    and re-decides against the new version, never blind-retries a side effect.
    """

    version: int
    reason: str = "approval_version_conflict"

    @property
    def kind(self) -> str:
        return "version_conflict"

    @property
    def grants_execution(self) -> bool:
        return False


class ApprovalFacts:
    """The one authority that writes approval facts and their ledger events."""

    def __init__(self, database: ApprovalDatabase, *, append_event=None) -> None:
        self.database = database
        self._append_event = append_event if append_event is not None \
            else append_session_event

    # -- schema ---------------------------------------------------------------

    @staticmethod
    def create_legacy_table(conn) -> None:
        """Create `server_approvals` with exactly the ten host columns."""
        conn.executescript(LEGACY_TABLE_DDL)
        conn.execute(LEGACY_INDEX_DDL)

    def ensure_schema(self) -> None:
        with self.database.transaction() as conn:
            self.create_legacy_table(conn)
            present = {row["name"] for row in
                       conn.execute("PRAGMA table_info(server_approvals)").fetchall()}
            for name, declaration in _CORRELATION_COLUMNS.items():
                if name not in present:
                    conn.execute(
                        f"ALTER TABLE server_approvals ADD COLUMN {name} {declaration}")
            conn.execute(_RECEIPTS_DDL)
            conn.execute(_USAGE_DDL)

    # -- the fact -------------------------------------------------------------

    def request(self, *, session_id: str, execution_id: str,
                request: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            return self.request_in_transaction(
                conn, session_id=session_id, execution_id=execution_id, request=request,
            )

    def request_in_transaction(self, conn, *, session_id: str, execution_id: str,
                               request: dict[str, Any]) -> dict[str, Any]:
        """Persist a pending approval before it is published; idempotent by the
        derived correlation, so the same native request never mints two rows."""
        parsed = ApprovalRequest.from_record(request)
        derived = approval_id_for(operation_digest=parsed.operation_digest,
                                  native_request_id=parsed.native_request_id)
        if parsed.approval_id != derived:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID",
                                source="facts.request (id is minted by the authority)",
                                target="approvalId does not bind this operation")
        if parsed.session_id != session_id or parsed.execution_id != execution_id:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID",
                                source="facts.request (binding)",
                                target="sessionId/executionId disagree with the request")
        prior = conn.execute("SELECT * FROM server_approvals WHERE id=?",
                             (parsed.approval_id,)).fetchone()
        if prior is not None:
            # Replay of the same operation: answer from the recorded row.
            return self._row(prior)
        timestamp = now_stamp()
        conn.execute(
            "INSERT INTO server_approvals("
            "id,session_id,execution_id,version,state,decision,scope_json,request_json,"
            "created_at,settled_at,native_request_id,operation_digest,ceiling_revision,"
            "policy_revision,native_generation) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (parsed.approval_id, session_id, execution_id, 1, OPEN, None, None,
             json.dumps(request, ensure_ascii=False, sort_keys=True), timestamp, None,
             parsed.native_request_id, parsed.operation_digest, parsed.ceiling_revision,
             parsed.policy_revision, parsed.native_generation),
        )
        body = {
            "approvalId": parsed.approval_id, "executionId": execution_id,
            "version": 1, "state": OPEN, "request": request,
        }
        self._append_event(
            conn, session_id, execution_id, "approval.requested",
            {"approval_id": parsed.approval_id, "version": 1, "request": request},
        )
        return body

    def get(self, approval_id: str) -> dict[str, Any]:
        row = self._fetch(approval_id)
        if row is None:
            raise ApprovalNotFound(approval_id)
        return self._row(row)

    def peek(self, approval_id: str) -> dict[str, Any] | None:
        row = self._fetch(approval_id)
        return None if row is None else self._row(row)

    # -- decide (CAS + idempotent) ---------------------------------------------

    def decide(self, *, approval_id: str, decision: str, scope: dict[str, Any],
               expected_version: int, request_id: str, session_id: str | None = None,
               now: dt.datetime | None = None) -> Any:
        """One authoritative decision per approval; checks run in the order
        that keeps a stale writer from overwriting a settled fact:
        replay -> CAS -> state -> correlation -> session -> execution -> expiry.
        """
        try:
            parsed_decision = ApprovalDecision(decision)
        except ValueError:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source="facts.decide",
                                target=f"decision {decision!r} is not allow or deny") from None
        scope_record = ApprovalScope.from_record(scope).as_record()
        moment = now if now is not None else dt.datetime.now(dt.timezone.utc)
        with self.database.transaction() as conn:
            prior = conn.execute("SELECT * FROM server_approvals WHERE id=?",
                                 (approval_id,)).fetchone()
            if prior is None:
                return UnknownApproval(reason="approval_not_found")
            recorded = json.loads(prior["request_json"])
            if recorded.get("decideRequestId") == request_id:
                # Duplicate delivery of the same decision request: answered from
                # the recorded row, never re-applied.
                return AlreadyRecorded(version=int(prior["version"]),
                                       decision=ApprovalDecision(prior["decision"]),
                                       request_id=request_id)
            if int(prior["version"]) != expected_version:
                return VersionConflict(version=int(prior["version"]))
            if prior["state"] != OPEN:
                return InvalidApproval(reason=f"approval_state:{prior['state']}")
            native_id = self._column(prior, "native_request_id") \
                or recorded.get("nativeRequestId")
            if native_id is None:
                # A row the old authority wrote without native correlation: we
                # can never reconcile it, so we never decide it either.
                return UnknownApproval(reason="approval_native_correlation_missing")
            if session_id is not None and prior["session_id"] != session_id:
                return InvalidApproval(reason="cross_session_approval")
            actionable, execution = self._execution_actionable(conn, prior["execution_id"])
            if execution is _EXECUTION_UNRESOLVED:
                return UnknownApproval(reason="execution_unresolved")
            if not actionable:
                timestamp = now_stamp()
                conn.execute(
                    "UPDATE server_approvals SET state=?,version=version+1,settled_at=? "
                    "WHERE id=? AND state=?", (INVALID, timestamp, approval_id, OPEN))
                self._append_event(
                    conn, prior["session_id"], prior["execution_id"], "approval.settled",
                    {"approval_id": approval_id, "decision": "invalidated"})
                return InvalidApproval(reason="execution_not_actionable")
            expires_at = parse_stamp(recorded.get("expiresAt"))
            if expires_at is not None and moment > expires_at:
                conn.execute(
                    "UPDATE server_approvals SET state=?,version=version+1,settled_at=? "
                    "WHERE id=? AND state=?", (INVALID, now_stamp(), approval_id, OPEN))
                self._append_event(
                    conn, prior["session_id"], prior["execution_id"], "approval.settled",
                    {"approval_id": approval_id, "decision": "invalidated",
                     "reason": "approval_expired"})
                return InvalidApproval(reason="approval_expired")

            recorded["decideRequestId"] = request_id
            cursor = conn.execute(
                "UPDATE server_approvals SET state=?,decision=?,scope_json=?,"
                "version=version+1,request_json=?,settled_at=? "
                "WHERE id=? AND state=? AND version=?",
                (SETTLED, parsed_decision.value, json.dumps(scope_record, sort_keys=True),
                 json.dumps(recorded, ensure_ascii=False, sort_keys=True), now_stamp(),
                 approval_id, OPEN, expected_version),
            )
            if cursor.rowcount != 1:
                # Lost the race after all: same typed answer, never an overwrite.
                fresh = conn.execute("SELECT version FROM server_approvals WHERE id=?",
                                     (approval_id,)).fetchone()
                return VersionConflict(version=int(fresh["version"]) if fresh else -1)
            row = conn.execute("SELECT * FROM server_approvals WHERE id=?",
                               (approval_id,)).fetchone()
            self._append_event(
                conn, row["session_id"], row["execution_id"], "approval.settled",
                {"approval_id": approval_id, "decision": parsed_decision.value},
            )
            return Recorded(version=int(row["version"]),
                            decision=ApprovalDecision(row["decision"]))

    # -- expiry / invalidation (legacy-compatible surfaces) ---------------------

    def expire(self, approval_id: str, reason: str) -> None:
        del reason
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM server_approvals WHERE id=?",
                               (approval_id,)).fetchone()
            if row is None or row["state"] != OPEN:
                return
            conn.execute(
                "UPDATE server_approvals SET state=?,version=version+1,settled_at=? "
                "WHERE id=? AND state=?", (INVALID, now_stamp(), approval_id, OPEN))

    def invalidate_for_execution(self, execution_id: str, reason: str) -> int:
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM server_approvals WHERE execution_id=? AND state=?",
                (execution_id, OPEN)).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE server_approvals SET state=?,version=version+1,settled_at=? "
                    "WHERE id=? AND state=?",
                    (INVALID, now_stamp(), row["id"], OPEN))
                self._append_event(
                    conn, row["session_id"], execution_id, "approval.settled",
                    {"approval_id": row["id"], "decision": "invalidated", "reason": reason})
            return len(rows)

    def open_for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            rows = conn.execute(
                "SELECT * FROM server_approvals WHERE execution_id=? AND state=?",
                (execution_id, OPEN)).fetchall()
        return [self._row(row) for row in rows]

    def expire_for_execution(self, conn, execution_id: str, reason: str) -> int:
        del reason
        cursor = conn.execute(
            "UPDATE server_approvals SET state=?,version=version+1,settled_at=? "
            "WHERE execution_id=? AND state=?",
            (INVALID, now_stamp(), execution_id, OPEN))
        return cursor.rowcount

    # -- native receipt / reconcile ---------------------------------------------

    def record_native_receipt(self, approval_id: str,
                              receipt: NativeReceipt) -> dict[str, Any]:
        if receipt.approval_id != approval_id:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID",
                                source="facts.record_native_receipt",
                                target="receipt names another approval")
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM server_approvals WHERE id=?",
                               (approval_id,)).fetchone()
            if row is None:
                raise ApprovalNotFound(approval_id)
            native_id = self._column(row, "native_request_id")
            if native_id is not None and receipt.native_request_id != native_id:
                raise PolicyRefusal("PERMISSION_APPROVAL_INVALID",
                                    source="facts.record_native_receipt",
                                    target="receipt correlates to another native request")
            existing = conn.execute(
                "SELECT * FROM server_approval_native_receipts WHERE approval_id=? AND"
                " native_request_id=?", (approval_id, receipt.native_request_id)).fetchone()
            if existing is not None and int(existing["confirmed"]) == 1 \
                    and not receipt.confirmed:
                # An unknown never downgrades a confirmed observation.
                return self._receipt_dict(existing)
            conn.execute(
                "INSERT INTO server_approval_native_receipts(approval_id,native_request_id,"
                "confirmed,observed_at,recorded_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(approval_id,native_request_id) DO UPDATE SET"
                " confirmed=excluded.confirmed, observed_at=excluded.observed_at,"
                " recorded_at=excluded.recorded_at",
                (approval_id, receipt.native_request_id, 1 if receipt.confirmed else 0,
                 receipt.observed_at.isoformat() if receipt.observed_at else None,
                 now_stamp()),
            )
            stored = conn.execute(
                "SELECT * FROM server_approval_native_receipts WHERE approval_id=? AND"
                " native_request_id=?", (approval_id, receipt.native_request_id)).fetchone()
            return self._receipt_dict(stored)

    def reconcile(self, approval_id: str, native_request_id: str) -> QueryOutcome:
        """`ApprovalState + nativeReceipt | Unknown` - and Unknown is its own
        outcome that never resolves to allow."""
        with self.database.read() as conn:
            row = conn.execute("SELECT * FROM server_approvals WHERE id=?",
                                (approval_id,)).fetchone()
            if row is None:
                return QueryUnknown(reason="approval_not_found")
            native_id = self._column(row, "native_request_id")
            if native_id is None or native_id != native_request_id:
                return QueryUnknown(reason="native_correlation_mismatch")
            receipt = conn.execute(
                "SELECT * FROM server_approval_native_receipts WHERE approval_id=? AND"
                " native_request_id=?", (approval_id, native_request_id)).fetchone()
        state = self._approval_state(row)
        parsed_receipt = None if receipt is None else NativeReceipt.of(
            native_request_id=receipt["native_request_id"],
            approval_id=receipt["approval_id"],
            confirmed=bool(int(receipt["confirmed"])),
            observed_at=receipt["observed_at"])
        if (state.state is ApprovalStateKind.SETTLED
                and state.decision is ApprovalDecision.ALLOW and parsed_receipt is None):
            # The user said allow; whether the native owner received it is
            # unknown - and unknown is never "the tool may run".
            return QueryUnknown(reason="native_receipt_unobserved")
        return QueriedApproval(state=state, receipt=parsed_receipt)

    # -- grants -------------------------------------------------------------------

    def grant_fields(self, approval_id: str) -> dict[str, Any] | None:
        """The stored one-time grant binding, in `BoundGrant` record spelling."""
        row = self._fetch(approval_id)
        if row is None:
            return None
        recorded = json.loads(row["request_json"])
        with self.database.read() as conn:
            used = conn.execute(
                "SELECT 1 FROM server_approval_grant_usage WHERE approval_id=?",
                (approval_id,)).fetchone() is not None
        return {
            "approvalId": row["id"],
            "operationDigest": self._column(row, "operation_digest"),
            "target": recorded.get("target"),
            "ceilingRevision": self._column(row, "ceiling_revision"),
            "policyRevision": self._column(row, "policy_revision"),
            "nativeGeneration": self._column(row, "native_generation"),
            "expiresAt": recorded.get("expiresAt"),
            "consumed": used,
        }

    def consume_grant(self, *, approval_id: str, operation_digest: str,
                      native_request_id: str,
                      moment: dt.datetime | None = None) -> bool:
        """Atomically spend the approval's one-time grant; `False` means it is
        not spendable (not settled-allow, foreign binding, or already used)."""
        when = (moment or dt.datetime.now(dt.timezone.utc)).isoformat()
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM server_approvals WHERE id=?",
                               (approval_id,)).fetchone()
            if row is None:
                return False
            if row["state"] != SETTLED or row["decision"] != ApprovalDecision.ALLOW.value:
                return False
            if self._column(row, "operation_digest") != operation_digest:
                return False
            if self._column(row, "native_request_id") != native_request_id:
                return False
            try:
                conn.execute(
                    "INSERT INTO server_approval_grant_usage(approval_id,operation_digest,"
                    "consumed_at) VALUES (?,?,?)", (approval_id, operation_digest, when))
            except Exception:
                # PRIMARY KEY conflict: the grant was already spent.
                return False
            return True

    # -- facts as DTOs --------------------------------------------------------------

    def approval_fact(self, approval_id: str) -> ApprovalFact | None:
        row = self._fetch(approval_id)
        if row is None:
            return None
        record = self._request_record(row)
        if record is None:
            return None
        with self.database.read() as conn:
            receipt = conn.execute(
                "SELECT * FROM server_approval_native_receipts WHERE approval_id=?",
                (approval_id,)).fetchone()
        state = self._approval_state(row)
        parsed_receipt = None if receipt is None else NativeReceipt.of(
            native_request_id=receipt["native_request_id"],
            approval_id=receipt["approval_id"],
            confirmed=bool(int(receipt["confirmed"])),
            observed_at=receipt["observed_at"])
        try:
            request = ApprovalRequest.from_record(record)
        except PolicyRefusal:
            return None  # a fact that cannot vouch for its own bindings is not one
        return ApprovalFact.of(request=request, state=state, receipt=parsed_receipt)

    # -- execution facts --------------------------------------------------------------

    def execution_state(self, execution_id: str) -> str | None:
        """The stored execution's state, or None when it cannot be resolved."""
        with self.database.read() as conn:
            try:
                row = conn.execute("SELECT state FROM server_turns WHERE id=?",
                                   (execution_id,)).fetchone()
            except Exception:
                return None
        return None if row is None else row["state"]

    # -- busy --------------------------------------------------------------------------

    def open_count(self) -> int:
        with self.database.read() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM server_approvals WHERE state=?", (OPEN,)).fetchone()[0])

    def busy(self) -> int:
        """Open approvals plus settled-allow grants whose native receipt is
        still unreconciled: the host consults this before unloading (C4).

        Since T018 this fact is not merely consultable - the plugin's
        `stop_hooks`/`disposal` read it and REFUSE the deactivation while it
        is non-zero, so an unresolved approval cannot disappear with the
        provider (C0's integration request #1)."""
        with self.database.read() as conn:
            try:
                rows = conn.execute(
                    "SELECT state, decision, id FROM server_approvals").fetchall()
                reconciled = {row["approval_id"] for row in conn.execute(
                    "SELECT approval_id FROM server_approval_native_receipts"
                    " WHERE confirmed=1").fetchall()}
            except Exception:
                return 1  # cannot tell -> busy; an unload-while-unknown is refused
        count = 0
        for row in rows:
            if row["state"] == OPEN:
                count += 1
            elif row["state"] == SETTLED and row["decision"] == \
                    ApprovalDecision.ALLOW.value and row["id"] not in reconciled:
                count += 1
        return count

    # -- internals ----------------------------------------------------------------

    def _fetch(self, approval_id: str):
        with self.database.read() as conn:
            return conn.execute("SELECT * FROM server_approvals WHERE id=?",
                                (approval_id,)).fetchone()

    def _execution_actionable(self, conn, execution_id: str):
        try:
            execution = conn.execute("SELECT state FROM server_turns WHERE id=?",
                                     (execution_id,)).fetchone()
        except Exception:
            return False, _EXECUTION_UNRESOLVED
        if execution is None or execution["state"] in TERMINAL_EXECUTION_STATES:
            return False, None
        return True, execution["state"]

    @staticmethod
    def _column(row, name: str) -> Any:
        try:
            return row[name]
        except (IndexError, KeyError):
            return None

    @staticmethod
    def _request_record(row) -> dict[str, Any] | None:
        raw = json.loads(row["request_json"])
        if not isinstance(raw, dict):
            return None
        record = {key: raw[key] for key in _REQUEST_WIRE_FIELDS if key in raw}
        return record or None

    def _row(self, row) -> dict[str, Any]:
        record = self._request_record(row) or json.loads(row["request_json"])
        return {
            "approvalId": row["id"],
            "sessionId": row["session_id"],
            "executionId": row["execution_id"],
            "version": int(row["version"]),
            "state": row["state"],
            "decision": row["decision"],
            "scope": json.loads(row["scope_json"]) if row["scope_json"] else None,
            "request": json.loads(row["request_json"]),
            "nativeRequestId": self._column(row, "native_request_id"),
            "operationDigest": self._column(row, "operation_digest"),
            "ceilingRevision": self._column(row, "ceiling_revision"),
            "policyRevision": self._column(row, "policy_revision"),
            "nativeGeneration": self._column(row, "native_generation"),
            "requestedAt": record.get("requestedAt") if isinstance(record, dict) else None,
            "expiresAt": record.get("expiresAt") if isinstance(record, dict) else None,
        }

    def _approval_state(self, row) -> ApprovalState:
        recorded = json.loads(row["request_json"])
        return ApprovalState.from_record({
            "approvalId": row["id"],
            "sessionId": row["session_id"],
            "executionId": row["execution_id"],
            "version": int(row["version"]),
            "state": row["state"],
            "decision": row["decision"],
            "scope": json.loads(row["scope_json"]) if row["scope_json"] else None,
            "requestId": recorded.get("decideRequestId"),
            "nativeRequestId": self._column(row, "native_request_id")
            or recorded.get("nativeRequestId") or "unrecorded",
        })

    @staticmethod
    def _receipt_dict(row) -> dict[str, Any]:
        return {
            "approvalId": row["approval_id"],
            "nativeRequestId": row["native_request_id"],
            "confirmed": bool(int(row["confirmed"])),
            "observedAt": row["observed_at"],
            "recordedAt": row["recorded_at"],
        }
