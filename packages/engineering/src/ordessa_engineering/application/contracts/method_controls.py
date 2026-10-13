"""Engineering method state; captured records are not management authority."""
from dataclasses import dataclass
from typing import Protocol
from ...domain.artifacts.method_binding import MethodRef
from ...domain.common.models.identity import Scope
from ...domain.common.models.values import Digest, validate_version, validate_id
from ...domain.common.outcomes.diagnostics import ReferenceError


@dataclass(frozen=True)
class MethodControl:
    scope: Scope
    method_ref: MethodRef
    enabled: bool
    version: int
    event_ref: Digest

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.method_ref) is not MethodRef or type(self.enabled) is not bool or type(self.event_ref) is not Digest:
            raise ReferenceError('INVALID_SCHEMA')
        validate_version(self.version)


@dataclass(frozen=True)
class MethodAdoption:
    scope: Scope
    adoption_id: str
    method_ref: MethodRef
    compiled_plan_digest: Digest
    version: int
    event_ref: Digest
    occurred_at: str

    def __post_init__(self):
        from ...domain.common.models.values import utc_instant
        if type(self.scope) is not Scope or type(self.method_ref) is not MethodRef or type(self.event_ref) is not Digest:
            raise ReferenceError('INVALID_SCHEMA')
        if type(self.compiled_plan_digest) is not Digest:
            raise ReferenceError('INVALID_SCHEMA')
        validate_id(self.adoption_id)
        validate_version(self.version, positive=True)
        utc_instant(self.occurred_at)


class MethodManagementPort(Protocol):
    """Actual control permission held through COMMIT; yields admitted event digest."""
    def guard_management(self, context, operation, method_ref, parameters): ...


class MethodStatePort(Protocol):
    def read_snapshot(self, method_ref):
        """Read the exact frozen definition for run history; no live effect grant."""
        ...
    def guard_method(self, context, method_ref, *, expected_version=None): ...
    def guard_selected(self, context, *, expected_version=None): ...
