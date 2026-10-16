"""Adapter unit-of-work provider for the original engineering library transaction.

This module opens the **same original** library transaction and exposes only
transaction-scoped storage primitives (via ``_TransactionScope``). It holds no
run/review/apply business decision, does not import application use-cases, and
does not create a second UoW implementation. The application opens this UoW and
coordinates business inside the scope.
"""
from __future__ import annotations

from contextlib import contextmanager

from ordessa_engineering.domain.artifacts.library_material_codec import (
    canonical_json, material_ref_to_dict, material_ref_from_dict,
)


class _TransactionScope:
    """The application ``TransactionScope`` bound to the live connection."""

    def __init__(self, library, connection, scope=None):
        self._library = library
        self._connection = connection
        self._scope = scope

    # reads (same original transaction/connection) -----------------------------
    def read(self, ref):
        return self._library.read(ref)

    def require_current(self, ref):
        return self._library.require_current(self._connection, ref)

    def head_ref(self, kind, stable_id):
        return self._library.head(kind, stable_id)

    def head_revision(self, kind, stable_id):
        return self._connection.execute(
            "SELECT revision, digest FROM heads WHERE kind=? AND stable_id=?",
            (kind, stable_id)).fetchone()

    def run_row(self, run_id):
        return self._library.run_row(run_id)

    def idempotency_row(self, operation_id):
        return self._connection.execute(
            "SELECT payload_digest, receipt_ref_json FROM idempotency WHERE operation_id=?",
            (operation_id,)).fetchone()

    def next_step_ordinal(self, run_id):
        return self._connection.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM step_log WHERE run_id=?", (run_id,)).fetchone()[0]

    def step_rows(self, run_id):
        from .step_rows import read_step_rows
        return read_step_rows(self._connection,run_id)

    def list_run_rows(self, *, after=None, limit=128):
        """Bounded current-method rows from this exact scoped read transaction."""
        import json
        from ....application.contracts.errors import ApplicationError
        from ....application.contracts.method_work import WORK_CONTRACT
        if self._scope is None:
            raise ApplicationError('SCOPE_MISMATCH')
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ApplicationError('INVALID_ARGUMENT')
        rows=self._connection.execute(
            "SELECT run_id,method_ref_json,registry_ref_json,input_json,status,cursor,wait_reason,created_at,updated_at "
            "FROM runs WHERE json_extract(input_json,'$.work_contract')=? "
            "AND json_extract(input_json,'$.scope.realm_id')=? AND json_extract(input_json,'$.scope.project_id')=? "
            "AND (? IS NULL OR run_id>?) ORDER BY run_id LIMIT ?",
            (WORK_CONTRACT,self._scope.realm_id,self._scope.project_id,after,after,limit)).fetchall()
        return [{'run_id':row[0], 'method_ref':material_ref_from_dict(json.loads(row[1])),
                 'registry_ref':json.loads(row[2]), 'inputs':json.loads(row[3]), 'status':row[4],
                 'cursor':row[5], 'wait_reason':row[6], 'created_at':row[7], 'updated_at':row[8]} for row in rows]

    # atomic write primitives --------------------------------------------------
    def write_material(self, *, kind, stable_id, revision, body, generated):
        return self._library._write_material(self._connection, kind=kind, stable_id=stable_id,
                                             revision=revision, body=body, generated=generated)

    def write_work_context(self, *, stable_id, revision, body):
        """Sole authorized writer of a declarative Work row.

        The library refuses this kind for every other writer, so a Work binding
        cannot be forged or overwritten through a generic material write. No
        program, cursor or run row is involved.
        """
        marker = '_ordessa_work_context_write'
        previous = getattr(self._connection, marker, False)
        self._connection.__dict__[marker] = True
        try:
            return self._library._write_material(self._connection, kind='work-context',
                stable_id=stable_id, revision=revision, body=body, generated=False)
        finally:
            self._connection.__dict__[marker] = previous

    def create_generated(self, *, kind, stable_id, body):
        return self._library._create_generated(self._connection, kind=kind, stable_id=stable_id, body=body)

    def insert_idempotency(self, operation_id, payload_digest, ref):
        self._connection.execute(
            "INSERT INTO idempotency VALUES (?, ?, ?)",
            (operation_id, payload_digest, canonical_json(material_ref_to_dict(ref))))

    def insert_run(self, *, run_id, method_ref, registry_ref, inputs, now):
        self._connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, 'RUNNING', 0, NULL, ?, ?)",
            (run_id, canonical_json(material_ref_to_dict(method_ref)), canonical_json(registry_ref),
             canonical_json(inputs), now, now))

    def insert_step_log(self, *, run_id, ordinal, step_id, operation, attempt, status, receipt_ref):
        self._connection.execute(
            "INSERT INTO step_log (run_id,ordinal,step_id,operation,attempt,status,receipt_ref_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, ordinal, step_id, operation, attempt, status, canonical_json(material_ref_to_dict(receipt_ref))))

    def replace_run_inputs(self, *, run_id, expected_inputs, inputs):
        from ordessa_engineering.application.contracts.errors import ApplicationError
        cursor = self._connection.execute(
            'UPDATE runs SET input_json=? WHERE run_id=? AND input_json=?',
            (canonical_json(inputs), run_id, canonical_json(expected_inputs)))
        if cursor.rowcount != 1:
            raise ApplicationError('RUN_WAIT_CHANGED')

    def update_run(self, *, run_id, status, cursor, wait_reason, now):
        if cursor is None:
            self._connection.execute(
                "UPDATE runs SET status=?, wait_reason=?, updated_at=? WHERE run_id=?",
                (status, wait_reason, now, run_id))
        else:
            self._connection.execute(
                "UPDATE runs SET status=?, cursor=?, wait_reason=?, updated_at=? WHERE run_id=?",
                (status, cursor, wait_reason, now, run_id))


class WorkflowTransactions:
    """Adapter implementation of the application ``UnitOfWork`` port."""

    def __init__(self, library):
        self.library = library

    @contextmanager
    def open(self):
        with self.library.transaction() as connection:
            yield _TransactionScope(self.library, connection)

    def transaction_scope(self, connection):
        """Bind a scope to an already-open connection (used inside ``open`` and by callers)."""
        return _TransactionScope(self.library, connection)
