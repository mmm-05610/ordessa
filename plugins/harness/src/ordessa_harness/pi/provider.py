"""Pi ExecutionProvider: command producer only; Runtime Composition owns launch."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from pacthold.work_core import ExecutionProjection, ExecutionStartReceipt, ExecutionStartRequest, Freshness, Outcome, Phase, ProviderDescriptor, Ref, RefType
from pacthold_runtime_compat.runtime_composition import RuntimeCompositionCoordinator, RuntimeBinding, TerminalRunHandle
from .config import PiPluginConfig, PiProfile
from .contract import PiContinuationV1
from .projection import command_from_request, composition_from_resolved_inputs

def _now(): return datetime.now(timezone.utc)

@dataclass
class PiHandle:
    execution_id: str; dispatch_id: str; session_id: str; command_digest: str
    runtime: TerminalRunHandle; projected_contracts: tuple[str, ...]; coordinator: Any = None; submitted: bool = False

@dataclass(frozen=True)
class PiObservation:
    projection: ExecutionProjection
    native_refs: tuple[Ref, ...]
    output_refs: tuple[Ref, ...]
    projected_contracts: tuple[str, ...]
    runtime_facts: Mapping[str, str]

class PiExecutionProvider:
    provider_id = "pi"
    def get_handle(self, dispatch_id): return self._handles[dispatch_id]
    def __init__(self, *, config_loader: Callable[[], PiPluginConfig] = PiPluginConfig.load,
                 composition_factory: Callable[[ExecutionStartRequest], tuple[RuntimeBinding, RuntimeCompositionCoordinator]] = composition_from_resolved_inputs):
        self._config_loader=config_loader; self._composition_factory=composition_factory; self._handles={}
    def descriptor(self): return ProviderDescriptor("pi", "Pi / DeepSeek Harness", "0.2.0")
    def capabilities(self): return {"start":"supported", "command-spec":"supported", "runtime-composition":"required", "io":"stdio+pty", "finish":"explicit", "continuation":"new-execution", "provider":"deepseek"}
    def input_limits(self): return {"agent-box.workspace@1":(1,1), "agent-box.prompt-fragment@1":(1,None), "agent-box.profile@1":(1,1), "agent-box.runtime-host@1":(1,1), "agent-box.sandbox@1":(1,1), "agent-box.terminal-session@1":(1,1), PiContinuationV1.contract_id:(0,1)}
    def start(self, request: ExecutionStartRequest) -> ExecutionStartReceipt:
        config=self._config_loader(); profile_value=next((x.value for x in request.resolved_inputs if x.contract_id == "agent-box.profile@1"), None)
        profile=config.profile()
        if profile_value is not None and isinstance(profile_value, PiProfile): profile=profile_value
        command=command_from_request(request, profile)
        binding, coordinator=self._composition_factory(request, command)
        runtime=coordinator.start(binding, command, execution_id=request.execution_id, dispatch_id=request.dispatch_id)
        continuation=next((x.value for x in request.resolved_inputs if isinstance(x.value, PiContinuationV1)), None)
        session_id=continuation.session_id if continuation else request.execution_id
        handle=PiHandle(request.execution_id, request.dispatch_id, session_id, command.digest, runtime, tuple(sorted(x.contract_id for x in request.resolved_inputs)), coordinator)
        self._handles[request.dispatch_id]=handle
        return ExecutionStartReceipt(request.execution_id, request.dispatch_id, request.inputs_digest, correlation_ref=Ref(RefType.SESSION,"pi",session_id,metadata={"provider":"deepseek","model":profile.model}), runtime_handle=handle)
    def observe(self, native_ref: Any) -> PiObservation:
        handle=self._handles[native_ref] if isinstance(native_ref,str) else (native_ref.runtime_handle if isinstance(native_ref,ExecutionStartReceipt) else native_ref)
        if not isinstance(handle, PiHandle): raise TypeError("observe requires PiHandle")
        if handle.submitted:
            process = handle.runtime.transport
            outcome = Outcome.FAILED if process is not None and getattr(process, "returncode", 0) not in (0, None) else Outcome.SUCCEEDED
            phase, resumable = Phase.TERMINAL, False
        else: phase, outcome, resumable = Phase.ACTIVE, None, True
        return PiObservation(ExecutionProjection(phase,outcome,resumable,Freshness.OBSERVED,_now()), (Ref(RefType.SESSION,"pi",handle.session_id,metadata={"provider":"deepseek"}),), (), handle.projected_contracts, {"io":"composition-owned", "runtime_correlation":handle.runtime.native_correlation})
    def finish(self, handle: PiHandle | ExecutionStartReceipt, *, coordinator: RuntimeCompositionCoordinator | None = None) -> PiObservation:
        if isinstance(handle, ExecutionStartReceipt): handle=handle.runtime_handle
        if not isinstance(handle, PiHandle): raise TypeError("finish requires PiHandle")
        if not handle.submitted:
            process = handle.runtime.transport
            if process is not None and callable(getattr(process, "wait", None)):
                process.wait(timeout=30)
            cleanup = coordinator or handle.coordinator
            if cleanup is not None: cleanup.cleanup(handle.runtime.attempt_key)
            handle.submitted=True
        return self.observe(handle)
