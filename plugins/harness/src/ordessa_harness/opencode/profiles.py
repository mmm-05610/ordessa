"""OpenCode native codec façade; persistence remains ProfileStore-owned."""
from dataclasses import dataclass
from pathlib import Path
from pacthold.extensions import ResourceSelection, SelectorField, SelectorCompatibility
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1
from pacthold.work_core import ProviderDescriptor, Ref, RefType
from ordessa_harness.generic.profile_store import ProfileStore, PROVIDER_ID
@dataclass(frozen=True)
class OpenCodeProfileRef:
    profile_id: str; revision: int; digest: str
    provider: str = PROVIDER_ID
    def as_ref(self): return Ref(RefType.ARTIFACT,PROVIDER_ID,self.profile_id,metadata={"harness_type":"opencode","revision":str(self.revision),"digest":self.digest})
class OpenCodeProfileAuthority:
    def __init__(self,root): self.store=ProfileStore(Path(root))
    def save(self,profile,*,expected_revision=None):
        row=self.store.put("opencode",profile,expected_revision); return OpenCodeProfileRef(row["profile_id"],row["revision"],row["digest"])
    def resolve(self,ref): return self.store.get("opencode",ref.profile_id,ref.revision)
class OpenCodeProfileProvider:
    provider_id=PROVIDER_ID
    def __init__(self,root): self.authority=OpenCodeProfileAuthority(root)
    def descriptor(self): return ProviderDescriptor(PROVIDER_ID,"Harness Profile Store","2.0")
    def list_profiles(self): return self.authority.store.list("opencode")
    def get_profile(self,pid,revision=None): return self.authority.store.get("opencode",pid,revision)
    def resolve(self,contract_id,ref,**kwargs): return self.authority.store.resolve(contract_id,ref)
class OpenCodeProfileSelector:
    id="opencode-profile-selector"; contract_id=AgentBoxProfileV1.contract_id; title="OpenCode profile"; fields=(SelectorField("profile_id","Profile",kind="select"),)
    compatibility=SelectorCompatibility(execution_provider_ids=frozenset({"opencode-direct"}),harness_types=frozenset({"opencode"}),supports_exact_revision=True,recommended=True)
    def __init__(self,provider): self.provider=provider
    def prepare(self,parameters,*,execution_id):
        del execution_id; x=self.provider.get_profile(str(parameters.get("profile_id",""))); ref=Ref(RefType.ARTIFACT,PROVIDER_ID,x["profile_id"],metadata={"harness_type":"opencode","revision":str(x["revision"]),"digest":x["digest"]}); return ResourceSelection(self.contract_id,ref,x["profile_id"],x["digest"])
class OpenCodeManager:
    def __init__(self,provider): self.provider=provider; self.harness_id="opencode"
    def descriptor(self): return {"id":"opencode","display_name":"OpenCode","version":"2.0","status":"ready","supported":True}
    def list_profiles(self): return self.provider.list_profiles()
    def get_profile(self,pid,revision=None): return self.provider.get_profile(pid,revision)
class OpenCodeContinuationResourceProvider:
    provider_id="opencode-continuation"; supported_contract_ids=frozenset({"agent-box.opencode-continuation@1"})
    def descriptor(self): return ProviderDescriptor(self.provider_id,"OpenCode continuation","2.0")
    def resolve(self,contract_id,ref,**kwargs):
        from .provider import OpenCodeContinuationV1
        if contract_id!=OpenCodeContinuationV1.contract_id or ref.provider!=self.provider_id: raise ValueError("CONTINUATION_REF_MISMATCH")
        return OpenCodeContinuationV1(ref.native_id)
