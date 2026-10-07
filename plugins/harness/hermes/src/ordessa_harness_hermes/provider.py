from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1, PromptFragmentV1, WorkspaceV1
from pacthold.work_core import ExecutionStartRequest, ExecutionStartReceipt, ExecutionProjection, Freshness, Outcome, Phase, ProviderDescriptor, Ref, RefType
from pacthold_runtime_compat.runtime_composition import RuntimeHostV1, SandboxV1, TerminalSessionV1
from .contracts import HermesContinuationV1
from .launch import HermesLaunchAdapter
from .composition import command_from_plan, composition_from_resolved_inputs

@dataclass
class HermesHandle:
    execution_id: str; dispatch_id: str; inputs_digest: str; workspace: WorkspaceV1; process: object; output_path: Path; profile_ref: Ref; submitted: bool=False; output: str=""; error: str=""

@dataclass(frozen=True)
class HermesObservation:
    projection: ExecutionProjection
    native_refs: tuple[Ref, ...]
    output_refs: tuple[Ref, ...]
    projected_contracts: tuple[str, ...]
    diagnostics: dict[str, object] = field(default_factory=dict)
    def __getitem__(self, key):
        return getattr(self, key)

class HermesExecutionProvider:
    provider_id="hermes-execution"
    def get_handle(self, dispatch_id): return self.handles[dispatch_id]
    def __init__(self, evidence_root: Path, *, launch_adapter: HermesLaunchAdapter, coordinator=None): self.evidence_root=Path(evidence_root); self.launch_adapter=launch_adapter; self.coordinator=coordinator; self.handles={}
    def descriptor(self): return ProviderDescriptor(self.provider_id, "Hermes ExecutionProvider", "0.1.0")
    def capabilities(self): return {"start":"supported","observe":"supported","finish":"supported","continuation-input":"transcript-context-handoff","native-resume":"unsupported"}
    def input_limits(self): return {WorkspaceV1.contract_id:(1,1),PromptFragmentV1.contract_id:(1,None),AgentBoxProfileV1.contract_id:(1,1),HermesContinuationV1.contract_id:(0,1),RuntimeHostV1.contract_id:(1,1),SandboxV1.contract_id:(1,1),TerminalSessionV1.contract_id:(1,1)}
    def _one(self, request, cid):
        values=request.inputs.get(cid, ())
        if len(values)!=1: raise ValueError(f"expected one {cid}")
        return values[0]
    def start(self, request: ExecutionStartRequest):
        workspace=self._one(request,WorkspaceV1.contract_id); profile=self._one(request,AgentBoxProfileV1.contract_id)
        if not isinstance(workspace,WorkspaceV1) or not isinstance(profile,AgentBoxProfileV1) or profile.agent_type!="hermes": raise TypeError("Hermes workspace/profile mismatch")
        profile_ref=next(x.ref for x in request.resolved_inputs if x.contract_id==AgentBoxProfileV1.contract_id)
        plan=self.launch_adapter.plan(execution_id=request.execution_id,profile_ref=profile_ref,workspace=workspace,profile=profile); command=command_from_plan(plan)
        if self.coordinator is None: binding, coordinator = composition_from_resolved_inputs(request, command)
        else: binding, coordinator = self.coordinator
        run=coordinator.start(binding,command,execution_id=request.execution_id,dispatch_id=request.dispatch_id); process=getattr(run,"transport",None)
        if process is None: raise RuntimeError("terminal composition did not return a process transport")
        prompt="\n\n".join(f"# {x.title}\n\n{x.content}" for x in request.inputs.get(PromptFragmentV1.contract_id,()) if isinstance(x,PromptFragmentV1))
        continuation=request.inputs.get(HermesContinuationV1.contract_id,())
        if continuation: prompt="Context handoff (native Hermes resume unavailable):\n"+continuation[0].transcript_ref+"\n\n"+prompt
        process.stdin.write(prompt+"\n"); process.stdin.flush()
        out=self.evidence_root/f"{request.dispatch_id}.txt"; out.parent.mkdir(parents=True,exist_ok=True)
        handle=HermesHandle(request.execution_id,request.dispatch_id,request.inputs_digest,workspace,process,out,profile_ref); self.handles[request.dispatch_id]=handle
        return ExecutionStartReceipt(request.execution_id,request.dispatch_id,request.inputs_digest,correlation_ref=None,runtime_handle=handle)
    def observe(self, native_ref):
        h=self.handles[native_ref] if isinstance(native_ref,str) else native_ref
        alive=h.process.poll() is None
        phase = Phase.ACTIVE if alive and not h.submitted else (Phase.TERMINAL if h.submitted else Phase.UNKNOWN)
        outcome = None if phase is not Phase.TERMINAL else (Outcome.SUCCEEDED if h.process.returncode == 0 else Outcome.FAILED)
        outputs = (Ref(RefType.ARTIFACT, self.provider_id, h.output_path.name, uri=h.output_path.as_uri()),) if h.submitted else ()
        return HermesObservation(ExecutionProjection(phase, outcome, phase is Phase.ACTIVE, Freshness.OBSERVED, datetime.now(timezone.utc)), (), outputs, (AgentBoxProfileV1.contract_id,), {"stderr":h.error[-2048:], "process_exit":h.process.returncode, "native_resume":"unsupported", "continuation":"transcript-context-handoff"})
    def finish(self, handle, *, timeout=300):
        h=handle.runtime_handle if isinstance(handle,ExecutionStartReceipt) else handle
        try: out, err=h.process.communicate(timeout=timeout)
        except Exception: h.process.kill(); out,err=h.process.communicate()
        h.output=out or ""; h.error=err or ""; h.output_path.write_text(h.output,encoding="utf-8"); h.submitted=True; result=self.observe(h); self.launch_adapter.cleanup(h.execution_id); return result
