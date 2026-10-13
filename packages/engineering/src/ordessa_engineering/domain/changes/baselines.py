"""Captured implementation baseline references; no repository authority."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, NewType
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.common.models.values import Digest, validate_id, RealmId, ProjectId
from ordessa_engineering.domain.common.models.identity import Scope
import re
RepositoryId = NewType("RepositoryId", str)

@dataclass(frozen=True)
class RepositorySnapshotRef:
    realm_id: RealmId
    project_id: ProjectId
    repository_id: RepositoryId
    vcs: Literal["git", "none"]
    commit_id: str | None
    tree_digest: Digest
    dirty_overlay_digest: Digest | None
    kind: Literal["repository_snapshot"] = field(default="repository_snapshot", init=False)

    def __post_init__(self):
        Scope(self.realm_id, self.project_id)
        validate_id(self.repository_id)
        if type(self.vcs) is not str or self.vcs not in {"git", "none"} or (self.vcs == "none" and self.commit_id is not None):
            raise ReferenceError("INVALID_SCHEMA")
        if self.commit_id is not None and (type(self.commit_id) is not str or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", self.commit_id)):
            raise ReferenceError("INVALID_SCHEMA")
        if type(self.tree_digest) is not Digest or (self.dirty_overlay_digest is not None and type(self.dirty_overlay_digest) is not Digest):
            raise ReferenceError("INVALID_SCHEMA")
