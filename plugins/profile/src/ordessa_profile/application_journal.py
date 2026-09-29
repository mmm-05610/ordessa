"""Application journal and applied receipts (application.md §3).

Durable, non-secret facts about switch applications.  The journal is the
crash-recovery source of truth — recovery reads journal state, it never
guesses from session rows (G11).  A receipt is written only for
port-confirmed applications; "legacy-unverified" history stays in the
session rows and can never be upgraded into a receipt (PV-04).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .contracts import (
    EVIDENCE_PORT_CONFIRMED,
    AppliedReceipt,
    JournalEntry,
    SessionRef,
)
from .errors import ProfileError
from .sensitive import json_dumps, json_loads

# Legal journal transitions.  Anything else is a bug and refuses loudly.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"applying", "rejected", "unknown"}),
    "applying": frozenset({"confirmed", "rejected", "unknown"}),
    "confirmed": frozenset(),
    "rejected": frozenset(),
    "unknown": frozenset({"confirmed", "rejected", "unknown"}),
}


def record(conn: sqlite3.Connection, entry: JournalEntry) -> None:
    conn.execute(
        "INSERT INTO profile_application_journal(operation_id, session_uid,"
        " state, profile_id, profile_revision, plan_digest, failure,"
        " detail_refs_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            entry.operation_id, entry.session_ref.session_uid, entry.state,
            entry.profile_id, entry.profile_revision, entry.plan_digest,
            entry.failure, json_dumps(list(entry.detail_refs)),
            entry.created_at, entry.updated_at,
        ),
    )


def transition(conn: sqlite3.Connection, *, operation_id: str, new_state: str,
               timestamp: str, failure: str | None = None,
               detail_refs: tuple[str, ...] = ()) -> None:
    row = get(conn, operation_id)
    if row is None:
        raise ProfileError(
            "PROFILE_VALUE_INVALID",
            f"journal operation {operation_id} does not exist", status=404,
        )
    current = row["state"]
    if new_state == current:
        # Re-stating an outcome (idempotent repeat) is allowed but recorded.
        pass
    elif new_state not in _TRANSITIONS.get(current, frozenset()):
        raise ProfileError(
            "PROFILE_VALUE_INVALID",
            f"illegal journal transition {current} -> {new_state}",
            status=409,
        )
    refs = list(json_loads(row["detail_refs_json"]))
    refs.extend(r for r in detail_refs if r not in refs)
    conn.execute(
        "UPDATE profile_application_journal SET state=?, failure="
        "COALESCE(?, failure), detail_refs_json=?, updated_at=?"
        " WHERE operation_id=?",
        (new_state, failure, json_dumps(refs), timestamp, operation_id),
    )


def get(conn: sqlite3.Connection,
        operation_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM profile_application_journal WHERE operation_id=?",
        (operation_id,),
    ).fetchone()
    return None if row is None else dict(row)


def latest_for_session(conn: sqlite3.Connection,
                       session_uid: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM profile_application_journal WHERE session_uid=?"
        " ORDER BY created_at DESC, operation_id DESC LIMIT 1",
        (session_uid,),
    ).fetchone()
    return None if row is None else dict(row)


def session_view(conn: sqlite3.Connection, session_uid: str) -> dict[str, Any]:
    """Journal + receipt projection for one session (inspectSessionConfig)."""
    journal = latest_for_session(conn, session_uid)
    receipt = latest_receipt(conn, session_uid)
    return {
        "journal": _journal_public(journal),
        "receipt": receipt.as_public_dict() if receipt else None,
        "evidence_kind": (
            receipt.evidence_kind if receipt else "legacy-unverified"
        ),
    }


def _journal_public(journal: dict[str, Any] | None) -> dict[str, Any] | None:
    if journal is None:
        return None
    return {
        "operation_id": journal["operation_id"],
        "state": journal["state"],
        "profile_id": journal["profile_id"],
        "profile_revision": int(journal["profile_revision"]),
        "plan_digest": journal["plan_digest"],
        "failure": journal["failure"],
        "detail_refs": json_loads(journal["detail_refs_json"]),
        "created_at": journal["created_at"],
        "updated_at": journal["updated_at"],
    }


# --- receipts ---------------------------------------------------------------


def record_receipt(conn: sqlite3.Connection, receipt: AppliedReceipt,
                   timestamp: str) -> None:
    conn.execute(
        "INSERT INTO profile_applied_receipts(operation_id, session_uid,"
        " receipt_json, confirmed_at) VALUES (?,?,?,?)"
        " ON CONFLICT(operation_id) DO NOTHING",
        (
            receipt.operation_id, receipt.session_ref.session_uid,
            json_dumps(receipt.as_public_dict()), timestamp,
        ),
    )


def get_receipt(conn: sqlite3.Connection,
                operation_id: str) -> AppliedReceipt | None:
    row = conn.execute(
        "SELECT receipt_json FROM profile_applied_receipts WHERE operation_id=?",
        (operation_id,),
    ).fetchone()
    if row is None:
        return None
    return _receipt_from_json(json_loads(row["receipt_json"]))


def latest_receipt(conn: sqlite3.Connection,
                   session_uid: str) -> AppliedReceipt | None:
    row = conn.execute(
        "SELECT receipt_json FROM profile_applied_receipts WHERE session_uid=?"
        " ORDER BY confirmed_at DESC, operation_id DESC LIMIT 1",
        (session_uid,),
    ).fetchone()
    if row is None:
        return None
    return _receipt_from_json(json_loads(row["receipt_json"]))


def _receipt_from_json(data: dict[str, Any]) -> AppliedReceipt:
    session_ref = SessionRef(
        realm=data["realm"], harness_id=data["harness_id"],
        native_session_key=data["native_session_key"],
        session_uid=data["session_uid"],
    )
    return AppliedReceipt(
        operation_id=data["operation_id"],
        session_ref=session_ref,
        runtime_generation=data["runtime_generation"],
        config_digest=data["config_digest"],
        profile_id=data["profile_id"],
        profile_revision=int(data["profile_revision"]),
        overlay_revision=data["overlay_revision"],
        policy_revision=int(data["policy_revision"]),
        provider_generations=data["provider_generations"],
        evidence_kind=data["evidence_kind"] or EVIDENCE_PORT_CONFIRMED,
        confirmed_at=data["confirmed_at"],
        execution_id=data.get("execution_id"),
    )
