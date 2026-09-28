"""Provider-neutral Agent Skills contract.

Resolved source access is an ephemeral, typed capability carried by
``ResolvedAgentSkill`` in the Skill provider. This public contract is fully
serializable; a Ref never contains a host path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping


@dataclass(frozen=True)
class AgentSkillV1:
    contract_id: ClassVar[str] = "agent-box.skill@1"
    skill_id: str
    name: str
    description: str
    revision: int
    digest: str
    format: str = "agent-skills"
    manifest_name: str = "SKILL.md"
    provenance: Mapping[str, str] = field(default_factory=dict)
    files: tuple[Mapping[str, Any], ...] = ()
    def __post_init__(self) -> None:
        if not self.skill_id or len(self.skill_id) > 96:
            raise ValueError("invalid skill_id")
        if not self.name or len(self.name) > 128:
            raise ValueError("invalid skill name")
        if not self.description or len(self.description) > 512:
            raise ValueError("invalid skill description")
        if self.revision < 1 or not self.digest.startswith("sha256:"):
            raise ValueError("invalid skill identity")
        if self.format != "agent-skills" or self.manifest_name != "SKILL.md":
            raise ValueError("unsupported Agent Skills format")

    def public_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "revision": self.revision,
            "digest": self.digest,
            "format": self.format,
            "manifest_name": self.manifest_name,
            "provenance": dict(self.provenance),
            "files": [dict(item) for item in self.files],
        }
