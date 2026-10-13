"""Original step storage and native recorded-execution ports; no grants minted."""
from typing import Callable, Protocol
from .execution_observations import AuthorizedAcpTurnReader


class DispatchExecutionPort(Protocol):
    # Composition retains these same original objects in EngineeringService.
    # They correlate owners; runtime query/effect guards still admit each call.
    records: AuthorizedAcpTurnReader
    query_factory: Callable

    def freeze_input(self,unit_ref,params): ...
    def query_digest(self,unit_ref,operation_ref,prompt_digest): ...
    def send(self,binding,*,timeout=60): ...
    def capture(self,binding): ...


class DispatchRepository(Protocol):
    def reserve(self,run_id,step_id,attempt,scope,binding_bytes,binding_digest,operation_ref): ...
    def get(self,run_id,step_id,attempt,scope): ...
    def by_operation(self,operation_ref,scope): ...
    def transition(self,run_id,step_id,attempt,scope,*,expected_version,fence,phase,result_blob_ref=None): ...


class DispatchSelectionPort(Protocol):
    def guard_selection(self,context,package,unit_ref):
        """Original selected profile/Unit/checkout capability provenance, held through COMMIT.

        Verify package.execution_profile_ref against original Manager/Agent
        materialization, complete Unit/source revision and actual action scopes.
        DTO equality or caller-selected profile labels do not authenticate.
        Also retain the current native query/source capability during capture
        and Engineering COMMIT. Reading historical facts does not require an
        active action Grant; this guard must not invent such a permission.
        """
        ...


class DispatchSourceSnapshotPort(Protocol):
    def guard_commit_snapshot(self, context, package, unit_ref):
        """Trusted original timed Unit/Profile/Directory snapshot + read permission.

        This captures acquisition-time query permission and exact returned source
        identity, not current permission, liveness or checkout through COMMIT.
        It must never claim liveDispatchAuthorized/currentThroughCommit true.
        """
        ...


class DispatchHistorySourcePort(Protocol):
    def guard_history_read(self,context,package,unit_ref):
        """Original authorized immutable read-time source facts, not live/action permission."""
        ...
