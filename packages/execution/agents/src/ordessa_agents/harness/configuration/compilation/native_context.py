"""Host-independent native observation context; this value issues no authority."""
from dataclasses import dataclass
from typing import Protocol
from ordessa_agents.harness.definitions import AdapterContext, ApplicationTarget

class NativeModelSnapshot(Protocol):
    target: ApplicationTarget
    owner: object
    native_generation: str
    busy: bool
    @property
    def config_options(self) -> list: ...

@dataclass(frozen=True)
class NativeLiveModelContext(AdapterContext):
    native_snapshot: NativeModelSnapshot
    credential_binding: object = None
