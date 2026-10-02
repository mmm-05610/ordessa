"""SQL access helpers; services own transaction boundaries.

Every function here takes the caller's connection so that the atomic switch
application (sessions row + overlay purge + turn record) stays one
``BEGIN IMMEDIATE`` unit (FR-008/FR-022).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .errors import ProfileError


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)


# --- idempotency (FR-002: repeated requests must not re-mutate) ---

def idempotency_check(conn: sqlite3.Connection, scope: str, key: str,
                      request_digest: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT request_digest, status, response_json FROM profile_idempotency "
        "WHERE scope=? AND key=?", (scope, key),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != request_digest:
        raise ProfileError(
            "IDEMPOTENCY_KEY_REUSED",
            "Idempotency key was already used with a different request",
            status=409,
        )
    return {"status": int(row["status"]), "response": json.loads(row["response_json"])}


def idempotency_insert(conn: sqlite3.Connection, scope: str, key: str,
                       request_digest: str, status: int,
                       response: dict[str, Any], timestamp: str) -> None:
    conn.execute(
        "INSERT INTO profile_idempotency(scope, key, request_digest, status,"
        " response_json, created_at) VALUES (?,?,?,?,?,?)",
        (scope, key, request_digest, status,
         json.dumps(response, ensure_ascii=False, sort_keys=True), timestamp),
    )


# --- profiles ---

def get_profile(conn: sqlite3.Connection, profile_id: str) -> dict[str, Any] | None:
    return row_to_dict(conn.execute(
        "SELECT * FROM profile_profiles WHERE profile_id=?", (profile_id,),
    ).fetchone())


def list_profiles(conn: sqlite3.Connection, *, include_archived: bool) -> list[dict[str, Any]]:
    if include_archived:
        rows = conn.execute(
            "SELECT * FROM profile_profiles ORDER BY created_at, profile_id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM profile_profiles WHERE archived_at IS NULL "
            "ORDER BY created_at, profile_id"
        ).fetchall()
    return [dict(row) for row in rows]


def insert_profile(conn: sqlite3.Connection, *, profile_id: str, version: int,
                   display_name: str, harness_id: str, revision: int,
                   archived_at: str | None, created_at: str,
                   updated_at: str, realm: str = "local") -> None:
    conn.execute(
        "INSERT INTO profile_profiles(profile_id, version, display_name,"
        " harness_id, current_revision, archived_at, created_at, updated_at,"
        " realm) VALUES (?,?,?,?,?,?,?,?,?)",
        (profile_id, version, display_name, harness_id, revision, archived_at,
         created_at, updated_at, realm),
    )


def active_profile_names(conn: sqlite3.Connection, *, realm: str,
                         harness_id: str) -> list[tuple[str, str]]:
    """(display_name, profile_id) of active profiles in one (realm, harness).
    Normalisation happens in Python: SQLite's LOWER/TRIM cannot do Unicode
    NFC + casefold (PM03)."""
    rows = conn.execute(
        "SELECT display_name, profile_id FROM profile_profiles WHERE realm=?"
        " AND harness_id=? AND archived_at IS NULL", (realm, harness_id),
    ).fetchall()
    return [(r["display_name"], r["profile_id"]) for r in rows]


def insert_revision(conn: sqlite3.Connection, *, profile_id: str,
                    config_revision: int, created_at: str) -> None:
    conn.execute(
        "INSERT INTO profile_revisions(profile_id, config_revision, created_at)"
        " VALUES (?,?,?)",
        (profile_id, config_revision, created_at),
    )


def revision_rows(conn: sqlite3.Connection, profile_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT config_revision, created_at FROM profile_revisions "
        "WHERE profile_id=? ORDER BY config_revision", (profile_id,),
    ).fetchall()]


def facet_values_at(conn: sqlite3.Connection, profile_id: str,
                    config_revision: int) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT facet_id, item_id, value_json, facet_version, quarantined,"
        " updated_at FROM profile_facet_values "
        "WHERE profile_id=? AND config_revision=? "
        "ORDER BY facet_id, item_id", (profile_id, config_revision),
    ).fetchall()]


def copy_revision_values(conn: sqlite3.Connection, *, profile_id: str,
                         from_revision: int, to_revision: int,
                         timestamp: str) -> None:
    conn.execute(
        "INSERT INTO profile_facet_values(profile_id, config_revision, facet_id,"
        " item_id, value_json, facet_version, quarantined, updated_at) "
        "SELECT profile_id, ?, facet_id, item_id, value_json, facet_version,"
        " quarantined, ? FROM profile_facet_values "
        "WHERE profile_id=? AND config_revision=?",
        (to_revision, timestamp, profile_id, from_revision),
    )


def upsert_facet_value(conn: sqlite3.Connection, *, profile_id: str,
                       config_revision: int, facet_id: str, item_id: str,
                       value_json: str, facet_version: str, timestamp: str,
                       quarantined: int = 0) -> None:
    conn.execute(
        "INSERT INTO profile_facet_values(profile_id, config_revision, facet_id,"
        " item_id, value_json, facet_version, quarantined, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(profile_id, config_revision, facet_id, item_id) DO UPDATE SET"
        " value_json=excluded.value_json, facet_version=excluded.facet_version,"
        " quarantined=excluded.quarantined, updated_at=excluded.updated_at",
        (profile_id, config_revision, facet_id, item_id, value_json,
         facet_version, quarantined, timestamp),
    )


def delete_facet_value(conn: sqlite3.Connection, *, profile_id: str,
                       config_revision: int, facet_id: str, item_id: str) -> None:
    """Clear only the new revision; historical revisions remain immutable."""
    conn.execute("DELETE FROM profile_facet_values WHERE profile_id=? AND config_revision=? "
                 "AND facet_id=? AND item_id=?", (profile_id, config_revision, facet_id, item_id))


def latest_turn_seq(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(turn_seq) AS s FROM profile_turns WHERE session_id=?",
        (session_id,),
    ).fetchone()
    return int(row["s"] or 0)


def last_confirmed_turn(conn: sqlite3.Connection,
                        session_id: str) -> dict[str, Any] | None:
    """The newest recorded turn of a session — the identity of the last
    effective configuration this session actually recorded.

    This is the *base* the sparse composition retains items from: a Profile
    that omits an item does not erase the value the native side still runs
    with (FR-02/FR-03, appendix §4).  It is read, never inferred from the
    latest Profile revision or from the overlay layer.
    """
    row = conn.execute(
        "SELECT turn_id, session_id, turn_seq, profile_id, config_revision"
        " FROM profile_turns WHERE session_id=? ORDER BY turn_seq DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return None if row is None else dict(row)


def turn_effective_items(conn: sqlite3.Connection,
                         turn_id: str) -> list[dict[str, Any]] | None:
    row = conn.execute(
        "SELECT sources_json FROM profile_turns WHERE turn_id=?",
        (turn_id,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["sources_json"])


def insert_turn(conn: sqlite3.Connection, *, turn_id: str, session_id: str,
                turn_seq: int, profile_id: str, config_revision: int,
                effective_digest: str, sources: list[dict[str, Any]],
                created_at: str) -> None:
    conn.execute(
        "INSERT INTO profile_turns(turn_id, session_id, turn_seq, profile_id,"
        " config_revision, effective_digest, sources_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (turn_id, session_id, turn_seq, profile_id, config_revision,
         effective_digest,
         json.dumps(sources, ensure_ascii=False, sort_keys=True), created_at),
    )


# --- sessions ---

def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    return row_to_dict(conn.execute(
        "SELECT * FROM profile_sessions WHERE session_id=?", (session_id,),
    ).fetchone())


def get_session_by_uid(conn: sqlite3.Connection, session_uid: str) -> dict[str, Any] | None:
    """Canonical identity lookup (v2); falls back to the legacy id only in
    the session service, never here."""
    return row_to_dict(conn.execute(
        "SELECT * FROM profile_sessions WHERE session_uid=?", (session_uid,),
    ).fetchone())


def upsert_session(conn: sqlite3.Connection, *, session_id: str,
                   harness_id: str, current_profile_id: str,
                   current_revision: int, switch_state: str,
                   pending_profile_id: str | None, pending_seq: int | None,
                   blockers: list[dict[str, Any]] | None, timestamp: str,
                   realm: str | None = None, session_uid: str | None = None,
                   native_session_key: str | None = None,
                   action_seq: int | None = None,
                   admission_facts_json: str | None = None) -> None:
    """Insert or update the session binding.

    ``action_seq`` and ``admission_facts_json`` are v3 recovery facts.  Both
    default to ``None``, which means *leave the stored value alone* on
    conflict — so a writer that only moves the safety state can never
    rewind the session's action counter or replay stale admission facts.
    """
    conn.execute(
        "INSERT INTO profile_sessions(session_id, harness_id, current_profile_id,"
        " current_revision, pending_profile_id, pending_seq, switch_state,"
        " blockers_json, created_at, updated_at, realm, native_session_key,"
        " session_uid, action_seq, admission_facts_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?, 0),?)"
        " ON CONFLICT(session_id) DO UPDATE SET"
        " current_profile_id=excluded.current_profile_id,"
        " current_revision=excluded.current_revision,"
        " pending_profile_id=excluded.pending_profile_id,"
        " pending_seq=excluded.pending_seq,"
        " switch_state=excluded.switch_state,"
        " blockers_json=excluded.blockers_json, updated_at=excluded.updated_at,"
        " realm=excluded.realm,"
        " native_session_key=excluded.native_session_key,"
        " session_uid=excluded.session_uid,"
        # A writer that omits action_seq must leave the stored counter alone.
        # The bare parameter (not `excluded.action_seq`) is what makes that
        # hold: excluded carries the INSERT-side COALESCE(?, 0), so routing it
        # through `excluded` rewound the counter to 0 on every ordinary
        # session write and broke last-action-wins (021 appendix §3.2, M04).
        " action_seq=COALESCE(?, profile_sessions.action_seq),"
        " admission_facts_json=COALESCE(excluded.admission_facts_json,"
        " profile_sessions.admission_facts_json)",
        (session_id, harness_id, current_profile_id, current_revision,
         pending_profile_id, pending_seq, switch_state,
         json.dumps(blockers, ensure_ascii=False) if blockers else None,
         timestamp, timestamp, realm, native_session_key, session_uid,
         action_seq, admission_facts_json, action_seq),
    )


def next_action_seq(conn: sqlite3.Connection, session_id: str) -> int:
    """Next session-level action index.  Selects and overlay writes both draw
    from this one counter so "which user action is later" is decidable per
    (facet_id, item_id) without a wall clock (appendix §3.2)."""
    row = conn.execute(
        "SELECT action_seq FROM profile_sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()
    return (int(row["action_seq"]) if row is not None else 0) + 1


def bump_action_seq(conn: sqlite3.Connection, session_id: str,
                    action_seq: int) -> None:
    conn.execute(
        "UPDATE profile_sessions SET action_seq=? WHERE session_id=?",
        (action_seq, session_id),
    )


def set_admission_facts(conn: sqlite3.Connection, session_id: str,
                        facts_json: str) -> None:
    conn.execute(
        "UPDATE profile_sessions SET admission_facts_json=?"
        " WHERE session_id=?", (facts_json, session_id),
    )


def session_overlays(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(
        "SELECT facet_id, item_id, value_json, facet_version, created_at,"
        " updated_at, action_seq, revision FROM profile_session_overlays"
        " WHERE session_id=? ORDER BY facet_id, item_id", (session_id,),
    ).fetchall()]


def upsert_overlay(conn: sqlite3.Connection, *, session_id: str, facet_id: str,
                   item_id: str, value_json: str, facet_version: str,
                   timestamp: str, action_seq: int) -> int:
    """Write one overlay row and return its new write revision.

    The revision increments on *every* upsert, including a rewrite of the
    identical value: a same-value rewrite is a fresh user intent and must
    survive an earlier admission's consumption (P09).  Comparing values or
    timestamps can never prove that.
    """
    conn.execute(
        "INSERT INTO profile_session_overlays(session_id, facet_id, item_id,"
        " value_json, facet_version, created_at, updated_at, action_seq,"
        " revision) VALUES (?,?,?,?,?,?,?,?,1)"
        " ON CONFLICT(session_id, facet_id, item_id) DO UPDATE SET"
        " value_json=excluded.value_json, facet_version=excluded.facet_version,"
        " updated_at=excluded.updated_at,"
        " action_seq=excluded.action_seq,"
        " revision=profile_session_overlays.revision + 1",
        (session_id, facet_id, item_id, value_json, facet_version, timestamp,
         timestamp, action_seq),
    )
    row = conn.execute(
        "SELECT revision FROM profile_session_overlays WHERE session_id=?"
        " AND facet_id=? AND item_id=?",
        (session_id, facet_id, item_id),
    ).fetchone()
    return int(row["revision"])


def consume_overlays(conn: sqlite3.Connection, *, session_id: str,
                     revisions: dict[tuple[str, str], int]) -> list[tuple[str, str]]:
    """CAS consumption of the overlay layer (appendix §4).

    Only rows inside the frozen admission mask whose current ``revision``
    still equals the frozen snapshot are removed.  A row written *during*
    the application — including one rewritten with the identical value —
    carries a higher revision and is deliberately left for the next turn.

    Returns the items actually consumed (useful for evidence/tests).
    """
    consumed: list[tuple[str, str]] = []
    for (facet_id, item_id), revision in sorted(revisions.items()):
        cur = conn.execute(
            "DELETE FROM profile_session_overlays WHERE session_id=? AND"
            " facet_id=? AND item_id=? AND revision=?",
            (session_id, facet_id, item_id, revision),
        )
        if cur.rowcount:
            consumed.append((facet_id, item_id))
    return consumed



def delete_overlay(conn: sqlite3.Connection, *, session_id: str, facet_id: str,
                   item_id: str) -> int:
    cur = conn.execute(
        "DELETE FROM profile_session_overlays WHERE session_id=? AND facet_id=?"
        " AND item_id=?", (session_id, facet_id, item_id),
    )
    return cur.rowcount
