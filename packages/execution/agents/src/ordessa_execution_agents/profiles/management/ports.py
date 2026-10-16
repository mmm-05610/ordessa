"""Profile reads and atomic change contract on the original Environment owner.

commit_change atomically compares expected_version (0 = absent), writes an optional
new immutable revision, updates the current Profile and records the request result.
All writes must share the original store/connection/request ledger or roll back.
Snapshot staging returns data only; the consuming Unit reservation commits it.
"""
from typing import Protocol, runtime_checkable

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import DomainWrite
from ..definitions.models import Profile, ProfileRevision, ProfileRevisionRef


@runtime_checkable
class ProfileStorePort(Protocol):
    def available(self) -> bool: ...
    def read_profile(self, environment: str, profile_id: str) -> dict[str, object] | None: ...
    def list_profiles(self, environment: str) -> tuple[dict[str, object], ...]: ...
    def read_revision(self, ref: ProfileRevisionRef) -> dict[str, object] | None: ...
    def read_result(self, request: RequestKey, digest: str) -> dict[str, object] | None: ...
    def commit_change(self, request: RequestKey, digest: str, profile: Profile,
                      expected_version: int, revision: ProfileRevision | None = None) -> dict[str, object]: ...
    def stage_snapshot_write(self, revision: ProfileRevision) -> DomainWrite: ...
