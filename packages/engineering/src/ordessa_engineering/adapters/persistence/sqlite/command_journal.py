"""SQLite command idempotency journal on a caller-owned transaction connection."""
from __future__ import annotations

import sqlite3

from ordessa_engineering.domain.common.mechanisms.codec import (canonical_value)

from ordessa_engineering.application.contracts.commands import CommandKey, JournalEntry, Reservation
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.values import (Digest, validate_id)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)

_MAX_RESULT_BYTES = 2 * 1024 * 1024
_STATES = {"pending", "completed", "rejected"}


class SQLiteCommandJournal:
    """Persist command identity and terminal results through a UoW access port.

    ``access.execute`` is deliberately the only connection surface used here:
    this adapter never opens a connection or controls the enclosing transaction.
    """

    def __init__(self, access):
        self.access = access

    def reserve(
        self,
        key: CommandKey,
        *,
        project_id: str,
        operation: str,
        operation_id: str,
        request_digest: Digest,
    ) -> Reservation:
        self.access.require_write()
        self._validate_key(key)
        self._require_scope(key, project_id=project_id)
        self._validate_id(operation)
        self._validate_id(operation_id)
        if type(request_digest) is not Digest:
            _fail("INVALID_COMMAND")

        existing = self._select(key)
        if existing is not None:
            if (existing.project_id != project_id or existing.operation != operation
                    or existing.request_digest != request_digest):
                _fail("REQUEST_IDENTITY_CONFLICT")
            # operation_id is allocated by the first reservation. A repeated
            # request must recover that identity rather than compare a new one.
            return Reservation(existing, False)

        try:
            self.access.execute(
                "INSERT INTO eng_commands "
                "(realm_id, principal_id, request_id, project_id, operation, "
                "operation_id, request_digest, state, result_bytes, version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', NULL, 0)",
                (key.realm_id, key.principal_id, key.request_id, project_id,
                 operation, operation_id, request_digest.hex),
            )
        except ApplicationError as exc:
            if exc.code != "STORAGE_CONSTRAINT":
                raise
            # The other uniqueness constraint is realm_id/operation_id. Do not
            # leak SQLite text or the conflicting row's identity.
            _fail("OPERATION_ID_CONFLICT")
        created = self._select(key)
        if created is None:
            _fail("JOURNAL_CORRUPT")
        if (created.project_id != project_id or created.operation != operation
                or created.operation_id != operation_id
                or created.request_digest != request_digest or created.state != "pending"
                or created.version != 0):
            _fail("JOURNAL_CORRUPT")
        return Reservation(created, True)

    def get(self, key: CommandKey) -> JournalEntry | None:
        self._validate_key(key)
        self._require_scope(key)
        entry = self._select(key)
        if entry is not None and entry.project_id != self.access.scope.project_id:
            _fail("SCOPE_MISMATCH")
        return entry

    def find_completed_review_request(self, scope, *, review_id: str,
                                      plan_digest: Digest) -> JournalEntry | None:
        """Find the unique terminal request carrying this exact Work review proof.

        This is a bounded lookup over the original journal, never a latest-row
        selector. The returned entry is re-read through the ordinary strict
        decoder before it leaves the adapter.
        """
        self._require_scope_for(scope)
        self._validate_id(review_id)
        if type(plan_digest) is not Digest or plan_digest.algorithm != "sha256":
            _fail("INVALID_COMMAND")
        rows = self.access.execute(
            "SELECT realm_id, principal_id, request_id FROM eng_commands "
            "WHERE realm_id=? AND project_id=? AND operation='engineering.reviews.request' "
            "AND state='completed' AND result_bytes IS NOT NULL "
            "AND json_extract(result_bytes, '$.work_review.review_id')=? "
            "AND json_extract(result_bytes, '$.work_review.plan_digest.hex')=? "
            "ORDER BY principal_id, request_id LIMIT 2",
            (scope.realm_id, scope.project_id, review_id, plan_digest.hex),
        ).fetchall()
        if len(rows) > 1:
            _fail("REVIEW_WORK_PROOF_AMBIGUOUS")
        if not rows:
            return None
        try:
            key = CommandKey(*rows[0])
        except (TypeError, ValueError, ReferenceError):
            _fail("JOURNAL_CORRUPT")
        entry = self._select(key)
        if (entry is None or entry.project_id != scope.project_id
                or entry.operation != "engineering.reviews.request" or entry.state != "completed"):
            _fail("JOURNAL_CORRUPT")
        return entry

    def _require_scope_for(self, scope):
        if (type(scope) is not Scope or type(self.access.scope) is not Scope
                or scope != self.access.scope):
            _fail("SCOPE_MISMATCH")

    def complete(
        self,
        key: CommandKey,
        *,
        expected_version: int,
        result_bytes: bytes,
        state: str = "completed",
    ) -> JournalEntry:
        self.access.require_write()
        self._validate_key(key)
        self._require_scope(key)
        if type(expected_version) is not int or not 0 <= expected_version <= (1 << 63) - 1:
            _fail("INVALID_COMMAND")
        if type(state) is not str or state not in {"completed", "rejected"}:
            _fail("INVALID_RESULT")
        self._validate_result(result_bytes)

        current = self._select(key)
        if current is None:
            _fail("COMMAND_NOT_FOUND")
        if current.project_id != self.access.scope.project_id:
            _fail("SCOPE_MISMATCH")
        if current.state != "pending":
            # A replay of the exact transition is a read-only success. Its
            # original CAS version is one below the terminal row's version.
            if (current.state == state and current.result_bytes == result_bytes
                    and expected_version == current.version - 1):
                return current
            _fail("VERSION_CONFLICT")
        if expected_version != current.version:
            _fail("VERSION_CONFLICT")

        if current.version == (1 << 63) - 1:
            _fail("VERSION_EXHAUSTED")

        cursor = self.access.execute(
            "UPDATE eng_commands SET state=?, result_bytes=?, version=version+1 "
            "WHERE realm_id=? AND principal_id=? AND request_id=? "
            "AND project_id=? AND version=? AND state='pending'",
            (state, result_bytes, key.realm_id, key.principal_id, key.request_id,
             self.access.scope.project_id, expected_version),
        )
        if getattr(cursor, "rowcount", None) != 1:
            _fail("VERSION_CONFLICT")
        completed = self._select(key)
        if completed is None or completed.project_id != self.access.scope.project_id:
            _fail("JOURNAL_CORRUPT")
        if (completed.state != state or completed.result_bytes != result_bytes
                or completed.version != expected_version + 1):
            _fail("JOURNAL_CORRUPT")
        return completed

    def _validate_key(self, key: CommandKey) -> None:
        if type(key) is not CommandKey:
            _fail("INVALID_COMMAND")
        for value in (key.realm_id, key.principal_id, key.request_id):
            self._validate_id(value)

    def _validate_id(self, value: str) -> None:
        try:
            validate_id(value)
        except (ReferenceError, TypeError, ValueError):
            _fail("INVALID_COMMAND")

    def _require_scope(self, key: CommandKey, *, project_id: str | None = None) -> None:
        scope = getattr(self.access, "scope", None)
        if type(scope) is not Scope:
            _fail("SCOPE_MISMATCH")
        if (key.realm_id != scope.realm_id
                or (project_id is not None and project_id != scope.project_id)):
            _fail("SCOPE_MISMATCH")

    def _validate_result(self, result_bytes: bytes) -> None:
        if type(result_bytes) is not bytes or len(result_bytes) > _MAX_RESULT_BYTES:
            _fail("INVALID_RESULT")
        try:
            canonical_value(result_bytes)
        except ApplicationError:
            raise
        except (ReferenceError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
            _fail("INVALID_RESULT")

    def _select(self, key: CommandKey) -> JournalEntry | None:
        row = self.access.execute(
            "SELECT realm_id, principal_id, request_id, project_id, operation, "
            "operation_id, request_digest, state, length(result_bytes), "
            "typeof(result_bytes), substr(result_bytes, 1, ?), version "
            "FROM eng_commands WHERE realm_id=? AND principal_id=? AND request_id=?",
            (_MAX_RESULT_BYTES + 1, key.realm_id, key.principal_id, key.request_id),
        ).fetchone()
        if row is None:
            return None
        try:
            (realm_id, principal_id, request_id, project_id, operation,
             operation_id, digest_hex, state, result_length, result_type,
             result_bytes, version) = row
            stored_key = CommandKey(realm_id, principal_id, request_id)
            validate_id(project_id)
            validate_id(operation)
            validate_id(operation_id)
            digest = Digest("sha256", digest_hex)
            if (type(state) is not str or state not in _STATES
                    or type(version) is not int or version < 0):
                _fail("JOURNAL_CORRUPT")
            if state == "pending":
                if result_length is not None or result_type != "null" or result_bytes is not None:
                    _fail("JOURNAL_CORRUPT")
                result = None
            else:
                if (type(result_length) is not int or not 0 <= result_length <= _MAX_RESULT_BYTES
                        or result_type != "blob" or type(result_bytes) is not bytes
                        or len(result_bytes) != result_length):
                    _fail("JOURNAL_CORRUPT")
                self._validate_result(result_bytes)
                result = result_bytes
            return JournalEntry(stored_key, project_id, operation, operation_id,
                                digest, state, result, version)
        except ApplicationError:
            raise
        except (ReferenceError, TypeError, ValueError, UnicodeError, OverflowError):
            _fail("JOURNAL_CORRUPT")


def _fail(code: str) -> None:
    raise ApplicationError(code)
