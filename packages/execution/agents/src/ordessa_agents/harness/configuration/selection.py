"""Harness credential selection values; no grant or storage authority.

Native credential identity remains provider-owned, without a generic Work Ref.
"""
from dataclasses import dataclass
from ordessa_agents.harness.definitions import NativeCredentialRef

@dataclass(frozen=True)
class CredentialSelection:
    contract_id: str
    ref: NativeCredentialRef
    requested_summary: str = ""
    exact_summary: str = ""

    def __post_init__(self):
        if type(self.ref) is not NativeCredentialRef:
            raise ValueError('credential selection requires its concrete native credential identity')
        if not isinstance(self.contract_id,str) or not self.contract_id:
            raise ValueError('credential selection requires a contract')

@dataclass(frozen=True)
class SelectorField:
    key: str
    label: str
    kind: str = "text"
    default: str = ""
    required: bool = True
    help: str = ""
