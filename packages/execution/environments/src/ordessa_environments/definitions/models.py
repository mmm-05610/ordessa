"""Neutral resource observations; provider configuration belongs to plugins."""
from dataclasses import dataclass
from typing import Mapping
from typing import Literal
from .errors import EnvironmentRefused

from .contracts import Capabilities


@dataclass(frozen=True)
class BackendObservation:
    backend_id: str
    state: str
    capabilities: Capabilities
    observed_at: str
    runtime_identity: str | None = None


@dataclass(frozen=True)
class EnvironmentSnapshot:
    identity: str
    provider_id: str
    backend_id: str | None
    phase: str
    generation: int
    observation: BackendObservation | None
    operation: str | None
    active_uses: int
    # Active uses are only this store's relationships, never an external census.


@dataclass(frozen=True)
class EnvironmentOperationReceipt:
    identity: str
    operation: str
    generation: int
    confirmed: bool


@dataclass(frozen=True)
class ProviderDescriptor:
    identity: str
    adapter_version: str
    backend_version: str
    capabilities: Mapping[str, bool]


@dataclass(frozen=True)
class ProcessObservation:
    identity: str
    state: Literal['running', 'exited', 'unknown']
    observed_at: str
    exit_code: int | None = None
    io_state: Literal['open', 'closed', 'unknown'] = 'open'

    def __post_init__(self):
        if not self.identity or not self.observed_at or self.state not in ('running','exited','unknown'):
            raise EnvironmentRefused('invalid process observation')
        if (self.state == 'exited') != (type(self.exit_code) is int):
            raise EnvironmentRefused('only actual exited observations have integer exit code')
        if self.io_state not in ('open','closed','unknown'):
            raise EnvironmentRefused('invalid process IO observation')


@dataclass(frozen=True)
class ProcessCancellation:
    outcome: Literal['requested', 'unsupported', 'unknown']
    observation: ProcessObservation

    def __post_init__(self):
        if self.outcome not in ('requested','unsupported','unknown'):
            raise EnvironmentRefused('invalid cancellation observation')
