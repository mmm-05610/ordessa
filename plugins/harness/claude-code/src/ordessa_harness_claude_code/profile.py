"""Pure Claude native renderer for explicitly selected Profile revisions."""
from dataclasses import dataclass
from pathlib import Path
from ordessa_execution_api.resources.profiles import exact_historical_envelope
from ordessa_execution_agents.harness.definitions import NativeProfileRef, NativeContinuationRef, ProviderDescriptor
PROVIDER_ID = "harness-profile"  # preserved historical reference identity
from .contracts import ClaudeContinuationV1
@dataclass(frozen=True)
class ClaudeProfileRef:
    profile_id: str; revision: int; digest: str; provider: str = PROVIDER_ID; harness_id: str = "claude-code"
    def as_ref(self): return NativeProfileRef(self.provider,self.profile_id,metadata={"harness_type":self.harness_id,"revision":str(self.revision),"digest":self.digest})
class ClaudeContinuationResourceProvider:
    provider_id="claude-code-continuation"
    supported_contract_ids=frozenset({ClaudeContinuationV1.contract_id})
    def descriptor(self): return ProviderDescriptor(self.provider_id,"Claude native continuation","2.0")
    def resolve(self,contract_id,ref,**kwargs):
        if contract_id!=ClaudeContinuationV1.contract_id or type(ref) is not NativeContinuationRef or ref.provider!=self.provider_id: raise ValueError("CONTINUATION_REF_MISMATCH")
        return ClaudeContinuationV1(ref.native_id,ref.metadata.get("project_key",""))
class ClaudeProjection:
    def __init__(self,root): self.root=Path(root).resolve()
    def materialize_current(self, execution_id, ref, *, modern_ref,
                            historical_ref, profile_views, resources=()):
        """Render a fixed view produced by the same Environment Profile owner."""
        from ordessa_execution_api.resources.profiles import HistoricalProfileViewPort
        if not isinstance(profile_views, HistoricalProfileViewPort):
            raise TypeError("admitted historical Profile view port required")
        view = profile_views.select_current(modern_ref, historical_ref)
        return self.materialize(execution_id, ref, historical_view=view, resources=resources)
    def materialize(self,execution_id,ref,*,historical_view,resources=()):
        import json
        if (type(ref) is not ClaudeProfileRef or ref.provider != PROVIDER_ID
                or ref.harness_id != "claude-code"):
            raise ValueError("PROFILE_REF_MISMATCH")
        envelope=exact_historical_envelope(historical_view,harness_type="claude-code",
            profile_id=ref.profile_id,revision=ref.revision,digest=ref.digest)
        data=envelope["native_payload"]; root=self.root/execution_id; (root/".claude").mkdir(parents=True,exist_ok=True)
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
