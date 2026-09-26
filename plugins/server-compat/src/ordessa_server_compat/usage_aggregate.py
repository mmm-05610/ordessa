"""Order 53: usage aggregation over the turn ledger — real numbers only.

The aggregate answers "how many tokens did this session (or this time range)
consume" strictly from what the families' own stores reported through the
completion boundary (``server_turns.usage_*_tokens``). A turn whose family
reported nothing is counted as *unknown*, never as zero; a session with no
reported turns aggregates to an explicitly-unknown result. No estimation, no
defaults, no cross-session leakage: every query is scoped by session ids the
caller already has.
"""
from __future__ import annotations

import json
from typing import Any

from pacthold.storage.database import Database


class UsageAggregator:
    """Read-only usage aggregation over completed turns."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def aggregate_by_session(self, session_ids: list[str]) -> dict[str, Any]:
        """Per-session usage sums with honest unknown accounting.

        **Aggregate root = a session's top-level (root) turns, and a delegated
        child turn rolls up into its parent's root** (Order 140, `65:78`). A child
        turn runs inside its parent's tool call but is recorded in a *different*
        session, so a purely session-scoped sum under-bills the conversation that
        spent the tokens. Here each completed turn is attributed to the session of
        the topmost turn in its `parent_turn_id` chain, so:

        * a delegated child's (and grandchild's) usage lands on the parent root, once;
        * a turn is never counted under two roots (no double count);
        * a session that delegates nothing reduces to its own completed turns
          exactly as before - every turn is its own root - so those numbers are
          byte-for-byte unchanged.

        Returns one entry per requested session id. Sessions with no reported
        turns show ``totalTokens: None`` — unknown, not zero.
        """
        result: dict[str, Any] = {}
        if not session_ids:
            return result
        with self.database.read() as conn:
            for session_id in session_ids:
                root_ids = [
                    str(row["id"]) for row in conn.execute(
                        "SELECT id FROM server_turns WHERE session_id=? "
                        "AND parent_turn_id IS NULL",
                        (session_id,),
                    ).fetchall()
                ]
                rows, unknown = self._subtree_usage(conn, root_ids)
                latest = conn.execute(
                    "SELECT latest_usage FROM server_sessions WHERE id=?",
                    (session_id,),
                ).fetchone()

                latest_usage = None
                if latest and latest[0]:
                    try:
                        latest_usage = json.loads(latest[0])
                    except ValueError:
                        latest_usage = None
                reported = len(rows)
                if reported == 0:
                    # No reported turns: the honest answer is unknown, not a
                    # zero that would read as "measured nothing".
                    result[session_id] = {
                        "inputTokens": None, "outputTokens": None,
                        "totalTokens": None, "turnsReported": 0,
                        "turnsUnknown": unknown,
                        "latestUsage": latest_usage,
                    }
                else:
                    result[session_id] = {
                        "inputTokens": sum(r["i"] or 0 for r in rows),
                        "outputTokens": sum(r["o"] or 0 for r in rows),
                        "totalTokens": sum(r["t"] or 0 for r in rows),
                        "turnsReported": reported,
                        "turnsUnknown": unknown,
                        "latestUsage": latest_usage,
                    }
        return result

    @staticmethod
    def _subtree_usage(conn, root_ids: list[str]) -> tuple[list[dict], int]:
        """Completed turns (and the unknown count) in the subtrees rooted at
        ``root_ids``, following delegated children transitively. Each turn belongs
        to exactly one root, so a caller that sums several sessions never counts a
        turn twice."""
        rows: list[dict] = []
        unknown = 0
        frontier = list(root_ids)
        seen = set(root_ids)
        while frontier:
            for turn_id in frontier:
                row = conn.execute(
                    "SELECT usage_input_tokens AS i, usage_output_tokens AS o, "
                    "usage_total_tokens AS t, usage_source AS src "
                    "FROM server_turns WHERE id=? AND state='completed'",
                    (turn_id,),
                ).fetchone()
                if row is None:
                    continue
                if row["i"] is None:
                    unknown += 1
                else:
                    rows.append(dict(row))
            children = []
            for turn_id in frontier:
                for child in conn.execute(
                    "SELECT id FROM server_turns WHERE parent_turn_id=?", (turn_id,),
                ).fetchall():
                    if child["id"] not in seen:
                        seen.add(child["id"])
                        children.append(str(child["id"]))
            frontier = children
        return rows, unknown



__all__ = ["UsageAggregator"]
