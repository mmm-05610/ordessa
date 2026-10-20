"""Harness-only definition metadata contracts and catalog admission facade."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import re

from ordessa_execution_agents.harness.definitions.errors import CoreDTOError
from ordessa_execution_agents.harness.definitions.activation import HarnessActivationRef, validate_namespace
from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_execution_agents.harness.definitions.runtime_providers import RUNTIME_PROVIDER_VERSION
from .errors import CatalogAdmissionRefused, CatalogIdentityConflict, CatalogUnavailable
from .registration import HarnessRegistration

HARNESS_DEFINITION_VERSION = "harness-definition/1"


def _text(value):
    return isinstance(value, str) and bool(value) and len(value) <= 128 and not any(
        ord(char) < 32 for char in value
    )


@dataclass(frozen=True)
class HarnessDefinitionDescriptor:
    provider_id: str
    definition_ref: Mapping
    implementation_digest: str
    protocol_id: str
    adapter_version: str
    backend_version: str | None = None
    capabilities: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.provider_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9._-]{0,127}", self.provider_id
        ):
            raise ValueError("explicit Harness provider identity required")
        if not isinstance(self.definition_ref, Mapping) or set(self.definition_ref) != {
            "environmentNamespace", "definitionId", "revision"
        }:
            raise ValueError("complete definition reference required")
        validate_namespace(self.definition_ref["environmentNamespace"])
        if not all(_text(self.definition_ref[key]) for key in ("definitionId", "revision")):
            raise ValueError("invalid definition identity")
        if not isinstance(self.implementation_digest, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.implementation_digest
        ):
            raise ValueError("implementation digest required")
        if (
            not _text(self.protocol_id)
            or not _text(self.adapter_version)
            or self.backend_version is not None and not _text(self.backend_version)
        ):
            raise ValueError("explicit protocol and version metadata required")
        if (
            not isinstance(self.capabilities, tuple)
            or not all(_text(value) for value in self.capabilities)
            or len(set(self.capabilities)) != len(self.capabilities)
        ):
            raise ValueError("explicit unique capability declarations required")
        object.__setattr__(self, "definition_ref", sealed_mapping(self.definition_ref))

    def snapshot(self):
        return HarnessDefinitionDescriptor(
            self.provider_id, self.definition_ref, self.implementation_digest,
            self.protocol_id, self.adapter_version, self.backend_version, self.capabilities,
        )

    def to_dict(self):
        import json
        return {
            "contractVersion": HARNESS_DEFINITION_VERSION,
            "providerId": self.provider_id,
            "definitionRef": json.loads(safe_json(self.definition_ref)),
            "implementationDigest": self.implementation_digest,
            "protocolId": self.protocol_id,
            "adapterVersion": self.adapter_version,
            "backendVersion": self.backend_version,
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class HarnessInstallationObservation:
    state: str
    native_version: str | None = None
    version_verified: bool = False
    evidence_ref: str | None = None

    def __post_init__(self):
        if self.state not in ("present", "missing", "unknown") or type(self.version_verified) is not bool:
            raise ValueError("bounded installation observation required")
        if self.native_version is not None and not _text(self.native_version):
            raise ValueError("invalid native version")
        if self.evidence_ref is not None and not _text(self.evidence_ref):
            raise ValueError("invalid installation evidence reference")
        if self.version_verified and (
            not self.native_version or not self.evidence_ref or self.state != "present"
        ):
            raise ValueError("verified version requires original presence and evidence")


@dataclass(frozen=True)
class HarnessDefinitionDeclaration:
    descriptor: HarnessDefinitionDescriptor
    installation_observer: object = field(repr=False)

    def __post_init__(self):
        if type(self.descriptor) is not HarnessDefinitionDescriptor or not callable(self.installation_observer):
            raise CoreDTOError("explicit definition descriptor and installation owner required")


@dataclass(frozen=True)
class _DefinitionSnapshot:
    descriptor: HarnessDefinitionDescriptor
    observer_identity: int
    observer: object = field(repr=False, compare=False)


def harness_registration_snapshot(declaration, *, phase="stage"):
    """Freeze exact descriptor/callback identity at every catalog boundary."""
    if phase not in ("stage", "commit", "read"):
        raise CoreDTOError("unsupported Harness admission phase")
    if (
        type(declaration) is not HarnessDefinitionDeclaration
        or any(hasattr(declaration, name) for name in (
            "owner", "owner_activation", "generation", "start", "stop", "release",
            "prompt", "create_session", "load_session", "run_process_operation"))
        or type(declaration.descriptor) is not HarnessDefinitionDescriptor
        or not callable(declaration.installation_observer)
        or hasattr(declaration, "configuration_routes")
    ):
        raise CoreDTOError("Harness declaration contains an invalid owner or aggregate")
    return _DefinitionSnapshot(
        declaration.descriptor.snapshot(), id(declaration.installation_observer),
        declaration.installation_observer,
    )


@dataclass(frozen=True)
class AdmittedHarnessDefinition:
    owner_activation: HarnessActivationRef
    descriptor: HarnessDefinitionDescriptor

    @property
    def provider_ref(self):
        owner = self.owner_activation
        return sealed_mapping({
            "environmentNamespace": owner.environment,
            "providerId": self.descriptor.provider_id,
            "ownerActivationRef": {
                "environmentNamespace": owner.environment,
                "pluginId": owner.plugin_id,
                "generation": owner.generation,
            },
            "generation": owner.generation,
            "contractVersion": RUNTIME_PROVIDER_VERSION,
            "implementationDigest": self.descriptor.implementation_digest,
        })


@dataclass
class _CatalogEntry:
    owner_id: str
    generation: int
    installation_id: str
    manifest_digest: str
    declaration: HarnessDefinitionDeclaration
    snapshot: _DefinitionSnapshot
    state: str = "staged"

    @property
    def owner_activation(self):
        return HarnessActivationRef(self.snapshot.descriptor.definition_ref["environmentNamespace"],
                                    self.owner_id, self.generation)


class HarnessCatalog:
    """Owns staged and admitted Harness definitions independently of plugins."""

    def __init__(self, environment_namespace, *, policy, principal_scope="local",
                 admission_lock=None, retirement_guard=None):
        validate_namespace(environment_namespace)
        if policy is None or not callable(getattr(policy, "admit_object_access", None)):
            raise CatalogUnavailable("Harness catalog access policy required")
        if not _text(principal_scope):
            raise CatalogIdentityConflict("explicit Harness principal scope required")
        if retirement_guard is not None and not callable(retirement_guard):
            raise CatalogUnavailable("trusted Harness retirement guard required")
        from threading import RLock
        self.environment_namespace = environment_namespace
        self._policy, self._principal_scope = policy, principal_scope
        self._lock = admission_lock or RLock()
        self._retirement_guard = retirement_guard
        self._entries = []
        self._staged = {}
        self._next_token = 0
        self._closed = False

    def _require_open(self):
        if self._closed:
            raise CatalogUnavailable("Harness catalog is closed")

    def _permission(self):
        self._require_open()
        if not self._policy.admit_object_access(
            self._principal_scope, f"{self.environment_namespace}:agents.runtime", "read"
        ):
            raise CatalogAdmissionRefused("Harness discovery refused")

    @staticmethod
    def _owner(owner_id, generation):
        if not isinstance(owner_id, str) or not re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", owner_id):
            raise CatalogIdentityConflict("valid Harness owner id required")
        if type(generation) is not int or generation < 1:
            raise CatalogIdentityConflict("valid Harness owner generation required")

    def stage(self, owner_id, generation, installation_id, manifest_digest, declarations):
        self._owner(owner_id, generation)
        if not _text(installation_id) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", manifest_digest or ""):
            raise CatalogIdentityConflict("original Harness installation identity required")
        if type(declarations) is not tuple or not declarations:
            raise CoreDTOError("non-empty immutable Harness declarations required")
        snapshots = tuple(harness_registration_snapshot(item) for item in declarations)
        if any(
            item.definition_ref["environmentNamespace"] != self.environment_namespace
            for item in (snapshot.descriptor for snapshot in snapshots)
        ):
            raise CatalogIdentityConflict("Harness declaration belongs to another environment")
        refs = [safe_json(item.descriptor.definition_ref) for item in snapshots]
        ids = [item.descriptor.provider_id for item in snapshots]
        if len(set(refs)) != len(refs) or len(set(ids)) != len(ids):
            raise CoreDTOError("duplicate Harness definitions or providers in registration")
        with self._lock:
            self._require_open()
            for existing in (*self._entries, *(entry for batch in self._staged.values() for entry in batch)):
                if existing.owner_id == owner_id and existing.generation == generation:
                    raise CatalogAdmissionRefused("Harness owner generation already registered")
                if existing.state != "retired" and (
                    safe_json(existing.snapshot.descriptor.definition_ref) in refs
                    or existing.snapshot.descriptor.provider_id in ids
                ):
                    raise CatalogAdmissionRefused("Harness definition already admitted")
            entries = tuple(
                _CatalogEntry(owner_id, generation, installation_id, manifest_digest, declaration, snapshot)
                for declaration, snapshot in zip(declarations, snapshots)
            )
            self._next_token += 1
            token = self._next_token
            self._staged[token] = entries
            return HarnessRegistration(self, token, entries)

    def _recheck(self, entries, phase):
        for entry in entries:
            if harness_registration_snapshot(entry.declaration, phase=phase) != entry.snapshot:
                raise CatalogAdmissionRefused("Harness declaration changed after staging")

    def _commit(self, token, entries):
        with self._lock:
            self._require_open()
            if self._staged.get(token) is not entries:
                raise CatalogAdmissionRefused("original staged Harness registration unavailable")
            self._recheck(entries, "commit")
            for entry in entries:
                entry.state = "active"
                self._entries.append(entry)
            del self._staged[token]
            return tuple(AdmittedHarnessDefinition(entry.owner_activation, entry.snapshot.descriptor)
                         for entry in entries)

    def _rollback(self, token, entries):
        with self._lock:
            if self._staged.get(token) is not entries:
                raise CatalogAdmissionRefused("original staged Harness registration unavailable")
            del self._staged[token]

    def _resolve(self, definition_ref, *, allow_draining=False, pinned_provider_ref=None):
        self._permission()
        if not isinstance(definition_ref, Mapping) or set(definition_ref) != {
            "environmentNamespace", "definitionId", "revision"
        }:
            raise CatalogIdentityConflict("complete definition reference required")
        if definition_ref["environmentNamespace"] != self.environment_namespace:
            raise CatalogIdentityConflict("Harness definition scope differs")
        allowed = ("active", "draining") if allow_draining else ("active",)
        matches = []
        for entry in self._entries:
            if entry.state not in allowed or safe_json(entry.snapshot.descriptor.definition_ref) != safe_json(definition_ref):
                continue
            if harness_registration_snapshot(entry.declaration, phase="read") != entry.snapshot:
                raise CatalogAdmissionRefused("Harness declaration changed after admission")
            admitted = AdmittedHarnessDefinition(entry.owner_activation, entry.snapshot.descriptor)
            if pinned_provider_ref is not None and safe_json(admitted.provider_ref) != safe_json(pinned_provider_ref):
                continue
            matches.append((admitted, entry))
        if len(matches) != 1:
            raise CatalogAdmissionRefused("exact active Harness definition unavailable")
        return matches[0]

    def describe(self, definition_ref):
        with self._lock:
            return self._resolve(definition_ref)[0]

    def describe_for_cleanup(self, definition_ref, pinned_provider_ref):
        if not isinstance(pinned_provider_ref, Mapping):
            raise CatalogIdentityConflict("complete cleanup provider pin required")
        with self._lock:
            admitted, _entry = self._resolve(
                definition_ref, allow_draining=True, pinned_provider_ref=pinned_provider_ref
            )
            if safe_json(admitted.provider_ref) != safe_json(pinned_provider_ref):
                raise CatalogAdmissionRefused("cleanup provider pin differs from original activation")
            return admitted

    def list(self):
        with self._lock:
            self._permission()
            refs = [entry.snapshot.descriptor.definition_ref for entry in self._entries if entry.state == "active"]
            return tuple(self._resolve(ref)[0] for ref in refs)

    def inspect_installation(self, definition_ref):
        with self._lock:
            admitted, entry = self._resolve(definition_ref)
            installation_ref = sealed_mapping({
                "environmentNamespace": self.environment_namespace,
                "installationId": entry.installation_id,
                "sourceRevision": entry.manifest_digest,
            })
            snapshot = entry.snapshot
        observation = snapshot.observer(installation_ref)
        if type(observation) is not HarnessInstallationObservation:
            raise CatalogAdmissionRefused("original installation observation required")
        with self._lock:
            current, current_entry = self._resolve(definition_ref)
            if current != admitted or current_entry is not entry or entry.snapshot != snapshot:
                raise CatalogAdmissionRefused("installation admission changed during observation")
            return sealed_mapping({
                "definitionRef": admitted.descriptor.definition_ref,
                "providerRef": admitted.provider_ref,
                "installationRef": installation_ref,
                "installationState": observation.state,
                "nativeVersion": observation.native_version,
                "versionVerified": observation.version_verified,
                "evidenceRef": observation.evidence_ref,
                "runtimeReady": "unknown",
            })

    def drain(self, owner_id, generation):
        self._owner(owner_id, generation)
        with self._lock:
            self._require_open()
            entries = [e for e in self._entries if e.owner_id == owner_id and e.generation == generation]
            if not entries or any(e.state != "active" for e in entries):
                raise CatalogAdmissionRefused("active Harness generation unavailable to drain")
            for entry in entries:
                entry.state = "draining"

    def retire(self, owner_id, generation):
        self._owner(owner_id, generation)
        if self._retirement_guard is None:
            raise CatalogUnavailable("trusted Harness retirement guard unavailable")
        # Acquire the owner lifecycle guard before catalog state lock to keep a
        # single lock order with activation teardown.
        with self._retirement_guard(owner_id, generation) as permit:
            if permit is not None:
                raise CatalogAdmissionRefused("Harness retirement guard returned an invalid permit")
            with self._lock:
                self._require_open()
                entries = [e for e in self._entries if e.owner_id == owner_id and e.generation == generation]
                if not entries or any(e.state != "draining" for e in entries):
                    raise CatalogAdmissionRefused("Harness generation must be drained before retirement")
                for entry in entries:
                    entry.state = "retired"

    def close(self):
        with self._lock:
            if any(entry.state != "retired" for entry in self._entries) or self._staged:
                raise CatalogAdmissionRefused("Harness catalog still owns staged or live definitions")
            self._closed = True


class HarnessAdmission:
    """Consumer facade over the context's single HarnessCatalog authority."""

    def __init__(self, context):
        catalog = getattr(context, "harness_catalog", None)
        if not isinstance(catalog, HarnessCatalog):
            raise CatalogUnavailable("context HarnessCatalog binding required")
        self._catalog = catalog

    def describe(self, definition_ref):
        return self._catalog.describe(definition_ref)

    def describe_for_cleanup(self, definition_ref, pinned_provider_ref):
        return self._catalog.describe_for_cleanup(definition_ref, pinned_provider_ref)

    def list(self):
        return self._catalog.list()

    def inspect_installation(self, definition_ref):
        return self._catalog.inspect_installation(definition_ref)
