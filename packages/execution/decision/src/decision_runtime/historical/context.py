"""Explicit host-supplied historical read authority; no grant issuance."""
from dataclasses import dataclass
from .values import ContractError, name

@dataclass(frozen=True, repr=False)
class ReadContext:
    """Opaque capability; identity comparison is performed by the composed port."""
    authority: object
    scope_ref: str
    def __post_init__(self):
        if self.authority is None: raise ContractError('read_authority')
        name(self.scope_ref)
    def __repr__(self): return '<ReadContext>'
