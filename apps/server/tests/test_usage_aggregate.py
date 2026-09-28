"""Order 53: usage aggregation over the ledger — real sums, honest unknowns.

The rules under test: sums come only from turns whose family reported usage;
turns without a fact are counted as unknown (never zero); and a session with
no reported turns aggregates to an explicitly-unknown result — never to zeros
that look like data.
"""
from __future__ import annotations

from ordessa_server_compat.usage_aggregate import UsageAggregator
from pacthold_runtime_compat.storage.database import Database

PROFILE_ID = "profile"
SESSION_A = "ses-a"
SESSION_B = "ses-b"
SESSION_EMPTY = "ses-empty"


def _seed(tmp_path, turns):
    """turns: list of (turn_id, session_id, i, o, t, source); i/o/t may be None."""
    db = Database(tmp_path)
    db.initialize()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO server_workspaces (id, connection_id, distribution,"
            " remote_user, remote_path, connection_state, created_at,"
            " updated_at) VALUES ('ws', 'conn', 'Ubuntu', 'tester', '/ws',"
            " 'connected', datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO server_profiles (id, version, name, harness_type,"
            " config_revision, config_object_digest, created_at, updated_at)"
            " VALUES ('profile', 1, 'profile', 'pi', 1, 'sha256:config',"
            " datetime('now'), datetime('now'))"
        )
        for session_id in (SESSION_A, SESSION_B, SESSION_EMPTY):
            conn.execute(
                "INSERT INTO server_sessions (id, workspace_id, profile_id,"
                " status, version, created_at, updated_at) VALUES"
                " (?, 'ws', 'profile', 'ready', 1, datetime('now'),"
                "  datetime('now'))",
                (session_id,),
            )
        for turn_id, session_id, i, o, t, source in turns:
            conn.execute(
                "INSERT INTO server_turns (id, session_id, profile_id,"
                " profile_revision, native_generation, state, capture_state,"
                " cleanup_state, input_object_digest, created_at, updated_at,"
                " usage_input_tokens, usage_output_tokens, usage_total_tokens,"
                " usage_source)"
                " VALUES (?,?, 'profile', 0, 0, 'completed', 'captured',"
                " 'cleaned', 'sha256:x', datetime('now'), datetime('now'),"
                " ?, ?, ?, ?)",
                (turn_id, session_id, i, o, t, source),
            )
    return db


def test_sums_only_reported_turns(tmp_path):
    db = _seed(tmp_path, turns=[
        ("t-1", SESSION_A, 11, 7, 18, "pi-acp-journal"),
        ("t-2", SESSION_B, 5, 3, 8, None),
        ("t-3", SESSION_EMPTY, None, None, None, None),
    ])
    agg = UsageAggregator(db)
    result = agg.aggregate_by_session([SESSION_A, SESSION_B, SESSION_EMPTY])
    assert result[SESSION_A]["inputTokens"] == 11
    assert result[SESSION_A]["outputTokens"] == 7
    assert result[SESSION_A]["totalTokens"] == 18
    assert result[SESSION_A]["turnsReported"] == 1
    assert result[SESSION_B]["totalTokens"] == 8
    assert result[SESSION_B]["turnsUnknown"] == 0
    assert result[SESSION_EMPTY]["totalTokens"] is None
