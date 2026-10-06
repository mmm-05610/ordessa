"""Explicit service settings; no ambient user or Agent configuration."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentServiceConfiguration:
    data_root: Path
    agent_contract_version: str = "agent-assembly/1"

    def __post_init__(self):
        if self.agent_contract_version not in ("agent-assembly/1", "agent-assembly/3"):
            raise ValueError("Agent Tools service requires a published Agent contract version")
        root = Path(self.data_root)
        if not root.is_absolute():
            raise ValueError("Agent Tools service requires an explicit absolute data root")
        if any(part.is_symlink() for part in (root, *root.parents)):
            raise ValueError("Agent Tools data root cannot traverse symlinks")
        object.__setattr__(self, "data_root", root)
