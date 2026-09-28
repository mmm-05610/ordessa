"""A fixed Agent-Box profile selected for an Execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class AgentBoxProfileV1:
    contract_id: ClassVar[str] = "agent-box.profile@1"

    name: str
    agent_type: str
    digest: str
    revision: int = 1
    provider: str = "agent-box-profile"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("name", self.name),
            ("agent_type", self.agent_type),
            ("digest", self.digest),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Agent-Box profile {field_name} is required")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("Agent-Box profile revision must be positive")
