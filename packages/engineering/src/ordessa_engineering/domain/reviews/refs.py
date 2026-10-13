"""Review identity and closed submission-target representation; no resolution."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, NewType
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.common.models.values import Digest, validate_id, RealmId, ProjectId
from ordessa_engineering.domain.common.models.identity import Scope
ReviewId = NewType("ReviewId", str)
SubmissionId = NewType("SubmissionId", str)

def _fields(value, names):
    Scope(value.realm_id, value.project_id)
    for name in names:
        validate_id(getattr(value, name))
    if type(value.digest) is not Digest:
        raise ReferenceError("INVALID_SCHEMA")


@dataclass(frozen=True)
class ReviewRef:
    realm_id: RealmId
    project_id: ProjectId
    review_id: ReviewId
    digest: Digest
    kind: Literal["review"] = field(default="review", init=False)

    def __post_init__(self):
        _fields(self, ("review_id",))


@dataclass(frozen=True)
class SubmissionRef:
    realm_id: RealmId
    project_id: ProjectId
    submission_id: SubmissionId
    digest: Digest
    kind: Literal["submission"] = field(default="submission", init=False)

    def __post_init__(self):
        _fields(self, ("submission_id",))
