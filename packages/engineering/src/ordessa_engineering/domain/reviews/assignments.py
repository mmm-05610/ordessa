"""Persisted assignment identity for one exact independent review Unit.

An assignment is an Engineering-issued role selection, not an authorization
Grant and not a property of a Unit's self-reported identity. Its Unit refs are
canonical original UnitRecords public refs authenticated by the owning query
port before persistence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from ordessa_infrastructure.encoding import canonical_bytes

from ..artifacts.method_binding import MethodRef
from ..common.mechanisms.hashing import record_digest
from ..common.models.identity import Scope
from ..common.models.values import Digest, utc_instant, validate_id, validate_version, validate_text
from ..common.outcomes.diagnostics import ReferenceError


def _unit_ref(raw: bytes | None) -> dict | None:
    if raw is None:
        return None
    if type(raw) is not bytes or not raw or len(raw) > 8192:
        raise ReferenceError("INVALID_SCHEMA")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError, TypeError):
        raise ReferenceError("INVALID_SCHEMA") from None
    if (type(value) is not dict
            or set(value) != {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}
            or any(type(value[name]) is not str or not value[name]
                   for name in ("environmentNamespace", "unitId", "sourceRevision"))
            or type(value["ownerProviderRef"]) is not dict
            or canonical_bytes(value) != raw):
        raise ReferenceError("INVALID_SCHEMA")
    validate_id(value["environmentNamespace"])
    validate_id(value["unitId"])
    validate_id(value["sourceRevision"])
    return value


@dataclass(frozen=True)
class ReviewerAssignmentRef:
    scope: Scope
    assignment_id: str
    digest: Digest

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.digest) is not Digest:
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.assignment_id)


@dataclass(frozen=True)
class HistoricalReviewerAssignment:
    scope: Scope
    assignment_id: str
    review_id: str
    plan_digest: Digest
    request_version: int
    fence: int
    method_ref: MethodRef
    reviewer_unit_ref_bytes: bytes
    author_unit_ref_bytes: bytes | None
    roles: tuple[str, ...]
    issuer_principal_id: str
    issuer_credential_epoch: int
    assigned_at: str
    digest: Digest = field(init=False)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.plan_digest) is not Digest
                or type(self.method_ref) is not MethodRef
                or type(self.roles) is not tuple or not self.roles
                or any(type(role) is not str for role in self.roles)):
            raise ReferenceError("INVALID_SCHEMA")
        for value in (self.assignment_id, self.review_id, self.issuer_principal_id):
            validate_id(value)
        validate_version(self.request_version)
        validate_version(self.fence, positive=True)
        validate_version(self.issuer_credential_epoch)
        utc_instant(self.assigned_at)
        roles = tuple(sorted(self.roles))
        if len(set(roles)) != len(roles):
            raise ReferenceError("INVALID_SCHEMA")
        for role in roles:
            validate_id(role)
        reviewer = _unit_ref(self.reviewer_unit_ref_bytes)
        author = _unit_ref(self.author_unit_ref_bytes)
        if reviewer is None:
            raise ReferenceError("INVALID_SCHEMA")
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "digest", record_digest("unit-reviewer-assignment", self.hash_payload()))

    def hash_payload(self):
        return {
            "scope": {"realm_id": self.scope.realm_id, "project_id": self.scope.project_id},
            "assignment_id": self.assignment_id,
            "review_id": self.review_id,
            "plan_digest": {"algorithm": self.plan_digest.algorithm, "hex": self.plan_digest.hex},
            "request_version": self.request_version,
            "fence": self.fence,
            "method_ref": {
                "method_id": self.method_ref.method_id,
                "release_version": self.method_ref.release_version,
                "schema_version": self.method_ref.schema_version,
                "snapshot_digest": {"algorithm": self.method_ref.snapshot_digest.algorithm,
                                    "hex": self.method_ref.snapshot_digest.hex},
            },
            "reviewer_unit_ref": _unit_ref(self.reviewer_unit_ref_bytes),
            "author_unit_ref": _unit_ref(self.author_unit_ref_bytes),
            "roles": list(self.roles),
            "issuer_principal_id": self.issuer_principal_id,
            "issuer_credential_epoch": self.issuer_credential_epoch,
            "assigned_at": self.assigned_at,
        }

    @property
    def ref(self) -> ReviewerAssignmentRef:
        return ReviewerAssignmentRef(self.scope, self.assignment_id, self.digest)

    @property
    def reviewer_unit_ref(self) -> dict:
        return _unit_ref(self.reviewer_unit_ref_bytes)

    @property
    def author_unit_ref(self) -> dict | None:
        return _unit_ref(self.author_unit_ref_bytes)


@dataclass(frozen=True)
class ReviewerAssignment:
    """Version2 Agent role selection by the ORIGINAL Engineering issuer."""
    scope: Scope
    assignment_id: str
    review_id: str
    plan_digest: Digest
    request_version: int
    fence: int
    method_ref: MethodRef
    reviewer_agent_ref_bytes: bytes
    author_agent_ref_bytes: bytes | None
    roles: tuple[str,...]
    issuer_principal_id: str
    issuer_credential_epoch: int
    assigned_at: str
    digest: Digest = field(init=False)

    def __post_init__(self):
        from ..common.models.execution_refs import read_agent_instance_ref
        if (type(self.scope) is not Scope or type(self.plan_digest) is not Digest
                or type(self.method_ref) is not MethodRef or type(self.roles) is not tuple or not self.roles
                or any(type(role) is not str for role in self.roles)):
            raise ReferenceError('INVALID_SCHEMA')
        for value in (self.assignment_id,self.review_id,self.issuer_principal_id):validate_id(value)
        validate_version(self.request_version);validate_version(self.fence,positive=True)
        validate_version(self.issuer_credential_epoch);utc_instant(self.assigned_at)
        roles=tuple(sorted(self.roles))
        if len(set(roles))!=len(roles):raise ReferenceError('INVALID_SCHEMA')
        for role in roles:validate_id(role)
        read_agent_instance_ref(self.reviewer_agent_ref_bytes)
        if self.author_agent_ref_bytes is not None:read_agent_instance_ref(self.author_agent_ref_bytes)
        object.__setattr__(self,'roles',roles)
        object.__setattr__(self,'digest',record_digest('agent-reviewer-assignment-v2',self.hash_payload()))

    def hash_payload(self):
        from ordessa_infrastructure.encoding import decode_json
        from ..common.mechanisms.codec import projection
        return {'schemaVersion':'engineering-agent-reviewer-assignment/2',
            'scope':projection(self.scope),'assignment_id':self.assignment_id,'review_id':self.review_id,
            'plan_digest':projection(self.plan_digest),'request_version':self.request_version,'fence':self.fence,
            'method_ref':projection(self.method_ref),'reviewer_agent_ref':decode_json(self.reviewer_agent_ref_bytes),
            'author_agent_ref':None if self.author_agent_ref_bytes is None else decode_json(self.author_agent_ref_bytes),
            'roles':list(self.roles),'issuer_principal_id':self.issuer_principal_id,
            'issuer_credential_epoch':self.issuer_credential_epoch,'assigned_at':self.assigned_at}

    @property
    def ref(self):return ReviewerAssignmentRef(self.scope,self.assignment_id,self.digest)

    @property
    def reviewer_agent_ref(self):
        from ordessa_infrastructure.encoding import decode_json
        return decode_json(self.reviewer_agent_ref_bytes)

    @property
    def author_agent_ref(self):
        from ordessa_infrastructure.encoding import decode_json
        return None if self.author_agent_ref_bytes is None else decode_json(self.author_agent_ref_bytes)

    def require_distinct_author(self):
        from ..common.models.execution_refs import read_agent_instance_ref,agent_instance_identity
        if self.author_agent_ref_bytes is not None and agent_instance_identity(read_agent_instance_ref(
                self.author_agent_ref_bytes))==agent_instance_identity(read_agent_instance_ref(self.reviewer_agent_ref_bytes)):
            raise ReferenceError('UNTRUSTED_REVIEWER')


@dataclass(frozen=True)
class ReviewerAssignmentControl:
    ref: ReviewerAssignmentRef
    state: str
    version: int
    revoked_at: str | None = None
    revoke_reason: str | None = None

    def __post_init__(self):
        if (type(self.ref) is not ReviewerAssignmentRef or type(self.state) is not str
                or self.state not in {"active", "revoked"}):
            raise ReferenceError("INVALID_SCHEMA")
        validate_version(self.version)
        if (self.state == "active" and self.version != 0) or (self.state == "revoked" and self.version != 1):
            raise ReferenceError("INVALID_SCHEMA")
        if self.state == "active" and (self.revoked_at is not None or self.revoke_reason is not None):
            raise ReferenceError("INVALID_SCHEMA")
        if self.state == "revoked":
            utc_instant(self.revoked_at)
            validate_text(self.revoke_reason)


__all__ = ["ReviewerAssignment", "HistoricalReviewerAssignment", "ReviewerAssignmentControl", "ReviewerAssignmentRef"]
