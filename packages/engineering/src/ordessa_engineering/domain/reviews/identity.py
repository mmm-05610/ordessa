"""Review record identity with its existing historical schema acceptance."""
from dataclasses import dataclass
from ordessa_engineering.domain.common.models.identity import Scope, ActorRef
from ordessa_engineering.domain.common.models.values import UtcInstant, validate_id, utc_instant
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError

@dataclass(frozen=True)
class RecordIdentity:
    scope: Scope
    record_id: str
    created_at: UtcInstant
    created_by: ActorRef
    schema_version: int = 1

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.created_by) is not ActorRef:
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.record_id)
        utc_instant(self.created_at)
        if type(self.schema_version) is not int or self.schema_version not in {1, 2}:
            raise ReferenceError("INVALID_SCHEMA")
