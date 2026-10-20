"""Caller inputs for one fixed Profile in an existing execution environment."""
from collections.abc import Mapping
from dataclasses import dataclass

from ordessa_execution_agents.profiles import ProfileRevisionRef
from ordessa_infrastructure.encoding.immutable_json import sealed_mapping


@dataclass(frozen=True)
class UnitSpec:
    agent_id: str
    profile_revision: ProfileRevisionRef
    environment_reference: Mapping

    def __post_init__(self):
        if not isinstance(self.agent_id, str) or not self.agent_id or self.agent_id.strip() != self.agent_id:
            raise ValueError('Explicit Agent identity required')
        if type(self.profile_revision) is not ProfileRevisionRef:
            raise ValueError('Fixed complete Profile revision required')
        if not isinstance(self.environment_reference, Mapping) or not self.environment_reference:
            raise ValueError('Existing Environment reference required')
        object.__setattr__(self, 'environment_reference', sealed_mapping(self.environment_reference))
