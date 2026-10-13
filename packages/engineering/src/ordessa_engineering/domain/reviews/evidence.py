"""Captured reviewer verification facts; actual trust remains an injected authority."""
from dataclasses import dataclass
from ordessa_engineering.domain.common.models.identity import Scope, ActorRef
from ordessa_engineering.domain.common.models.values import Digest, validate_id, validate_version, validate_items, ordered_unique
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError

@dataclass(frozen=True)
class VerifiedReviewerEvidence:
    """Captured verification facts; only a trusted application port admits them.

    This public value does not grant access or attest itself. Production gate
    consumers must revalidate current trust versions through the original owner.
    """
    scope: Scope
    reviewer: ActorRef
    roles: tuple[str, ...]
    verifier_id: str
    verifier_version: str
    trust_version: int
    request_digest: Digest
    raw_response_digest: Digest
    observations_digest: Digest
    capability_digest: Digest

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.reviewer) is not ActorRef:
            raise ReferenceError("INVALID_SCHEMA")
        for value in (self.verifier_id, self.verifier_version):
            validate_id(value)
        validate_version(self.trust_version)
        validate_items(self.roles, str, nonempty=True)
        for role in self.roles:
            validate_id(role)
        object.__setattr__(self, "roles", ordered_unique(self.roles, lambda role: role, code="DUPLICATE_ROLE"))
        for value in (self.request_digest, self.raw_response_digest, self.observations_digest, self.capability_digest):
            if type(value) is not Digest:
                raise ReferenceError("INVALID_SCHEMA")
