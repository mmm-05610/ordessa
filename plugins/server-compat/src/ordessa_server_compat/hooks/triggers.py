"""Order 59 G5: hook trigger facts - bounded, scanned, honestly labelled.

One trigger row per observed hook execution: which hook, which event, when,
the exit code, and a **bounded** output summary. Two rules are this module's
own and both are counter-tested:

* **blocking is a fact, not a mood**: an exit code of 2 is the families'
  blocking signal for the events that define it, so the row carries
  ``blocking=True`` and ``effect="blocked"``. Everything else is ``"ran"``
  (exit 0) or ``"failed"`` - never silently folded into "success";
* **the summary is bounded and scanned**: the text is truncated to a fixed
  budget with the truncation recorded, and a summary that carries the
  execution's injected credential material is refused outright - an output
  line is not a place a secret may rest.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_server.errors import ServerError
from ordessa_server.ids import now, opaque_id
from pacthold.storage import Database

MAX_SUMMARY_CHARS = 512
#: The families' blocking exit code (Claude Code documents `exit 2` as the
#: blocking result for the events that define one; Codex shares the shape).
BLOCKING_EXIT_CODE = 2


class TriggerError(RuntimeError):
    """A typed refusal of one trigger fact."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def classify_exit(exit_code: int) -> tuple[bool, str]:
    """(blocking, effect) for one exit code, as the ledger will present it."""
    if exit_code == BLOCKING_EXIT_CODE:
        return True, "blocked"
    if exit_code == 0:
        return False, "ran"
    return False, "failed"


class HookTriggerRecords:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(
        self, *, hook_id: str, event: str, exit_code: int,
        output: bytes | str | None = None, forbidden: bytes | None = None,
        at: str | None = None,
    ) -> dict[str, Any]:
        """Ingest one trigger fact; the summary is bounded and scanned first."""
        if not isinstance(hook_id, str) or not hook_id:
            raise TriggerError("HOOK_TRIGGER_INVALID", "a trigger names its hook")
        if not isinstance(event, str) or not event:
            raise TriggerError("HOOK_TRIGGER_INVALID", "a trigger names its event")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise TriggerError("HOOK_TRIGGER_INVALID", "exit_code must be an integer")
        raw = output.encode("utf-8", errors="replace") if isinstance(output, str) else (output or b"")
        secret = forbidden or b""
        if secret and secret in raw:
            raise TriggerError(
                "HOOK_TRIGGER_CONTAINS_SECRET",
                "the output summary carries credential material and is not stored",
            )
        truncated = len(raw) > MAX_SUMMARY_CHARS
        summary = raw[:MAX_SUMMARY_CHARS].decode("utf-8", errors="replace")
        blocking, effect = classify_exit(exit_code)
        with self.database.transaction() as conn:
            if conn.execute("SELECT 1 FROM server_hooks WHERE id=?", (hook_id,)).fetchone() is None:
                raise ServerError("HOOK_NOT_FOUND", "Hook was not found", status=404)
            trigger_id = opaque_id("trigger")
            timestamp = at or now()
            conn.execute(
                "INSERT INTO server_hook_triggers(id,hook_id,event,at,exit_code,"
                "output_summary,summary_truncated,blocking,effect) VALUES (?,?,?,?,?,?,?,?,?)",
                (trigger_id, hook_id, event, timestamp, exit_code, summary,
                 1 if truncated else 0, 1 if blocking else 0, effect),
            )
            return self._view(conn, trigger_id)

    def list(self, *, hook_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise TriggerError("HOOK_TRIGGER_INVALID", "limit must be 1..500")
        with self.database.read() as conn:
            if hook_id is None:
                rows = conn.execute(
                    "SELECT * FROM server_hook_triggers ORDER BY at DESC, id DESC LIMIT ?",
                    (limit,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM server_hook_triggers WHERE hook_id=? "
                    "ORDER BY at DESC, id DESC LIMIT ?", (hook_id, limit)).fetchall()
        return [self._view_row(row) for row in rows]

    def _view(self, conn, trigger_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM server_hook_triggers WHERE id=?", (trigger_id,)).fetchone()
        return self._view_row(row)

    def _view_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "trigger_id": row["id"],
            "hook_id": row["hook_id"],
            "event": row["event"],
            "at": row["at"],
            "exit_code": int(row["exit_code"]),
            "output_summary": row["output_summary"],
            "truncated": bool(row["summary_truncated"]),
            "blocking": bool(row["blocking"]),
            "effect": row["effect"],
        }


def trigger_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """The wire-facing trigger shape: the same facts, camelCase.

    Accepts either a ledger row (``output_summary`` / ``summary_truncated``)
    or the record layer's own view (``output_summary`` with ``truncated``),
    so every handler projects through this one function.
    """
    raw = "summary_truncated" in row
    return {
        "triggerId": row["id"] if raw else row["trigger_id"],
        "hookId": row["hook_id"],
        "event": row["event"],
        "at": row["at"],
        "exitCode": int(row["exit_code"]),
        "outputSummary": row["output_summary"],
        "truncated": bool(row["summary_truncated"] if raw else row["truncated"]),
        "blocking": bool(row["blocking"]),
        "effect": row["effect"],
    }
