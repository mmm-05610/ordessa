"""Acceptance receipt facts on the original Engineering UoW and action ledger."""
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.changes.adoption import (
    AcceptanceReceipt, decode_acceptance_receipt, encode_acceptance_receipt,
)
from ordessa_engineering.domain.common.models.values import validate_id
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION


class SQLiteAcceptanceRepository:
    def __init__(self, access):
        self.access = access

    def _schema(self):
        self.access.check_active()
        if getattr(self.access._connection, '_ordessa_schema_version', None) not in (ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION):
            raise ApplicationError('ACCEPTANCE_SCHEMA_REQUIRED')

    def create(self, receipt):
        self._schema()
        self.access.require_write()
        if type(receipt) is not AcceptanceReceipt or receipt.scope != self.access.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        try:
            raw = encode_acceptance_receipt(receipt)
            if decode_acceptance_receipt(raw) != receipt:
                raise ApplicationError('ACCEPTANCE_RECEIPT_INVALID')
        except (ReferenceError, TypeError, ValueError, RecursionError, OverflowError):
            raise ApplicationError('ACCEPTANCE_RECEIPT_INVALID') from None
        prefix = (receipt.scope.realm_id, receipt.scope.project_id)
        debit = self.access.execute(
            'SELECT approval_id,action,intent_digest,target_digest FROM eng_action_consumptions '
            'WHERE realm_id=? AND project_id=? AND action_instance_id=?',
            prefix + (receipt.action_instance_id,)).fetchone()
        expected = (receipt.approval_ref.approval_id, 'accept_artifact',
                    receipt.intent_digest.hex, receipt.plan.digest.hex)
        if debit != expected:
            raise ApplicationError('ACCEPTANCE_ACTION_BINDING_INVALID')
        self.access.execute(
            'INSERT INTO eng_acceptance_receipts '
            '(realm_id,project_id,adoption_id,action_instance_id,approval_id,intent_digest,plan_digest,receipt_digest,canonical_bytes) '
            'VALUES (?,?,?,?,?,?,?,?,?)',
            prefix + (receipt.adoption_id, receipt.action_instance_id,
                receipt.approval_ref.approval_id, receipt.intent_digest.hex,
                receipt.plan.digest.hex, receipt.digest.hex, raw))
        return receipt.ref

    def resolve(self, adoption_id):
        self._schema()
        try:
            validate_id(adoption_id)
        except (ReferenceError, TypeError, ValueError):
            raise ApplicationError('INVALID_ARGUMENT') from None
        prefix = (self.access.scope.realm_id, self.access.scope.project_id)
        row = self.access.execute(
            'SELECT action_instance_id,approval_id,intent_digest,plan_digest,receipt_digest,canonical_bytes '
            'FROM eng_acceptance_receipts WHERE realm_id=? AND project_id=? AND adoption_id=?',
            prefix + (adoption_id,)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        try:
            raw = bytes(row[5])
            receipt = decode_acceptance_receipt(raw)
        except (ReferenceError, TypeError, ValueError, RecursionError, OverflowError):
            raise ApplicationError('ACCEPTANCE_RECORD_CORRUPT') from None
        if (encode_acceptance_receipt(receipt) != raw
                or receipt.scope != self.access.scope or receipt.adoption_id != adoption_id
                or row[:5] != (receipt.action_instance_id, receipt.approval_ref.approval_id,
                    receipt.intent_digest.hex, receipt.plan.digest.hex, receipt.digest.hex)):
            raise ApplicationError('ACCEPTANCE_RECORD_CORRUPT')
        return receipt
