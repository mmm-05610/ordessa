"""Immutable Submission content on the original active Engineering UoW."""
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.changes.submission import Submission
from ordessa_engineering.domain.changes.agent_submission_report import AgentSubmissionReport
from ordessa_engineering.domain.changes.submission_codec import encode_submission, decode_submission
from ordessa_engineering.domain.reviews.refs import SubmissionRef
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .submission_schema import SUBMISSION_SCHEMA_VERSION
from .dispatch_schema import (DISPATCH_SCHEMA_VERSION, DISPATCH_DDL,
                              WORK_DISPATCH_SCHEMA_VERSION)
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION


class SQLiteSubmissionRepository:
    def __init__(self, access):
        self.access = access

    def _prefix(self):
        self.access.check_active()
        if getattr(self.access._connection, '_ordessa_schema_version', None) not in (SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
            raise ApplicationError('SUBMISSION_SCHEMA_REQUIRED')
        return self.access.scope.realm_id, self.access.scope.project_id

    def create(self, record):
        self.access.require_write()
        prefix = self._prefix()
        if type(record) not in (Submission, AgentSubmissionReport) or record.scope != self.access.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        if (type(record) is AgentSubmissionReport or record.schema_version == 2) and getattr(self.access._connection, '_ordessa_schema_version', None) != WORK_DISPATCH_SCHEMA_VERSION:
            raise ApplicationError('WORK_DISPATCH_SCHEMA_REQUIRED')
        raw = encode_submission(record)
        if decode_submission(raw) != record:
            raise ApplicationError('RECORD_CORRUPT')
        row = self.access.execute('SELECT digest,canonical_bytes FROM eng_submissions WHERE realm_id=? AND project_id=? AND submission_id=?',
            prefix + (record.submission_id,)).fetchone()
        if row is not None:
            if row != (record.digest.hex, raw):
                raise ApplicationError('SUBMISSION_IDENTITY_CONFLICT')
            return record.ref
        self.access.execute('INSERT INTO eng_submissions VALUES (?,?,?,?,?)',
            prefix + (record.submission_id,record.digest.hex,raw))
        return record.ref

    def resolve(self, ref):
        prefix = self._prefix()
        if type(ref) is not SubmissionRef or (ref.realm_id,ref.project_id) != prefix:
            raise ApplicationError('SCOPE_MISMATCH')
        row = self.access.execute('SELECT digest,canonical_bytes FROM eng_submissions WHERE realm_id=? AND project_id=? AND submission_id=?',
            prefix + (ref.submission_id,)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        try:
            value = decode_submission(bytes(row[1]))
        except (ReferenceError,TypeError,ValueError):
            raise ApplicationError('RECORD_CORRUPT') from None
        if value.ref != ref or row[0] != ref.digest.hex:
            raise ApplicationError('RECORD_CORRUPT')
        return value
