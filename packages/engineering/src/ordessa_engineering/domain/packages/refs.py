"""Exact implementation package identity, not an execution capability."""
from dataclasses import dataclass, field
from typing import Literal
from ..common.models.identity import Scope
from ..common.models.values import Digest, validate_id
from ..common.outcomes.diagnostics import ReferenceError

@dataclass(frozen=True)
class ImplementationPackageRef:
    realm_id: str
    project_id: str
    package_id: str
    digest: Digest
    kind: Literal['implementation_package'] = field(default='implementation_package', init=False)

    def __post_init__(self):
        Scope(self.realm_id, self.project_id)
        validate_id(self.package_id)
        if type(self.digest) is not Digest:
            raise ReferenceError('INVALID_PACKAGE_REF')
