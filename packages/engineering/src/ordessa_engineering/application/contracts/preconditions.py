"""Application read-set expectation projection; SQLite still consumes ReadSet.versions.

The signed-63-bit range is preserved. This value is not a new CAS authority.
"""
from dataclasses import dataclass
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest, validate_id
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError

__all__ = ['VersionExpectation']


@dataclass(frozen=True)
class VersionExpectation:
    kind: str
    realm_id: str
    project_id: str
    object_id: str
    expected_version: int
    expected_digest: Digest | None = None

    def __post_init__(self):
        Scope(self.realm_id, self.project_id)
        validate_id(self.kind)
        validate_id(self.object_id)
        # Preserve the existing SQLite CAS range, distinct from JSON numbers.
        if type(self.expected_version) is not int or not 0 <= self.expected_version <= (1 << 63) - 1:
            raise ReferenceError("INVALID_VERSION")
        if self.expected_digest is not None and type(self.expected_digest) is not Digest:
            raise ReferenceError("INVALID_SCHEMA")
