"""Claude native codec façade over the shared ProfileStore."""
from dataclasses import dataclass
from pathlib import Path
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1
from pacthold.work_core import Ref, RefType, ProviderDescriptor
from ordessa_harness.generic.profile_store import ProfileStore, PROVIDER_ID
from .contracts import ClaudeContinuationV1
@dataclass(frozen=True)
class ClaudeProfileRef:
    profile_id: str; revision: int; digest: str; provider: str = PROVIDER_ID; harness_id: str = "claude-code"
    def as_ref(self): return Ref(RefType.ARTIFACT,self.provider,self.profile_id,metadata={"harness_type":self.harness_id,"revision":str(self.revision),"digest":self.digest})
class ClaudeProfileProvider:
    provider_id=PROVIDER_ID
    def __init__(self,root): self.store=ProfileStore(Path(root))
    def descriptor(self): return ProviderDescriptor(PROVIDER_ID,"Harness Profile Store","2.0")
    def put(self,pid,value,revision=None):
        row=self.store.put("claude-code",{"profile_id":pid,"native_payload":value},expected_revision=(revision-1 if revision else None)); return ClaudeProfileRef(pid,row["revision"],row["digest"])
    def get(self,pid,revision):
        row=self.store.get("claude-code",pid,revision); return {"profile_id":pid,"revision":row["revision"],"digest":row["digest"],"harness_type":"claude-code","profile":row["native_payload"]}
    def make_ref(self,pid,revision=1):
        row=self.store.get("claude-code",pid,revision); return ClaudeProfileRef(pid,row["revision"],row["digest"])
    def list_profiles(self): return tuple(ClaudeProfileRef(x["profile_id"],x["revision"],x["digest"]) for x in self.store.list("claude-code"))
    def resolve(self,contract_id,ref,**kwargs):
        if contract_id!=AgentBoxProfileV1.contract_id or ref.provider!=PROVIDER_ID: raise ValueError("PROFILE_REF_MISMATCH")
        row=self.store.get("claude-code",ref.native_id,int(ref.metadata["revision"]))
        if row["digest"]!=ref.metadata.get("digest"): raise ValueError("PROFILE_DIGEST_DRIFT")
        return AgentBoxProfileV1(row["name"],"claude-code",row["digest"],row["revision"],PROVIDER_ID)
class ClaudeContinuationResourceProvider:
    provider_id="claude-code-continuation"
    supported_contract_ids=frozenset({ClaudeContinuationV1.contract_id})
    def descriptor(self): return ProviderDescriptor(self.provider_id,"Claude native continuation","2.0")
    def resolve(self,contract_id,ref,**kwargs):
        if contract_id!=ClaudeContinuationV1.contract_id or ref.provider!=self.provider_id or ref.type is not RefType.SESSION: raise ValueError("CONTINUATION_REF_MISMATCH")
        return ClaudeContinuationV1(ref.native_id,ref.metadata.get("project_key",""))
from .profile import ClaudeProfileProvider as _P
class ClaudeProjection:
    def __init__(self,root,repository): self.root=Path(root).resolve(); self.repository=repository
    def materialize(self,execution_id,ref,*,resources=()):
        import json, shutil
        data=self.repository.get(ref.profile_id,ref.revision)["profile"]; root=self.root/execution_id; (root/".claude").mkdir(parents=True,exist_ok=True)
        (root/".claude/settings.json").write_text(json.dumps(data.get("settings",{}),sort_keys=True,indent=2)+"\n",encoding="utf-8")
        for kind,name,content in resources:
            if kind=="instruction": (root/name).write_text(content,encoding="utf-8")
            elif kind=="mcp": (root/".mcp.json").write_text(json.dumps({"mcpServers":{name:content}},sort_keys=True),encoding="utf-8")
            elif kind=="skill":
                target=root/".claude"/"skills"/name/"SKILL.md"; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(content,encoding="utf-8")
        manifest={"profile_ref":{"id":ref.profile_id,"revision":ref.revision,"digest":ref.digest},"native_files":sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()),"credential_locator":data.get("credential_locator")}
        (root/"agent-box-manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        return root
    def cleanup(self,execution_id):
        import shutil; shutil.rmtree(self.root/execution_id,ignore_errors=True)
