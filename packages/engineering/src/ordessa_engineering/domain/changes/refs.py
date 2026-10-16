"""Exact proposal references; no proposal models or execution."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, NewType
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.common.models.values import Digest, validate_id, RealmId, ProjectId
from ordessa_engineering.domain.common.models.identity import Scope
ChangeId = NewType("ChangeId", str)
ProposalId = NewType("ProposalId", str)

def _fields(value, names):
    Scope(value.realm_id, value.project_id)
    for name in names:
        validate_id(getattr(value, name))
    if type(value.digest) is not Digest:
        raise ReferenceError("INVALID_SCHEMA")


@dataclass(frozen=True)
class ProposalRef:
    realm_id: RealmId
    project_id: ProjectId
    change_id: ChangeId
    proposal_id: ProposalId
    digest: Digest
    kind: Literal["proposal"] = field(default="proposal", init=False)

    def __post_init__(self):
        _fields(self, ("change_id", "proposal_id"))
