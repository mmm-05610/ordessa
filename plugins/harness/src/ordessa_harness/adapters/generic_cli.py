from __future__ import annotations
import re
from pacthold_runtime_compat.runtime_composition import HarnessCommandSpec, declare_source
class GenericCliAdapter:
    def __init__(self,key): self.key=key
    def validate_native_payload(self,payload):
        if not isinstance(payload,dict): raise ValueError("NATIVE_PAYLOAD_OBJECT_REQUIRED")
    def build_command(self,definition,request,profile):
        mode=definition.launch_modes[0]; argv=list(mode.argv)
        executable=profile.get("executable",definition.executable.identity) if isinstance(profile,dict) else definition.executable.identity
        argv[0]="/runtime/bin/"+executable
        prompt=[]
        for item in request.resolved_inputs:
            value=getattr(item,"value",None)
            if hasattr(value,"content"): prompt.append(value.content)
        if prompt: argv.append("\n\n".join(prompt))
        home=str(profile.get("native_home","")) if isinstance(profile,dict) else ""
        sources=[declare_source("workspace",self._one(request,"agent-box.workspace@1").path,"/workspace",access="rw",provenance="workspace")]
        if home: sources.append(declare_source("profile-home",home,definition.profile.guest_home,access="rw",provenance="profile"))
        skills = [x.value for x in request.resolved_inputs if x.contract_id == "agent-box.skill@1"]
        if skills:
            if not definition.profile.skill_target:
                raise ValueError("SKILL_TARGET_UNDECLARED")
            seen = set()
            for skill in sorted(skills, key=lambda value: (value.skill_id, value.revision, value.digest)):
                contract = getattr(skill, "contract", skill)
                source = getattr(skill, "source", None)
                if source is None or not hasattr(source, "projection_source"):
                    raise ValueError("SKILL_SOURCE_CAPABILITY_MISSING")
                slug = contract.skill_id
                target = definition.profile.skill_target.format(skill_id=slug)
                if target in seen:
                    raise ValueError("SKILL_TARGET_COLLISION")
                seen.add(target)
                sources.append(declare_source("skill-tree", str(source.projection_source()), target, access="ro", provenance=f"skill:{contract.skill_id}:{contract.revision}", authorized_scope="execution"))
        environment={"AGENT_BOX_EXECUTION_ID":request.execution_id}
        if definition.profile.skill_env:
            environment[definition.profile.skill_env] = definition.profile.guest_home
        return HarnessCommandSpec(tuple(argv),"/workspace",environment,mode.io,runtime_sources=tuple(sources),projector_id=self.key)
    def _one(self,request,contract):
        values=[x.value for x in request.resolved_inputs if x.contract_id==contract]
        if len(values)!=1: raise ValueError(f"exact input required: {contract}")
        return values[0]
    def declare_runtime_sources(self,definition,request,profile): return ()
    def decode_observation(self,value): return value
    def observe(self,handle): return handle
    def finish(self,handle): return handle
