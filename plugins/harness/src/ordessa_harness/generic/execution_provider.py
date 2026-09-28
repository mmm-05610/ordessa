from __future__ import annotations
from dataclasses import dataclass
from pacthold.work_core import ExecutionStartReceipt, ExecutionStartRequest, ProviderDescriptor, Ref, RefType
from pacthold_runtime_compat.runtime_composition import assemble_runtime_composition
@dataclass
class GenericHandle:
    request: object; runtime: object; command: object; submitted: bool=False
class GenericExecutionProvider:
    def __init__(self,definition,adapter): self.definition,self.adapter=definition,adapter; self.provider_id=f"{definition.harness_type}-execution"; self._handles={}
    def descriptor(self): return ProviderDescriptor(self.provider_id,self.definition.display_name+" execution",self.definition.identity.version)
    def capabilities(self): return {key:"supported" for key in self.definition.capabilities}
    def input_limits(self): return {x.contract_id:(x.minimum,x.maximum) for x in self.definition.inputs}
    def start(self,request: ExecutionStartRequest):
        profile=next((x.value for x in request.resolved_inputs if x.contract_id=="agent-box.profile@1"),{})
        command=self.adapter.build_command(self.definition,request,profile)
        binding,coordinator=assemble_runtime_composition(request,command)
        runtime=coordinator.start(binding,command,execution_id=request.execution_id,dispatch_id=request.dispatch_id)
        handle=GenericHandle(request,runtime,command); self._handles[request.dispatch_id]=handle
        return ExecutionStartReceipt(request.execution_id,request.dispatch_id,request.inputs_digest,correlation_ref=Ref(RefType.SESSION,self.provider_id,request.execution_id),runtime_handle=handle)
    def get_handle(self,dispatch_id): return self._handles[dispatch_id]
    def observe(self,handle): return self.adapter.observe(handle)
    def finish(self,handle):
        if not handle.submitted: handle.submitted=True
        return self.adapter.finish(handle)
