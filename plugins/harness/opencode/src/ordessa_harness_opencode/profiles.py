"""OpenCode historical reference value and independent continuation provider."""
from dataclasses import dataclass
from ordessa_execution_agents.harness.definitions import ProviderDescriptor, NativeProfileRef, NativeContinuationRef

PROVIDER_ID = "harness-profile"  # preserved historical reference identity

@dataclass(frozen=True)
class OpenCodeProfileRef:
    profile_id: str
    revision: int
    digest: str
    provider: str = PROVIDER_ID

    def as_ref(self):
        return NativeProfileRef(PROVIDER_ID, self.profile_id,
                   metadata={"harness_type": "opencode", "revision": str(self.revision),
                             "digest": self.digest})

class OpenCodeContinuationResourceProvider:
    provider_id = "opencode-continuation"
    supported_contract_ids = frozenset({"agent-box.opencode-continuation@1"})

    def descriptor(self):
        return ProviderDescriptor(self.provider_id, "OpenCode continuation", "2.0")

    def resolve(self, contract_id, ref, **kwargs):
        from . import OpenCodeContinuationV1
        if contract_id != OpenCodeContinuationV1.contract_id or type(ref) is not NativeContinuationRef or ref.provider != self.provider_id:
            raise ValueError("CONTINUATION_REF_MISMATCH")
        return OpenCodeContinuationV1(ref.native_id)
