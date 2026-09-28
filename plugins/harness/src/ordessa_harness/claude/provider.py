from __future__ import annotations
import hashlib, json, subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1, PromptFragmentV1, WorkspaceV1
from pacthold.work_core import (ExecutionProjection, ExecutionStartReceipt, ExecutionStartRequest, Freshness, Outcome,
    Phase, ProviderDescriptor, Ref, RefType)
from pacthold_runtime_compat.runtime_composition import RuntimeBinding, RuntimeHostV1, SandboxV1, TerminalSessionV1, TerminalRunHandle
from .contracts import ClaudeContinuationV1
from .composition import command_from_plan, compose, composition_from_resolved_inputs

def _now(): return datetime.now(timezone.utc)

@dataclass
class ClaudeHandle:
    execution_id: str; dispatch_id: str; workspace: WorkspaceV1; profile: AgentBoxProfileV1
    run: TerminalRunHandle; submitted: bool = False; outcome: Outcome | None = None
    continuation: str | None = None; output_path: Path | None = None

@dataclass(frozen=True)
class ClaudeObservation:
    projection: ExecutionProjection; native_refs: tuple[Ref, ...]; output_refs: tuple[Ref, ...]
    projected_contracts: tuple[str, ...]; diagnostics: dict[str, Any]

class ClaudeCodeExecutionProvider:
    provider_id = "claude-code-execution"
    def __init__(self, evidence_root: Path, *, launch_adapter, coordinator=None, runtime_binding: RuntimeBinding | None=None):
        self.evidence_root=Path(evidence_root).resolve(); self.launch_adapter=launch_adapter; self.coordinator=coordinator; self.runtime_binding=runtime_binding; self.handles={}
    def descriptor(self): return ProviderDescriptor(self.provider_id, "Claude Code execution", "0.1.0")
    def get_handle(self, dispatch_id): return self.handles[dispatch_id]
    def capabilities(self): return {"start":"supported", "observe":"supported", "finish":"supported", "continuation-input":"supported", "direct-stdio":"supported", "pty":"conditional", "completion-signal":"explicit", "git-output":"supported"}
    def input_limits(self):
        result={WorkspaceV1.contract_id:(1,1), PromptFragmentV1.contract_id:(1,None), AgentBoxProfileV1.contract_id:(1,1), ClaudeContinuationV1.contract_id:(0,1)}
        if self.coordinator is None: result.update({RuntimeHostV1.contract_id:(1,1), SandboxV1.contract_id:(1,1), TerminalSessionV1.contract_id:(1,1)})
        return result
    @staticmethod
    def _one(request, contract):
        values=request.inputs.get(contract, ())
        if len(values) != 1: raise ValueError(f"expected one {contract}")
        return values[0]
    def start(self, request: ExecutionStartRequest):
        workspace=self._one(request, WorkspaceV1.contract_id); profile=self._one(request, AgentBoxProfileV1.contract_id)
        if not isinstance(workspace, WorkspaceV1) or not isinstance(profile, AgentBoxProfileV1): raise TypeError("Claude input type mismatch")
        fragments=request.inputs.get(PromptFragmentV1.contract_id, ())
        prompt="\n\n".join(f"# {f.title}\n\n{f.content}" for f in fragments if isinstance(f, PromptFragmentV1))
        if not prompt: raise ValueError("Claude requires prompt content")
        continuation=next(iter(request.inputs.get(ClaudeContinuationV1.contract_id, ())), None)
        if continuation is not None and not isinstance(continuation, ClaudeContinuationV1): raise TypeError("invalid Claude continuation")
        profile_ref=next(i.ref for i in request.resolved_inputs if i.contract_id == AgentBoxProfileV1.contract_id)
        plan=self.launch_adapter.plan(execution_id=request.execution_id, profile_ref=profile_ref, profile=profile, workspace=workspace, prompt=prompt, continuation=continuation.session_id if continuation else None)
        terminal_ref=next((i.value for i in request.resolved_inputs if i.contract_id == TerminalSessionV1.contract_id), None)
        terminal_identity = getattr(terminal_ref, "ref", terminal_ref)
        io_mode = str(getattr(terminal_identity, "metadata", {}).get("io_mode", "stdio"))
        command=command_from_plan(plan, execution_id=request.execution_id, io_mode=io_mode)
        binding, coordinator=((self.runtime_binding, self.coordinator) if self.coordinator is not None else composition_from_resolved_inputs(request, command))
        run=compose(coordinator, binding, command, execution_id=request.execution_id, dispatch_id=request.dispatch_id)
        handle=ClaudeHandle(request.execution_id, request.dispatch_id, workspace, profile, run, continuation=continuation.session_id if continuation else None)
        self.handles[request.dispatch_id]=handle
        return ExecutionStartReceipt(request.execution_id, request.dispatch_id, request.inputs_digest,
            correlation_ref=Ref(RefType.SESSION, self.provider_id, request.dispatch_id, uri=f"claude://run/{request.dispatch_id}"), runtime_handle=handle)
    def observe(self, native_ref):
        handle=native_ref.runtime_handle if isinstance(native_ref, ExecutionStartReceipt) else (self.handles[native_ref] if isinstance(native_ref, str) else native_ref)
        process=getattr(handle.run.transport, "process", handle.run.transport); alive=process.poll() is None if hasattr(process, "poll") else True
        projection=ExecutionProjection(Phase.TERMINAL, handle.outcome, False, Freshness.OBSERVED, _now()) if handle.submitted else (ExecutionProjection(Phase.ACTIVE, None, True, Freshness.OBSERVED, _now()) if alive else ExecutionProjection(Phase.UNKNOWN, None, None, Freshness.UNREACHABLE, _now()))
        session_id=handle.continuation or handle.dispatch_id
        marker=handle.workspace.path / "claude-session.json"
        try: session_id=str(json.loads(marker.read_text(encoding="utf-8")).get("session_id") or session_id)
        except (OSError, ValueError, TypeError): pass
        outputs=[]
        if handle.output_path and handle.output_path.is_file():
            outputs.append(Ref(RefType.ARTIFACT, self.provider_id, hashlib.sha256(handle.output_path.read_bytes()).hexdigest(), uri=handle.output_path.as_uri(), metadata={"kind":"claude-stdout"}))
        return ClaudeObservation(projection, (Ref(RefType.SESSION, self.provider_id, session_id, uri=f"claude://session/{session_id}", metadata={"native_authority":"project-keyed-jsonl"}),), tuple(outputs), tuple(), {"terminal_run":handle.run.native_correlation})
    def finish(self, handle, **kwargs):
        del kwargs
        if isinstance(handle, ExecutionStartReceipt): handle=handle.runtime_handle
        if not handle.submitted:
            process=getattr(handle.run.transport, "process", handle.run.transport)
            if hasattr(process, "poll") and process.poll() is None: process.terminate()
            handle.submitted=True; handle.outcome=Outcome.SUCCEEDED if getattr(process, "returncode", 0) in (0, None) else Outcome.FAILED
            if self.coordinator is not None: self.coordinator.cleanup(handle.run.attempt_key)
            self.launch_adapter.cleanup(handle.execution_id)
        return self.observe(handle)
