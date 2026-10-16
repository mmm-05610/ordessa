"""Resource provider ports without SDK, host or governance dependencies."""
from typing import Any, Mapping, Protocol

from .contracts import ExecutionSpace, FileArea
from .models import BackendObservation


class BackendUse(Protocol):
    files: FileArea
    execution: ExecutionSpace

    def release(self) -> Mapping[str, object]: ...


class EnvironmentResourceProvider(Protocol):
    identity: str
    binding_id: str
    operations: frozenset[str]

    def create(self, reference: Mapping[str, Any], *, operation_id: str) -> BackendObservation: ...
    def inspect(self, backend_id: str) -> BackendObservation: ...
    def recover_creation(self, operation_id: str) -> BackendObservation:
        """Read-only correlation lookup for explicitly requested reconciliation."""
        ...
    def start(self, backend_id: str) -> BackendObservation: ...
    def stop(self, backend_id: str) -> BackendObservation: ...
    def delete(self, backend_id: str) -> None:
        """Return only after confirmed removal of this immutable backend ID."""
        ...
    def open_use(self, backend_id: str, *, use_id: str, generation: int) -> BackendUse: ...
