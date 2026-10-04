"""Explicit local directory authority; filesystem identity never grants access.

The caller injects the existing Workspace records and the Environment's same
domain store/fingerprint ports. This module opens no database or Environment.
It is not yet registered as a production contribution for node preparation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
from typing import Protocol
from uuid import uuid4

from ordessa_environment_api import AdmissionRefusedError, EnvironmentId, GuaranteeUnavailableError, IdentityMismatchError, RequestKey
from ordessa_environment_api.domain import DomainStorePort, DomainWrite
from pacthold.agents.public import DirectoryBindingRef

NAMESPACE = "workspace.directory-bindings"
PURPOSES = frozenset({"read", "write", "execute"})


def _text(value):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("bounded nonempty identity required")
    if len(value) > 1024:
        raise ValueError("identity exceeds limit")


def _purposes(value):
    if not isinstance(value, tuple) or not value or len(set(value)) != len(value) or any(item not in PURPOSES for item in value):
        raise ValueError("purposes must be a unique nonempty tuple of read/write/execute")
    return tuple(sorted(value))


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _request_identity(request):
    return {"environmentNamespace": request.environment_namespace, "principalScope": request.principal_scope, "requestId": request.request_id}


@dataclass(frozen=True)
class ProjectRef:
    environment_namespace: str
    project_id: str
    project_revision: int

    def __post_init__(self):
        EnvironmentId(self.environment_namespace)
        _text(self.project_id)
        if type(self.project_revision) is not int or self.project_revision < 1:
            raise ValueError("project revision must be a positive integer")

    def to_dict(self):
        return {"environmentNamespace": self.environment_namespace, "projectId": self.project_id, "projectRevision": self.project_revision}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"environmentNamespace", "projectId", "projectRevision"}:
            raise ValueError("invalid ProjectRef fields")
        return cls(value["environmentNamespace"], value["projectId"], value["projectRevision"])


@dataclass(frozen=True)
class LocalDirectoryRealm:
    host_id: str
    filesystem_realm: str
    native_realm: str

    def __post_init__(self):
        for value in (self.host_id, self.filesystem_realm, self.native_realm):
            _text(value)

    def to_dict(self):
        return {"hostId": self.host_id, "filesystemRealm": self.filesystem_realm, "nativeRealm": self.native_realm}


@dataclass(frozen=True)
class DirectoryGrant:
    principal_scope: str
    project_ref: ProjectRef
    purposes: tuple[str, ...]
    authority_revision: str
    expires_at: float

    def __post_init__(self):
        _text(self.principal_scope)
        _text(self.authority_revision)
        if not isinstance(self.project_ref, ProjectRef):
            raise ValueError("ProjectRef required")
        object.__setattr__(self, "purposes", _purposes(self.purposes))
        if type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at):
            raise ValueError("expiry must be a finite UTC epoch")

    def to_dict(self):
        return {"principalScope": self.principal_scope, "projectRef": self.project_ref.to_dict(), "purposes": list(self.purposes),
                "authorityRevision": self.authority_revision, "expiresAt": self.expires_at}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"principalScope", "projectRef", "purposes", "authorityRevision", "expiresAt"} or not isinstance(value["purposes"], list):
            raise ValueError("invalid DirectoryGrant fields")
        return cls(value["principalScope"], ProjectRef.from_dict(value["projectRef"]), tuple(value["purposes"]), value["authorityRevision"], value["expiresAt"])


class DirectoryAuthorityPort(Protocol):
    """Read-only bounded authorization, supplied by the trusted deployment."""
    def authorize(self, principal: str, project_ref: ProjectRef, purposes: tuple[str, ...]) -> DirectoryGrant | None: ...
    def revalidate(self, principal: str, project_ref: ProjectRef, grant: DirectoryGrant) -> DirectoryGrant | None: ...


@dataclass(frozen=True)
class DirectoryBindingEvidence:
    binding_ref: DirectoryBindingRef
    project_ref: ProjectRef
    realm: LocalDirectoryRealm
    canonical_path: str
    device: int
    inode: int
    grant: DirectoryGrant
    purposes: tuple[str, ...]

    def to_dict(self):
        return {"bindingRef": self.binding_ref.to_dict(), "projectRef": self.project_ref.to_dict(),
                **self.realm.to_dict(), "canonicalPath": self.canonical_path, "device": self.device, "inode": self.inode,
                "grant": self.grant.to_dict(), "purposes": list(self.purposes)}


class DirectoryBindingService:
    def __init__(self, *, environment_namespace, principal_scope, store, fingerprint_port, records, authority_port, realm):
        EnvironmentId(environment_namespace)
        _text(principal_scope)
        if not isinstance(realm, LocalDirectoryRealm):
            raise ValueError("trusted local realm is required")
        self.environment_namespace = environment_namespace
        self.principal_scope = principal_scope
        self.store, self.fingerprint_port, self.records = store, fingerprint_port, records
        self.authority_port, self.realm = authority_port, realm

    def _resources(self, *, issue=False):
        if not isinstance(self.store, DomainStorePort):
            raise GuaranteeUnavailableError("directory binding requires the same atomic domain store")
        if self.authority_port is None or not callable(getattr(self.authority_port, "revalidate", None)):
            raise GuaranteeUnavailableError("directory authority is unavailable")
        if issue and (not callable(getattr(self.authority_port, "authorize", None)) or self.fingerprint_port is None
                      or not callable(getattr(self.fingerprint_port, "fingerprint", None)) or not callable(getattr(self.fingerprint_port, "describe", None))):
            raise GuaranteeUnavailableError("directory issue requires explicit authority and fingerprint capabilities")

    def _principal(self, principal):
        if principal != self.principal_scope:
            raise AdmissionRefusedError("directory principal does not match the trusted scope")

    def _project(self, ref):
        if not isinstance(ref, ProjectRef) or ref.environment_namespace != self.environment_namespace:
            raise IdentityMismatchError("directory project namespace does not match")
        try:
            row = self.records.get(ref.project_id)
        except Exception:
            raise IdentityMismatchError("project record is unavailable") from None
        if not isinstance(row, dict) or row.get("id") != ref.project_id or type(row.get("version")) is not int or row["version"] != ref.project_revision or row.get("archived_at") is not None:
            raise IdentityMismatchError("project revision or availability changed")
        if row.get("env_kind") != "local" or row.get("env_host") != self.realm.host_id:
            raise GuaranteeUnavailableError("project does not have matching local host evidence")
        return row

    def _grant(self, grant, project, purposes):
        if (not isinstance(grant, DirectoryGrant) or grant.principal_scope != self.principal_scope
                or grant.project_ref != project or not set(purposes) <= set(grant.purposes)):
            raise AdmissionRefusedError("directory purpose authorization was refused")
        if grant.expires_at <= time.time():
            raise AdmissionRefusedError("directory authorization expired")
        return grant

    def _facts(self, row):
        path = row.get("normalized_path")
        try:
            if not isinstance(path, str) or not Path(path).is_absolute():
                raise ValueError("absolute directory required")
            canonical = Path(path).resolve(strict=True)
            fd = os.open(canonical, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                observed = os.fstat(fd)
                current = Path(path).resolve(strict=True)
                actual = current.stat()
                if (not stat.S_ISDIR(observed.st_mode) or current != canonical
                        or (actual.st_dev, actual.st_ino) != (observed.st_dev, observed.st_ino)):
                    raise ValueError("directory identity changed")
                return {"canonicalPath": str(canonical), "device": observed.st_dev, "inode": observed.st_ino}
            finally:
                os.close(fd)
        except (OSError, ValueError, RuntimeError):
            raise IdentityMismatchError("actual local directory identity is unavailable or changed") from None

    def issue(self, request: RequestKey, project_ref: ProjectRef, purposes: tuple[str, ...]):
        self._resources(issue=True)
        if not isinstance(request, RequestKey) or request.environment_namespace != self.environment_namespace:
            raise IdentityMismatchError("directory request namespace does not match")
        self._principal(request.principal_scope)
        purposes = _purposes(purposes)
        if not isinstance(project_ref, ProjectRef):
            raise ValueError("ProjectRef required")
        parameters = {"projectRef": project_ref.to_dict(), "purposes": list(purposes), "realm": self.realm.to_dict()}
        try:
            self.fingerprint_port.describe()
            digest = self.fingerprint_port.fingerprint(request, "workspace.directory.issue", _digest(parameters))
        except Exception:
            raise GuaranteeUnavailableError("directory protected fingerprint is unavailable") from None
        previous = self.store.read_domain_result(request, digest)
        if previous is not None:
            ref = DirectoryBindingRef.from_dict(dict(previous))
            self._match_request(ref, project_ref, purposes, request, digest)
            return ref
        row = self._project(project_ref)
        try:
            grant = self.authority_port.authorize(self.principal_scope, project_ref, purposes)
        except Exception:
            raise AdmissionRefusedError("directory authority could not confirm authorization") from None
        grant = self._grant(grant, project_ref, purposes)
        content = {"projectRef": project_ref.to_dict(), "realm": self.realm.to_dict(), **self._facts(row),
                   "grant": grant.to_dict(), "purposes": list(purposes),
                   "issuance": {"request": _request_identity(request), "requestDigest": digest}}
        ref = DirectoryBindingRef(self.environment_namespace, "dir-" + uuid4().hex, 1, _digest(content))
        # Recheck before publishing the immutable binding. This is data-only;
        # it still grants no access without a revalidate at the actual use site.
        if self._facts(self._project(project_ref)) != {name: content[name] for name in ("canonicalPath", "device", "inode")}:
            raise IdentityMismatchError("directory changed before publication")
        current = self._revalidate_grant(project_ref, grant, purposes)
        if current != grant:
            raise IdentityMismatchError("directory authority changed before publication")
        result = self.store.commit_domain_change(request, digest, (DomainWrite(NAMESPACE, ref.binding_id, 0, content),), ref.to_dict())
        confirmed = DirectoryBindingRef.from_dict(dict(result))
        self._match_request(confirmed, project_ref, purposes, request, digest)
        return confirmed

    def _match_request(self, ref, project, purposes, request, digest):
        evidence = self.revalidate(ref, self.principal_scope, purposes)
        row = self.store.read_domain(self.environment_namespace, NAMESPACE, ref.binding_id)
        if (evidence.project_ref != project or evidence.purposes != purposes or evidence.realm != self.realm
                or row is None or row["value"].get("issuance") != {"request": _request_identity(request), "requestDigest": digest}):
            raise IdentityMismatchError("stored directory result does not match the fixed issuance request")
        return evidence

    def _revalidate_grant(self, project, grant, purposes):
        try:
            current = self.authority_port.revalidate(self.principal_scope, project, grant)
        except Exception:
            raise AdmissionRefusedError("directory authority could not confirm current authorization") from None
        current = self._grant(current, project, purposes)
        if current.authority_revision != grant.authority_revision or current != grant:
            raise IdentityMismatchError("directory authorization changed; existing binding is not renewed")
        return current

    def revalidate(self, ref: DirectoryBindingRef, principal: str, purposes: tuple[str, ...]):
        self._resources()
        self._principal(principal)
        purposes = _purposes(purposes)
        if not isinstance(ref, DirectoryBindingRef) or ref.environment_namespace != self.environment_namespace:
            raise IdentityMismatchError("directory binding namespace does not match")
        row = self.store.read_domain(self.environment_namespace, NAMESPACE, ref.binding_id)
        if row is None or row.get("record_id") != ref.binding_id or row["revision"] != ref.binding_revision or _digest(row["value"]) != ref.content_digest:
            raise IdentityMismatchError("directory binding identity or digest does not match")
        content = row["value"]
        try:
            if set(content) != {"projectRef", "realm", "canonicalPath", "device", "inode", "grant", "purposes", "issuance"}:
                raise ValueError("binding shape mismatch")
            if content["realm"] != self.realm.to_dict():
                raise ValueError("realm mismatch")
            project = ProjectRef.from_dict(content["projectRef"])
            grant = DirectoryGrant.from_dict(content["grant"])
            if not isinstance(content["purposes"], list):
                raise ValueError("binding purposes invalid")
            bound_purposes = _purposes(tuple(content["purposes"]))
        except (ValueError, KeyError, TypeError):
            raise IdentityMismatchError("directory binding record is incompatible with the trusted realm") from None
        if not set(purposes) <= set(bound_purposes):
            raise AdmissionRefusedError("requested purpose exceeds this immutable directory binding")
        self._grant(grant, project, purposes)
        self._revalidate_grant(project, grant, purposes)
        actual = self._facts(self._project(project))
        if actual != {name: content[name] for name in ("canonicalPath", "device", "inode")}:
            raise IdentityMismatchError("bound directory object or alias changed")
        return DirectoryBindingEvidence(ref, project, self.realm, actual["canonicalPath"], actual["device"], actual["inode"], grant, bound_purposes)
