"""Profile management on the original Environment authority and atomic store.

Business rules, admission and revision coordination live here; the injected
Environment owns identity/trust/lock/fingerprint, and its original store commits
all changes atomically through the Profile storage port. No native Unit effects.
"""
from __future__ import annotations
from ordessa_execution_agents.profiles.definitions.codec import decode_profile, decode_revision_ref, encode_content, encode_revision_ref

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Mapping

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError, UnknownResultError,
)
from ordessa_infrastructure.database.records import DomainWrite
from .ports import ProfileStorePort
from .environment_store import EnvironmentProfileStore
from .compatibility import (SNAPSHOT_PREFIX, PROFILE_CAPABILITY, historical_action,
                             creation_facts, revision_facts, metadata_facts, clone_facts)

from ..definitions.models import Profile, ProfileRevision, ProfileRevisionRef
from ..definitions.validation import (ProfileNotFound, ProfileRevisionConflict,
                                      ProfileValidationError, canonical_content)
from ..definitions.codec import canonical, content_digest, decode_content

class ProfileService:
    def __init__(self, environment):
        self._environment = environment
        self._profile_store: ProfileStorePort = EnvironmentProfileStore(environment)

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
            return {PROFILE_CAPABILITY: self._profile_store.available()
                    and env._policy is not None and env._fingerprint_port is not None,
                    "nodes": False, "managedInput": False}

    def _storage(self) -> ProfileStorePort:
        if not self._profile_store.available():
            raise GuaranteeUnavailableError("Profile management requires the original store's atomic record capability")
        return self._profile_store

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
    def _change(self, kind: str, request: RequestKey, profile_id: str, parameters: dict[str, object]):
        env = self._environment
        # Same ordering point as Environment's admission/lifecycle cuts. No
        # plugin/native callback runs inside this data-only transaction.
        with env._admission_lock:
            env._check_open()
            env._check_environment(request.environment_namespace)
            if request.principal_scope != env._principal_scope:
                raise AdmissionRefusedError("request principal does not match the trusted environment principal")
            if env._policy is None or not env._policy.admit_invoke(
                env._principal_scope, f"pacthold.agents.profiles.{historical_action(kind)}", "reliable"
            ):
                raise AdmissionRefusedError("Profile write permission unavailable or refused")
            if not env._policy.admit_object_access(
                env._principal_scope, f"{env.environment_id}:agents.profile:{profile_id}", "write"
            ):
                raise AdmissionRefusedError("Profile target write permission unavailable or refused")
            if env._fingerprint_port is None:
                raise GuaranteeUnavailableError("Profile writes require the environment's protected fingerprint port")
            store = self._storage()
            env._fingerprint_port.describe()
            digest = env._fingerprint_port.fingerprint(
                request, f"pacthold.agents.profiles.{historical_action(kind)}", content_digest(canonical(parameters))
            )
            replay = store.read_result(request, digest)
            yield store, digest, replay

    def _profile(self, profile_id: str) -> Profile:
        row = self._storage().read_profile(self.environment_namespace, profile_id)
        if row is None:
            raise ProfileNotFound("Profile does not exist in this environment")
        return self._profile_record(row, profile_id)

    def _replay(self, value, profile_id, version, *, ref=None, name=None):
        """Validate the historical result, without comparing today's Profile."""
        try:
            profile = decode_profile(value)
            if (profile.profile_id != profile_id or profile.current_revision.profile_id != profile_id
                    or profile.current_revision.environment_namespace != self.environment_namespace
                    or type(profile.version) is not int or profile.version != version
                    or (ref is not None and profile.current_revision != ref)
                    or (name is not None and profile.name != name)
                    or (profile.archived_at is not None and not isinstance(profile.archived_at, str))):
                raise ValueError("result identity mismatch")
            self._name(profile.name)
            self._revision(profile.current_revision)
            return profile
        except (ValueError, TypeError, KeyError, IdentityMismatchError,
                GuaranteeUnavailableError, ProfileNotFound):
            raise UnknownResultError("stored Profile result cannot be verified; do not resend") from None

    def _profile_record(self, row, requested_id=None) -> Profile:
        try:
            profile = decode_profile(row['value'])
            ref = profile.current_revision
            if (row["record_id"] != profile.profile_id
                    or (requested_id is not None and profile.profile_id != requested_id)
                    or ref.profile_id != profile.profile_id
                    or ref.environment_namespace != self.environment_namespace
                    or type(profile.version) is not int or profile.version < 1
                    or row["revision"] != profile.version):
                raise ValueError("identity or revision mismatch")
            self._name(profile.name)
            if profile.archived_at is not None and not isinstance(profile.archived_at, str):
                raise ValueError("invalid archive metadata")
            return profile
        except (ValueError, TypeError, KeyError):
            raise GuaranteeUnavailableError("Profile management identity or revision is inconsistent") from None

    def list(self, *, include_archived: bool = False) -> tuple[Profile, ...]:
        with self._environment._admission_lock:
            self._read_permission()
            profiles = []
            for row in self._storage().list_profiles(self.environment_namespace):
                profile = self._profile_record(row)
                try:
                    self._read_permission(profile.profile_id)
                except AdmissionRefusedError:
                    continue
                if include_archived or profile.archived_at is None:
                    profiles.append(profile)
            return tuple(profiles)

    def get(self, profile_id: str) -> Profile:
        with self._environment._admission_lock:
            self._read_permission(profile_id)
            return self._profile(profile_id)

    def _revision(self, ref: ProfileRevisionRef) -> ProfileRevision:
        self._environment._check_environment(ref.environment_namespace)
        row = self._storage().read_revision(ref)
        if row is None:
            raise ProfileNotFound("Profile content revision does not exist")
        try:
            stored_ref = decode_revision_ref(row['value']['ref'])
        except (ValueError, TypeError, KeyError):
            raise GuaranteeUnavailableError("Profile revision identity is inconsistent") from None
        if stored_ref != ref:
            raise ProfileRevisionConflict("Profile content digest does not match its immutable revision")
        if row["record_id"] != f"{ref.profile_id}@{ref.revision}" or row["revision"] != 1:
            raise GuaranteeUnavailableError("Profile revision record is not immutable")
        try:
            content_json = canonical_content(row["value"]["content"], self.environment_namespace)
        except (ValueError, TypeError, KeyError):
            raise GuaranteeUnavailableError("Profile revision content is inconsistent") from None
        if content_digest(content_json) != ref.digest:
            raise GuaranteeUnavailableError("Profile revision digest is inconsistent")
        return ProfileRevision(ref, decode_content(row["value"]["content"], self.environment_namespace))

    def select_current(self, profile_id: str) -> ProfileRevision:
        """Capture the current unarchived revision under one Environment lock.

        Exact revision audit remains available after archive via get_revision;
        archive only blocks current selection. No historical metadata grants a
        provider or changes the core's opaque-content interpretation.
        """
        with self._environment._admission_lock:
            self._read_permission(profile_id)
            current = self._profile(profile_id)
            if current.archived_at is not None:
                raise AdmissionRefusedError("archived Profile cannot be selected")
            return self._revision(current.current_revision)

    def get_revision(self, ref: ProfileRevisionRef) -> ProfileRevision:
        with self._environment._admission_lock:
            if type(ref) is not ProfileRevisionRef:
                raise ProfileValidationError("fixed Profile reference required")
            if ref.profile_id.startswith(SNAPSHOT_PREFIX):
                self._snapshot_permission(ref.profile_id, "read")
            else:
                self._read_permission(ref.profile_id)
            return self._revision(ref)

    def stage_snapshot(self, content: dict[str, object]) -> tuple[ProfileRevisionRef, DomainWrite | None]:
        """Freeze an ad-hoc content into an immutable content-addressed snapshot.

        The derived identity is deterministic in the canonical Profile
        content, so the same body always yields the same snapshot reference
        and the consuming request stays idempotent. The returned write must
        commit in the same transaction as the consuming operation's reserve:
        either both persist or neither does. An existing record with the same
        content needs no write; a differing record at the same identity is a
        collision and is never rewritten. The snapshot carries no managed Profile
        record, so an orphan snapshot can never present itself as a created or
        updated instance.
        """
        env = self._environment
        with env._admission_lock:
            env._check_open()
            content_value = decode_content(content, self.environment_namespace)
            content_json = canonical_content(encode_content(content_value), self.environment_namespace)
            digest = content_digest(content_json)
            ref = ProfileRevisionRef(self.environment_namespace, SNAPSHOT_PREFIX + digest[7:55], 1, digest)
            self._snapshot_permission(ref.profile_id, "write")
            # Preparation immediately rereads the frozen snapshot while
            # executing/recovering its reserved operation. Check both object
            # rights now, before the caller can reserve that operation.
            self._snapshot_permission(ref.profile_id, "read")
            row = self._storage().read_revision(ref)
            if row is not None:
                try:
                    self._revision(ref)
                except (ProfileRevisionConflict, ProfileNotFound, GuaranteeUnavailableError, ValueError, TypeError):
                    raise GuaranteeUnavailableError("immutable snapshot record collision") from None
                return ref, None
            revision = ProfileRevision(ref, content_value)
            return ref, self._storage().stage_snapshot_write(revision)

    @staticmethod
    def _mint(profile_id: str) -> None:
        if not isinstance(profile_id, str) or not profile_id or profile_id.startswith(SNAPSHOT_PREFIX):
            raise ProfileValidationError("profile id must avoid the reserved snapshot prefix")

    @staticmethod
    def _name(name: str) -> str:
        if not isinstance(name, str) or not name.strip() or len(name) > 256:
            raise ProfileValidationError("Profile name must be nonempty and bounded")
        return name

    def create(self, *, profile_id: str, name: str,
                content: dict[str, object], request: RequestKey) -> Profile:
        self._mint(profile_id)
        content_value = decode_content(content, self.environment_namespace)
        content_json = canonical_content(encode_content(content_value), self.environment_namespace)
        ref = ProfileRevisionRef(self.environment_namespace, profile_id, 1, content_digest(content_json))
        profile = Profile(profile_id, 1, self._name(name), None, ref)
        with self._change("create", request, profile_id, creation_facts(profile, content_json)) as (store, digest, replay):
            if replay is not None:
                return self._replay(replay, profile_id, 1, ref=ref, name=name)
            result = store.commit_change(request, digest, profile, 0,
                ProfileRevision(ref, content_value))
            return decode_profile(result)

    def revise(self, profile_id: str, *, content: dict[str, object],
             expected_version: int, base_revision: ProfileRevisionRef,
             request: RequestKey) -> Profile:
        content_value = decode_content(content, self.environment_namespace)
        content_json = canonical_content(encode_content(content_value), self.environment_namespace)
        parameters = revision_facts(profile_id, content_json, expected_version, base_revision)
        with self._change("revise", request, profile_id, parameters) as (store, digest, replay):
            if replay is not None:
                expected_ref = ProfileRevisionRef(self.environment_namespace, profile_id,
                    base_revision.revision + 1, content_digest(content_json))
                return self._replay(replay, profile_id, expected_version + 1, ref=expected_ref)
            current = self._profile(profile_id)
            self._cas(current, expected_version, base_revision)
            if current.archived_at is not None:
                raise ProfileRevisionConflict("archived Profile must be restored before content editing")
            self._revision(base_revision)
            ref = ProfileRevisionRef(self.environment_namespace, profile_id,
                             base_revision.revision + 1, content_digest(content_json))
            profile = Profile(profile_id, current.version + 1,
                                        current.name, None, ref)
            result = store.commit_change(request, digest, profile, current.version,
                ProfileRevision(ref, content_value))
            return decode_profile(result)

    @staticmethod
    def _cas(current, expected_version, base=None):
        if type(expected_version) is not int or expected_version < 1:
            raise ProfileValidationError("expected_version must be a positive integer")
        if current.version != expected_version or (
            base is not None and current.current_revision != base
        ):
            raise ProfileRevisionConflict("Profile management or base content revision conflict")

    def _metadata(self, kind, profile_id, expected, request, *, name=None):
        if kind == "rename":
            name = self._name(name)
        parameters = metadata_facts(kind, profile_id, expected, name)
        with self._change(kind, request, profile_id, parameters) as (store, digest, replay):
            if replay is not None:
                return self._replay(replay, profile_id, expected + 1, name=name)
            current = self._profile(profile_id)
            self._cas(current, expected)
            archived = current.archived_at
            if kind == "archive":
                archived = archived or datetime.now(timezone.utc).isoformat()
            elif kind == "restore":
                archived = None
            profile = Profile(profile_id, current.version + 1,
                                        name if kind == "rename" else current.name,
                                        archived, current.current_revision)
            result = store.commit_change(request, digest, profile, current.version)
            return decode_profile(result)

    def rename(self, profile_id: str, *, name: str, expected_version: int,
               request: RequestKey) -> Profile:
        return self._metadata("rename", profile_id, expected_version, request,
                              name=name)

    def archive(self, profile_id: str, *, expected_version: int,
                request: RequestKey) -> Profile:
        return self._metadata("archive", profile_id, expected_version, request)

    def restore(self, profile_id: str, *, expected_version: int,
                request: RequestKey) -> Profile:
        return self._metadata("restore", profile_id, expected_version, request)

    def clone(self, source_ref: ProfileRevisionRef, *, profile_id: str, name: str,
              request: RequestKey) -> Profile:
        self._mint(profile_id)
        parameters = clone_facts(source_ref, profile_id, self._name(name))
        with self._change("clone", request, profile_id, parameters) as (store, digest, replay):
            self._read_permission(source_ref.profile_id)
            if replay is not None:
                expected_ref = ProfileRevisionRef(self.environment_namespace, profile_id, 1, source_ref.digest)
                return self._replay(replay, profile_id, 1, ref=expected_ref, name=name)
            revision = self._revision(source_ref)
            ref = ProfileRevisionRef(self.environment_namespace, profile_id, 1, source_ref.digest)
            profile = Profile(profile_id, 1, name, None, ref)
            result = store.commit_change(request, digest, profile, 0, ProfileRevision(ref, revision.content))
            return decode_profile(result)

    def preview(self, ref: ProfileRevisionRef) -> Mapping[str, Any]:
        # No provider registry is independently invented. Until the trusted
        # contribution seam is attached, applicability and reference coverage
        # are explicitly unavailable, even for an empty declarations list.
        self.get_revision(ref)
        return {"profileRef": encode_revision_ref(ref), "status": "unresolved",
                "referenceCoverage": "unknown", "ready": False,
                "error": {"code": "providerUnavailable", "retryable": False}}
