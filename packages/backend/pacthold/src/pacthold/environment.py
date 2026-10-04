"""``pacthold.environment`` — the E1 empty Environment (spec 026 order 003).

One instance-scoped object that owns the unique indices of an environment:
installations, enablement, activations, participant instances, capabilities,
objects, activities and usages. Nothing here is process-global; two
``Environment`` objects never see each other's registries (T003-06), and the
module imports no product, no plugin, no server and no concrete store.

Dependency direction (load-bearing):

* DTO/ref/error types come from the frozen contract package
  ``ordessa_environment_api`` — this module never redefines them, so there is
  exactly one wire vocabulary (C95-2).
* Contribution/provider validation is REUSED from ``pacthold.core.registration``
  (``CoreRegistry`` staged batches) — no second registry implementation
  (T003-03).
* A ``StorePort``/``PolicyPort``/``ProtectedFingerprintPort`` are optional
  injections; absence refuses exactly the guarantees that need them and
  leaves ordinary raw/read paths working (M06, G003-1 counterexample).

Order scope: activate/instantiate/bind/invoke/use/release/query/lookup,
single-writer authority, bounded observation, and lifecycle closure. Durable
recovery remains an additive StorePort capability and is not implied by these
in-process observations.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from functools import wraps
import secrets
from threading import Condition, RLock
from types import MappingProxyType
import time
from typing import Any, Mapping

from ordessa_environment_api import (
    CONTRACT_VERSION,
    ActivationReceipt,
    ActivityReceipt,
    AdmissionRefusedError,
    AuthorityConflictError,
    AuthorityKey,
    AuthorityRegistration,
    BindingSnapshot,
    ChangeReservation,
    CreationReceipt,
    CurrentFactView,
    EnvironmentId,
    FingerprintDescriptor,
    GuaranteeUnavailableError,
    IdentityMismatchError,
    ObjectRef,
    PersistentReference,
    PolicyPort,
    ProtectedFingerprintPort,
    ReferenceStatus,
    RequestKey,
    RevisionSelector,
    SequenceTriple,
    StorePort,
    SubscriptionRef,
    UsageRecord,
    UsageRef,
)
from ordessa_environment_api.errors import EnvironmentError
from ordessa_environment_api.guarantee import GuaranteeLevel
from ordessa_environment_api.identity import ActivationRef, ParticipantInstanceRef, SurfaceRef
from ordessa_environment_api.targets import CanonicalFactTarget

from .core.registration import (
    BatchAlreadyUsedError,
    CoreContributionSet,
    CoreRegistry,
    CoreRegistrySnapshot,
    RegistrationConflictError,
)

__all__ = [
    "Environment",
    "EnvironmentClosedError",
    "InvocationPreflight",
    "InstallationRecord",
    "ObservationBatch",
    "ObservationFrame",
    "ObservationAttachmentUnknownError",
    "ObservationReleasePendingError",
    "SubscriptionHandle",
    "WouldDeadlockError",
]


def _admission_locked(method):
    """Serialize lifecycle admission-cut methods with invoke claim admission."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._admission_lock:
            return method(self, *args, **kwargs)
    return wrapped


class EnvironmentClosedError(EnvironmentError):
    code = "ENVIRONMENT_CLOSED"


class WouldDeadlockError(EnvironmentError):
    """A wait registration would close a cycle in the wait graph (V3-9)."""

    code = "WOULD_DEADLOCK"


class ObservationReleasePendingError(EnvironmentError):
    """Detach did not confirm; observer responsibility remains a blocker."""

    code = "OBSERVATION_RELEASE_PENDING"

    def __init__(self, ref: SubscriptionRef, message: str = "observation detach is pending") -> None:
        super().__init__(f"{message}: {ref.subscription_id}")
        self.ref = ref


class ObservationAttachmentUnknownError(EnvironmentError):
    """Attach raised without proving whether a source observer was created."""

    code = "OBSERVATION_ATTACHMENT_UNKNOWN"

    def __init__(self, ref: SubscriptionRef) -> None:
        super().__init__(f"source attachment outcome is unknown: {ref.subscription_id}")
        self.ref = ref


@dataclass(frozen=True)
class InstallationRecord:
    """A discovered installation unit — being installed enables nothing."""

    installation_id: str
    manifest_digest: str
    declared_contracts: tuple[str, ...] = ()


@dataclass(frozen=True)
class InvocationPreflight:
    """Safe capability metadata returned by the read-only invoke preflight.

    This deliberately contains no port objects, key material, or fingerprint
    values. A successful result proves that the requested checks passed at the
    instant of the check; ``invoke`` repeats admission and claim checks before
    dispatch because lifecycle or policy state may change afterwards.
    """

    environment_id: str
    surface_id: str
    guarantee: GuaranteeLevel
    effect: bool
    backend_durable: bool
    fingerprint_descriptor: FingerprintDescriptor | None = None


@dataclass(frozen=True)
class ObservationFrame:
    """One bounded, Environment-sequenced observation envelope."""

    kind: str
    revision: str | None
    cursor: str
    source: Mapping[str, Any]
    value: Any = None
    patch: Any = None
    reason: str | None = None


@dataclass(frozen=True)
class ObservationBatch:
    """A credit-bounded delivery batch; a gap requires a fresh snapshot."""

    subscription_id: str
    frames: tuple[ObservationFrame, ...]
    cursor: str | None
    resync_required: bool = False


@dataclass
class _AuthorityEntry:
    registration: AuthorityRegistration
    activation: ActivationRef


@dataclass
class _ObservationEntry:
    ref: SubscriptionRef
    binding: BindingSnapshot
    target: CanonicalFactTarget
    registration: AuthorityRegistration
    principal: str
    usage: UsageRef
    source: Any
    expires_at: float
    lease_seconds: float = 30.0
    initial_cursor: str | None = None
    detach: Any = None
    queue: list[ObservationFrame] | None = None
    sequence: int = 0
    cursor: str | None = None
    acknowledged_cursor: str | None = None
    gap_reason: str | None = None
    revoked: bool = False
    released: bool = False
    release_requested: bool = False
    detach_pending: bool = False
    attachment_unknown: bool = False
    attach_in_progress: bool = True
    detach_in_progress: bool = False
    initial_snapshot_seen: bool = False
    invalid_initial_sequence: bool = False


class SubscriptionHandle:
    """Convenience lease returned by ``read_and_subscribe``.

    The ref remains owned by Environment; all operations route back through
    its principal/target checks rather than exposing the internal entry.
    """

    __slots__ = ("_environment", "ref", "_principal", "_target")

    def __init__(self, environment: "Environment", ref: SubscriptionRef,
                 principal: str, target: CanonicalFactTarget) -> None:
        self._environment = environment
        self.ref = ref
        self._principal = principal
        self._target = target

    def observe(self, cursor: str | None = None, credits: int = 32,
                timeout_ms: int = 0) -> ObservationBatch:
        return self._environment.observe(
            self.ref, cursor, credits, timeout_ms,
            principal=self._principal, target=self._target,
        )

    def release(self) -> None:
        self._environment.unsubscribe(
            self.ref, principal=self._principal, target=self._target,
        )


class _ObservationSink:
    """Source callback adapter which buffers synchronous attach-time events."""

    __slots__ = ("_environment", "_subscription_id")

    def __init__(self, environment: "Environment", subscription_id: str) -> None:
        self._environment = environment
        self._subscription_id = subscription_id

    def snapshot(self, revision: str, value: Any) -> None:
        self._environment._observation_event(self._subscription_id, "snapshot", revision, value=value)

    def delta(self, revision: str, patch: Any) -> None:
        self._environment._observation_event(self._subscription_id, "delta", revision, patch=patch)

    def gap(self, reason: str) -> None:
        self._environment._observation_event(self._subscription_id, "gap", None, reason=reason)

    def revoked(self) -> None:
        self._environment._observation_event(self._subscription_id, "revoked", None)


@dataclass
class _ActivationEntry:
    ref: ActivationRef
    contributions: CoreContributionSet
    state: str = "active"  # active|draining|retired
    contribution_revision: int = 0


@dataclass
class _CapabilityEntry:
    surface: SurfaceRef
    owner_activation: ActivationRef
    operation_kinds: tuple[str, ...]
    historical: bool = False


@dataclass
class _ObjectEntry:
    ref: ObjectRef
    owner_activation: ActivationRef
    state: str = "available"  # available|closing|released|unknown
    historical: bool = False
    management: str = "owned"  # owned|borrowed|static-projection (V3-10)


@dataclass
class _ActivityEntry:
    request: RequestKey
    receipt: ActivityReceipt
    current: CurrentFactView
    binding_digest: str = ""


class _EnvironmentActivationStage:
    """One staged activation over the Environment's existing CoreRegistry."""

    __slots__ = ("_environment", "_plugin_id", "_payload", "_batch", "_receipt")

    def __init__(self, environment: "Environment", plugin_id: str,
                 payload: CoreContributionSet, batch: Any) -> None:
        self._environment = environment
        self._plugin_id = plugin_id
        self._payload = payload
        self._batch = batch
        self._receipt: ActivationReceipt | None = None

    @property
    def state(self) -> str:
        if self._receipt is not None:
            entry = self._environment._activations.get((
                self._receipt.activation.plugin_id, self._receipt.activation.generation
            ))
            if entry is not None and entry.state == "retired":
                return "retired"
        return self._batch.state

    @property
    def receipt(self) -> ActivationReceipt | None:
        return self._receipt

    def commit(self) -> ActivationReceipt:
        if self._receipt is not None:
            return self._receipt
        self._receipt = self._environment._commit_activation_stage(
            self._plugin_id, self._payload, self._batch
        )
        return self._receipt

    def rollback(self) -> None:
        # A committed owner may already have been observed or used. CoreRegistry
        # correctly refuses rollback after publication; retirement must go
        # through Environment lifecycle blockers via retire_activation().
        self._environment._registry.rollback(self._batch)


class Environment:
    """The single root of one environment's identity indices.

    G003-1: boots read-only with no Server/Harness/Profile/SQLite anywhere in
    its import chain; reliable effects are refused (typed) when the optional
    ports are absent instead of silently downgrading to raw.
    """

    def __init__(
        self,
        environment_id: str | EnvironmentId,
        *,
        store: StorePort | None = None,
        policy: PolicyPort | None = None,
        fingerprint_port: ProtectedFingerprintPort | None = None,
        principal_scope: str = "local",
    ) -> None:
        self._id = environment_id if isinstance(environment_id, EnvironmentId) else EnvironmentId(environment_id)
        self._store = store
        self._policy = policy
        self._fingerprint_port = fingerprint_port
        self._principal_scope = principal_scope
        # Serialize in-memory request admission/claim with drain/retire cuts.
        # This lock is always released before user/native dispatch callbacks.
        self._admission_lock = RLock()
        # Observation waiters share the admission lock so enqueue, release,
        # expiry and lifecycle cuts have one ordering point.
        self._observation_changed = Condition(self._admission_lock)
        self._closed = False
        # instance-scoped indices — the ONLY state, no module globals (T003-06)
        self._installations: dict[str, InstallationRecord] = {}
        self._enabled: set[str] = set()  # T003-04: starts empty
        self._activations: dict[tuple[str, int], _ActivationEntry] = {}
        self._activation_generations: dict[str, int] = {}
        self._instances: dict[tuple[str, int], tuple[ActivationRef, str]] = {}
        self._capabilities: dict[str, _CapabilityEntry] = {}
        self._objects: dict[tuple[str, int, str], _ObjectEntry] = {}
        self._activities: dict[tuple[str, str, str], _ActivityEntry] = {}
        self._usages: dict[str, UsageRecord] = {}
        self._usage_seq = 0
        self._usage_object: dict[str, ObjectRef] = {}  # handover linkage
        # 004 lifecycle + relationship state (all instance-scoped)
        self._published_revision = 0
        self._settlements: dict[str, tuple[str, ...]] = {}  # activation key -> notes
        self._cut_revision = 0
        self._retire_pending: dict[tuple[str, int], tuple[str, ...]] = {}
        # E5: source key@revision -> declared relation set (full replacement)
        self._relations: dict[tuple[str, str], tuple[PersistentReference, ...]] = {}
        self._relation_epoch = 0
        self._reservations: dict[str, ChangeReservation] = {}
        # wait graph: waiter activation key -> set of waited activation keys
        self._wait_edges: dict[tuple[str, int], set[tuple[str, int]]] = {}
        self._unclassified: dict[tuple[str, int], int] = {}  # delivery obligations per activation
        self._authorities: dict[AuthorityKey, _AuthorityEntry] = {}
        self._subscriptions: dict[str, _ObservationEntry] = {}
        self._subscription_seq = 0
        # T003-03: reuse the existing staged-batch registry for validation.
        self._registry = CoreRegistry()

    # -- identity -----------------------------------------------------------

    @property
    def environment_id(self) -> str:
        return self._id.value

    @property
    def contract_version(self) -> str:
        return CONTRACT_VERSION

    @property
    def registry_snapshot(self) -> CoreRegistrySnapshot:
        return self._registry.snapshot()

    def _check_open(self) -> None:
        if self._closed:
            raise EnvironmentClosedError(f"environment {self.environment_id} is closed")

    def _check_environment(self, ref_environment: str) -> None:
        if ref_environment != self.environment_id:
            raise IdentityMismatchError(
                f"ref belongs to environment {ref_environment!r}, not {self.environment_id!r}"
            )

    # -- installation & enablement (T003-04) --------------------------------

    def install(self, record: InstallationRecord) -> None:
        """Register a discovered installation. Installed is NOT enabled."""
        self._check_open()
        if not isinstance(record, InstallationRecord):
            raise TypeError("install requires an InstallationRecord")
        if record.installation_id in self._installations:
            raise RegistrationConflictError(
                f"installation {record.installation_id} already registered"
            )
        self._installations[record.installation_id] = record

    def enable(self, installation_id: str) -> None:
        self._check_open()
        if installation_id not in self._installations:
            raise EnvironmentError(f"cannot enable unknown installation {installation_id!r}")
        self._enabled.add(installation_id)

    def disable(self, installation_id: str) -> None:
        self._check_open()
        self._enabled.discard(installation_id)

    @property
    def installed(self) -> tuple[str, ...]:
        return tuple(sorted(self._installations))

    @property
    def enabled(self) -> tuple[str, ...]:
        return tuple(sorted(self._enabled))

    # -- activation (E1 activate) -------------------------------------------

    def activate(
        self, plugin_id: str, contributions: CoreContributionSet | None = None, *, principal: str = "local"
    ) -> ActivationReceipt:
        """One transaction: validate, bump generation, publish — or nothing.

        T003-04: activation requires the installation to be EXPLICITLY
        enabled; the enablement set starts empty, so a fresh environment is
        read-only by construction (installed alone activates nothing).
        """
        return self.stage_activation(plugin_id, contributions).commit()

    def stage_activation(
        self, owner: str, contributions: CoreContributionSet | None = None
    ) -> _EnvironmentActivationStage:
        """Stage an activation using this Environment's single CoreRegistry.

        Installation and enablement are product metadata: this method never
        creates either implicitly. The returned handle publishes registry and
        Environment activation facts together at ``commit()``.
        """
        self._check_open()
        if owner not in self._enabled:
            raise AdmissionRefusedError(
                f"plugin {owner!r} is not enabled in this environment "
                f"(installed={self.installed}, enabled={self.enabled})"
            )
        payload = contributions if contributions is not None else CoreContributionSet()
        batch = self._registry.stage(owner, payload)
        return _EnvironmentActivationStage(self, owner, payload, batch)

    def _commit_activation_stage(
        self, plugin_id: str, payload: CoreContributionSet, batch: Any
    ) -> ActivationReceipt:
        self._check_open()
        self._registry.commit(batch)
        generation = self._activation_generations.get(plugin_id, 0) + 1
        self._activation_generations[plugin_id] = generation
        ref = ActivationRef(environment=self.environment_id, plugin_id=plugin_id, generation=generation)
        entry = _ActivationEntry(ref=ref, contributions=payload)
        entry.contribution_revision += 1
        self._activations[(plugin_id, generation)] = entry
        self._published_revision += 1  # one revision per committed batch (T004-02)
        # Capabilities contributed by this activation: static catalog ids from
        # the payload's contracts (pure query surface — no ExecutionPlan needed,
        # T003-03).
        for contract in payload.contracts:
            raw_id = str(getattr(contract, "contract_id"))
            surface_id, _, version = raw_id.rpartition("@")
            surface_id = surface_id.replace("@", ".")
            self._capabilities[surface_id] = _CapabilityEntry(
                surface=SurfaceRef(
                    environment=self.environment_id,
                    surface_id=surface_id,
                    contract_version=version or "1",
                    owner=ref,
                ),
                owner_activation=ref,
                operation_kinds=("read",),
            )
        return ActivationReceipt(
            activation=ref,
            published_contribution_revision=f"cr-{entry.contribution_revision}",
        )

    def _activation_entry(self, ref: ActivationRef) -> _ActivationEntry:
        self._check_environment(ref.environment)
        entry = self._activations.get((ref.plugin_id, ref.generation))
        if entry is None or entry.ref != ref:
            raise IdentityMismatchError(f"unknown activation {ref!r}")
        return entry

    # -- instances & objects (E1 instantiate/use/release) --------------------

    def instantiate(
        self,
        surface_id: str,
        request: RequestKey,
        *,
        instance_id: str,
        object_id: str | None = None,
    ) -> CreationReceipt:
        """Creation attempt first; Object/Usage handed over in one step (V3-1)."""
        self._check_open()
        self._check_environment(request.environment_namespace)
        cap = self._admit_capability(surface_id)
        key = (request.environment_namespace, request.principal_scope, request.request_id)
        existing = self._activities.get(key)
        if existing is not None:
            # same key replays the original creation — never a second instance;
            # same key with different creation parameters is a spent-key conflict
            if existing.binding_digest == f"{surface_id}:{instance_id}:{object_id}":
                return CreationReceipt(
                    activity=existing.request.request_id,
                    objects=(),
                    usages=(),
                    unknown_outputs_possible=existing.current.outcome == "unknown",
                )
            raise IdentityMismatchError(
                f"request key {key} already used with a different target (digest conflict)"
            )
        generation = self._activation_generations.get(cap.owner_activation.plugin_id, 1)
        instance_ref = ParticipantInstanceRef(
            environment=self.environment_id, instance_id=instance_id, generation=generation
        )
        self._instances[(instance_id, generation)] = (cap.owner_activation, surface_id)
        objects: tuple[ObjectRef, ...] = ()
        usages: tuple[UsageRef, ...] = ()
        if object_id is not None:
            obj_ref = ObjectRef(
                environment=self.environment_id,
                owner_instance_id=instance_id,
                owner_generation=generation,
                object_id=object_id,
            )
            self._objects[(instance_id, generation, object_id)] = _ObjectEntry(
                ref=obj_ref, owner_activation=cap.owner_activation
            )
            objects = (obj_ref,)
            usages = (self._new_usage(obj_ref, ("use",)),)
        receipt = ActivityReceipt(
            request=request, issued_revision="rev-1", delivery="acknowledged",
            safe_summary={"created": instance_id},
            sequences=SequenceTriple(source_revision=None, ingest_sequence=1,
                                     environment_knowledge_revision=1),
        )
        self._activities[key] = _ActivityEntry(
            request=request, receipt=receipt,
            current=CurrentFactView(outcome="concluded", revision=1),
            binding_digest=f"{surface_id}:{instance_id}:{object_id}",
        )
        return CreationReceipt(activity=request.request_id, objects=objects, usages=usages)

    def _new_usage(self, obj_ref: ObjectRef, rights: tuple[str, ...]) -> UsageRef:
        self._usage_seq += 1
        usage = UsageRef(environment=self.environment_id, usage_id=f"u-{self._usage_seq}")
        self._usages[usage.usage_id] = UsageRecord(usage=usage, rights=rights, state="active")
        self._usage_object[usage.usage_id] = obj_ref
        return usage

    def _object_entry(self, ref: ObjectRef) -> _ObjectEntry:
        self._check_environment(ref.environment)
        entry = self._objects.get(
            (ref.owner_instance_id, ref.owner_generation, ref.object_id)
        )
        # A-01: full identity or nothing — never a partial match by object id.
        if entry is None or entry.ref != ref:
            raise IdentityMismatchError(f"object ref does not match any full identity: {ref!r}")
        return entry

    def use(self, ref: ObjectRef, purpose: str) -> UsageRecord:
        self._check_open()
        entry = self._object_entry(ref)
        if entry.historical or entry.state != "available":
            raise AdmissionRefusedError(
                f"object {ref.object_id} is {entry.state}{' (historical)' if entry.historical else ''}; use refused"
            )
        usage = self._new_usage(ref, ("use", purpose))
        return self._usages[usage.usage_id]

    def release(self, usage: UsageRef, evidence: Mapping[str, str] | None = None) -> UsageRecord:
        self._check_open()
        self._check_environment(usage.environment)
        record = self._usages.get(usage.usage_id)
        if record is None or record.usage != usage:
            raise IdentityMismatchError(f"unknown usage {usage!r}")
        if record.state != "active":
            return record  # idempotent release
        released = UsageRecord(usage=usage, rights=record.rights, state="released")
        self._usages[usage.usage_id] = released
        return released

    # -- binding (E1 bind) ----------------------------------------------------

    def _admit_capability(self, surface_id: str) -> _CapabilityEntry:
        cap = self._capabilities.get(surface_id)
        if cap is None:
            raise AdmissionRefusedError(f"capability {surface_id!r} unknown in this environment")
        owner_state = self._activations[
            (cap.owner_activation.plugin_id, cap.owner_activation.generation)
        ].state
        if owner_state in ("draining", "retired") or cap.historical:
            raise AdmissionRefusedError(
                f"capability {surface_id!r} is {owner_state}: new admissions are cut"
            )
        return cap

    def bind(self, surface_id: str, expected_contract_version: str | None = None) -> BindingSnapshot:
        self._check_open()
        cap = self._admit_capability(surface_id)
        if expected_contract_version is not None and cap.surface.contract_version != expected_contract_version:
            raise IdentityMismatchError(
                f"capability {surface_id} is at {cap.surface.contract_version}, "
                f"not the expected {expected_contract_version}"
            )
        return BindingSnapshot(
            environment=self.environment_id,
            logical_surface=surface_id,
            provider_activation=cap.owner_activation,
            transport_contract="in-process",
            environment_context_revision=f"cr-{cap.owner_activation.generation}",
        )

    # -- invoke & query (E1 invoke/query; C2 request-key discipline) ---------

    def check_invocation(
        self,
        surface_id: str,
        *,
        guarantee: GuaranteeLevel = GuaranteeLevel.RAW,
        principal: str = "local",
        effect: bool = True,
    ) -> InvocationPreflight:
        """Read-only preflight for a possible invoke; it never spends a key.

        This is useful to fail closed before a caller writes its own durable
        submission intent. It checks the current lifecycle capability, effect
        policy, and (for RELIABLE) the same protected-fingerprint metadata and
        atomic namespaced dispatch-claim primitives required by ``invoke``.
        The result is informational only: ``invoke`` repeats these admission
        checks under the same lifecycle lock and atomically claims the request
        key immediately before dispatch.
        """
        if not isinstance(guarantee, GuaranteeLevel):
            raise TypeError("guarantee must be a GuaranteeLevel")
        if not isinstance(effect, bool):
            raise TypeError("effect must be a bool")

        with self._admission_lock:
            self._check_open()
            self._admit_capability(surface_id)

            if effect:
                if self._policy is None:
                    raise AdmissionRefusedError(
                        f"policy is unavailable for effectful invoke on {surface_id} for {principal}"
                    )
                if not self._policy.admit_invoke(principal, surface_id, guarantee.value):
                    raise AdmissionRefusedError(
                        f"policy refused invoke on {surface_id} for {principal}"
                    )

            required_store_methods = ("claim_dispatch", "read_request", "record_dispatch_result")
            backend_durable = self._store is not None and all(
                callable(getattr(self._store, name, None)) for name in required_store_methods
            )
            descriptor: FingerprintDescriptor | None = None
            if guarantee is GuaranteeLevel.RELIABLE:
                describe = getattr(self._fingerprint_port, "describe", None)
                fingerprint = getattr(self._fingerprint_port, "fingerprint", None)
                if not backend_durable or not callable(describe) or not callable(fingerprint):
                    raise GuaranteeUnavailableError(
                        "reliable invocation requires protected fingerprint and atomic namespaced "
                        "dispatch-claim/read capabilities; refused before dispatch "
                        "(frozen StorePort has no safe fallback)"
                    )
                try:
                    descriptor = describe()
                except Exception as exc:
                    raise GuaranteeUnavailableError(
                        "reliable invocation protected-fingerprint metadata is unavailable"
                    ) from exc
                if not isinstance(descriptor, FingerprintDescriptor):
                    raise GuaranteeUnavailableError(
                        "reliable invocation protected-fingerprint metadata is invalid"
                    )

            return InvocationPreflight(
                environment_id=self.environment_id,
                surface_id=surface_id,
                guarantee=guarantee,
                effect=effect,
                backend_durable=backend_durable,
                fingerprint_descriptor=descriptor,
            )

    def invoke(
        self,
        surface_id: str,
        request: RequestKey,
        *,
        guarantee: GuaranteeLevel = GuaranteeLevel.RAW,
        input_digest: str = "",
        principal: str = "local",
        handler: Any = None,
    ) -> tuple[ActivityReceipt, CurrentFactView]:
        """Admission → request-key dedup → guarantee check → dispatch.

        G003-1 counterexample held by construction: a RELIABLE invocation
        without the fingerprint port or store is refused BEFORE any dispatch;
        RAW keeps working. Same key + same digest replays the original
        receipt; same key + different digest is a conflict, never a re-issue.
        """
        key = (request.environment_namespace, request.principal_scope, request.request_id)
        unknown_current = CurrentFactView(outcome="unknown", revision=0)
        with self._admission_lock:
            self._check_open()
            self._check_environment(request.environment_namespace)
            existing = self._activities.get(key)
            if existing is not None:
                if existing.binding_digest == input_digest:
                    return existing.receipt, existing.current
                if existing.binding_digest == "" and guarantee is GuaranteeLevel.RELIABLE:
                    reader = getattr(self._store, "read_request", None)
                    if (self._fingerprint_port is not None and callable(reader)
                            and callable(getattr(self._store, "claim_dispatch", None))):
                        expected = self._fingerprint_port.fingerprint(request, "", input_digest)
                        durable = reader(request)
                        if durable is not None and durable.get("digest") == expected:
                            existing.binding_digest = input_digest
                            return existing.receipt, existing.current
                raise IdentityMismatchError(
                    f"request key {key} is spent with a different input digest (comparison conflict)"
                )

            if guarantee is GuaranteeLevel.RELIABLE:
                # The frozen StorePort intentionally has no dispatch-claim or
                # namespaced-read methods. Reliable effects require these additive
                # concrete capabilities; never reinterpret reserve_request's
                # replay answer as permission to call a handler again.
                required_store_methods = ("claim_dispatch", "read_request", "record_dispatch_result")
                if (self._store is None or self._fingerprint_port is None
                        or any(not callable(getattr(self._store, name, None))
                               for name in required_store_methods)):
                    raise GuaranteeUnavailableError(
                        "reliable invocation requires protected fingerprint and atomic namespaced "
                        "dispatch-claim/read capabilities; refused before dispatch "
                        "(frozen StorePort has no safe fallback)"
                    )
                if handler is None or not callable(handler):
                    raise GuaranteeUnavailableError(
                        "reliable invocation requires an explicit dispatch handler; refused before dispatch"
                    )
            elif handler is not None and not callable(handler):
                raise TypeError("invoke handler must be callable")

            # Policy and live capability admission are serialized with drain:
            # no cut can land between this admission and the durable claim.
            if handler is not None and self._policy is None:
                raise AdmissionRefusedError(
                    f"policy is unavailable for effectful invoke on {surface_id} for {principal}"
                )
            if self._policy is not None and not self._policy.admit_invoke(
                principal, surface_id, guarantee.value
            ):
                raise AdmissionRefusedError(f"policy refused invoke on {surface_id} for {principal}")
            self._admit_capability(surface_id)

            if guarantee is GuaranteeLevel.RELIABLE:
                self._fingerprint_port.describe()
                mac = self._fingerprint_port.fingerprint(request, "", input_digest)
                claimed = self._store.claim_dispatch(request, mac)
                if not claimed:
                    durable = self._store.read_request(request)
                    if durable is None:
                        raise GuaranteeUnavailableError(
                            "dispatch claim exists but its namespaced read is unavailable; outcome unknown"
                        )
                    receipt, current = self._activity_from_durable(request, durable)
                    self._activities[key] = _ActivityEntry(
                        request=request, receipt=receipt, current=current, binding_digest=input_digest
                    )
                    return receipt, current

            revision = 1
            pending_receipt = ActivityReceipt(
                request=request, issued_revision=f"rev-{revision}", delivery="issue_possible",
                safe_summary={"surface": surface_id},
                sequences=SequenceTriple(
                    source_revision=None, ingest_sequence=len(self._activities) + 1,
                    environment_knowledge_revision=revision,
                ),
            )
            # This in-memory reservation gives RAW the same single-process
            # same-key discipline without claiming restart consistency. The
            # external callback below runs after this lock is released.
            self._activities[key] = _ActivityEntry(
                request=request, receipt=pending_receipt, current=unknown_current,
                binding_digest=input_digest,
            )

        try:
            if handler is not None:
                handler()
        except BaseException:
            unknown_receipt = ActivityReceipt(
                request=request, issued_revision=pending_receipt.issued_revision,
                delivery="unknown", safe_summary=pending_receipt.safe_summary,
                sequences=pending_receipt.sequences,
            )
            try:
                if guarantee is GuaranteeLevel.RELIABLE:
                    self._store.record_dispatch_result(
                        request, self._receipt_mapping(unknown_receipt),
                        self._current_mapping(unknown_current),
                    )
            finally:
                with self._admission_lock:
                    self._activities[key] = _ActivityEntry(
                        request=request, receipt=unknown_receipt, current=unknown_current,
                        binding_digest=input_digest,
                    )
            raise

        receipt = ActivityReceipt(
            request=request, issued_revision=f"rev-{revision}", delivery="acknowledged",
            safe_summary={"surface": surface_id},
            sequences=SequenceTriple(
                source_revision=None, ingest_sequence=len(self._activities),
                environment_knowledge_revision=revision,
            ),
        )
        current = CurrentFactView(outcome="concluded", revision=revision)
        if guarantee is GuaranteeLevel.RELIABLE:
            recorded = self._store.record_dispatch_result(
                request, self._receipt_mapping(receipt), self._current_mapping(current)
            )
            if not recorded:
                receipt = ActivityReceipt(
                    request=request, issued_revision=f"rev-{revision}", delivery="unknown",
                    safe_summary={"surface": surface_id, "result-persisted": False},
                    sequences=receipt.sequences,
                )
                current = unknown_current
        with self._admission_lock:
            self._activities[key] = _ActivityEntry(
                request=request, receipt=receipt, current=current, binding_digest=input_digest
            )
        return receipt, current

    @staticmethod
    def _receipt_mapping(receipt: ActivityReceipt) -> dict[str, Any]:
        sequence = receipt.sequences
        return {
            "delivery": receipt.delivery,
            "issued_revision": receipt.issued_revision,
            "safe_summary": dict(receipt.safe_summary),
            "sequences": ({
                "source_revision": sequence.source_revision,
                "ingest_sequence": sequence.ingest_sequence,
                "environment_knowledge_revision": sequence.environment_knowledge_revision,
            } if sequence is not None else None),
        }

    @staticmethod
    def _current_mapping(current: CurrentFactView) -> dict[str, Any]:
        return {
            "outcome": current.outcome,
            "revision": current.revision,
            "conflicts": list(current.conflicts),
            "obligations": list(current.obligations),
        }

    @staticmethod
    def _activity_from_durable(request: RequestKey, row: Mapping[str, Any]):
        """Reconstitute only frozen DTO data returned for the exact RequestKey."""
        receipt_data = row.get("receipt") or {}
        current_data = row.get("current") or {}
        legacy = row.get("state") == "legacy"
        delivery = "unknown" if legacy else receipt_data.get("delivery", "unknown")
        if delivery == "issue_possible":
            delivery = "unknown"
        sequence_data = receipt_data.get("sequences")
        sequences = SequenceTriple(**sequence_data) if isinstance(sequence_data, Mapping) else None
        if legacy:
            sequences = None
        receipt = ActivityReceipt(
            request=request,
            issued_revision=receipt_data.get("issued_revision", "rev-0"),
            delivery=delivery,
            safe_summary=({"recovery": "legacy-spent-unknown"} if legacy else
                          receipt_data.get("safe_summary", {"recovery": "unknown"})),
            sequences=sequences,
        )
        outcome = "unknown" if legacy else current_data.get("outcome", "unknown")
        if outcome not in {"pending", "running", "unknown", "concluded", "disputed"}:
            outcome = "unknown"
        current = CurrentFactView(
            outcome=outcome,
            revision=current_data.get("revision", 0),
            conflicts=tuple(current_data.get("conflicts", ())),
            obligations=tuple(current_data.get("obligations", ())),
        )
        return receipt, current

    @_admission_locked
    def query(self, request: RequestKey) -> tuple[ActivityReceipt, CurrentFactView] | None:
        """Read-side query by request identity (separate from invoke rights)."""
        self._check_open()
        self._check_environment(request.environment_namespace)
        entry = self._activities.get(
            (request.environment_namespace, request.principal_scope, request.request_id)
        )
        if entry is not None:
            return entry.receipt, entry.current
        reader = getattr(self._store, "read_request", None)
        if not callable(reader):
            return None
        durable = reader(request)
        if durable is None:
            return None
        receipt, current = self._activity_from_durable(request, durable)
        self._activities[(request.environment_namespace, request.principal_scope,
                          request.request_id)] = _ActivityEntry(
            request=request, receipt=receipt, current=current,
            # Query does not carry an input digest, so keep it unknown until a
            # later reliable invoke compares the protected fingerprint.
            binding_digest="",
        )
        return receipt, current

    def lookup(self, ref: ObjectRef, mode: str = "history-read") -> Mapping[str, Any]:
        """History-read is its own permission axis (V3-3): it never grants or
        requires invoke rights, and it works on historical refs."""
        if mode not in ("history-read",):
            raise EnvironmentError(f"unknown lookup mode {mode!r}")
        entry = self._object_entry(ref)
        return {
            "ref": entry.ref,
            "state": entry.state,
            "historical": entry.historical,
            "owner_activation": entry.owner_activation,
        }

    # -- lifecycle: drain / retire / closure (004, T004-03..05) ----------------

    def drain(self, activation: ActivationRef) -> "CutReceiptLike":
        """Atomically close new admissions for this activation.

        The linearization point is the single ``state`` flip below (this
        object is not thread-safe by design — callers serialize access, same
        rule as the rest of the in-memory indices). After the cut: activate
        of a NEW generation still works, but bind/use/invoke on THIS
        generation's capabilities and late ``instantiate`` are refused.
        """
        self._sweep_expired_observations()
        with self._admission_lock:
            self._check_open()
            entry = self._activation_entry(activation)
            if entry.state == "retired":
                raise AdmissionRefusedError("cannot drain a retired activation")
            entry.state = "draining"
            self._cut_revision += 1
            blockers = self._blockers(activation)
            return CutReceiptLike(
                activation=activation,
                admission_cut_revision=f"cut-{self._cut_revision}",
                blockers=blockers,
            )

    def _sweep_expired_observations(self) -> None:
        """Expire observer leases without calling a source under the core lock."""
        detaches: list[tuple[_ObservationEntry, Any]] = []
        now = time.monotonic()
        with self._observation_changed:
            for entry in self._subscriptions.values():
                if not entry.released and now >= entry.expires_at:
                    detach = self._request_observation_release_locked(entry)
                    if callable(detach):
                        detaches.append((entry, detach))
        for entry, detach in detaches:
            try:
                self._attempt_observation_detach(entry, detach)
            except ObservationReleasePendingError:
                # The associated entry remains a blocker and the same detach
                # callback can be retried by the owning release path.
                continue

    def _blockers(self, activation: ActivationRef) -> tuple[str, ...]:
        blockers: list[str] = []
        for (instance, generation), (owner, _surface) in self._instances.items():
            if owner == activation:
                obj_entry = next(
                    (o for (i, g, oid), o in self._objects.items()
                     if i == instance and g == generation),
                    None,
                )
                if obj_entry is not None and obj_entry.state == "unknown":
                    # unknown responsibility blocks retirement and is never deleted
                    blockers.append(f"object-unknown:{instance}")
        retiring_objects = {
            (i, g) for (i, g), (owner, _s) in self._instances.items() if owner == activation
        }
        for usage in self._usages.values():
            if usage.state != "active":
                continue
            linked = self._usage_object.get(usage.usage.usage_id)
            settles_at_close = linked is not None and (
                (linked.owner_instance_id, linked.owner_generation) in retiring_objects
            )
            if not settles_at_close:  # handover usages of own objects settle at close
                blockers.append(f"active-usage:{usage.usage.usage_id}")
        pending = self._unclassified.get((activation.plugin_id, activation.generation), 0)
        if pending:
            blockers.append(f"unclassified-deliveries:{pending}")
        for waiter, targets in self._wait_edges.items():
            if (activation.plugin_id, activation.generation) in targets:
                blockers.append(f"waited-by:{waiter[0]}@{waiter[1]}")
        for sub in self._subscriptions.values():
            if not sub.released and sub.binding.provider_activation == activation:
                if sub.attachment_unknown:
                    blockers.append(f"observation-attach-unknown:{sub.ref.subscription_id}")
                elif sub.detach_pending or sub.release_requested:
                    blockers.append(f"observation-detach-pending:{sub.ref.subscription_id}")
                else:
                    blockers.append(f"active-subscription:{sub.ref.subscription_id}")
        return tuple(blockers)

    @_admission_locked
    def retire(
        self, activation: ActivationRef, closure_evidence: Mapping[str, str] | None = None
    ) -> tuple[str, tuple[str, ...]]:
        """Retire per M05/D5: owned work needs scope-exit evidence; borrowed
        only releases; static keeps content; unknown blocks, never deletes.

        Returns ``(state, blockers)`` where state is ``retired`` or
        ``retire-pending``.
        """
        self._check_open()
        entry = self._activation_entry(activation)
        if entry.state != "draining":
            raise AdmissionRefusedError("retire requires a drain cut first (closure ordering)")
        blockers = list(self._blockers(activation))
        # owned objects demand exit evidence; borrowed/static objects do not
        for (instance, generation), (owner, _surface) in self._instances.items():
            if owner != activation:
                continue
            obj_entry = next(
                (o for (i, g, oid), o in self._objects.items() if i == instance and g == generation),
                None,
            )
            if obj_entry is None:
                continue
            if obj_entry.management == "owned" and not closure_evidence:
                blockers.append(f"owned-exit-evidence-missing:{instance}")
        if blockers:
            self._retire_pending[(activation.plugin_id, activation.generation)] = tuple(blockers)
            return "retire-pending", tuple(blockers)
        self._finish_retire(activation)
        return "retired", ()

    def retire_activation(
        self, activation: ActivationRef,
        closure_evidence: Mapping[str, str] | None = None,
    ) -> tuple[str, tuple[str, ...]]:
        """Safely retire a committed activation through the normal drain gate.

        This is the committed-stage cleanup path. It never unregisters a live
        owner directly; active usages, owned objects without exit evidence and
        other lifecycle blockers leave the activation ``retire-pending``.
        """
        self._sweep_expired_observations()
        with self._admission_lock:
            self._check_open()
            entry = self._activation_entry(activation)
            if entry.state == "retired":
                return "retired", ()
            if entry.state == "active":
                self.drain(activation)
            return self.retire(activation, closure_evidence)

    def _finish_retire(self, activation: ActivationRef) -> None:
        retiring_keys = {
            (i, g) for (i, g), (owner, _s) in self._instances.items() if owner == activation
        }
        # static projections lose the relation, never the content; published
        # persistent references survive retirement (E5)
        for cap in self._capabilities.values():
            if cap.owner_activation == activation:
                cap.historical = True
        for obj in self._objects.values():
            if obj.owner_activation == activation:
                obj.historical = True
                if obj.management == "static-projection":
                    obj.state = "released"  # relation closed, content untouched
                elif obj.management == "borrowed":
                    obj.state = "released"  # our usage released; nothing killed
        self._activations[(activation.plugin_id, activation.generation)].state = "retired"
        for key, authority in list(self._authorities.items()):
            if authority.activation == activation:
                self._authorities.pop(key, None)
        self._wait_edges.pop((activation.plugin_id, activation.generation), None)
        # settle the handover usages of this activation's own objects
        for usage_id, linked in list(self._usage_object.items()):
            if (linked.owner_instance_id, linked.owner_generation) in retiring_keys and                     self._usages.get(usage_id) is not None and self._usages[usage_id].state == "active":
                u = self._usages[usage_id]
                self._usages[usage_id] = UsageRecord(usage=u.usage, rights=u.rights, state="released")
        # release the owner's registry claims so a NEW generation may
        # re-contribute the same contracts (the registry is owner-keyed)
        try:
            self._registry.unregister(activation.plugin_id)
        except Exception:
            pass  # already unregistered — nothing to release

    def mark_object_management(self, ref: ObjectRef, management: str) -> None:
        if management not in ("owned", "borrowed", "static-projection"):
            raise EnvironmentError(f"unknown management kind {management!r}")
        entry = self._object_entry(ref)
        entry.management = management

    def register_settlement(self, activation_key_plugin: str, generation: int, note: str) -> None:
        """Failed activation external objects land here — no 'no side
        effects' claim (T004-02)."""
        self._settlements.setdefault((activation_key_plugin, generation), ())
        self._settlements[(activation_key_plugin, generation)] += (note,)

    def settlements(self, plugin_id: str, generation: int) -> tuple[str, ...]:
        return self._settlements.get((plugin_id, generation), ())

    # -- wait graph (T004-06) --------------------------------------------------

    def register_wait(self, waiter: ActivationRef, target: ActivationRef) -> None:
        """Register a wait edge; refuse registrations that close a cycle.

        ``async`` alone proves nothing — the edge set is checked regardless of
        whether the callback already returned (V3-9 counterexample).
        """
        self._check_open()
        self._activation_entry(waiter)
        self._activation_entry(target)
        wkey = (waiter.plugin_id, waiter.generation)
        tkey = (target.plugin_id, target.generation)
        if wkey == tkey:
            raise WouldDeadlockError("an activation cannot wait on itself")
        # cycle check: can target (transitively) reach waiter already?
        reachable: set[tuple[str, int]] = set()
        stack = [tkey]
        while stack:
            node = stack.pop()
            if node == wkey:
                raise WouldDeadlockError(
                    f"wait {wkey} -> {tkey} would close a cycle in the wait graph"
                )
            if node in reachable:
                continue
            reachable.add(node)
            stack.extend(self._wait_edges.get(node, ()))
        self._wait_edges.setdefault(wkey, set()).add(tkey)

    def clear_wait(self, waiter: ActivationRef, target: ActivationRef) -> None:
        self._wait_edges.get((waiter.plugin_id, waiter.generation), set()).discard(
            (target.plugin_id, target.generation)
        )

    def wait_edges(self) -> Mapping[tuple[str, int], frozenset[tuple[str, int]]]:
        return {k: frozenset(v) for k, v in self._wait_edges.items()}

    def note_unclassified_delivery(self, activation: ActivationRef, count: int = 1) -> None:
        self._activation_entry(activation)
        key = (activation.plugin_id, activation.generation)
        self._unclassified[key] = self._unclassified.get(key, 0) + count

    def resolve_unclassified(self, activation: ActivationRef) -> None:
        self._unclassified.pop((activation.plugin_id, activation.generation), None)

    # -- E5 persistent relationships (T004-08) ---------------------------------

    def publish_reference_set(
        self,
        source_key: CanonicalFactTarget,
        source_revision: str,
        relations: tuple[PersistentReference, ...],
        operation_id: str,
    ) -> None:
        """Full replacement of the declared set for one source version.

        Idempotent per (source, revision, operation); unknown never re-runs
        the domain write. A conflicting open change reservation on a target
        refuses the publish — new relations and destructive changes never
        both pass the same gate.
        """
        self._check_open()
        for rel in relations:
            if rel.source_key != source_key or rel.source_revision != source_revision:
                raise IdentityMismatchError("relation source does not match the publishing key")
            for res in self._reservations.values():
                if res.target_key == rel.target_key and res.change_kind in ("delete", "rewrite"):
                    raise AdmissionRefusedError(
                        f"target {rel.target_key.stable_entity_id} holds a destructive "
                        f"change reservation {res.reservation_id}"
                    )
        key = (source_key.stable_entity_id, source_revision)
        existing = self._relations.get(key)
        if existing is not None and tuple(r.relation_id for r in existing) == tuple(
            r.relation_id for r in relations
        ):
            return  # idempotent republication of the same set
        self._relation_epoch += 1
        self._relations[key] = tuple(
            PersistentReference(
                relation_id=r.relation_id, source_key=r.source_key, source_revision=r.source_revision,
                target_key=r.target_key, revision_selector=r.revision_selector,
                declaring_owner_domain=r.declaring_owner_domain,
                policy_contract_id=r.policy_contract_id,
                policy_contract_version=r.policy_contract_version,
                operation_id=operation_id, source_commit_evidence=r.source_commit_evidence,
                status=ReferenceStatus.PUBLISHED, coverage_epoch=self._relation_epoch,
            )
            for r in relations
        )

    def inspect_incoming(
        self, target_key: CanonicalFactTarget, change_kind: str = "archive", coverage_epoch: int = 0
    ) -> Mapping[str, Any]:
        """Declared incoming relations + coverage verdict. Deactivating the
        declaring plugin never erases published relations; a coverage gap is
        reported as unknown, never as 'no references'."""
        incoming = tuple(
            r for relations in self._relations.values() for r in relations
            if r.target_key == target_key and r.status is ReferenceStatus.PUBLISHED
        )
        coverage = "known" if incoming else "unknown"
        blocking = change_kind in ("delete", "rewrite") and bool(incoming)
        return {
            "target": target_key,
            "relations": incoming,
            "coverage": coverage,
            "blocking-destructive-change": blocking,
        }

    # -- E3 single-writer authority and bounded observation -----------------

    @_admission_locked
    def register_authority(
        self, registration: AuthorityRegistration, activation: ActivationRef
    ) -> AuthorityRegistration:
        """Claim one canonical fact writer slot under this Environment.

        The declaration is identity metadata only; fact schema, value and
        revision remain owned by the supplied source adapter. Exact same-owner
        metadata replay is idempotent. A second writer for the same semantic
        authority and canonical target fails closed.
        """
        self._check_open()
        if not isinstance(registration, AuthorityRegistration):
            raise TypeError("registration must be an AuthorityRegistration")
        owner = self._activation_entry(activation)
        if owner.state != "active":
            raise AdmissionRefusedError("authority registration requires an active owner activation")
        existing = self._authorities.get(registration.key)
        if existing is not None:
            if existing.activation == activation and existing.registration == registration:
                return existing.registration
            raise AuthorityConflictError(
                f"authority {registration.key.authority_kind!r} for "
                f"{registration.key.target.stable_entity_id!r} already has a writer"
            )
        stable_registration = AuthorityRegistration(
            key=registration.key,
            declaring_owner_domain=registration.declaring_owner_domain,
            target_schema_id=registration.target_schema_id,
            schema_major=registration.schema_major,
            normalized_from=tuple(registration.normalized_from),
            alias_bindings=MappingProxyType(dict(registration.alias_bindings)),
        )
        self._authorities[registration.key] = _AuthorityEntry(stable_registration, activation)
        self._published_revision += 1
        return stable_registration

    @staticmethod
    def _observation_target_name(target: CanonicalFactTarget) -> str:
        return f"{target.realm}:{target.identity_namespace}:{target.stable_entity_id}"

    def _check_observation_admission(
        self, binding: BindingSnapshot, target: CanonicalFactTarget, principal: str
    ) -> tuple[_CapabilityEntry, _AuthorityEntry]:
        self._check_environment(binding.environment)
        cap = self._admit_capability(binding.logical_surface)
        if cap.owner_activation != binding.provider_activation:
            raise IdentityMismatchError("binding provider activation is stale or does not match its surface")
        # Authority kind is domain-owned metadata. Core must not guess a kind;
        # the target/provider pair has to identify one registered writer.
        matches = [
            authority for key, authority in self._authorities.items()
            if key.target == target and authority.activation == binding.provider_activation
        ]
        if len(matches) != 1:
            raise AdmissionRefusedError(
                "canonical target and provider do not identify one registered authority"
            )
        authority = matches[0]
        if authority.activation != binding.provider_activation:
            raise IdentityMismatchError("binding provider does not own the requested canonical target")
        if self._policy is None:
            raise AdmissionRefusedError("policy is unavailable for protected observation")
        if not self._policy.admit_object_access(
            principal, self._observation_target_name(target), "observe"
        ):
            raise AdmissionRefusedError(f"policy refused observation of {target.stable_entity_id}")
        return cap, authority

    def _observation_usage(self) -> UsageRef:
        self._usage_seq += 1
        usage = UsageRef(environment=self.environment_id, usage_id=f"u-{self._usage_seq}")
        self._usages[usage.usage_id] = UsageRecord(usage=usage, rights=("observe",), state="active")
        return usage

    def _observation_source_identity(self, entry: _ObservationEntry) -> Mapping[str, Any]:
        activation = entry.binding.provider_activation
        return MappingProxyType({
            "environment": self.environment_id,
            "providerActivation": f"{activation.plugin_id}@{activation.generation}",
            "generation": activation.generation,
        })

    def _observation_event(
        self, subscription_id: str, kind: str, revision: str | None,
        *, value: Any = None, patch: Any = None, reason: str | None = None,
    ) -> None:
        with self._observation_changed:
            entry = self._subscriptions.get(subscription_id)
            if (entry is None or entry.released or entry.release_requested
                    or entry.revoked or entry.gap_reason is not None):
                return
            if kind not in {"snapshot", "delta", "gap", "revoked"}:
                entry.gap_reason = "invalid-source-frame"
                entry.queue = []
                self._observation_changed.notify_all()
                return
            if kind in {"snapshot", "delta"} and (not isinstance(revision, str) or not revision):
                entry.gap_reason = "invalid-source-revision"
                entry.queue = []
                self._observation_changed.notify_all()
                return
            if kind == "revoked":
                entry.revoked = True
                entry.queue = []
            if kind == "gap":
                entry.sequence += 1
                entry.cursor = f"obs:{subscription_id}:{entry.sequence}"
                frame = ObservationFrame(
                    kind="gap", revision=None, cursor=entry.cursor,
                    source=self._observation_source_identity(entry),
                    reason=reason or "source-gap",
                )
                assert entry.queue is not None
                if len(entry.queue) >= 64:
                    entry.gap_reason = "buffer-overflow"
                    entry.queue = []
                else:
                    entry.queue.append(frame)
            elif kind in {"snapshot", "delta"}:
                if kind == "snapshot":
                    entry.initial_snapshot_seen = True
                elif not entry.initial_snapshot_seen:
                    entry.invalid_initial_sequence = True
                if len(entry.queue or ()) >= 64:
                    entry.gap_reason = "buffer-overflow"
                    entry.queue = []
                else:
                    entry.sequence += 1
                    entry.cursor = f"obs:{subscription_id}:{entry.sequence}"
                    envelope = ObservationFrame(
                        kind=kind,
                        revision=revision,
                        cursor=entry.cursor,
                        source=MappingProxyType({
                            "environment": self.environment_id,
                            "providerActivation": (
                                f"{entry.binding.provider_activation.plugin_id}@"
                                f"{entry.binding.provider_activation.generation}"
                            ),
                            "generation": entry.binding.provider_activation.generation,
                        }),
                        value=deepcopy(value) if kind == "snapshot" else None,
                        patch=deepcopy(patch) if kind == "delta" else None,
                    )
                    assert entry.queue is not None
                    entry.queue.append(envelope)
            self._observation_changed.notify_all()

    def read_and_subscribe(
        self,
        binding: BindingSnapshot,
        target: CanonicalFactTarget,
        cursor: str | None,
        credits: int,
        *,
        source: Any,
        principal: str = "local",
        lease_seconds: float = 30.0,
    ) -> SubscriptionHandle:
        """Atomically admit a bounded observer and attach an owner source.

        ``source.attach(sink, cursor=cursor)`` must atomically emit either a
        full snapshot or an explicit gap followed by a new full snapshot, then
        return an idempotent detach callback. It owns domain revisioning; this
        Environment owns only source identity, admission, credit and lifecycle.
        The callback runs outside the lifecycle lock. A provisional observer
        is recorded first, so a concurrent drain sees it as a blocker.
        """
        if type(credits) is not int or credits < 0 or credits > 256:
            raise ValueError("credits must be an integer from 0 through 256")
        if not isinstance(target, CanonicalFactTarget):
            raise TypeError("target must be a CanonicalFactTarget")
        if not isinstance(principal, str) or not principal:
            raise ValueError("principal is required")
        if type(lease_seconds) not in (int, float) or lease_seconds <= 0 or lease_seconds > 300:
            raise ValueError("lease_seconds must be greater than 0 and at most 300")
        attach = getattr(source, "attach", None)
        if not callable(attach):
            raise TypeError("source must provide attach(sink, cursor=cursor)")

        with self._admission_lock:
            self._check_open()
            _cap, authority = self._check_observation_admission(binding, target, principal)
            self._subscription_seq += 1
            subscription_id = f"s-{self._subscription_seq}-{secrets.token_hex(6)}"
            ref = SubscriptionRef(environment=self.environment_id, subscription_id=subscription_id)
            entry = _ObservationEntry(
                ref=ref, binding=binding, target=target,
                registration=authority.registration, principal=principal,
                usage=self._observation_usage(), source=source,
                expires_at=time.monotonic() + float(lease_seconds),
                lease_seconds=float(lease_seconds), initial_cursor=cursor, queue=[],
            )
            self._subscriptions[subscription_id] = entry

        sink = _ObservationSink(self, subscription_id)
        try:
            detach = attach(sink, cursor=cursor)
            if not callable(detach):
                raise TypeError("source.attach must return a callable detach")
        except BaseException as exc:
            with self._observation_changed:
                current = self._subscriptions.get(subscription_id)
                if current is not None:
                    current.attach_in_progress = False
                    current.attachment_unknown = True
                    current.release_requested = True
                    current.queue = []
                    self._observation_changed.notify_all()
            raise ObservationAttachmentUnknownError(ref) from exc

        should_detach = False
        invalid_initial = False
        with self._observation_changed:
            current = self._subscriptions.get(subscription_id)
            if current is not None:
                current.attach_in_progress = False
                current.detach = detach
            if (current is not None and not current.released and not current.revoked
                    and (not current.initial_snapshot_seen or current.invalid_initial_sequence)):
                self._request_observation_release_locked(current)
                should_detach = True
                invalid_initial = True
            elif (current is None or current.released or current.release_requested
                  or time.monotonic() >= current.expires_at or self._closed):
                if current is not None and not current.released:
                    self._request_observation_release_locked(current)
                should_detach = True
            else:
                # A zero-credit open is never allowed to return an unbounded
                # initial payload. Caller observes an explicit resync gap.
                if credits == 0:
                    current.gap_reason = "zero-credit"
                    current.queue = []
        if should_detach:
            if current is not None:
                self._attempt_observation_detach(current, detach)
            else:
                detach()
            if invalid_initial:
                raise AdmissionRefusedError("source attach did not provide an atomic initial snapshot")
            raise AdmissionRefusedError("observation lease expired or was released during source attach")
        return SubscriptionHandle(self, ref, principal, target)

    def _subscription_entry(
        self, ref: SubscriptionRef, principal: str, target: CanonicalFactTarget
    ) -> _ObservationEntry:
        self._check_environment(ref.environment)
        entry = self._subscriptions.get(ref.subscription_id)
        if entry is None or entry.ref != ref:
            raise IdentityMismatchError("unknown subscription ref")
        if entry.principal != principal:
            raise IdentityMismatchError("subscription ref belongs to a different principal scope")
        if entry.target != target:
            raise IdentityMismatchError("subscription ref is bound to a different canonical target")
        return entry

    def _complete_observation_release_locked(self, entry: _ObservationEntry) -> None:
        entry.released = True
        entry.release_requested = True
        entry.detach_pending = False
        entry.attachment_unknown = False
        entry.queue = []
        entry.detach = None
        record = self._usages.get(entry.usage.usage_id)
        if record is not None and record.state == "active":
            self._usages[entry.usage.usage_id] = UsageRecord(
                usage=entry.usage, rights=record.rights, state="released"
            )
        self._observation_changed.notify_all()

    def _request_observation_release_locked(self, entry: _ObservationEntry) -> Any:
        if entry.released:
            return None
        entry.release_requested = True
        entry.queue = []
        self._observation_changed.notify_all()
        if entry.attach_in_progress or entry.attachment_unknown:
            return None
        if callable(entry.detach):
            return entry.detach
        self._complete_observation_release_locked(entry)
        return None

    def _attempt_observation_detach(self, entry: _ObservationEntry, detach: Any) -> None:
        """Run source cleanup outside the Environment lock; retain failures."""
        with self._observation_changed:
            if entry.released:
                return
            if entry.detach_in_progress:
                raise ObservationReleasePendingError(entry.ref, "observation detach is already in progress")
            entry.detach_in_progress = True
            entry.detach_pending = False
        try:
            detach()
        except BaseException as exc:
            with self._observation_changed:
                entry.release_requested = True
                entry.detach_pending = True
                entry.detach_in_progress = False
                entry.queue = []
                self._observation_changed.notify_all()
            raise ObservationReleasePendingError(entry.ref) from exc
        with self._observation_changed:
            entry.detach_in_progress = False
            self._complete_observation_release_locked(entry)

    def resolve_observation_attachment(
        self,
        ref: SubscriptionRef,
        *,
        principal: str,
        target: CanonicalFactTarget,
        confirmed_detached: bool,
    ) -> None:
        """Settle an attach-unknown obligation after source-side reconciliation.

        An attach exception never implies that no observer was created. Only
        explicit confirmation from the owning source adapter can release this
        blocker when no detach handle was returned.
        """
        if confirmed_detached is not True:
            raise AdmissionRefusedError(
                "attach-unknown settlement requires confirmed_detached=True"
            )
        with self._observation_changed:
            entry = self._subscription_entry(ref, principal, target)
            if not entry.attachment_unknown:
                if entry.released:
                    return
                raise AdmissionRefusedError("subscription has no attach-unknown obligation")
            entry.attach_in_progress = False
            entry.attachment_unknown = False
            self._complete_observation_release_locked(entry)

    def observe(
        self,
        ref: SubscriptionRef,
        cursor: str | None,
        credits: int,
        timeout_ms: int,
        *,
        principal: str,
        target: CanonicalFactTarget,
    ) -> ObservationBatch:
        """Pull at most ``credits`` frames; timeout is bounded to one second."""
        if type(credits) is not int or credits < 0 or credits > 256:
            raise ValueError("credits must be an integer from 0 through 256")
        if type(timeout_ms) is not int or timeout_ms < 0 or timeout_ms > 1000:
            raise ValueError("timeout_ms must be an integer from 0 through 1000")
        if not principal:
            raise ValueError("principal is required")
        with self._observation_changed:
            admitted = self._subscription_entry(ref, principal, target)
            if admitted.released:
                raise AdmissionRefusedError("subscription is released")
            if admitted.release_requested:
                if admitted.attachment_unknown:
                    raise ObservationAttachmentUnknownError(ref)
                raise ObservationReleasePendingError(ref)
            policy = self._policy
            allowed = policy is not None and policy.admit_object_access(
                principal, self._observation_target_name(target), "observe"
            )
            if not allowed:
                pending_detach = self._request_observation_release_locked(admitted)
            else:
                pending_detach = None
        if not allowed:
            if callable(pending_detach):
                self._attempt_observation_detach(admitted, pending_detach)
            if admitted.attachment_unknown:
                raise ObservationAttachmentUnknownError(ref)
            if admitted.release_requested and not admitted.released:
                raise ObservationReleasePendingError(ref, "policy revocation stopped observation")
            raise AdmissionRefusedError("policy refused or unavailable for protected observation")
        deadline = time.monotonic() + timeout_ms / 1000
        with self._observation_changed:
            entry = self._subscription_entry(ref, principal, target)
            if entry.released:
                raise AdmissionRefusedError("subscription is released")
            if entry.release_requested:
                raise ObservationReleasePendingError(ref)
            owner = self._activation_entry(entry.binding.provider_activation)
            authority = self._authorities.get(entry.registration.key)
            if owner.state == "retired" or authority is None or authority.activation != owner.ref:
                raise IdentityMismatchError("subscription provider generation is no longer authoritative")
            if time.monotonic() >= entry.expires_at:
                detach = self._request_observation_release_locked(entry)
                expired = True
            else:
                detach = None
                expired = False
            if (not expired and cursor is not None
                    and cursor not in (entry.acknowledged_cursor, entry.initial_cursor)):
                # A cursor from another subscription or a stale chain cannot
                # be used to claim continuity. Force a fresh read.
                entry.gap_reason = "cursor-mismatch"
                entry.queue = []
            if not expired and credits == 0:
                return ObservationBatch(
                    subscription_id=entry.ref.subscription_id,
                    frames=(ObservationFrame(
                        kind="gap", revision=None, cursor=entry.acknowledged_cursor or "",
                        source=self._observation_source_identity(entry),
                        reason="zero-credit",
                    ),),
                    cursor=entry.acknowledged_cursor,
                    resync_required=True,
                )
            while not expired and not entry.queue and entry.gap_reason is None and not entry.revoked:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._observation_changed.wait(remaining)
                if time.monotonic() >= entry.expires_at:
                    detach = self._request_observation_release_locked(entry)
                    expired = True
                    break
            if expired:
                batch = ObservationBatch(
                    subscription_id=entry.ref.subscription_id,
                    frames=(ObservationFrame(
                        kind="gap", revision=None, cursor=entry.acknowledged_cursor or "",
                        source=self._observation_source_identity(entry), reason="lease-expired",
                    ),), cursor=entry.acknowledged_cursor, resync_required=True,
                )
            elif entry.revoked:
                batch = ObservationBatch(
                    subscription_id=entry.ref.subscription_id,
                    frames=(ObservationFrame(
                        kind="revoked", revision=None, cursor=entry.acknowledged_cursor or "",
                        source=self._observation_source_identity(entry), reason="source-revoked",
                    ),), cursor=entry.acknowledged_cursor, resync_required=True,
                )
            elif entry.gap_reason is not None:
                batch = ObservationBatch(
                    subscription_id=entry.ref.subscription_id,
                    frames=(ObservationFrame(
                        kind="gap", revision=None, cursor=entry.acknowledged_cursor or "",
                        source=self._observation_source_identity(entry), reason=entry.gap_reason,
                    ),), cursor=entry.acknowledged_cursor, resync_required=True,
                )
            else:
                frames = tuple((entry.queue or [])[:credits])
                del (entry.queue or [])[:len(frames)]
                if frames:
                    entry.acknowledged_cursor = frames[-1].cursor
                batch = ObservationBatch(
                    subscription_id=entry.ref.subscription_id,
                    frames=frames, cursor=frames[-1].cursor if frames else entry.acknowledged_cursor,
                    resync_required=any(frame.kind == "gap" for frame in frames)
                    and not any(frame.kind == "snapshot" for frame in frames),
                )
                # A successful read, including an empty long-poll, is an
                # authenticated observer renewal; otherwise healthy idle
                # views expire despite active polling.
                entry.expires_at = time.monotonic() + entry.lease_seconds
        if callable(detach):
            self._attempt_observation_detach(entry, detach)
        return batch

    def unsubscribe(
        self, ref: SubscriptionRef, *, principal: str = "local",
        target: CanonicalFactTarget | None = None,
    ) -> None:
        """Idempotently release an observer lease and its source callback."""
        self._check_environment(ref.environment)
        with self._observation_changed:
            entry = self._subscriptions.get(ref.subscription_id)
            if entry is None:
                return
            if entry.ref != ref or entry.principal != principal:
                raise IdentityMismatchError("subscription ref identity or principal does not match")
            if target is not None and entry.target != target:
                raise IdentityMismatchError("subscription ref is bound to a different canonical target")
            detach = self._request_observation_release_locked(entry)
            if entry.attachment_unknown:
                raise ObservationAttachmentUnknownError(ref)
            if entry.attach_in_progress:
                raise ObservationReleasePendingError(ref, "source attachment is still in progress")
            if entry.released:
                return
        if callable(detach):
            self._attempt_observation_detach(entry, detach)

    def prepare_resource_change(
        self,
        target_key: CanonicalFactTarget,
        expected_revision: str,
        change_kind: str,
        operation_id: str,
    ) -> ChangeReservation:
        """One admission ticket per destructive change; serialized against
        new relations at the same gate (E5)."""
        self._check_open()
        if change_kind not in ("archive", "delete", "rewrite"):
            raise EnvironmentError(f"unknown change kind {change_kind!r}")
        for res in self._reservations.values():
            if res.target_key == target_key and res.reservation_id != operation_id:
                raise AdmissionRefusedError(
                    f"target already holds reservation {res.reservation_id}"
                )
        incoming = self.inspect_incoming(target_key, change_kind)
        if change_kind in ("delete", "rewrite") and incoming["relations"]:
            refused = tuple(r.relation_id for r in incoming["relations"])
            self._reservations[operation_id] = ChangeReservation(
                reservation_id=operation_id, target_key=target_key,
                expected_revision=expected_revision, change_kind=change_kind,
                operation_id=operation_id, refused_relations=refused,
            )
            raise AdmissionRefusedError(
                f"destructive change on {target_key.stable_entity_id} blocked by "
                f"published relations {refused} (coverage {incoming['coverage']})"
            )
        reservation = ChangeReservation(
            reservation_id=operation_id, target_key=target_key,
            expected_revision=expected_revision, change_kind=change_kind,
            operation_id=operation_id,
        )
        self._reservations[operation_id] = reservation
        return reservation

    def release_reservation(self, operation_id: str, *, executed: bool) -> None:
        """The ONLY release path for a reservation — UI close, TTL or process
        death never auto-releases (E5). ``executed`` records the outcome;
        a not-executed change keeps its reservation until evidence resolves it."""
        if executed:
            self._reservations.pop(operation_id, None)
        # not executed: the reservation stays until an explicit resolution

    # -- lifecycle stubs (004 implements the real gates) ----------------------

    @_admission_locked
    def mark_retired(self, activation: ActivationRef) -> None:
        """Historical transition used by 003 tests: retire makes capabilities
        and objects historical (read-only), it never deletes them."""
        entry = self._activation_entry(activation)
        entry.state = "retired"
        for cap in self._capabilities.values():
            if cap.owner_activation == activation:
                cap.historical = True
        for obj in self._objects.values():
            if obj.owner_activation == activation:
                obj.historical = True

    def close(self) -> None:
        """Close admission and request observer detaches without losing failures."""
        self._sweep_expired_observations()
        detaches: list[tuple[_ObservationEntry, Any]] = []
        unresolved: list[_ObservationEntry] = []
        with self._observation_changed:
            self._closed = True
            for entry in self._subscriptions.values():
                detach = self._request_observation_release_locked(entry)
                if callable(detach):
                    detaches.append((entry, detach))
                elif not entry.released:
                    unresolved.append(entry)
        first_error: ObservationReleasePendingError | None = None
        for entry, detach in detaches:
            try:
                self._attempt_observation_detach(entry, detach)
            except ObservationReleasePendingError as exc:
                first_error = first_error or exc
        if first_error is not None:
            raise first_error
        if unresolved:
            entry = unresolved[0]
            if entry.attachment_unknown:
                raise ObservationAttachmentUnknownError(entry.ref)
            raise ObservationReleasePendingError(entry.ref, "observation close is pending")


@dataclass(frozen=True)
class CutReceiptLike:
    """Drain result mirror of the frozen ``CutReceipt`` DTO shape."""

    activation: ActivationRef
    admission_cut_revision: str
    blockers: tuple[str, ...]
    closed_new_admission: bool = True
