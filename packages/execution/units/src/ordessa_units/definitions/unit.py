"""Fixed Agent(Harness + Profile) and execution-environment reference."""
from dataclasses import dataclass
from collections.abc import Mapping

from ordessa_agents.profiles import ProfileRevisionRef
from ordessa_infrastructure.encoding.immutable_json import sealed_mapping


@dataclass(frozen=True)
class UnitDefinition:
    agent_id: str
    harness_id: str
    profile_revision: ProfileRevisionRef
    environment_reference: Mapping | None

    def __post_init__(self):
        for text in (self.agent_id, self.harness_id):
            if not isinstance(text, str) or not text or text.strip() != text:
                raise ValueError('Unit requires explicit Agent/Harness identity')
        if type(self.profile_revision) is not ProfileRevisionRef:
            raise ValueError('Unit requires a fixed complete Profile revision')
        if self.environment_reference is not None:
            if not isinstance(self.environment_reference, Mapping):
                raise ValueError('Unit Environment reference must be a mapping')
            object.__setattr__(self, 'environment_reference', sealed_mapping(self.environment_reference))
