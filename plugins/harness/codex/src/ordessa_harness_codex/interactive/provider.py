"""Provider-neutral interactive Codex Harness over a PTY TerminalSession."""
from __future__ import annotations
import json, shlex, sys, hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1, PromptFragmentV1, WorkspaceV1, CredentialRefV1
from pacthold.work_core import ExecutionProjection, ExecutionStartReceipt, ExecutionStartRequest, Freshness, Outcome, Phase, ProviderDescriptor, Ref, RefType
from ..contracts import CodexContinuationV1
from ..launch import CodexLaunchAdapter
from ..composition import command_from_plan, compose, composition_from_resolved_inputs
from pacthold_runtime_compat.runtime_composition import RuntimeBinding, TerminalRunHandle, RuntimeHostV1, SandboxV1, TerminalSessionV1, RuntimeCompositionCoordinator

def _now(): return datetime.now(timezone.utc)

@dataclass
class CodexInteractiveHandle:
    execution_id: str; dispatch_id: str; inputs_digest: str; workspace: WorkspaceV1; profile: AgentBoxProfileV1
    session_event_path: Path; projected_contracts: tuple[str, ...]; composition_handle: TerminalRunHandle
    requested_continuation: str | None = None; submitted: bool = False; submitted_outcome: Outcome | None = None
    # Honest PROJECTED-level receipt captured from the composition attempt.
    projection: Mapping[str, Any] | None = None
    @property
    def provider_correlation_ref(self): return f"codex://run/{self.dispatch_id}"

@dataclass(frozen=True)
class CodexInteractiveObservation:
    projection: ExecutionProjection; native_refs: tuple[Ref, ...]; output_refs: tuple[Ref, ...]
    projected_contracts: tuple[str, ...]; diagnostics: Mapping[str, Any]

class CodexInteractiveExecutionProvider:
    provider_id = "codex-interactive"
    def __init__(self, evidence_root: Path, *, launch_adapter: CodexLaunchAdapter, credential_materializer=None, coordinator: Any | None = None, runtime_binding: RuntimeBinding | None = None, terminal_observer: Any | None = None):
        self.evidence_root=evidence_root.resolve(); self._launch_adapter=launch_adapter; self._credential_materializer=credential_materializer; self._coordinator=coordinator; self._runtime_binding=runtime_binding; self._terminal_observer=terminal_observer; self._handles={}
    def descriptor(self): return ProviderDescriptor(self.provider_id, "Codex interactive", "0.1.0")
    def capabilities(self): return {"start":"supported","observe":"supported","attach":"supported","finish":"supported","continuation-input":"supported","pty":"required","completion-signal":"explicit"}
    def input_limits(self):
        limits={WorkspaceV1.contract_id:(1,1),PromptFragmentV1.contract_id:(1,None),AgentBoxProfileV1.contract_id:(1,1),CodexContinuationV1.contract_id:(0,1),CredentialRefV1.contract_id:(0,1)}
        if self._coordinator is None: limits.update({RuntimeHostV1.contract_id:(1,1),SandboxV1.contract_id:(1,1),TerminalSessionV1.contract_id:(1,1)})
        return limits
    @staticmethod
    def _one(request, contract):
        values=request.inputs.get(contract, ())
        if len(values)!=1: raise ValueError(f"expected one {contract}, got {len(values)}")
        return values[0]
    def start(self, request: ExecutionStartRequest):
        workspace=self._one(request,WorkspaceV1.contract_id); profile=self._one(request,AgentBoxProfileV1.contract_id)
        if not isinstance(workspace,WorkspaceV1) or not isinstance(profile,AgentBoxProfileV1): raise TypeError("resolved workspace/profile mismatch")
        fragments=request.inputs.get(PromptFragmentV1.contract_id,()); prompt="\n\n".join(f"# {f.title}\n\n{f.content}" for f in fragments if isinstance(f,PromptFragmentV1))
        if not prompt: raise ValueError("Codex interactive provider requires prompt content")
        continuation=next(iter(request.inputs.get(CodexContinuationV1.contract_id,())),None)
        self.evidence_root.mkdir(parents=True,exist_ok=True); event=self.evidence_root/f"{request.dispatch_id}.session-start.json"; event.unlink(missing_ok=True)
        hook=json.dumps("/usr/bin/python3 -c \"import runpy; runpy.run_path('/runtime/hooks/session-start')\" /runtime/home/session-start.json")
        extra=["--no-alt-screen","--dangerously-bypass-hook-trust","-c",f"hooks.SessionStart=[{{matcher=\"startup|resume\",hooks=[{{type=\"command\",command={hook},timeout=3}}]}}]"]
        if continuation is not None: extra += ["resume", continuation.thread_id]
        extra.append(prompt)
        profile_ref=next(i.ref for i in request.resolved_inputs if i.contract_id==AgentBoxProfileV1.contract_id)
        plan=self._launch_adapter.plan_interactive(execution_id=request.execution_id,profile_ref=profile_ref,profile=profile,workspace=workspace,extra_args=extra)
        command=command_from_plan(plan,execution_id=request.execution_id,io_mode="pty",requires_control_plane_network=True)
        binding, coordinator=((self._runtime_binding,self._coordinator) if self._coordinator is not None else composition_from_resolved_inputs(request,command,credential_materializer=self._credential_materializer))
        run=compose(coordinator,binding,command,execution_id=request.execution_id,dispatch_id=request.dispatch_id)
        projection=coordinator.projection_receipt(run.attempt_key) if isinstance(coordinator,RuntimeCompositionCoordinator) else None
        handle=CodexInteractiveHandle(request.execution_id,request.dispatch_id,request.inputs_digest,workspace,profile,event,tuple(sorted(request.inputs)),run,continuation.thread_id if continuation else None,projection=projection)
        self._handles[request.dispatch_id]=handle
        return ExecutionStartReceipt(request.execution_id,request.dispatch_id,request.inputs_digest,correlation_ref=Ref(RefType.SESSION,self.provider_id,request.dispatch_id,uri=handle.provider_correlation_ref),runtime_handle=handle)
    def get_handle(self, dispatch_id): return self._handles[dispatch_id]
    def recover_handle(self, **kwargs): raise RuntimeError("interactive recovery requires a live TerminalSession carrier")
    def observe(self, native_ref):
        handle=self.get_handle(native_ref) if isinstance(native_ref,str) else native_ref
        if isinstance(handle,ExecutionStartReceipt): handle=handle.runtime_handle
        transport=handle.composition_handle.transport; process=getattr(transport,"process",transport); alive=process.poll() is None if hasattr(process,"poll") else True
        projection=ExecutionProjection(Phase.TERMINAL,handle.submitted_outcome or Outcome.FAILED,False,Freshness.OBSERVED,_now()) if handle.submitted else (ExecutionProjection(Phase.ACTIVE,None,True,Freshness.OBSERVED,_now()) if alive else ExecutionProjection(Phase.UNKNOWN,None,None,Freshness.UNREACHABLE,_now()))
        session_id = handle.dispatch_id
        marker = handle.workspace.path / "session-start.json"
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            session_id = str(value.get("session_id") or session_id)
        except (OSError, ValueError, TypeError):
            pass
        outputs = ()
        marker_out = handle.workspace.path / "fake-codex-output.txt"
        if marker_out.is_file():
            outputs = (Ref(RefType.ARTIFACT, self.provider_id, "sha256:" + hashlib.sha256(marker_out.read_bytes()).hexdigest(), uri=marker_out.as_uri(), metadata={"kind":"harness-output"}),)
        return CodexInteractiveObservation(projection,(Ref(RefType.SESSION,self.provider_id,session_id,uri=f"codex://session/{session_id}", metadata={"source_provider": self.provider_id}),),outputs,handle.projected_contracts,{"terminal_run":handle.composition_handle.native_correlation,"projection":handle.projection})
    def finish(self, handle, **kwargs):
        if isinstance(handle,ExecutionStartReceipt): handle=handle.runtime_handle
        if not handle.submitted:
            process=getattr(handle.composition_handle.transport,"process",handle.composition_handle.transport)
            if hasattr(process,"poll") and process.poll() is None: process.terminate()
            handle.submitted=True; handle.submitted_outcome=Outcome.SUCCEEDED
            if self._coordinator is not None: self._coordinator.cleanup(handle.composition_handle.attempt_key)
            self._launch_adapter.cleanup(handle.execution_id)
        return self.observe(handle)

__all__=["CodexInteractiveExecutionProvider","CodexInteractiveHandle","CodexInteractiveObservation"]
