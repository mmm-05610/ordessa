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


class EnvironmentNativeManagement(Protocol):
    """The optional thin management port a provider may expose.

    A provider maps the closed native action set onto *its own* official calls
    and answers in neutral facts; it never proxies an arbitrary remote
    interface and never creates or deletes a resource from this port. A target
    is the immutable backend identity of an already registered resource, so the
    native entry and the normal lifecycle address the same backend.
    """

    native_actions: frozenset[str]

    def native_describe(self) -> Mapping[str, Any]:
        """Availability plus this provider's own gateway/binding facts."""
        ...

    def native_request(self, action: str, *, target: str | None,
                       request_id: str) -> Mapping[str, Any]:
        """Run one bounded read.

        An uncertain outcome raises ``EnvironmentOperationUnknown`` and keeps
        the correlation id; it is never dispatched a second time.
        """
        ...
