"""Storage for Sessions, Turns, and durable session events.

Each business acceptance runs inside exactly one `BEGIN IMMEDIATE`
transaction that also inserts its idempotency row, so concurrent racers
cannot both own an acceptance: the loser observes the committed receipt.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from ordessa_server.errors import ServerError
from ordessa_server_compat.execution.session_store_guard import SessionStoreGuardError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.ids import now, opaque_id
from pacthold.storage import Database


#: A Turn is active while it can still be stopped or dispatched. Terminal states
#: (`completed`, `failed`, `cancelled`, `unknown`) are history: nothing that arrives
#: afterwards changes what happened.
ACTIVE_TURN_STATES = ("accepted", "dispatching", "running", "capturing")

#: The complement: a Turn that already happened. Exposed so both cancel entry
#: points (the wire method and the retained REST route) answer the same thing.
TERMINAL_TURN_STATES = ("completed", "failed", "cancelled", "unknown")

#: Kinds that get a `wire_seq`. This must be **exactly** the set of kinds the wire
#: turns into frames (`wire/projection.py:_EVENT_KIND_MAP`) — a kind that produces a
#: frame but is missing here gets no number, and `event_frame` then falls back to the
#: storage `seq`, so the same stream carries two number spaces and a client that
#: sorts or de-duplicates by `seq` drops the body and the tool cards (`AUD-B-010`).
#: The equivalence is a gate, not a comment:
#: `tests/server/test_wire_seq_numbering_spaces_128.py`.
WIRE_VISIBLE_EVENT_KINDS = frozenset({
    "turn.accepted", "turn.state", "message.delta", "message.final", "tool.update",
    "approval.requested", "approval.settled", "config.changed", "queue.updated",
    "workspace.connection",
    # Order 128: these four produce frames and were never numbered.
    "usage.updated", "thought.delta", "plan.updated", "mode.updated",
})


def _version_error(message: str, current: dict[str, Any]) -> ServerError:
    error = ServerError("RECORD_VERSION_CONFLICT", message, status=409)
    error.current = current  # type: ignore[attr-defined]
    return error


class SessionRecords:
    #: Re-exported on the class so callers holding a records object (the wire
    #: handlers, the session service) can ask the same question without importing
    #: this module's module-level names.
    ACTIVE_TURN_STATES = ACTIVE_TURN_STATES
    TERMINAL_TURN_STATES = TERMINAL_TURN_STATES

    def __init__(self, database: Database, idempotency: IdempotentRecords, *,
                 home_concurrency: Mapping[str, str] | None = None,
                 shared_store_guards: Mapping[str, Callable[[], None]] | None = None,
                 core_filer: Callable[..., Mapping[str, Any]] | None = None) -> None:
        self.database = database
        self.idempotency = idempotency
        #: a-3 K2-S/K2-S' single filing seam (see attach_core_filer).
        self.core_filer = core_filer
        #: Order 66 stage B: per-family read-only guards for the shared session
        #: library, run before a role switch is admitted. A family absent from
        #: this mapping has no shared store to guard (profile-home) or has
        #: none that carries credential tables.
        self.shared_store_guards = dict(shared_store_guards or {})
        #: Order 67's narrowed lock, per Harness family: a family whose home
        #: cannot be proven safe for concurrent writers declares "exclusive"
        #: in its deployment, and admission then holds the pre-67 rule for
        #: that family alone (one active Turn per Profile). "shared" - every
        #: family with first-hand evidence of safe concurrent turns - leaves
        #: the Session as the only uniqueness unit. Families absent from this
        #: mapping keep "shared": the lock is declared, never guessed.
        self.home_concurrency = dict(home_concurrency or {})

    def _refuse_exclusive_home_concurrency(self, conn, profile) -> None:
        """The narrowed lock: refuse a second active Turn for one Profile.

        Only families that declared `homeConcurrency = "exclusive"` reach the
        check; the refusal names the asset (the Harness home), so a client can
        tell this apart from the Session-scoped admission above.
        """
        if self.home_concurrency.get(str(profile["harness_type"]), "shared") != "exclusive":
            return
        active = conn.execute(
            "SELECT 1 FROM server_turns WHERE profile_id=? AND state IN (?,?,?,?) LIMIT 1",
            (profile["id"], *ACTIVE_TURN_STATES),
        ).fetchone()
        if active is not None:
            raise ServerError(
                "TURN_CONCURRENCY_CONFLICT",
                "Profile already has an active execution: this Harness's home "
                "permits one execution at a time",
                status=409,
            )

    # -- session records -------------------------------------------------

    def create_session(
        self, *, key: str, request_digest: str, workspace_id: str, profile_id: str,
    ) -> tuple[int, dict[str, Any]]:
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, "POST:/sessions", key, request_digest)
            if prior:
                return prior
            if conn.execute(
                "SELECT 1 FROM server_workspaces WHERE id=?", (workspace_id,),
            ).fetchone() is None:
                raise ServerError("WORKSPACE_NOT_FOUND", "Workspace was not found", status=404)
            if conn.execute(
                "SELECT 1 FROM server_profiles WHERE id=?", (profile_id,),
            ).fetchone() is None:
                raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
            timestamp = now()
            body = {
                "session_id": opaque_id("session"), "workspace_id": workspace_id,
                "profile_id": profile_id, "status": "ready", "checkpoint": None,
            }
            conn.execute(
                "INSERT INTO server_sessions(id,workspace_id,profile_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (body["session_id"], workspace_id, profile_id, "ready", timestamp, timestamp),
            )
            self.idempotency.insert(conn, "POST:/sessions", key, request_digest, 201, body)
            return 201, body

    # -- wire/1 intent acceptance (one transaction owns it) ---------------

    def accept_intent(
        self, *, session_id: str | None, workspace_id: str | None, profile_id: str,
        request_id: str, request_digest: str, message_object_digest: str,
        public_message: Mapping[str, Any],
        display_name: str | None = None,
        overrides: list[dict[str, Any]] | None = None,
        expected_version: int | None = None, queue_records=None,
        resolve_config_version=None,
        effective_config_object_digest: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Accept one send intent atomically.

        Returns `(outcome, body)` where outcome is `accepted` for the winner and
        `replay` for a duplicate delivery of the same requestId. One
        transaction either creates the Session with its first execution, or
        enqueues a follow-up item behind the running execution; a duplicate
        requestId never creates or dispatches anything.
        """
        scope = "sessions.send"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, request_id, request_digest)
            if prior:
                return "replay", prior[1]

            if session_id is None:
                if workspace_id is None:
                    raise ServerError("WORKSPACE_NOT_FOUND", "Workspace was not found", status=404)
                if conn.execute(
                    "SELECT 1 FROM server_workspaces WHERE id=?", (workspace_id,),
                ).fetchone() is None:
                    raise ServerError("WORKSPACE_NOT_FOUND", "Workspace was not found", status=404)
                session_id = opaque_id("session")
                timestamp = now()
                conn.execute(
                    "INSERT INTO server_sessions(id,workspace_id,profile_id,status,display_name,version,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (session_id, workspace_id, profile_id, "ready", display_name, 1, timestamp, timestamp),
                )
            else:
                session = conn.execute(
                    "SELECT * FROM server_sessions WHERE id=?", (session_id,),
                ).fetchone()
                if session is None:
                    raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)
                if bool(session["archived_at"]):
                    raise ServerError("SESSION_ARCHIVED", "Session is archived", status=409)
                if expected_version is not None and int(session["version"]) != expected_version:
                    raise ServerError(
                        "RECORD_VERSION_CONFLICT",
                        "Session changed before the send was accepted",
                        status=409,
                    )
                if session["profile_id"] != profile_id:
                    # A running Session may only switch role through the
                    # explicit switch method, which can be refused.
                    raise ServerError(
                        "CAPABILITY_UNSUPPORTED",
                        "Session is bound to a different role; switch the role first",
                        status=409,
                    )

            profile = conn.execute(
                "SELECT * FROM server_profiles WHERE id=?", (profile_id,),
            ).fetchone()
            if profile is None:
                raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
            if bool(profile["archived_at"]):
                raise ServerError("PROFILE_ARCHIVED", "Profile is archived", status=409)
            if bool(profile["recovery_pending"]):
                raise ServerError(
                    "PROFILE_RECOVERY_REQUIRED",
                    "Profile has unresolved recovery evidence",
                    status=409,
                )
            config_version = int(profile["config_revision"])
            if resolve_config_version is not None:
                config_version = int(resolve_config_version(conn, profile, overrides))

            self._append_session_event(
                conn, session_id, None, "message.final",
                {
                    "message_id": opaque_id("message"), "role": "user",
                    "display_kind": "visible", "text": str(public_message.get("text", "")),
                },
            )

            active = conn.execute(
                "SELECT * FROM server_turns WHERE session_id=? AND state IN "
                "('accepted','dispatching','running','capturing') ORDER BY created_at LIMIT 1",
                (session_id,),
            ).fetchone()
            if active is None:
                execution_id = self._insert_execution(
                    conn, session_id=session_id, profile=profile,
                    config_version=config_version,
                    input_object_digest=message_object_digest,
                    effective_config_object_digest=effective_config_object_digest,
                )
                body = {
                    "outcome": "accepted", "sessionId": session_id,
                    "executionId": execution_id, "configVersion": config_version,
                    "queued": False,
                }
            else:
                if queue_records is None:
                    raise ServerError(
                        "QUEUE_ITEM_NOT_FOUND", "Queue storage is unavailable", status=503,
                    )
                item = queue_records.enqueue_in_transaction(
                    conn, session_id=session_id, profile_id=profile_id,
                    config_version=config_version, request_id=request_id,
                    request_digest=request_digest,
                    message_object_digest=message_object_digest,
                    effective_config_object_digest=effective_config_object_digest,
                    public_message=public_message,
                )
                body = {
                    "outcome": "accepted", "sessionId": session_id,
                    "executionId": None, "configVersion": config_version,
                    "queued": True, "queueItemId": item["itemId"],
                }

            self.idempotency.insert(conn, scope, request_id, request_digest, 202, body)
            return "accepted", body

    def _insert_execution(
        self, conn, *, session_id: str, profile, config_version: int,
        input_object_digest: str, effective_config_object_digest: str | None = None,
        queue_item_id: str | None = None,
    ) -> str:
        execution_id = opaque_id("execution")
        timestamp = now()
        self._refuse_exclusive_home_concurrency(conn, profile)
        try:
            conn.execute(
                "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,native_generation,"
                "state,capture_state,cleanup_state,input_object_digest,effective_config_object_digest,"
                "queue_item_id,execution_key,created_at,updated_at) "
                "VALUES (?,?,?,?,?,'accepted','pending','pending',?,?,?,?,?,?)",
                (execution_id, session_id, profile["id"], config_version,
                 int(profile["native_generation"]), input_object_digest,
                 effective_config_object_digest, queue_item_id,
                 f"execution:{execution_id}", timestamp, timestamp),
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ServerError(
                    "TURN_CONCURRENCY_CONFLICT",
                    "Session already has an active execution",
                    status=409,
                ) from exc
            raise
        conn.execute(
            "UPDATE server_profiles SET run_state='active',updated_at=? WHERE id=?",
            (timestamp, profile["id"]),
        )
        conn.execute(
            "UPDATE server_sessions SET status='active',version=version+1,updated_at=? WHERE id=?",
            (timestamp, session_id),
        )
        self._append_session_event(
            conn, session_id, execution_id, "turn.accepted",
            {"state": "accepted", "profile_revision": config_version},
        )
        return execution_id

    def switch_profile(
        self, *, session_id: str, profile_id: str, expected_version: int, request_id: str,
        request_digest: str,
    ) -> tuple[str, dict[str, Any]]:
        """Switch a Session's role, or refuse while an execution is running.

        The old link is returned on refusal so the client keeps the real state
        instead of the selection it attempted.
        """
        scope = f"sessions.switchProfile:{session_id}"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, request_id, request_digest)
            if prior:
                return "replay", prior[1]
            session = conn.execute(
                "SELECT * FROM server_sessions WHERE id=?", (session_id,),
            ).fetchone()
            if session is None:
                raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)
            if int(session["version"]) != expected_version:
                raise _version_error(
                    "Session changed before the role switch", self._session_view(conn, session_id),
                )
            target = conn.execute(
                "SELECT * FROM server_profiles WHERE id=?", (profile_id,),
            ).fetchone()
            if target is None:
                raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
            if bool(target["archived_at"]):
                raise ServerError("PROFILE_ARCHIVED", "Profile is archived", status=409)
            active = conn.execute(
                "SELECT 1 FROM server_turns WHERE session_id=? AND state IN "
                "('accepted','dispatching','running','capturing') LIMIT 1",
                (session_id,),
            ).fetchone()
            if active is not None:
                body = {
                    "outcome": "rejected",
                    "reason": "execution_running",
                    "session": self._session_view(conn, session_id),
                }
                self.idempotency.insert(conn, scope, request_id, request_digest, 200, body)
                return "rejected", body
            # Order 66 stage B: the switch's preflight. Switching keeps the
            # Session and changes which role advances it, so it is only ever a
            # same-family move (cross-family is the clone rule, 60 G5), the
            # target role must not be mid-turn, and the family's shared store
            # must pass its read-only credential guard. The data layer does
            # nothing: the store is the same directory either way.
            current = None
            if session["profile_id"]:
                current = conn.execute(
                    "SELECT * FROM server_profiles WHERE id=?", (session["profile_id"],),
                ).fetchone()
            if (current is not None
                    and str(current["harness_type"]) != str(target["harness_type"])):
                raise ServerError(
                    "PROFILE_HARNESS_MISMATCH",
                    "A Session keeps its Harness family across a role switch; "
                    "cross-family work starts as a new Session",
                    status=409,
                )
            target_active = conn.execute(
                "SELECT 1 FROM server_turns WHERE profile_id=? AND state IN "
                "('accepted','dispatching','running','capturing') LIMIT 1",
                (profile_id,),
            ).fetchone()
            if target_active is not None:
                raise ServerError(
                    "TURN_CONCURRENCY_CONFLICT",
                    "The target Profile already has an active execution",
                    status=409,
                )
            guard = self.shared_store_guards.get(str(target["harness_type"]))
            if guard is not None:
                workspace = conn.execute(
                    "SELECT env_kind FROM server_workspaces WHERE id=?",
                    (session["workspace_id"],),
                ).fetchone()
                env_kind = str(workspace["env_kind"]) if workspace is not None else ""
                if env_kind != "local":
                    # Fail closed: the guard reads the library on this machine,
                    # and a remote placement's library is not here yet. A
                    # switch that cannot be guarded is refused, never waved
                    # through (order 66 §3).
                    raise ServerError(
                        "SESSION_STORE_GUARD_UNAVAILABLE",
                        "the shared session store of this family lives on a "
                        "remote machine and cannot be guarded here",
                        status=409,
                    )
                try:
                    guard()
                except SessionStoreGuardError as exc:
                    raise ServerError(
                        exc.code, exc.message or "the shared session store was refused",
                        status=409,
                    ) from exc
            timestamp = now()
            # Switching to the role the Session already uses changes nothing, so
            # the record is written (the version still moves, as any accepted
            # write does) but no `config.changed` is published: that event means
            # "the effective configuration changed", and reporting it here would
            # tell the client to re-read a configuration that did not move.
            configuration_changed = str(session["profile_id"] or "") != profile_id
            if configuration_changed:
                # Order 66 §0: each execution materialises the *current*
                # binding. The recorded home locator pinned the previous
                # role's home; after a switch the next turn must derive the
                # new role's home instead (the session's own state lives in
                # the shared family library, not in the role directory). The
                # locator is cleared, not rewritten: derivation is the one
                # rule that survives profile renames.
                conn.execute(
                    "UPDATE server_sessions SET profile_id=?,home_locator=NULL,"
                    "version=version+1,updated_at=? WHERE id=?",
                    (profile_id, timestamp, session_id),
                )
            else:
                conn.execute(
                    "UPDATE server_sessions SET profile_id=?,version=version+1,"
                    "updated_at=? WHERE id=?",
                    (profile_id, timestamp, session_id),
                )
            if configuration_changed:
                # The Session's effective configuration just changed identity, and
                # the contract delivers that to clients as `config.changed` with the
                # window it applies to. It is `next_send` because this backend
                # freezes a configuration per execution: nothing already running is
                # rewritten (the refusal above is the running case). A replayed
                # request returns before this point, so it never emits a second one.
                self._append_session_event(
                    conn, session_id, None, "config.changed", {"effective_for": "next_send"},
                )
            body = {"outcome": "confirmed", "session": self._session_view(conn, session_id)}
            self.idempotency.insert(conn, scope, request_id, request_digest, 200, body)
            return "confirmed", body

    def list_sessions(
        self, *, workspace_id: str | None, include_archived: bool,
        after_rowid: int = 0, limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return a stable keyset page of authoritative Session records."""
        clauses = ["rowid>?"]
        values: list[Any] = [after_rowid]
        if workspace_id is not None:
            clauses.append("workspace_id=?")
            values.append(workspace_id)
        if not include_archived:
            clauses.append("archived_at IS NULL")
        values.append(limit)
        with self.database.read() as conn:
            if workspace_id is not None and conn.execute(
                "SELECT 1 FROM server_workspaces WHERE id=?", (workspace_id,),
            ).fetchone() is None:
                raise ServerError("WORKSPACE_NOT_FOUND", "Workspace was not found", status=404)
            rows = conn.execute(
                "SELECT rowid AS catalog_rowid,* FROM server_sessions WHERE "
                + " AND ".join(clauses) + " ORDER BY rowid LIMIT ?",
                tuple(values),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_session(
        self, *, session_id: str, expected_version: int, request_id: str,
        request_digest: str, display_name: str | None = None,
        pinned: bool | None = None, workspace_id: str | None = None,
    ) -> dict[str, Any]:
        scope = f"sessions.update:{session_id}"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, request_id, request_digest)
            if prior:
                return prior[1]["session"]
            row = conn.execute(
                "SELECT * FROM server_sessions WHERE id=?", (session_id,),
            ).fetchone()
            if row is None:
                raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)
            current = self._session_view(conn, session_id)
            if int(row["version"]) != expected_version:
                raise _version_error("Session changed before the update", current)
            if workspace_id is not None and workspace_id != row["workspace_id"]:
                target = conn.execute(
                    "SELECT * FROM server_workspaces WHERE id=?", (workspace_id,),
                ).fetchone()
                if target is None:
                    raise ServerError("WORKSPACE_NOT_FOUND", "Workspace was not found", status=404)
                if bool(target["archived_at"]):
                    raise ServerError("WORKSPACE_ARCHIVED", "Workspace is archived", status=409)
                active = conn.execute(
                    "SELECT 1 FROM server_turns WHERE session_id=? AND state IN "
                    "('accepted','dispatching','running','capturing') LIMIT 1",
                    (session_id,),
                ).fetchone()
                if active is not None:
                    raise ServerError(
                        "CAPABILITY_UNSUPPORTED",
                        "Session workspace cannot change while an execution is active",
                        status=409,
                    )
            timestamp = now()
            conn.execute(
                "UPDATE server_sessions SET display_name=COALESCE(?,display_name),"
                "pinned=COALESCE(?,pinned),workspace_id=COALESCE(?,workspace_id),"
                "version=version+1,updated_at=? WHERE id=?",
                (display_name, None if pinned is None else int(pinned), workspace_id,
                 timestamp, session_id),
            )
            updated = self._session_view(conn, session_id)
            self.idempotency.insert(
                conn, scope, request_id, request_digest, 200, {"session": updated},
            )
            return updated

    def archive_session(
        self, *, session_id: str, expected_version: int, request_id: str,
        request_digest: str,
    ) -> dict[str, Any]:
        scope = f"sessions.archive:{session_id}"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, request_id, request_digest)
            if prior:
                return prior[1]["session"]
            row = conn.execute(
                "SELECT * FROM server_sessions WHERE id=?", (session_id,),
            ).fetchone()
            if row is None:
                raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)
            if int(row["version"]) != expected_version:
                raise _version_error(
                    "Session changed before it was archived", self._session_view(conn, session_id),
                )
            timestamp = now()
            conn.execute(
                "UPDATE server_sessions SET archived_at=COALESCE(archived_at,?),"
                "version=version+1,updated_at=? WHERE id=?",
                (timestamp, timestamp, session_id),
            )
            updated = self._session_view(conn, session_id)
            self.idempotency.insert(
                conn, scope, request_id, request_digest, 200, {"session": updated},
            )
            return updated

    def intent_outcome(self, request_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT * FROM server_idempotency WHERE scope=? AND key=?",
                ("sessions.send", request_id),
            ).fetchone()
        if row is None:
            # "unknown" is not a safe-to-resend signal; the client must query
            # with the original identifier rather than minting a new one.
            return {"outcome": "unknown"}
        body = json.loads(row["response_json"])
        return {
            "outcome": "accepted",
            "sessionId": body["sessionId"],
            "executionId": body.get("executionId"),
            "configVersion": body["configVersion"],
            "queueItemId": body.get("queueItemId"),
        }

    @staticmethod
    def _session_view(conn, session_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM server_sessions WHERE id=?", (session_id,)).fetchone()
        return {
            "id": row["id"], "version": int(row["version"]),
            "workspaceId": row["workspace_id"], "profileId": row["profile_id"],
            "displayName": row["display_name"] or row["id"],
            "pinned": bool(row["pinned"]),
            "archivedAt": row["archived_at"],
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        }

    # -- turn acceptance (one transaction owns it) ------------------------

    def create_turn(
        self, *, session_id: str, key: str, request_digest: str,
        input_object_digest: str, expected_profile_revision: int,
        effective_config_object_digest: str,
    ) -> tuple[bool, int, dict[str, Any]]:
        """Accept one business intent.

        Returns `(claimed, status, body)`. `claimed` is true only for the
        racer whose transaction inserted the idempotency row; that racer —
        and no replay — owns the right to dispatch.
        """
        scope = f"POST:/sessions/{session_id}/turns"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, key, request_digest)
            if prior:
                return False, prior[0], prior[1]
            session = conn.execute(
                "SELECT * FROM server_sessions WHERE id=?", (session_id,),
            ).fetchone()
            if session is None:
                raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)
            profile = conn.execute(
                "SELECT * FROM server_profiles WHERE id=?", (session["profile_id"],),
            ).fetchone()
            if profile is None:
                raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
            if int(profile["config_revision"]) != expected_profile_revision:
                raise ServerError(
                    "PROFILE_REVISION_CONFLICT",
                    "Profile revision changed before Turn creation",
                    status=409,
                )
            if bool(profile["recovery_pending"]):
                raise ServerError(
                    "PROFILE_RECOVERY_REQUIRED",
                    "Profile has unresolved recovery evidence",
                    status=409,
                )
            turn_id = opaque_id("turn")
            timestamp = now()
            self._refuse_exclusive_home_concurrency(conn, profile)
            try:
                conn.execute(
                    "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,native_generation,state,capture_state,cleanup_state,input_object_digest,effective_config_object_digest,execution_key,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,'accepted','pending','pending',?,?,?,?,?)",
                    (turn_id, session_id, session["profile_id"], expected_profile_revision,
                     int(profile["native_generation"]), input_object_digest,
                     effective_config_object_digest, f"execution:{turn_id}",
                     timestamp, timestamp),
                )
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise ServerError(
                        "TURN_CONCURRENCY_CONFLICT",
                        "Session already has an active Turn",
                        status=409,
                    ) from exc
                raise
            conn.execute(
                "UPDATE server_profiles SET run_state='active',updated_at=? WHERE id=?",
                (timestamp, session["profile_id"]),
            )
            conn.execute(
                "UPDATE server_sessions SET status='active',updated_at=? WHERE id=?",
                (timestamp, session_id),
            )
            event = self._append_session_event(
                conn, session_id, turn_id, "turn.accepted",
                {"state": "accepted", "profile_revision": expected_profile_revision},
            )
            body = {
                "turn_id": turn_id, "session_id": session_id, "state": "accepted",
                "event_seq": event["seq"],
            }
            self.idempotency.insert(conn, scope, key, request_digest, 202, body)
            return True, 202, body

    # -- restart recovery evidence ----------------------------------------

    def seal_interrupted_turns(self) -> int:
        """Seal pre-restart active Turns as unknown; never redispatch them."""
        active_states = ACTIVE_TURN_STATES
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM server_turns WHERE state IN (?,?,?,?) ORDER BY created_at,id",
                active_states,
            ).fetchall()
            timestamp = now()
            for row in rows:
                conn.execute(
                    "UPDATE server_turns SET state='unknown',capture_state='unknown',"
                    "cleanup_state='unknown',error_code='SERVER_RESTART_INTERRUPTED',updated_at=? "
                    "WHERE id=?",
                    (timestamp, row["id"]),
                )
                conn.execute(
                    "UPDATE server_sessions SET status='recovery_required',updated_at=? WHERE id=?",
                    (timestamp, row["session_id"]),
                )
                self._settle_profile_after_turn(
                    conn, row["profile_id"], row["id"], timestamp, recovery_pending=1,
                )
                self._append_session_event(
                    conn, row["session_id"], row["id"], "turn.capture",
                    {"state": "unknown", "error_code": "SERVER_RESTART_INTERRUPTED"},
                )
                self._append_session_event(
                    conn, row["session_id"], row["id"], "turn.state",
                    {"state": "unknown", "error_code": "SERVER_RESTART_INTERRUPTED"},
                )
            return len(rows)

    # -- dispatch/cancel/terminal transitions ------------------------------

    def get_turn_context(self, turn_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT t.*,s.workspace_id,s.checkpoint_object_digest,s.checkpoint_native_id,"
                "s.native_platform,s.home_locator,"
                "p.harness_type,p.name AS profile_name,"
                "p.config_object_digest AS profile_config_object_digest,"
                "t.effective_config_object_digest AS config_object_digest,"
                "p.credential_id,p.account_id,"
                "p.permission_preset,p.permission_rules_json,p.origin_profile_id,"
                "w.connection_id,w.distribution,w.remote_user,w.remote_path,"
                "w.env_kind,w.env_host,w.normalized_path "
                "FROM server_turns t JOIN server_sessions s ON s.id=t.session_id "
                "JOIN server_profiles p ON p.id=t.profile_id "
                "JOIN server_workspaces w ON w.id=s.workspace_id WHERE t.id=?",
                (turn_id,),
            ).fetchone()
        if row is None:
            raise ServerError("TURN_NOT_FOUND", "Turn was not found", status=404)
        return dict(row)

    def attach_core_filer(self, filer) -> None:
        """Compose the Core filing collaborator exactly once (no probing)."""
        if self.core_filer is not None and self.core_filer is not filer:
            raise ServerError(
                "IDEMPOTENCY_CONFLICT", "Core filer already composed", status=409,
            )
        self.core_filer = filer

    def file_core_records(self, turn_id: str) -> None:
        """a-3 K2-S/K2-S': post-commit Core filing, idempotency-first.

        The single implementation home for every filing point: the three
        acceptance entries route here through the service, and the queue-
        adoption successor is filed by `complete_turn` itself right after its
        transaction commits. Dormant while no filer is composed (the runtime
        wiring flips with the E leg - confluence by construction, never a
        double-file window). The turn's own `execution_key` (or, for rows
        predating the migration, its turn-id derivation) is the Work Core
        idempotency key, so a replay re-files nothing; the receipt's
        correlation is persisted as given, never computed here.
        """
        if self.core_filer is None:
            return
        filing = self.get_turn_filing(turn_id)
        if filing["work_id"] is not None or filing["dispatch_id"] is not None:
            return
        execution_key = filing["execution_key"] or f"execution:{turn_id}"
        receipt = self.core_filer(
            turn_id=turn_id, session_id=filing["session_id"],
            execution_key=execution_key,
        )
        self.set_turn_dispatch(
            turn_id, work_id=receipt["work_id"],
            execution_id=receipt["core_execution_id"],
            dispatch_id=receipt["dispatch_id"], state="accepted",
        )

    def get_turn_filing(self, turn_id: str) -> dict[str, Any]:
        """The filing facts of one Turn (a-3 K2-S): key, links, session.

        Deliberately narrow: the post-commit filing step must see exactly the
        idempotency inputs and the current Core links (NULL until filed), and
        nothing else - it never re-reads the live Profile.
        """
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT id,session_id,execution_key,work_id,execution_id,dispatch_id "
                "FROM server_turns WHERE id=?",
                (turn_id,),
            ).fetchone()
        if row is None:
            raise ServerError("TURN_NOT_FOUND", "Turn was not found", status=404)
        return dict(row)

    def set_turn_dispatch(
        self, turn_id: str, *, work_id: str, execution_id: str,
        dispatch_id: str, state: str = "running",
    ) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM server_turns WHERE id=?", (turn_id,)).fetchone()
            if row is None:
                raise ServerError("TURN_NOT_FOUND", "Turn was not found", status=404)
            conn.execute(
                "UPDATE server_turns SET work_id=?,execution_id=?,dispatch_id=?,state=?,updated_at=? WHERE id=?",
                (work_id, execution_id, dispatch_id, state, now(), turn_id),
            )
            return self._append_session_event(
                conn, row["session_id"], turn_id, "turn.state", {"state": state},
            )

    def append_turn_event(self, turn_id: str, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute("SELECT session_id FROM server_turns WHERE id=?", (turn_id,)).fetchone()
            if row is None:
                raise ServerError("TURN_NOT_FOUND", "Turn was not found", status=404)
            return self._append_session_event(conn, row["session_id"], turn_id, kind, data)

    def _settle_profile_after_turn(
        self, conn, profile_id: str, turn_id: str, timestamp: str, *,
        recovery_pending: int | None = None,
    ) -> bool:
        """Set the Profile idle only when no *other* active Turn remains.

        Order 67: the uniqueness unit is the Session, so two different
        Sessions of one Profile may run at the same time. A finishing Turn
        must therefore not stamp the Profile idle while its sibling is still
        in flight - the last active Turn settles the Profile. Returns whether
        the Profile was settled by this call.
        """
        other = conn.execute(
            "SELECT 1 FROM server_turns WHERE profile_id=? AND id<>? "
            "AND state IN (?,?,?,?) LIMIT 1",
            (profile_id, turn_id, *ACTIVE_TURN_STATES),
        ).fetchone()
        if other is not None:
            return False
        if recovery_pending is None:
            conn.execute(
                "UPDATE server_profiles SET run_state='idle',updated_at=? WHERE id=?",
                (timestamp, profile_id),
            )
        else:
            conn.execute(
                "UPDATE server_profiles SET run_state='idle',recovery_pending=?,"
                "updated_at=? WHERE id=?",
                (recovery_pending, timestamp, profile_id),
            )
        return True

    def complete_turn(
        self, turn_id: str, *, checkpoint_object_digest: str,
        checkpoint_native_id: str, result_object_digest: str, queue_records=None,
        native_platform: str | None = None, home_locator: str | None = None,
        usage: dict[str, Any] | None = None, usage_source: str | None = None,
        change_set_object_digest: str | None = None,
        terminal_reason: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM server_turns WHERE id=?", (turn_id,)).fetchone()
            if row is None:
                raise ServerError("TURN_NOT_FOUND", "Turn was not found", status=404)
            if row["state"] == "completed":
                events = conn.execute(
                    "SELECT * FROM server_session_events WHERE turn_id=? AND kind='turn.capture' ORDER BY seq DESC LIMIT 1",
                    (turn_id,),
                ).fetchone()
                return dict(row), self._event_dict(events)
            if row["state"] not in {"running", "capturing"}:
                raise ServerError("TURN_STATE_CONFLICT", "Turn cannot complete from its current state", status=409)
            timestamp = now()
            # Order 51: the usage fact, tokens only, exactly as the family's
            # own store reported them. Absent stays absent (NULL): no zeroes,
            # no estimates, no per-character stand-ins.
            usage_columns = ""
            usage_values: list[Any] = []
            change_set_column = ""
            change_set_values: list[Any] = []
            if change_set_object_digest:
                change_set_column = ",change_set_object_digest=?"
                change_set_values = [change_set_object_digest]
            # Order 134 (122 consumer side): a harness completion may carry a
            # machine-readable stop reason (e.g. max_tokens). When present and
            # not a clean end_turn we persist it in terminal_reason so the wire
            # projection's `reason` surfaces truncation. Absent -> we do not add
            # the column at all, so the UPDATE is byte-identical to before.
            terminal_column = ""
            terminal_values: list[Any] = []
            if terminal_reason is not None:
                terminal_column = ",terminal_reason=?"
                terminal_values = [terminal_reason]
            if usage:
                usage_columns = (",usage_input_tokens=?,usage_output_tokens=?,"
                                 "usage_total_tokens=?,usage_source=?")
                usage_values = [
                    usage.get("inputTokens"), usage.get("outputTokens"),
                    usage.get("totalTokens"), usage_source,
                ]
            conn.execute(
                "UPDATE server_turns SET state='completed',capture_state='captured',cleanup_state='pending',result_object_digest=?,updated_at=?"
                + usage_columns + change_set_column + terminal_column + " WHERE id=?",
                [result_object_digest, timestamp, *usage_values, *change_set_values,
                 *terminal_values, turn_id],
            )
            latest_usage = None
            if usage:
                latest_usage = json.dumps({
                    "turnId": turn_id, "usageSource": usage_source, **usage,
                }, sort_keys=True, separators=(",", ":"))
            conn.execute(
                "UPDATE server_sessions SET status='ready',checkpoint_object_digest=?,checkpoint_native_id=?,"
                "native_platform=COALESCE(?,native_platform),home_locator=COALESCE(?,home_locator),"
                "latest_usage=COALESCE(?,latest_usage),updated_at=? WHERE id=?",
                (checkpoint_object_digest, checkpoint_native_id, native_platform, home_locator,
                 latest_usage, timestamp, row["session_id"]),
            )
            # Order 67: two different Sessions of one Profile may complete
            # concurrently, so the optimistic generation check would refuse
            # the second legal Turn. The counter is monotonic - one advance
            # per completed Turn - and nothing reads its parity, so it
            # advances unconditionally; the Profile settles only when this
            # was its last active Turn.
            conn.execute(
                "UPDATE server_profiles SET native_generation=native_generation+1,"
                "updated_at=? WHERE id=?",
                (timestamp, row["profile_id"]),
            )
            self._settle_profile_after_turn(conn, row["profile_id"], turn_id, timestamp)
            if latest_usage:
                self._append_session_event(
                    conn, row["session_id"], turn_id, "usage.updated",
                    {"turn_id": turn_id, "usage": usage},
                )
            event = self._append_session_event(
                conn, row["session_id"], turn_id, "turn.capture",
                {"state": "captured", "checkpoint_native_id": checkpoint_native_id,
                 "checkpoint_object_digest": checkpoint_object_digest,
                 "result_object_digest": result_object_digest},
            )
            self._append_session_event(
                conn, row["session_id"], turn_id, "turn.state", {"state": "completed"},
            )
            next_execution_id = None
            if queue_records is not None:
                if row["queue_item_id"] is not None:
                    queue_records.mark_terminal(conn, row["queue_item_id"], "completed")
                item = queue_records.claim_next(conn, row["session_id"])
                if item is not None:
                    profile = conn.execute(
                        "SELECT * FROM server_profiles WHERE id=?", (item["profileId"],),
                    ).fetchone()
                    if profile is None:
                        raise ServerError("PROFILE_NOT_FOUND", "Queued Profile was not found", status=404)
                    next_execution_id = self._insert_execution(
                        conn, session_id=row["session_id"], profile=profile,
                        config_version=item["configVersion"],
                        input_object_digest=item["_messageObjectDigest"],
                        effective_config_object_digest=item["_effectiveConfigObjectDigest"],
                        queue_item_id=item["itemId"],
                    )
            updated = conn.execute("SELECT * FROM server_turns WHERE id=?", (turn_id,)).fetchone()
            result = dict(updated)
            result["next_execution_id"] = next_execution_id
        if next_execution_id is not None:
            # a-3 K2-S' (C-notice-S-a3half-ruled 04:35Z, open point 1 = post-hook):
            # a queue-adopted successor is filed right after the completion
            # transaction commits - filing follows the acceptance/claim points;
            # E's chained dispatch stays a pure consumer (missing row key is a
            # typed refusal). Dormant while no filer is composed.
            self.file_core_records(str(next_execution_id))
        return result, event

    def mark_turn_cleanup(self, turn_id: str, state: str) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE server_turns SET cleanup_state=?,updated_at=? WHERE id=?",
                (state, now(), turn_id),
            )

    def turn_ancestry_profile_ids(self, turn_id: str) -> list[str]:
        """The turn's own Profile and every ancestor's, oldest first.

        Order 086: the delegation cycle rule reads the chain from the ledger
        rather than from the caller, because a caller cannot vouch for its own
        ancestry - a turn is only ever created with a parent that already
        exists, so walking `parent_turn_id` upwards terminates.
        """
        profile_ids: list[str] = []
        visited: set[str] = set()
        with self.database.read() as conn:
            current: str | None = turn_id
            while current is not None and current not in visited:
                visited.add(current)
                row = conn.execute(
                    "SELECT profile_id,parent_turn_id FROM server_turns WHERE id=?",
                    (current,),
                ).fetchone()
                if row is None:
                    break
                profile_ids.append(str(row["profile_id"]))
                current = row["parent_turn_id"]
        return list(reversed(profile_ids))

    def live_child_turn_ids(self, parent_turn_id: str) -> list[str]:
        """Every still-active turn delegated *from* one parent turn.

        Order 65's cancellation rule needs the ledger to be the one that knows
        who is whose child; `parent_turn_id` is set when a child turn is
        created, so this is the same link the usage attribution rides on.
        """
        placeholders = ",".join("?" * len(ACTIVE_TURN_STATES))
        with self.database.read() as conn:
            rows = conn.execute(
                f"SELECT id FROM server_turns WHERE parent_turn_id=? "
                f"AND state IN ({placeholders}) ORDER BY rowid",
                (parent_turn_id, *ACTIVE_TURN_STATES),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def record_cancel_request(self, turn_id: str) -> dict[str, Any]:
        """Record that a stop was asked for, if there is anything to stop.

        A turn that already reached a terminal state is returned untouched: the
        request is not a fact about it, and recording one would both write a
        `stop_requested_at` the turn never had and publish a stop frame for an
        execution that has already finished. The caller decides what to tell the
        client; the store only refuses to invent the request.
        """
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM server_turns WHERE id=?", (turn_id,)).fetchone()
            if row is None:
                raise ServerError("TURN_NOT_FOUND", "Turn was not found", status=404)
            if row["state"] not in ACTIVE_TURN_STATES:
                return dict(row)
            timestamp = now()
            conn.execute(
                "UPDATE server_turns SET stop_requested_at=COALESCE(stop_requested_at,?),updated_at=? "
                "WHERE id=?",
                (timestamp, timestamp, turn_id),
            )
            return self._append_session_event(
                conn, row["session_id"], turn_id, "turn.state",
                {"state": row["state"], "cancel_requested": True},
            )

    def finish_cancelled(
        self, turn_id: str, *, queue_records=None,
        terminal_reason: str | None = None,
        checkpoint_object_digest: str | None = None,
        checkpoint_native_id: str | None = None,
        native_platform: str | None = None,
        home_locator: str | None = None,
    ) -> dict[str, Any]:
        """Record a cancelled turn without pretending its input vanished.

        Under the native-home model the Harness kept writing its own directory
        up to the moment it stopped, so a cancel that arrives mid-turn still
        leaves facts behind: when an audit of that directory succeeded, the
        Session keeps its reference (manifest, native id, platform, locator)
        and the next turn reopens the same native session. With no audit the
        columns are left exactly as they were - which is itself the honest
        statement that nothing was observed.
        """
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM server_turns WHERE id=?", (turn_id,)).fetchone()
            if row is None:
                raise ServerError("TURN_NOT_FOUND", "Turn was not found", status=404)
            if row["state"] in {"completed", "failed", "cancelled", "unknown"}:
                return dict(row)
            timestamp = now()
            terminal_column = ",terminal_reason=?" if terminal_reason is not None else ""
            terminal_values = [terminal_reason] if terminal_reason is not None else []
            conn.execute(
                f"UPDATE server_turns SET state='cancelled',capture_state=?,"
                f"error_code='TURN_CANCELLED'{terminal_column},updated_at=? WHERE id=?",
                ["captured" if checkpoint_object_digest else "not-captured",
                 *terminal_values, timestamp, turn_id],
            )
            conn.execute(
                "UPDATE server_sessions SET status='ready',"
                "checkpoint_object_digest=COALESCE(?,checkpoint_object_digest),"
                "checkpoint_native_id=COALESCE(?,checkpoint_native_id),"
                "native_platform=COALESCE(?,native_platform),"
                "home_locator=COALESCE(?,home_locator),updated_at=? WHERE id=?",
                (checkpoint_object_digest, checkpoint_native_id, native_platform,
                 home_locator, timestamp, row["session_id"]),
            )
            self._settle_profile_after_turn(conn, row["profile_id"], turn_id, timestamp)
            if queue_records is not None:
                if row["queue_item_id"] is not None:
                    queue_records.mark_terminal(conn, row["queue_item_id"], "cancelled")
                queue_records.pause_pending(conn, row["session_id"], "cancelled")
            return self._append_session_event(
                conn, row["session_id"], turn_id, "turn.state",
                {"state": "cancelled", "error_code": "TURN_CANCELLED"},
            )

    def fail_turn(
        self, turn_id: str, code: str, *, capture_state: str = "failed", queue_records=None,
    ) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM server_turns WHERE id=?", (turn_id,)).fetchone()
            if row is None:
                raise ServerError("TURN_NOT_FOUND", "Turn was not found", status=404)
            if row["state"] in {"completed", "failed", "cancelled", "unknown"}:
                return dict(row)
            state = "unknown" if code in {"WORKER_DISCONNECTED", "DISPATCH_AMBIGUOUS"} else "failed"
            recovery_required = state == "unknown" or (
                row["state"] in {"running", "capturing"} and capture_state == "failed"
            )
            timestamp = now()
            conn.execute(
                "UPDATE server_turns SET state=?,capture_state=?,error_code=?,updated_at=? WHERE id=?",
                (state, capture_state, code[:128], timestamp, turn_id),
            )
            conn.execute(
                "UPDATE server_sessions SET status=?,updated_at=? WHERE id=?",
                ("recovery_required" if recovery_required else "ready", timestamp, row["session_id"]),
            )
            self._settle_profile_after_turn(
                conn, row["profile_id"], turn_id, timestamp,
                recovery_pending=1 if recovery_required else 0,
            )
            if queue_records is not None:
                if row["queue_item_id"] is not None:
                    queue_records.mark_terminal(conn, row["queue_item_id"], "failed")
                queue_records.pause_pending(conn, row["session_id"], code)
            self._append_session_event(
                conn, row["session_id"], turn_id, "turn.capture",
                {"state": capture_state, "error_code": code[:128]},
            )
            return self._append_session_event(
                conn, row["session_id"], turn_id, "turn.state",
                {"state": state, "error_code": code[:128]},
            )

    # -- reads --------------------------------------------------------------

    def turn_message_deltas(self, turn_id: str) -> list[str]:
        """The text of one turn's ``message.delta`` events, in append order.

        Order 146 (`AUD-B-029`): a delegated child's summary must be read from the
        *turn's own* events, not from a session snapshot's first 200 rows (which
        truncated the newest content and returned an empty summary on continuation).
        This is scoped to one turn and unbounded by the session window; the caller
        still applies the declared summary-character bound.
        """
        with self.database.read() as conn:
            rows = conn.execute(
                "SELECT data_json FROM server_session_events "
                "WHERE turn_id=? AND kind='message.delta' ORDER BY seq",
                (turn_id,),
            ).fetchall()
        pieces: list[str] = []
        for row in rows:
            try:
                data = json.loads(row["data_json"])
            except ValueError:
                continue
            pieces.append(str(data.get("text") or ""))
        return pieces

    def get_session(self, session_id: str, *, event_limit: int = 200) -> dict[str, Any]:
        """One session plus an *oldest-first* `event_limit` head of its turns/events.

        The two lists are a snapshot window, not the whole session: when a session
        has more rows than the limit, the **oldest** `event_limit` are returned and
        the newest are dropped, silently. Read them for scalars and existence only.
        For a turn's own content use `turn_message_deltas`, and for the newest
        events of a session use `list_events_page` (which reads `DESC` and reverses).
        """
        with self.database.read() as conn:
            row = conn.execute("SELECT * FROM server_sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)
            turns = conn.execute(
                "SELECT id,state,capture_state,cleanup_state,profile_revision,native_generation,"
                "work_id,execution_id,dispatch_id,result_object_digest,error_code,"
                "stop_requested_at,created_at "
                "FROM server_turns WHERE session_id=? ORDER BY created_at,id LIMIT ?",
                (session_id, event_limit),
            ).fetchall()
            events = conn.execute(
                "SELECT seq,event_id,turn_id,kind,schema_version,data_json,created_at "
                "FROM server_session_events WHERE session_id=? ORDER BY seq LIMIT ?",
                (session_id, event_limit),
            ).fetchall()
        return {
            "session_id": row["id"], "workspace_id": row["workspace_id"],
            "profile_id": row["profile_id"], "status": row["status"],
            "version": int(row["version"] or 1),
            "display_name": row["display_name"], "pinned": bool(row["pinned"]),
            "archived_at": row["archived_at"],
            "checkpoint": ({"object_digest": row["checkpoint_object_digest"],
                            "native_id": row["checkpoint_native_id"]}
                           if row["checkpoint_object_digest"] else None),
            "turns": [dict(item) for item in turns],
            "events": [self._event_dict(item) for item in events],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def raw_events(self, session_id: str, after: int, *, limit: int = 500) -> list[Any]:
        """Return stored event rows after `after`, for wire frame projection.

        Deliberately returns raw rows: the wire layer owns kind projection, and
        internal bookkeeping kinds must not be re-encoded here.
        """
        with self.database.read() as conn:
            if conn.execute("SELECT 1 FROM server_sessions WHERE id=?", (session_id,)).fetchone() is None:
                raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)
            maximum = conn.execute(
                "SELECT COALESCE(MAX(seq),0) FROM server_session_events WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            if after > maximum:
                raise ServerError("EVENT_CURSOR_AHEAD", "Event cursor is beyond current history", status=409)
            return conn.execute(
                "SELECT seq,wire_seq,event_id,session_id,turn_id,kind,schema_version,data_json,created_at "
                "FROM server_session_events WHERE session_id=? AND seq>? ORDER BY seq LIMIT ?",
                (session_id, after, limit),
            ).fetchall()

    def history_page(
        self, session_id: str, *, after: int | None = None,
        before: int | None = None, limit: int = 200,
    ) -> tuple[list[Any], int, bool]:
        """Read a consistent history page and its raw event-log head.

        `after` is a forward/live position. `before` is an exclusive backward
        boundary. The returned rows are always in durable ascending order and
        `has_older` only describes the backward view.
        """
        if after is not None and before is not None:
            raise ValueError("history directions are mutually exclusive")
        with self.database.read() as conn:
            conn.execute("BEGIN")
            if conn.execute(
                "SELECT 1 FROM server_sessions WHERE id=?", (session_id,),
            ).fetchone() is None:
                raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)
            head = int(conn.execute(
                "SELECT COALESCE(MAX(seq),0) FROM server_session_events WHERE session_id=?",
                (session_id,),
            ).fetchone()[0])
            if after is not None:
                if after > head:
                    raise ServerError(
                        "EVENT_CURSOR_AHEAD", "Event cursor is beyond current history", status=409,
                    )
                rows = conn.execute(
                    "SELECT seq,wire_seq,event_id,session_id,turn_id,kind,schema_version,"
                    "data_json,created_at FROM server_session_events "
                    "WHERE session_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (session_id, after, limit),
                ).fetchall()
                return rows, head, False
            boundary = head + 1 if before is None else before
            if boundary > head + 1:
                raise ServerError(
                    "EVENT_CURSOR_AHEAD", "History page cursor is beyond current history", status=409,
                )
            descending = conn.execute(
                "SELECT seq,wire_seq,event_id,session_id,turn_id,kind,schema_version,"
                "data_json,created_at FROM server_session_events "
                "WHERE session_id=? AND seq<? ORDER BY seq DESC LIMIT ?",
                (session_id, boundary, limit),
            ).fetchall()
            rows = list(reversed(descending))
            earliest = int(rows[0]["seq"]) if rows else boundary
            has_older = conn.execute(
                "SELECT 1 FROM server_session_events WHERE session_id=? AND seq<? LIMIT 1",
                (session_id, earliest),
            ).fetchone() is not None
            return rows, head, has_older

    def list_events(self, session_id: str, after: int, *, limit: int = 500) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            if conn.execute("SELECT 1 FROM server_sessions WHERE id=?", (session_id,)).fetchone() is None:
                raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)
            maximum = conn.execute(
                "SELECT COALESCE(MAX(seq),0) FROM server_session_events WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            if after > maximum:
                raise ServerError("EVENT_CURSOR_AHEAD", "Event cursor is beyond current history", status=409)
            rows = conn.execute(
                "SELECT seq,wire_seq,event_id,turn_id,kind,schema_version,data_json,created_at "
                "FROM server_session_events WHERE session_id=? AND seq>? ORDER BY seq LIMIT ?",
                (session_id, after, limit),
            ).fetchall()
        return [self._event_dict(row) for row in rows]

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _append_session_event(
        conn, session_id: str, turn_id: str | None, kind: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        seq = int(conn.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM server_session_events WHERE session_id=?",
            (session_id,),
        ).fetchone()[0])
        event_id = opaque_id("event")
        created_at = now()
        wire_seq = None
        if kind in WIRE_VISIBLE_EVENT_KINDS:
            wire_seq = int(conn.execute(
                "SELECT COALESCE(MAX(wire_seq),0)+1 FROM server_session_events WHERE session_id=?",
                (session_id,),
            ).fetchone()[0])
        conn.execute(
            "INSERT INTO server_session_events(session_id,seq,wire_seq,event_id,turn_id,kind,schema_version,data_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, seq, wire_seq, event_id, turn_id, kind, 1,
             json.dumps(data, ensure_ascii=False, sort_keys=True), created_at),
        )
        return {
            "session_id": session_id, "seq": seq, "wire_seq": wire_seq, "event_id": event_id,
            "turn_id": turn_id, "kind": kind, "schema_version": 1,
            "data": data, "created_at": created_at,
        }

    @staticmethod
    def _event_dict(row) -> dict[str, Any]:
        item = dict(row)
        item["data"] = json.loads(item.pop("data_json"))
        return item
