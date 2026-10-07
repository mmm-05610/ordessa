"""Pi profile authority and non-secret configuration."""
from __future__ import annotations
from dataclasses import dataclass, field
import json, os, shutil
from pathlib import Path
from typing import Any, Mapping, ClassVar
from pacthold.work_core.runtime import agent_box_home

PACKAGE = "pi"

class PiConfigError(ValueError):
    pass

@dataclass(frozen=True)
class PiProfile:
    """Immutable profile authority selected before Dispatch.

    ``credential_locator`` is an opaque locator only; its value is never
    loaded by this package or copied into a command, Ref, or evidence.
    """
    contract_id: ClassVar[str] = "agent-box.profile@1"
    profile_id: str
    revision: int
    digest: str
    binary: str
    provider: str = "deepseek"
    model: str = "deepseek/deepseek-v4-flash"
    thinking: str = "high"
    agent_dir: Path = Path(".")
    session_root: Path = Path(".")
    credential_locator: str | None = None
    skill_dirs: tuple[Path, ...] = ()
    mcp_config: Path | None = None
    instructions: Path | None = None
    helper: Path | None = None
    io_mode: str = "stdio"

    def __post_init__(self) -> None:
        if not self.profile_id or self.revision < 1 or not self.digest.startswith("sha256:"):
            raise PiConfigError("Pi profile identity is invalid")
        if self.provider != "deepseek": raise PiConfigError("Pi provider is fixed to deepseek")
        if not self.binary or (self.binary != "pi" and not Path(self.binary).is_absolute()):
            raise PiConfigError("Pi executable must be pi or an absolute path")
        if self.io_mode not in {"stdio", "pty"}: raise PiConfigError("Pi io_mode must be stdio or pty")

@dataclass(frozen=True)
class PiPluginConfig:
    binary: str
    model: str = "deepseek/deepseek-v4-flash"
    provider: str = "deepseek"
    thinking: str = "high"
    version: str = "unknown"
    update_policy: str = "pinned"
    agent_dir: Path | None = None
    session_root: Path | None = None
    evidence_root: Path | None = None
    credential_locator: str | None = None
    skill_dirs: tuple[Path, ...] = ()
    mcp_config: Path | None = None
    instructions: Path | None = None
    helper: Path | None = None
    io_mode: str = "stdio"
    profile_id: str = "pi-default"
    revision: int = 1
    digest: str = "sha256:pi-default"
    source: Path | None = None
    extra: Mapping[str, str] = field(default_factory=dict)

    @property
    def resolved_binary(self) -> str: return shutil.which(self.binary) or self.binary if self.binary == "pi" else self.binary
    @property
    def resolved_agent_dir(self) -> Path: return (self.agent_dir or (agent_box_home()/"plugins/pi/agent")).resolve()
    @property
    def resolved_session_root(self) -> Path: return (self.session_root or (agent_box_home()/"plugins/pi/sessions")).resolve()
    @property
    def canonical_model(self) -> str: return self.model if "/" in self.model else "deepseek/" + self.model
    def profile(self) -> PiProfile:
        return PiProfile(self.profile_id, self.revision, self.digest, self.resolved_binary,
            self.provider, self.canonical_model, self.thinking, self.resolved_agent_dir,
            self.resolved_session_root, self.credential_locator, self.skill_dirs,
            self.mcp_config, self.instructions, self.helper, self.io_mode)
    @classmethod
    def load(cls, path: Path | None = None) -> "PiPluginConfig":
        target = path or (agent_box_home()/"plugins/pi/config.json")
        if not target.is_file(): raise PiConfigError(f"Pi profile config not found: {target}")
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict): raise PiConfigError("Pi profile config must be an object")
        allowed = {"binary","model","provider","thinking","version","update_policy","agent_dir","session_root","evidence_root","credential_locator","skill_dirs","mcp_config","instructions","helper","io_mode","profile_id","revision","digest"}
        unknown = set(raw)-allowed
        if unknown: raise PiConfigError(f"unknown Pi profile keys: {sorted(unknown)}")
        def path(name): return Path(raw[name]).expanduser() if raw.get(name) else None
        return cls(binary=str(raw.get("binary", "pi")), model=str(raw.get("model", cls.__dataclass_fields__["model"].default)), provider=str(raw.get("provider","deepseek")), thinking=str(raw.get("thinking","high")), version=str(raw.get("version","unknown")), update_policy=str(raw.get("update_policy","pinned")), agent_dir=path("agent_dir"), session_root=path("session_root"), evidence_root=path("evidence_root"), credential_locator=str(raw["credential_locator"]) if raw.get("credential_locator") else None, skill_dirs=tuple(Path(x).expanduser() for x in raw.get("skill_dirs", ())), mcp_config=path("mcp_config"), instructions=path("instructions"), helper=path("helper"), io_mode=str(raw.get("io_mode","stdio")), profile_id=str(raw.get("profile_id","pi-default")), revision=int(raw.get("revision",1)), digest=str(raw.get("digest","sha256:pi-default")), source=target)

__all__ = ["PiConfigError", "PiPluginConfig", "PiProfile"]
