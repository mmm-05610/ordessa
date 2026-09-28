"""Hermes native codec backed by the unified ProfileStore."""
from pathlib import Path
from pacthold.extensions import ResourceSelection, SelectorField, SelectorCompatibility
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1
from pacthold.work_core import ProviderDescriptor, Ref, RefType
from ordessa_harness.generic.profile_store import ProfileStore, PROVIDER_ID
class ProfileRef:
    def __init__(self,pid,revision,digest): self.harness_id,self.profile_id,self.revision,self.digest,self.provider="hermes",pid,revision,digest,PROVIDER_ID
    def as_ref(self): return Ref(RefType.ARTIFACT,PROVIDER_ID,self.profile_id,metadata={"harness_type":"hermes","revision":str(self.revision),"digest":self.digest})
class HermesProfileProvider:
    provider_id=PROVIDER_ID
    def __init__(self,root): self.store=ProfileStore(Path(root))
    def descriptor(self): return ProviderDescriptor(PROVIDER_ID,"Harness Profile Store","2.0")
    def save(self,data,*,expected_revision=None): return self.store.put("hermes",data,expected_revision)
    def list_profiles(self): return self.store.list("hermes")
    def get(self,pid,revision=None): return self.store.get("hermes",pid,revision)
    def ref(self,pid,revision=None):
        x=self.get(pid,revision); return Ref(RefType.ARTIFACT,PROVIDER_ID,pid,metadata={"harness_type":"hermes","revision":str(x["revision"]),"digest":x["digest"]})
    def resolve(self,contract_id,ref,**kwargs):
        x=self.store.resolve(contract_id,ref); return x
class HermesProfileSelector:
    id="hermes-profile-selector"; contract_id=AgentBoxProfileV1.contract_id; title="Hermes profile"; fields=(SelectorField("profile_id","Profile",kind="select"),)
    compatibility=SelectorCompatibility(execution_provider_ids=frozenset({"hermes-execution"}),harness_types=frozenset({"hermes"}),supports_exact_revision=True,recommended=True)
    def __init__(self,provider): self.provider=provider
    def prepare(self,parameters,*,execution_id):
        del execution_id; ref=self.provider.ref(str(parameters.get("profile_id",""))); return ResourceSelection(self.contract_id,ref,ref.native_id,ref.metadata["digest"])
