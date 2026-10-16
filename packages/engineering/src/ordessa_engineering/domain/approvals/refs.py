"""Exact approval grant reference; not issuance or verification."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, NewType
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.common.models.values import Digest, validate_id, RealmId, ProjectId
from ordessa_engineering.domain.common.models.identity import Scope
ApprovalId = NewType("ApprovalId", str)

@dataclass(frozen=True)
class ApprovalRef:
    realm_id: RealmId
    project_id: ProjectId
    approval_id: ApprovalId
    grant_digest: Digest
    kind: Literal["approval"] = field(default="approval", init=False)

    def __post_init__(self):
        Scope(self.realm_id, self.project_id)
        validate_id(self.approval_id)
        if type(self.grant_digest) is not Digest:
            raise ReferenceError("INVALID_SCHEMA")


@dataclass(frozen=True)
class ConsentPolicyRef:
    policy_id: str
    revision: int
    digest: Digest

    def __post_init__(self):
        validate_id(self.policy_id)
        if type(self.revision) is not int or self.revision < 1 or type(self.digest) is not Digest:
            raise ReferenceError('INVALID_CONSENT_POLICY')


@dataclass(frozen=True)
class NoticeRef:
    scope: Scope
    notice_id: str
    digest: Digest

    def __post_init__(self):
        validate_id(self.notice_id)
        if type(self.scope) is not Scope or type(self.digest) is not Digest:
            raise ReferenceError('INVALID_NOTICE')


