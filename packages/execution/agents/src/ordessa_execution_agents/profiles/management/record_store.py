"""Adapt Profile operations to the explicit Profile owner's atomic domain store.

No SQLite imports, new connection, schema migration, alternate store or ledger.
The owner is resolved from the original Profile store at each call, preserving its
lifecycle and synthetic test seams. Namespace/record mappings are explicit.
"""
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import (
    DomainRevisionConflict, DomainStorePort, DomainWrite,
)

from .compatibility import PROFILE_RECORDS, REVISION_RECORDS, SNAPSHOT_RECORDS, SNAPSHOT_PREFIX
from ..definitions.models import Profile, ProfileRevision, ProfileRevisionRef
from ..definitions.codec import encode_profile, encode_revision
from ..definitions.errors import ProfileRevisionConflict, ProfileStoreUnavailable


class RecordProfileStore:
    def __init__(self, store):
        self._store = store

    def available(self) -> bool:
        return isinstance(self._store, DomainStorePort)

    def _owner(self) -> DomainStorePort:
        owner = self._store
        if not isinstance(owner, DomainStorePort):
            raise ProfileStoreUnavailable("Profile management requires the original store's atomic record capability")
        return owner

    def read_profile(self, environment: str, profile_id: str) -> dict[str, object] | None:
        row = self._owner().read_domain(environment, PROFILE_RECORDS, profile_id)
        return dict(row) if row is not None else None

    def list_profiles(self, environment: str) -> tuple[dict[str, object], ...]:
        return tuple(dict(row) for row in self._owner().list_domain(environment, PROFILE_RECORDS))

    def read_revision(self, ref: ProfileRevisionRef) -> dict[str, object] | None:
        namespace = SNAPSHOT_RECORDS if ref.profile_id.startswith(SNAPSHOT_PREFIX) else REVISION_RECORDS
        row = self._owner().read_domain(ref.environment_namespace, namespace, f"{ref.profile_id}@{ref.revision}")
        return dict(row) if row is not None else None

    def read_result(self, request: RequestKey, digest: str) -> dict[str, object] | None:
        result = self._owner().read_domain_result(request, digest)
        return dict(result) if result is not None else None

    def commit_change(self, request: RequestKey, digest: str, profile: Profile,
                      expected_version: int, revision: ProfileRevision | None = None) -> dict[str, object]:
        writes = [DomainWrite(PROFILE_RECORDS, profile.profile_id, expected_version, encode_profile(profile))]
        if revision is not None:
            writes.append(DomainWrite(REVISION_RECORDS, f"{revision.ref.profile_id}@{revision.ref.revision}",
                                      0, encode_revision(revision)))
        try:
            return dict(self._owner().commit_domain_change(
                request, digest, tuple(writes), encode_profile(profile)))
        except DomainRevisionConflict as error:
            # Infrastructure reports only the technical CAS conflict. Keep the
            # Profiles owner's public optimistic-concurrency error stable.
            raise ProfileRevisionConflict("Profile record revision conflict") from error

    def stage_snapshot_write(self, revision: ProfileRevision) -> DomainWrite:
        return DomainWrite(SNAPSHOT_RECORDS, f"{revision.ref.profile_id}@{revision.ref.revision}",
                           0, encode_revision(revision))
