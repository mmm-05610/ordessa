"""Shared scope and attribution; no record schema, authentication or permission."""
from dataclasses import dataclass
from .values import RealmId, ProjectId, ActorId, validate_id
from ..outcomes.diagnostics import ReferenceError

@dataclass(frozen=True)
class Scope:
    realm_id: RealmId
    project_id: ProjectId

    def __post_init__(self):
        validate_id(self.realm_id)
        validate_id(self.project_id)


@dataclass(frozen=True)
class ActorRef:
    actor_id: ActorId
    actor_kind: str
    issuer: str

    def __post_init__(self):
        validate_id(self.actor_id)
        validate_id(self.issuer)
        if type(self.actor_kind) is not str or self.actor_kind not in {"human", "agent", "checker", "service"}:
            raise ReferenceError("INVALID_ACTOR")
