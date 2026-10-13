"""Original-library repository for immutable Unit reviewer assignments."""
from __future__ import annotations

import json
from dataclasses import asdict

from ordessa_infrastructure.encoding import canonical_bytes

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.method_codec import decode_method_ref
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest, validate_id, validate_version
from ordessa_engineering.domain.reviews.assignments import (
    ReviewerAssignment,
    ReviewerAssignmentControl,
    ReviewerAssignmentRef,
    _unit_ref,
)
from ordessa_engineering.domain.reviews.codec import _digest as decode_digest
from ordessa_engineering.domain.common.mechanisms.codec import decode_scope
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION


def _json(raw: bytes) -> str:
    return raw.decode("utf-8")


def _record_bytes(record: ReviewerAssignment) -> bytes:
    return canonical_bytes({**record.hash_payload(), "digest": asdict(record.digest)})


def _decode_record(raw: bytes) -> ReviewerAssignment:
    try:
        value = json.loads(raw)
        required = {
            "scope", "assignment_id", "review_id", "plan_digest", "request_version", "fence",
            "method_ref", "reviewer_unit_ref", "author_unit_ref", "roles", "issuer_principal_id",
            "issuer_credential_epoch", "assigned_at", "digest",
        }
        if type(value) is not dict or set(value) != required or canonical_bytes(value) != raw:
            raise ValueError("invalid assignment record")
        plan_digest = decode_digest(value["plan_digest"])
        method_ref = decode_method_ref(value["method_ref"])
        digest = decode_digest(value["digest"])
        reviewer_bytes = canonical_bytes(value["reviewer_unit_ref"])
        author_bytes = (None if value["author_unit_ref"] is None
                        else canonical_bytes(value["author_unit_ref"]))
        record = ReviewerAssignment(
            decode_scope(value["scope"]), value["assignment_id"], value["review_id"],
            plan_digest, value["request_version"], value["fence"], method_ref,
            reviewer_bytes, author_bytes, tuple(value["roles"]), value["issuer_principal_id"],
            value["issuer_credential_epoch"], value["assigned_at"],
        )
        if record.digest != digest or _record_bytes(record) != raw:
            raise ValueError("assignment digest differs")
        return record
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise ApplicationError("REVIEWER_ASSIGNMENT_CORRUPT") from exc


class SQLiteReviewerAssignmentRepository:
    def __init__(self, access):
        self.access = access

    def _prefix(self):
        self.access.check_active()
        return self.access.scope.realm_id, self.access.scope.project_id

    def _require_schema(self):
        if getattr(self.access._connection, "_ordessa_schema_version", None) != REVIEWER_ASSIGNMENT_SCHEMA_VERSION:
            raise ApplicationError("REVIEWER_ASSIGNMENT_SCHEMA_REQUIRED")

    @staticmethod
    def _ref(record):
        return ReviewerAssignmentRef(record.scope, record.assignment_id, record.digest)

    def get(self, ref: ReviewerAssignmentRef) -> ReviewerAssignment:
        self._require_schema()
        if type(ref) is not ReviewerAssignmentRef or ref.scope != self.access.scope:
            raise ApplicationError("SCOPE_MISMATCH")
        validate_id(ref.assignment_id)
        row = self.access.execute(
            "SELECT realm_id,project_id,assignment_id,review_id,plan_digest,request_version,fence,"
            "method_ref_json,reviewer_unit_ref_json,author_unit_ref_json,roles_json,issuer_principal_id,"
            "issuer_credential_epoch,assigned_at,digest,canonical_bytes FROM eng_unit_reviewer_assignments "
            "WHERE realm_id=? AND project_id=? AND assignment_id=?",
            self._prefix() + (ref.assignment_id,),
        ).fetchone()
        if row is None:
            raise ApplicationError("NOT_FOUND")
        record = _decode_record(bytes(row[15]))
        expected = (record.scope.realm_id, record.scope.project_id, record.assignment_id,
            record.review_id, record.plan_digest.hex, record.request_version, record.fence,
            _json(canonical_bytes({"method_id": record.method_ref.method_id,
                "release_version": record.method_ref.release_version,
                "schema_version": record.method_ref.schema_version,
                "snapshot_digest": asdict(record.method_ref.snapshot_digest)})),
            _json(record.reviewer_unit_ref_bytes),
            None if record.author_unit_ref_bytes is None else _json(record.author_unit_ref_bytes),
            _json(canonical_bytes(list(record.roles))), record.issuer_principal_id,
            record.issuer_credential_epoch, record.assigned_at, record.digest.hex)
        if (record.ref != ref or tuple(row[:15]) != expected
                or (record.scope.realm_id, record.scope.project_id, record.assignment_id)
                    != (ref.scope.realm_id, ref.scope.project_id, ref.assignment_id)):
            raise ApplicationError("REVIEWER_ASSIGNMENT_CORRUPT")
        return record

    def active_for_review(self, review_id: str) -> tuple[ReviewerAssignment, ReviewerAssignmentControl]:
        self._require_schema()
        validate_id(review_id)
        row = self.access.execute(
            "SELECT c.assignment_id,c.state,c.version,c.revoked_at,c.revoke_reason "
            "FROM eng_unit_reviewer_assignment_controls c "
            "WHERE c.realm_id=? AND c.project_id=? AND c.review_id=? AND c.state='active'",
            self._prefix() + (review_id,),
        ).fetchall()
        if len(row) != 1:
            raise ApplicationError("REVIEWER_ASSIGNMENT_UNAVAILABLE")
        assignment_id, state, version, revoked_at, reason = row[0]
        assignment = self.get(ReviewerAssignmentRef(
            self.access.scope, assignment_id, self._assignment_digest(assignment_id)))
        control = ReviewerAssignmentControl(assignment.ref, state, version, revoked_at, reason)
        self._validate_plan_binding(assignment)
        return assignment, control

    def _assignment_digest(self, assignment_id):
        row = self.access.execute(
            "SELECT digest FROM eng_unit_reviewer_assignments WHERE realm_id=? AND project_id=? AND assignment_id=?",
            self._prefix() + (assignment_id,),
        ).fetchone()
        if row is None or type(row[0]) is not str:
            raise ApplicationError("REVIEWER_ASSIGNMENT_CORRUPT")
        return Digest("sha256", row[0])

    def _validate_plan_binding(self, assignment, *, allow_recorded=True):
        plan = self.access._connection.execute(
            "SELECT plan_digest,canonical_bytes FROM eng_review_plans WHERE realm_id=? AND project_id=? AND review_id=?",
            self._prefix() + (assignment.review_id,),
        ).fetchone()
        request = self.access._connection.execute(
            "SELECT state,version,fence FROM eng_review_requests WHERE realm_id=? AND project_id=? AND review_id=?",
            self._prefix() + (assignment.review_id,),
        ).fetchone()
        if plan is None or request is None:
            raise ApplicationError("REVIEWER_ASSIGNMENT_CORRUPT")
        from ordessa_engineering.domain.reviews.codec import decode_plan
        stored_plan = decode_plan(bytes(plan[1]))
        request_matches = request == ("requested", assignment.request_version, assignment.fence)
        if allow_recorded:
            request_matches = request_matches or request == (
                "recorded", assignment.request_version + 1, assignment.fence)
        if (stored_plan.plan_digest.hex != plan[0]
                or stored_plan.plan_digest != assignment.plan_digest
                or stored_plan.requirement.method_ref != assignment.method_ref
                or tuple(sorted(stored_plan.reviewer_requirements)) != assignment.roles
                or not request_matches):
            raise ApplicationError("REVIEWER_ASSIGNMENT_CHANGED")

    def insert(self, assignment: ReviewerAssignment) -> ReviewerAssignmentRef:
        self._require_schema()
        self.access.require_write()
        if type(assignment) is not ReviewerAssignment or assignment.scope != self.access.scope:
            raise ApplicationError("SCOPE_MISMATCH")
        self._validate_plan_binding(assignment, allow_recorded=False)
        active = self.access.execute(
            "SELECT assignment_id FROM eng_unit_reviewer_assignment_controls "
            "WHERE realm_id=? AND project_id=? AND review_id=? AND request_version=? AND state='active'",
            self._prefix() + (assignment.review_id, assignment.request_version),
        ).fetchall()
        if len(active) > 1:
            raise ApplicationError("REVIEWER_ASSIGNMENT_CORRUPT")
        if active:
            raise ApplicationError("REVIEWER_ASSIGNMENT_ALREADY_ACTIVE")
        raw = _record_bytes(assignment)
        if len(raw) > 262144:
            raise ApplicationError("REVIEWER_ASSIGNMENT_BOUND_EXCEEDED")
        prefix = self._prefix()
        self.access.execute(
            "INSERT INTO eng_unit_reviewer_assignments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            prefix + (assignment.assignment_id, assignment.review_id, assignment.plan_digest.hex,
                assignment.request_version, assignment.fence, _json(canonical_bytes({
                    "method_id": assignment.method_ref.method_id,
                    "release_version": assignment.method_ref.release_version,
                    "schema_version": assignment.method_ref.schema_version,
                    "snapshot_digest": asdict(assignment.method_ref.snapshot_digest),
                })),
                _json(assignment.reviewer_unit_ref_bytes),
                None if assignment.author_unit_ref_bytes is None else _json(assignment.author_unit_ref_bytes),
                _json(canonical_bytes(list(assignment.roles))), assignment.issuer_principal_id,
                assignment.issuer_credential_epoch, assignment.assigned_at, assignment.digest.hex, raw))
        self.access.execute(
            "INSERT INTO eng_unit_reviewer_assignment_controls "
            "(realm_id,project_id,assignment_id,review_id,request_version,state,version,revoked_at,revoke_reason) "
            "VALUES (?,?,?,?,?,'active',0,NULL,NULL)",
            prefix + (assignment.assignment_id, assignment.review_id, assignment.request_version),
        )
        return assignment.ref

    def control(self, ref: ReviewerAssignmentRef) -> ReviewerAssignmentControl:
        assignment = self.get(ref)
        row = self.access.execute(
            "SELECT review_id,request_version,state,version,revoked_at,revoke_reason FROM eng_unit_reviewer_assignment_controls "
            "WHERE realm_id=? AND project_id=? AND assignment_id=?",
            self._prefix() + (ref.assignment_id,),
        ).fetchone()
        if row is None:
            raise ApplicationError("REVIEWER_ASSIGNMENT_CORRUPT")
        try:
            if (row[0], row[1]) != (assignment.review_id, assignment.request_version):
                raise ValueError("assignment control identity differs")
            return ReviewerAssignmentControl(ref, row[2], row[3], row[4], row[5])
        except Exception as exc:
            raise ApplicationError("REVIEWER_ASSIGNMENT_CORRUPT") from exc

    def revoke(self, ref: ReviewerAssignmentRef, *, expected_version: int,
               revoked_at: str, reason: str, event_id: str):
        self._require_schema()
        self.access.require_write()
        assignment = self.get(ref)
        validate_version(expected_version)
        validate_id(event_id)
        if type(revoked_at) is not str or not revoked_at or type(reason) is not str or not reason:
            raise ApplicationError("INVALID_INPUT")
        control = self.control(ref)
        if control.state != "active" or control.version != expected_version:
            raise ApplicationError("REVIEWER_ASSIGNMENT_CHANGED")
        event = canonical_bytes({"scope": asdict(ref.scope), "assignment_ref": asdict(ref),
            "action": "revoke", "from_version": expected_version,
            "to_version": expected_version + 1, "reason": reason, "at": revoked_at})
        prefix = self._prefix()
        self.access.execute(
            "UPDATE eng_unit_reviewer_assignment_controls SET state='revoked',version=?,revoked_at=?,revoke_reason=? "
            "WHERE realm_id=? AND project_id=? AND assignment_id=? AND state='active' AND version=?",
            (expected_version + 1, revoked_at, reason) + prefix + (ref.assignment_id, expected_version),
        )
        if self.access._connection.execute("SELECT changes()").fetchone() != (1,):
            raise ApplicationError("REVIEWER_ASSIGNMENT_CHANGED")
        self.access.execute("INSERT INTO eng_unit_reviewer_assignment_events VALUES (?,?,?,?,?,?,?,?)",
            prefix + (event_id, assignment.assignment_id, expected_version, expected_version+1, "revoke", event))
        return self.control(ref)

    def check_active_control(self, assignment_id: str, expected_version: int):
        """ReadSet resolver: exact original assignment must remain active at COMMIT."""
        self._require_schema()
        validate_id(assignment_id)
        validate_version(expected_version)
        row = self.access.execute(
            "SELECT state,version FROM eng_unit_reviewer_assignment_controls "
            "WHERE realm_id=? AND project_id=? AND assignment_id=?",
            self._prefix() + (assignment_id,),
        ).fetchone()
        if row != ("active", expected_version):
            raise ApplicationError("REVIEWER_ASSIGNMENT_CHANGED")
        digest = self._assignment_digest(assignment_id)
        assignment = self.get(ReviewerAssignmentRef(self.access.scope, assignment_id, digest))
        self._validate_plan_binding(assignment)


__all__ = ["SQLiteReviewerAssignmentRepository"]
