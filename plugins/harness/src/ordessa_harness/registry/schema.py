"""Typed, bounded schema for the versioned official Harness registry."""
from __future__ import annotations
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

# 能力词汇表**不是**这里定义的：canonical 合同（`pacthold.resource_contracts.
# harness_capabilities`）是唯一事实来源，注册表只把它当作封闭集合使用。这样
# TOML、部署声明与 wire 投影不可能各说一套；此处若有第二个手写集合，就等于
# 又开了一份可以静默漂移的 schema。
from pacthold_runtime_compat.resource_contracts.harness_capabilities import CANONICAL_CAPABILITY_IDS

_KINDS = frozenset({"stdio", "pty"})
_CAPS = frozenset(CANONICAL_CAPABILITY_IDS)

def _s(value, name, limit=128):
    if not isinstance(value, str) or not value or len(value) > limit: raise ValueError(f"invalid {name}")
    return value
def _tuple(value, name, limit=32):
    if not isinstance(value, (list, tuple)) or len(value) > limit or any(not isinstance(x, str) or not x or len(x) > 256 for x in value): raise ValueError(f"invalid {name}")
    return tuple(value)

@dataclass(frozen=True)
class Identity:
    harness_type: str; display_name: str; description: str; version: str; visual: Mapping[str, str] = field(default_factory=dict)
@dataclass(frozen=True)
class ExecutableSpec:
    identity: str; resolver_kind: str; bundle_members: tuple[str, ...] = (); version_probe: tuple[str, ...] = (); metadata: Mapping[str, str] = field(default_factory=dict)
@dataclass(frozen=True)
class ProfileSpec:
    native_home: str; guest_home: str; config_format: str; payload_schema: str; codec: str; overlay_policy: str; slots: tuple[str, ...] = (); skill_target: str | None = None; skill_env: str | None = None; mcp_target: str | None = None; mcp_key: str | None = None; hooks_target: str | None = None; hooks_key: str | None = None; memory_paths: tuple[str, ...] = ()
@dataclass(frozen=True)
class LaunchMode:
    name: str; argv: tuple[str, ...]; io: str = "stdio"; resume_contract: str | None = None
@dataclass(frozen=True)
class RuntimeSpec:
    io: str; host_capabilities: tuple[str, ...] = (); sandbox_capabilities: tuple[str, ...] = (); network: str = "optional"; terminal: str = "stdio"
@dataclass(frozen=True)
class InputSpec:
    contract_id: str; minimum: int; maximum: int | None; required: bool; selectors: tuple[str, ...]; target: str; transformer: str
@dataclass(frozen=True)
class CredentialSpec:
    contract: str; locator_provider: str; guest_target_class: str; materializer: str; required: bool = False
@dataclass(frozen=True)
class ContinuationSpec:
    kind: str; contract_id: str | None = None; target_provider: str | None = None
@dataclass(frozen=True)
class HarnessDefinition:
    schema_version: int; identity: Identity; executable: ExecutableSpec; profile: ProfileSpec; launch_modes: tuple[LaunchMode, ...]; runtime: RuntimeSpec; inputs: tuple[InputSpec, ...]; credential: CredentialSpec | None; continuation: ContinuationSpec; capabilities: frozenset[str]; driver: str
    @property
    def harness_type(self): return self.identity.harness_type
    @property
    def display_name(self): return self.identity.display_name

def definition_from_dict(raw: Mapping) -> HarnessDefinition:
    allowed={"schema_version","identity","executable","profile","launch_modes","runtime","inputs","credential","continuation","capabilities","driver"}
    if set(raw)-allowed: raise ValueError(f"unknown registry fields: {sorted(set(raw)-allowed)}")
    if raw.get("schema_version") != 1: raise ValueError("unsupported definition schema_version")
    ident=raw["identity"]
    if set(ident)-{"harness_type","display_name","description","version","visual"}: raise ValueError("unknown identity field")
    identity=Identity(_s(ident["harness_type"],"harness_type"),_s(ident["display_name"],"display_name"),_s(ident.get("description",""),"description",512),_s(ident["version"],"version"),MappingProxyType(dict(ident.get("visual",{}))))
    exe=raw["executable"]; executable=ExecutableSpec(_s(exe["identity"],"executable identity"),_s(exe["resolver_kind"],"resolver kind"),_tuple(exe.get("bundle_members",()),"bundle_members"),_tuple(exe.get("version_probe",()),"version_probe"),MappingProxyType(dict(exe.get("metadata",{}))))
    prof=raw["profile"]
    if set(prof)-{"native_home","guest_home","config_format","payload_schema","codec","overlay_policy","slots","skill_target","skill_env","mcp_target","mcp_key","hooks_target","hooks_key","memory_paths"}: raise ValueError("unknown profile field")
    guest=_s(prof["guest_home"],"guest_home")
    if not guest.startswith("/") or ".." in guest.split("/"): raise ValueError("guest_home must be canonical")
    slots=_tuple(prof.get("slots",()),"profile slots")
    if len(set(slots)) != len(slots): raise ValueError("duplicate resource slot")
    skill_target=prof.get("skill_target")
    if skill_target is not None:
        skill_target=_s(skill_target,"skill_target",256)
        if not skill_target.startswith("/") or "{skill_id}" not in skill_target or ".." in skill_target.split("/"):
            raise ValueError("skill_target must be a canonical bounded template")
    skill_env=prof.get("skill_env")
    if skill_env is not None and (not isinstance(skill_env, str) or not skill_env.isupper() or len(skill_env) > 64): raise ValueError("invalid skill_env")
    mcp_target=prof.get("mcp_target")
    mcp_key=prof.get("mcp_key")
    if (mcp_target is None) != (mcp_key is None):
        raise ValueError("mcp_target and mcp_key are declared together")
    if mcp_target is not None:
        mcp_target=_s(mcp_target,"mcp_target",256)
        mcp_key=_s(mcp_key,"mcp_key",64)
        if (not mcp_target.startswith("/") or ".." in mcp_target.split("/")
                or "{" in mcp_target or "}" in mcp_target):
            raise ValueError("mcp_target must be a canonical absolute file path")
        if not (mcp_target.endswith(".json") or mcp_target.endswith(".toml")):
            raise ValueError("mcp_target must name a json or toml file")
        if "mcp" not in slots:
            raise ValueError("a declared mcp_target requires the mcp slot")
    hooks_target=prof.get("hooks_target")
    hooks_key=prof.get("hooks_key")
    if hooks_target is None:
        if hooks_key is not None:
            raise ValueError("hooks_key needs hooks_target")
    else:
        hooks_target=_s(hooks_target,"hooks_target",256)
        if (not hooks_target.startswith("/") or ".." in hooks_target.split("/")
                or "{" in hooks_target or "}" in hooks_target):
            raise ValueError("hooks_target must be a canonical absolute file path")
        if not hooks_target.endswith(".json"):
            raise ValueError("hooks_target must name a json file")
        if hooks_key is not None:
            hooks_key=_s(hooks_key,"hooks_key",64)
        if "hook" not in slots and "hooks" not in slots:
            raise ValueError("a declared hooks_target requires a hook slot")
    memory_paths=tuple(prof.get("memory_paths",()))
    if len(memory_paths) > 8:
        raise ValueError("at most 8 memory paths are declared")
    for relative in memory_paths:
        value=_s(relative,"memory_paths entry",256)
        if value.startswith("/") or ".." in value.split("/") or "{" in value:
            raise ValueError("memory_paths entries are guest-home-relative")
    if len(set(memory_paths)) != len(memory_paths):
        raise ValueError("duplicate memory path")
    profile=ProfileSpec(_s(prof["native_home"],"native_home"),guest,_s(prof["config_format"],"config_format"),_s(prof["payload_schema"],"payload_schema"),_s(prof["codec"],"codec"),_s(prof["overlay_policy"],"overlay_policy"),slots,skill_target,skill_env,mcp_target,mcp_key,hooks_target,hooks_key,memory_paths)
    modes=[]; mode_names=set()
    for item in raw["launch_modes"]:
        if set(item)-{"name","argv","io","resume_contract"}: raise ValueError("unknown launch mode field")
        name=_s(item["name"],"launch mode");
        if name in mode_names: raise ValueError("duplicate launch mode")
        mode_names.add(name); argv=_tuple(item["argv"],"argv",64)
        if any(" " in token or "\n" in token or "\x00" in token for token in argv): raise ValueError("argv must be bounded tokens")
        io=item.get("io","stdio");
        if io not in _KINDS: raise ValueError("invalid launch io")
        modes.append(LaunchMode(name,argv,io,item.get("resume_contract")))
    runtime=raw["runtime"]
    if set(runtime)-{"io","host_capabilities","sandbox_capabilities","network","terminal"}: raise ValueError("unknown runtime field")
    io=runtime.get("io","stdio")
    if io not in _KINDS: raise ValueError("invalid runtime io")
    runtime_spec=RuntimeSpec(io,_tuple(runtime.get("host_capabilities",()),"host capabilities"),_tuple(runtime.get("sandbox_capabilities",()),"sandbox capabilities"),_s(runtime.get("network","optional"),"network"),_s(runtime.get("terminal","stdio"),"terminal"))
    inputs=[]
    for item in raw.get("inputs",[]):
        maximum=item.get("maximum")
        if not isinstance(item.get("minimum"),int) or item["minimum"]<0 or (maximum is not None and (not isinstance(maximum,int) or maximum<item["minimum"])): raise ValueError("invalid input cardinality")
        inputs.append(InputSpec(_s(item["contract_id"],"contract id"),item["minimum"],maximum,bool(item.get("required",item["minimum"]>0)),_tuple(item.get("selectors",()),"selectors"),_s(item.get("target",""),"projection target"),_s(item.get("transformer","generic"),"transformer")))
    input_ids = [item.contract_id for item in inputs]
    if len(input_ids) != len(set(input_ids)):
        raise ValueError("duplicate input contract")
    for item in inputs:
        if item.contract_id == "agent-box.skill@1" and (item.minimum != 0 or item.maximum is None or item.maximum > 32 or item.target != "skill-tree"):
            raise ValueError("invalid Skill input declaration")
    cont=raw.get("continuation",{})
    if set(cont)-{"kind","contract_id","target_provider"}: raise ValueError("unknown continuation field")
    continuation=ContinuationSpec(_s(cont.get("kind","none"),"continuation kind"),cont.get("contract_id"),cont.get("target_provider"))
    if continuation.kind == "none" and (continuation.contract_id or continuation.target_provider): raise ValueError("none continuation cannot declare a route")
    raw_caps=raw.get("capabilities",())
    if not isinstance(raw_caps,(list,tuple)) or any(not isinstance(item,str) or not item for item in raw_caps):
        raise ValueError("capabilities must be a list of capability ids")
    caps=frozenset(raw_caps)
    # 未知 id（含 streaming/approvals/attachments/sessions 这类**原生**别名）一律类型化拒绝：
    # 运行时只认 canonical 词汇，别名一旦进得来，消费方就会把它当成一个真的产品能力。
    if not caps <= _CAPS: raise ValueError(f"unknown capability: {sorted(caps - _CAPS)}")
    if continuation.kind == "native_session" and "native_continuation" not in caps: raise ValueError("native continuation capability missing")
    cred=raw.get("credential"); credential=None
    if cred:
        if set(cred)-{"contract","locator_provider","guest_target_class","materializer","required"}: raise ValueError("unknown credential field")
        target = str(cred.get("guest_target_class", "")).lower()
        if target in {"path", "value", "secret", "host-path"} or "raw" in target: raise ValueError("unsafe credential target")
        credential=CredentialSpec(_s(cred["contract"],"credential contract"),_s(cred["locator_provider"],"credential locator"),_s(cred["guest_target_class"],"credential target"),_s(cred["materializer"],"credential materializer"),bool(cred.get("required",False)))
    return HarnessDefinition(int(raw["schema_version"]),identity,executable,profile,tuple(modes),runtime_spec,tuple(inputs),credential,continuation,caps,_s(raw["driver"],"driver"))
