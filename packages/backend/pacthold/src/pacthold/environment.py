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

Order scope: activate/instantiate/bind/invoke/use/release/query/lookup and
the neutral identity model. drain/retire/reply closures and subscription
delivery land in order 004; persistence in order 005.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ordessa_environment_api import (
    CONTRACT_VERSION,
    ActivationReceipt,
    ActivityReceipt,
    AdmissionRefusedError,
    BindingSnapshot,
    ChangeReservation,
    CreationReceipt,
    CurrentFactView,
    EnvironmentId,
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
    UsageRecord,
    UsageRef,
)
from ordessa_environment_api.errors import EnvironmentError
from ordessa_environment_api.guarantee import GuaranteeLevel
from ordessa_environment_api.identity import ActivationRef, ParticipantInstanceRef, SurfaceRef
from ordessa_environment_api.targets import CanonicalFactTarget

from .core.registration import (
    CoreContributionSet,
    CoreRegistry,
    CoreRegistrySnapshot,
    RegistrationConflictError,
)

__all__ = [
    "Environment",
    "EnvironmentClosedError",
    "InstallationRecord",
    "WouldDeadlockError",
]


class EnvironmentClosedError(EnvironmentError):
    code = "ENVIRONMENT_CLOSED"


class WouldDeadlockError(EnvironmentError):
    """A wait registration would close a cycle in the wait graph (V3-9)."""

    code = "WOULD_DEADLOCK"


@dataclass(frozen=True)
class InstallationRecord:
    """A discovered installation unit — being installed enables nothing."""

    installation_id: str
    manifest_digest: str
    declared_contracts: tuple[str, ...] = ()


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
        self._check_open()
        if plugin_id not in self._enabled:
            raise AdmissionRefusedError(
                f"plugin {plugin_id!r} is not enabled in this environment "
                f"(installed={self.installed}, enabled={self.enabled})"
            )
        payload = contributions if contributions is not None else CoreContributionSet()
        batch = self._registry.stage(plugin_id, payload)  # typed conflict → nothing published
        try:
            self._registry.commit(batch)
        except Exception:
            raise
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
        self._check_open()
        self._check_environment(request.environment_namespace)
        key = (request.environment_namespace, request.principal_scope, request.request_id)
        existing = self._activities.get(key)
        if existing is not None:
            if existing.binding_digest == input_digest:
                return existing.receipt, existing.current
            raise IdentityMismatchError(
                f"request key {key} is spent with a different input digest (comparison conflict)"
            )
        if guarantee is GuaranteeLevel.RELIABLE:
            if self._store is None or self._fingerprint_port is None:
                raise GuaranteeUnavailableError(
                    "reliable invocation requires StorePort and ProtectedFingerprintPort; "
                    "refused before dispatch (no silent downgrade, raw path unaffected)"
                )
            descriptor = self._fingerprint_port.describe()
            mac = self._fingerprint_port.fingerprint(request, "", input_digest)
            claimed = self._store.reserve_request(request, mac)
            if not claimed:
                raise IdentityMismatchError(f"store refused request key {key} (spent)")
        if self._policy is not None and not self._policy.admit_invoke(
            principal, surface_id, guarantee.value
        ):
            raise AdmissionRefusedError(f"policy refused invoke on {surface_id} for {principal}")
        cap = self._admit_capability(surface_id)
        revision = 1
        receipt = ActivityReceipt(
            request=request, issued_revision=f"rev-{revision}", delivery="acknowledged",
            safe_summary={"surface": surface_id},
            sequences=SequenceTriple(
                source_revision=None, ingest_sequence=len(self._activities) + 1,
                environment_knowledge_revision=revision,
            ),
        )
        current = CurrentFactView(outcome="concluded", revision=revision)
        self._activities[key] = _ActivityEntry(
            request=request, receipt=receipt, current=current, binding_digest=input_digest
        )
        if guarantee is GuaranteeLevel.RELIABLE and self._store is not None:
            self._store.commit_activity(request.request_id, {"receipt": receipt.issued_revision})
        return receipt, current

    def query(self, request: RequestKey) -> tuple[ActivityReceipt, CurrentFactView] | None:
        """Read-side query by request identity (separate from invoke rights)."""
        self._check_open()
        self._check_environment(request.environment_namespace)
        entry = self._activities.get(
            (request.environment_namespace, request.principal_scope, request.request_id)
        )
        if entry is None:
            return None
        return entry.receipt, entry.current

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
        return tuple(blockers)

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
        """Read-only close of the in-memory indices; no external effects here."""
        self._closed = True


@dataclass(frozen=True)
class CutReceiptLike:
    """Drain result mirror of the frozen ``CutReceipt`` DTO shape."""

    activation: ActivationRef
    admission_cut_revision: str
    blockers: tuple[str, ...]
    closed_new_admission: bool = True
