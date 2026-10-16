from __future__ import annotations
from dataclasses import dataclass
import re
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
_KINDS = re.compile('^[a-z][a-z0-9-]{0,63}$')
_IDENTIFIER = re.compile('^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,191}$')
_DIGEST = re.compile('^sha256:[0-9a-f]{64}$')

@dataclass(frozen=True)
class MaterialRef:
    library_id: str
    kind: str
    stable_id: str
    revision: int
    digest: str

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.library_id):
            raise EngineeringError('ref_library_id')
        if not _KINDS.fullmatch(self.kind):
            raise EngineeringError('ref_kind')
        if not _IDENTIFIER.fullmatch(self.stable_id):
            raise EngineeringError('ref_stable_id')
        if type(self.revision) is not int or self.revision < 1:
            raise EngineeringError('ref_revision')
        if not _DIGEST.fullmatch(self.digest):
            raise EngineeringError('ref_digest')
