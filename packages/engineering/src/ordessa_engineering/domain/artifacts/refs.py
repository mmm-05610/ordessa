"""Exact artifact revision references; no lookup or authorization."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, NewType
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.common.models.values import Digest, validate_id, RealmId, ProjectId
from ordessa_engineering.domain.common.models.identity import Scope
ArtifactId = NewType("ArtifactId", str)
RevisionId = NewType("RevisionId", str)

def _fields(value, names):
    Scope(value.realm_id, value.project_id)
    for name in names:
        validate_id(getattr(value, name))
    if type(value.digest) is not Digest:
        raise ReferenceError("INVALID_SCHEMA")


@dataclass(frozen=True)
class ArtifactRevisionRef:
    realm_id: RealmId
    project_id: ProjectId
    artifact_id: ArtifactId
    revision_id: RevisionId
    digest: Digest
    kind: Literal["artifact_revision"] = field(default="artifact_revision", init=False)

    def __post_init__(self):
        _fields(self, ("artifact_id", "revision_id"))
