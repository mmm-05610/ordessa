"""Data-only Profile catalog on the same Environment and persistent store.

The catalog owns immutable definition revisions; it cannot prepare a native
unit, apply configuration or submit input. No domain-specific request ledger
or database runtime is introduced.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Mapping

from ordessa_environment_api import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError, RequestKey, UnknownResultError,
)
from ordessa_environment_api.domain import DomainStorePort, DomainWrite

from pacthold.agents.contracts import (
    ProfileCatalogEntry, ProfileManifest, ProfileNotFound, ProfileRef,
    ProfileRevisionConflict, ProfileValidationError, canonical, content_digest,
    manifest_content,
)

CATALOG = "agents.profile-catalog"
MANIFESTS = "agents.profile-manifests"
# Content-addressed ad-hoc manifests are isolated from named Profile records.
# They remain operation-bound evidence and never become catalog entries.
SNAPSHOTS = "agents.profile-snapshots"
SNAPSHOT_PREFIX = "snap-"


class ProfileCatalog:
    def __init__(self, environment):
        self._environment = environment

    @property
    def environment_namespace(self) -> str:
        return self._environment.environment_id

    def request_key(self, request_id: str) -> RequestKey:
        """Bind an authenticated service request to this trusted realm."""
        return RequestKey(self.environment_namespace, self._environment._principal_scope, request_id)

    def capabilities(self) -> Mapping[str, Any]:
        with self._environment._admission_lock:
            self._environment._check_open()
            env = self._environment
            return {"profileCatalog": isinstance(env._store, DomainStorePort)
                    and env._policy is not None and env._fingerprint_port is not None,
                    "nodes": False, "managedInput": False}

    def _store(self) -> DomainStorePort:
        store = self._environment._store
        if not isinstance(store, DomainStorePort):
            raise GuaranteeUnavailableError("Profile catalog requires the same store's atomic domain-record capability")
        return store

    def _read_permission(self, profile_id: str = "*") -> None:
        env = self._environment
        env._check_open()
        if env._policy is None or not env._policy.admit_object_access(
            env._principal_scope, f"{env.environment_id}:agents.profile:{profile_id}", "read"
        ):
            raise AdmissionRefusedError("Profile read permission unavailable or refused")

    def _snapshot_permission(self, snapshot_id: str, mode: str) -> None:
        env = self._environment
        env._check_open()
        if mode not in {"read", "write"}:
            raise ValueError("snapshot permission mode is invalid")
        if env._policy is None or not env._policy.admit_object_access(
            env._principal_scope,
            f"{env.environment_id}:agents.profile-snapshot:{snapshot_id}",
            mode,
        ):
            raise AdmissionRefusedError("Profile snapshot access unavailable or refused")

    @contextmanager
    def _change(self, kind: str, request: RequestKey, parameters: Mapping[str, Any]):
        env = self._environment
        # Same ordering point as Environment's admission/lifecycle cuts. No
        # plugin/native callback runs inside this data-only transaction.
        with env._admission_lock:
            env._check_open()
            env._check_environment(request.environment_namespace)
            if request.principal_scope != env._principal_scope:
                raise AdmissionRefusedError("request principal does not match the trusted environment principal")
            if env._policy is None or not env._policy.admit_invoke(
                env._principal_scope, f"pacthold.agents.profiles.{kind}", "reliable"
            ):
                raise AdmissionRefusedError("Profile write permission unavailable or refused")
            target_id = parameters.get("profileId")
            if target_id is None:
                target_id = parameters["entry"]["profileId"]
            if not env._policy.admit_object_access(
                env._principal_scope, f"{env.environment_id}:agents.profile:{target_id}", "write"
            ):
                raise AdmissionRefusedError("Profile target write permission unavailable or refused")
            if env._fingerprint_port is None:
                raise GuaranteeUnavailableError("Profile writes require the environment's protected fingerprint port")
            store = self._store()
            env._fingerprint_port.describe()
            digest = env._fingerprint_port.fingerprint(
                request, f"pacthold.agents.profiles.{kind}", content_digest(canonical(parameters))
            )
            replay = store.read_domain_result(request, digest)
            yield store, digest, replay

    def _catalog(self, profile_id: str) -> ProfileCatalogEntry:
        row = self._store().read_domain(self.environment_namespace, CATALOG, profile_id)
        if row is None:
            raise ProfileNotFound("Profile does not exist in this environment")
        return self._entry(row, profile_id)

    def _replay(self, value, profile_id, revision, *, ref=None, display_name=None):
        """Validate the historical result, without comparing today's catalog."""
        try:
            if not isinstance(value, dict) or set(value) != {
                "profileId", "catalogRevision", "displayName", "archivedAt", "currentManifestRef"
            }:
                raise ValueError("invalid result fields")
            entry = ProfileCatalogEntry.from_dict(value)
            if (entry.profile_id != profile_id or entry.current_manifest_ref.profile_id != profile_id
                    or entry.current_manifest_ref.environment_namespace != self.environment_namespace
                    or type(entry.catalog_revision) is not int or entry.catalog_revision != revision
                    or (ref is not None and entry.current_manifest_ref != ref)
                    or (display_name is not None and entry.display_name != display_name)
                    or (entry.archived_at is not None and not isinstance(entry.archived_at, str))):
                raise ValueError("result identity mismatch")
            self._name(entry.display_name)
            self._manifest(entry.current_manifest_ref)
            return entry
        except (ValueError, TypeError, KeyError, IdentityMismatchError,
                GuaranteeUnavailableError, ProfileNotFound):
            raise UnknownResultError("stored Profile result cannot be verified; do not resend") from None

    def _entry(self, row, requested_id=None) -> ProfileCatalogEntry:
        try:
            entry = ProfileCatalogEntry.from_dict(row["value"])
            ref = entry.current_manifest_ref
            if (row["record_id"] != entry.profile_id
                    or (requested_id is not None and entry.profile_id != requested_id)
                    or ref.profile_id != entry.profile_id
                    or ref.environment_namespace != self.environment_namespace
                    or type(entry.catalog_revision) is not int or entry.catalog_revision < 1
                    or row["revision"] != entry.catalog_revision):
                raise ValueError("identity or revision mismatch")
            self._name(entry.display_name)
            if entry.archived_at is not None and not isinstance(entry.archived_at, str):
                raise ValueError("invalid archive metadata")
            return entry
        except (ValueError, TypeError, KeyError):
            raise GuaranteeUnavailableError("Profile catalog identity or revision is inconsistent") from None

    def list(self, *, include_archived: bool = False) -> tuple[ProfileCatalogEntry, ...]:
        with self._environment._admission_lock:
            self._read_permission()
            entries = []
            for row in self._store().list_domain(self.environment_namespace, CATALOG):
                entry = self._entry(row)
                try:
                    self._read_permission(entry.profile_id)
                except AdmissionRefusedError:
                    continue
                if include_archived or entry.archived_at is None:
                    entries.append(entry)
            return tuple(entries)

    def read_entry(self, profile_id: str) -> ProfileCatalogEntry:
        with self._environment._admission_lock:
            self._read_permission(profile_id)
            return self._catalog(profile_id)

    def _manifest(self, ref: ProfileRef) -> ProfileManifest:
        self._environment._check_environment(ref.environment_namespace)
        namespace = SNAPSHOTS if ref.profile_id.startswith(SNAPSHOT_PREFIX) else MANIFESTS
        row = self._store().read_domain(self.environment_namespace, namespace,
                                       f"{ref.profile_id}@{ref.manifest_revision}")
        if row is None:
            raise ProfileNotFound("Profile manifest revision does not exist")
        try:
            stored_ref = ProfileRef.from_dict(row["value"]["ref"])
        except (ValueError, TypeError, KeyError):
            raise GuaranteeUnavailableError("Profile manifest identity is inconsistent") from None
        if stored_ref != ref:
            raise ProfileRevisionConflict("Profile content digest does not match its immutable revision")
        if row["record_id"] != f"{ref.profile_id}@{ref.manifest_revision}" or row["revision"] != 1:
            raise GuaranteeUnavailableError("Profile manifest record is not immutable")
        try:
            content = manifest_content(row["value"]["content"], self.environment_namespace)
        except (ValueError, TypeError, KeyError):
            raise GuaranteeUnavailableError("Profile manifest content is inconsistent") from None
        if content_digest(content) != ref.content_digest:
            raise GuaranteeUnavailableError("Profile manifest digest is inconsistent")
        return ProfileManifest(ref, content)

    def read(self, ref: ProfileRef) -> ProfileManifest:
        with self._environment._admission_lock:
            if type(ref) is not ProfileRef:
                raise ProfileValidationError("fixed Profile reference required")
            if ref.profile_id.startswith(SNAPSHOT_PREFIX):
                self._snapshot_permission(ref.profile_id, "read")
            else:
                self._read_permission(ref.profile_id)
            return self._manifest(ref)

    def stage_snapshot(self, manifest: Mapping[str, Any]) -> tuple[ProfileRef, DomainWrite | None]:
        """Freeze an ad-hoc manifest into an immutable content-addressed snapshot.

        The derived identity is deterministic in the canonical manifest
        content, so the same body always yields the same snapshot reference
        and the consuming request stays idempotent. The returned write must
        commit in the same transaction as the consuming operation's reserve:
        either both persist or neither does. An existing record with the same
        content needs no write; a differing record at the same identity is a
        collision and is never rewritten. The snapshot carries no catalog
        entry, so an orphan snapshot can never present itself as a created or
        updated instance.
        """
        env = self._environment
        with env._admission_lock:
            env._check_open()
            content = manifest_content(manifest, self.environment_namespace)
            digest = content_digest(content)
            ref = ProfileRef(self.environment_namespace, SNAPSHOT_PREFIX + digest[7:55], 1, digest)
            self._snapshot_permission(ref.profile_id, "write")
            # Preparation immediately rereads the frozen snapshot while
            # executing/recovering its reserved operation. Check both object
            # rights now, before the caller can reserve that operation.
            self._snapshot_permission(ref.profile_id, "read")
            record_id = f"{ref.profile_id}@{ref.manifest_revision}"
            row = self._store().read_domain(self.environment_namespace, SNAPSHOTS, record_id)
            if row is not None:
                try:
                    self._manifest(ref)
                except (ProfileRevisionConflict, ProfileNotFound, GuaranteeUnavailableError, ValueError, TypeError):
                    raise GuaranteeUnavailableError("immutable snapshot record collision") from None
                return ref, None
            import json
            return ref, DomainWrite(SNAPSHOTS, record_id, 0,
                                    {"ref": ref.to_dict(), "content": json.loads(content)})

    @staticmethod
    def _mint(profile_id: str) -> None:
        if not isinstance(profile_id, str) or not profile_id or profile_id.startswith(SNAPSHOT_PREFIX):
            raise ProfileValidationError("profile id must avoid the reserved snapshot prefix")

    @staticmethod
    def _name(name: str) -> str:
        if not isinstance(name, str) or not name.strip() or len(name) > 256:
            raise ProfileValidationError("displayName must be nonempty and bounded")
        return name

    def _writes(self, entry: ProfileCatalogEntry, previous_revision: int,
                content: str | None = None) -> tuple[DomainWrite, ...]:
        writes = [DomainWrite(CATALOG, entry.profile_id, previous_revision, entry.to_dict())]
        if content is not None:
            import json
            writes.append(DomainWrite(MANIFESTS,
                                      f"{entry.profile_id}@{entry.current_manifest_ref.manifest_revision}",
                                      0, {"ref": entry.current_manifest_ref.to_dict(),
                                          "content": json.loads(content)}))
        return tuple(writes)

    def create(self, *, profile_id: str, display_name: str,
                manifest: Mapping[str, Any], request: RequestKey) -> ProfileCatalogEntry:
        self._mint(profile_id)
        content = manifest_content(manifest, self.environment_namespace)
        ref = ProfileRef(self.environment_namespace, profile_id, 1, content_digest(content))
        entry = ProfileCatalogEntry(profile_id, 1, self._name(display_name), None, ref)
        with self._change("create", request, {"entry": entry.to_dict(), "content": content}) as (store, digest, replay):
            if replay is not None:
                return self._replay(replay, profile_id, 1, ref=ref, display_name=display_name)
            result = store.commit_domain_change(request, digest, self._writes(entry, 0, content), entry.to_dict())
            return ProfileCatalogEntry.from_dict(result)

    def edit(self, profile_id: str, *, manifest: Mapping[str, Any],
             expected_catalog_revision: int, base_manifest_ref: ProfileRef,
             request: RequestKey) -> ProfileCatalogEntry:
        content = manifest_content(manifest, self.environment_namespace)
        parameters = {"profileId": profile_id, "content": content,
                      "expectedCatalogRevision": expected_catalog_revision,
                      "baseManifestRef": base_manifest_ref.to_dict()}
        with self._change("edit", request, parameters) as (store, digest, replay):
            if replay is not None:
                expected_ref = ProfileRef(self.environment_namespace, profile_id,
                    base_manifest_ref.manifest_revision + 1, content_digest(content))
                return self._replay(replay, profile_id, expected_catalog_revision + 1, ref=expected_ref)
            current = self._catalog(profile_id)
            self._cas(current, expected_catalog_revision, base_manifest_ref)
            if current.archived_at is not None:
                raise ProfileRevisionConflict("archived Profile must be restored before content editing")
            self._manifest(base_manifest_ref)
            ref = ProfileRef(self.environment_namespace, profile_id,
                             base_manifest_ref.manifest_revision + 1, content_digest(content))
            entry = ProfileCatalogEntry(profile_id, current.catalog_revision + 1,
                                        current.display_name, None, ref)
            result = store.commit_domain_change(request, digest,
                                               self._writes(entry, current.catalog_revision, content), entry.to_dict())
            return ProfileCatalogEntry.from_dict(result)

    @staticmethod
    def _cas(current, expected_catalog_revision, base=None):
        if type(expected_catalog_revision) is not int or expected_catalog_revision < 1:
            raise ProfileValidationError("expectedCatalogRevision must be a positive integer")
        if current.catalog_revision != expected_catalog_revision or (
            base is not None and current.current_manifest_ref != base
        ):
            raise ProfileRevisionConflict("Profile catalog or base manifest revision conflict")

    def _metadata(self, kind, profile_id, expected, request, *, display_name=None):
        parameters = {"profileId": profile_id, "expectedCatalogRevision": expected}
        if kind == "rename":
            parameters["displayName"] = self._name(display_name)
        with self._change(kind, request, parameters) as (store, digest, replay):
            if replay is not None:
                return self._replay(replay, profile_id, expected + 1, display_name=display_name)
            current = self._catalog(profile_id)
            self._cas(current, expected)
            archived = current.archived_at
            if kind == "archive":
                archived = archived or datetime.now(timezone.utc).isoformat()
            elif kind == "restore":
                archived = None
            entry = ProfileCatalogEntry(profile_id, current.catalog_revision + 1,
                                        display_name if kind == "rename" else current.display_name,
                                        archived, current.current_manifest_ref)
            result = store.commit_domain_change(request, digest, self._writes(entry, current.catalog_revision), entry.to_dict())
            return ProfileCatalogEntry.from_dict(result)

    def rename(self, profile_id: str, *, display_name: str, expected_catalog_revision: int,
               request: RequestKey) -> ProfileCatalogEntry:
        return self._metadata("rename", profile_id, expected_catalog_revision, request,
                              display_name=display_name)

    def archive(self, profile_id: str, *, expected_catalog_revision: int,
                request: RequestKey) -> ProfileCatalogEntry:
        return self._metadata("archive", profile_id, expected_catalog_revision, request)

    def restore(self, profile_id: str, *, expected_catalog_revision: int,
                request: RequestKey) -> ProfileCatalogEntry:
        return self._metadata("restore", profile_id, expected_catalog_revision, request)

    def clone(self, source_ref: ProfileRef, *, profile_id: str, display_name: str,
              request: RequestKey) -> ProfileCatalogEntry:
        self._mint(profile_id)
        parameters = {"sourceRef": source_ref.to_dict(), "profileId": profile_id,
                      "displayName": self._name(display_name)}
        with self._change("clone", request, parameters) as (store, digest, replay):
            self._read_permission(source_ref.profile_id)
            if replay is not None:
                expected_ref = ProfileRef(self.environment_namespace, profile_id, 1, source_ref.content_digest)
                return self._replay(replay, profile_id, 1, ref=expected_ref, display_name=display_name)
            manifest = self._manifest(source_ref)
            ref = ProfileRef(self.environment_namespace, profile_id, 1, source_ref.content_digest)
            entry = ProfileCatalogEntry(profile_id, 1, display_name, None, ref)
            result = store.commit_domain_change(request, digest, self._writes(entry, 0, manifest.content_json), entry.to_dict())
            return ProfileCatalogEntry.from_dict(result)

    def preview(self, ref: ProfileRef) -> Mapping[str, Any]:
        # No provider registry is independently invented. Until the trusted
        # contribution seam is attached, applicability and reference coverage
        # are explicitly unavailable, even for an empty declarations list.
        self.read(ref)
        return {"profileRef": ref.to_dict(), "status": "unresolved",
                "referenceCoverage": "unknown", "ready": False,
                "error": {"code": "providerUnavailable", "retryable": False}}
