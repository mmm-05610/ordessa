"""Core node identity/publication primitives on the Environment's same store.

Internal signatures (no wire or service readiness):
  reserve(request, digest, OperationIntent, *, usages=()) -> OperationRecord
  publish(request, digest, expected_revision, usages) -> NodeRecord projection
  read(ParticipantInstanceRef) / list() -> frozen NodeRecord projections
NodeEvidencePort.inspect(operation, steps) -> NodePublicationEvidence is an
explicit trusted adapter over the currently admitted RuntimeProvider query
and owner read faces. It grants no permission or dispatch capability. Tests
inject controlled facts; no production adapter is installed by this module.

AgentNodeRef is the existing ParticipantInstanceRef, encoded with exactly
three fields. Identity allocation starts at generation 1; advancing an
existing logical identity requires an explicit migration/replacement contract
and is refused here. Provider activation generation never allocates nodes.
There is no node state machine, configuration value or native-session ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping, Protocol

from ordessa_environment_api import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError,
    RequestKey, UnknownResultError,
)
from ordessa_environment_api.domain import DomainStorePort, DomainWrite
from ordessa_environment_api.identity import ParticipantInstanceRef
from ordessa_environment_api.operations import (
    OperationIntent, OperationStorePort, UsageMutation, node_holder,
    operation_holder, safe_json, sealed_mapping,
)

AgentNodeRef = ParticipantInstanceRef
IDENTITIES = "core.participants"
NODES = "agents.nodes"
_BINDING_FIELDS = frozenset({"nodeRef", "harnessProviderRef", "harnessDefinitionRef",
    "harnessUnitRef", "profileSnapshotRef", "preparationContextRef",
    "configurationTargetRef", "nativeSessionRefs", "operationRef"})
_SOURCE_FIELDS = frozenset({"stepId", "providerRef", "inputDigest", "recoveryCorrelation", "evidenceRef"})


def encode_node_ref(ref: ParticipantInstanceRef):
    if type(ref) is not ParticipantInstanceRef or ref.generation < 1:
        raise IdentityMismatchError("node identity requires a positive core generation")
    return {"environmentNamespace": ref.environment, "instanceId": ref.instance_id, "generation": ref.generation}


def decode_node_ref(value):
    if not isinstance(value, Mapping) or set(value) != {"environmentNamespace", "instanceId", "generation"}:
        raise IdentityMismatchError("node reference requires exactly its three identity fields")
    try:
        ref = ParticipantInstanceRef(value["environmentNamespace"], value["instanceId"], value["generation"])
        encode_node_ref(ref)
        return ref
    except (TypeError, ValueError):
        raise IdentityMismatchError("invalid node reference") from None


def _request_ref(request):
    return {"environmentNamespace": request.environment_namespace,
            "principalScope": request.principal_scope, "requestId": request.request_id}


def _same_reference(left, right):
    # References are JSON identities: bool/int/float must remain distinct.
    # Wrapping supports absent owner evidence without inventing a reference.
    return safe_json({"reference": left}) == safe_json({"reference": right})


def _hash(value):
    return "sha256:" + hashlib.sha256(safe_json(value).encode()).hexdigest()


def _safe_projection(value):
    # References and safe source summaries only; never configuration values,
    # temporary endpoints, secret material or native stdout/stderr.
    plain = json.loads(safe_json(value))
    denied = {"token", "password", "secret", "apikey", "authorization", "credentials",
              "endpoint", "url", "stdout", "stderr", "config", "configuration", "value", "payload"}
    def walk(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key.lower().replace("_", "").replace("-", "") in denied:
                    raise IdentityMismatchError("node projections must contain safe references only")
                walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
    walk(plain)
    return plain


@dataclass(frozen=True)
class NodePublicationEvidence:
    """Owner-read source projection, not a caller-issued runtime grant.

    Owner references retain their exact leaf identity instead of the core
    inventing unit/configuration/endpoint schemas. Each requires scoped
    sourceRevision and ownerProviderRef provenance. Native sessions are at
    most one sourceRevision-bearing owner mapping, never synthesized here.
    """
    provider_ref: Mapping
    binding: Mapping
    step_sources: tuple[Mapping, ...]
    access_surface_refs: tuple[Mapping, ...]

    def __post_init__(self):
        if not isinstance(self.step_sources, tuple) or not self.step_sources:
            raise ValueError("complete named step source evidence is required")
        if not isinstance(self.access_surface_refs, tuple) or not self.access_surface_refs:
            raise ValueError("actual owner access surface references are required")
        object.__setattr__(self, "provider_ref", sealed_mapping(_safe_projection(self.provider_ref)))
        object.__setattr__(self, "binding", sealed_mapping(_safe_projection(self.binding)))
        object.__setattr__(self, "step_sources", tuple(sealed_mapping(_safe_projection(x)) for x in self.step_sources))
        object.__setattr__(self, "access_surface_refs", tuple(sealed_mapping(_safe_projection(x)) for x in self.access_surface_refs))


class NodeEvidencePort(Protocol):
    def inspect(self, operation, steps) -> NodePublicationEvidence | None:
        """Re-read actual facts through the current admitted owner; never invoke."""
        ...


class NodePublication:
    def __init__(self, environment, *, evidence_port: NodeEvidencePort | None = None):
        self._environment = environment
        self._evidence_port = evidence_port

    def _store(self):
        store = self._environment._store
        if not isinstance(store, (OperationStorePort,)) or not isinstance(store, DomainStorePort):
            raise GuaranteeUnavailableError("nodes require the same store's operation and domain capabilities")
        return store

    def _permission(self, ref=None, *, request=None, action=None):
        env = self._environment
        env._check_open()
        if ref is not None: env._check_environment(ref.environment)
        if request is not None:
            env._check_environment(request.environment_namespace)
            if request.principal_scope != env._principal_scope:
                raise AdmissionRefusedError("node request principal differs from trusted environment principal")
        target = f"{env.environment_id}:agents.node:{ref.instance_id if ref else '*'}"
        if env._policy is None or not env._policy.admit_object_access(env._principal_scope, target, "write" if action else "read"):
            raise AdmissionRefusedError("node target permission unavailable or refused")
        if action and not env._policy.admit_invoke(env._principal_scope, f"pacthold.agents.nodes.{action}", "reliable"):
            raise AdmissionRefusedError("node invocation permission unavailable or refused")

    def reserve(self, request: RequestKey, digest: str, intent: OperationIntent,
                *, usages: tuple[UsageMutation, ...] = (),
                writes: tuple[DomainWrite, ...] = ()):
        """Reserve identity and pre-dispatch resource holds in one transaction.

        Replays return the original reservation; they cannot acquire new holds.
        The coordinator must include the fixed resource recipe in its digest.
        Extra ``writes`` (e.g. an operation-bound immutable snapshot) commit in
        the same transaction: either the identity, the holds, the writes and
        the operation all persist, or none of them do.
        """
        env = self._environment
        with env._admission_lock:
            if type(intent) is not OperationIntent:
                raise IdentityMismatchError("node reservation requires a frozen operation intent")
            ref = decode_node_ref(intent.node_ref)
            from pacthold.agents.contracts import ProfileRef
            try:
                profile = ProfileRef.from_dict(json.loads(safe_json(intent.profile_snapshot_ref)))
            except (ValueError, TypeError):
                raise IdentityMismatchError("node reservation requires a complete Profile snapshot") from None
            if profile.environment_namespace != ref.environment:
                raise IdentityMismatchError("node Profile snapshot is in another environment")
            _safe_projection(intent.context_ref)
            self._permission(ref, request=request, action="prepare")
            store = self._store()
            identity = {"nodeRef": encode_node_ref(ref), "operationRequest": _request_ref(request),
                        "operationRef": intent.operation_ref, "intentDigest": _hash(intent.to_dict())}
            existing = store.read_operation(request)
            if existing is not None:
                operation = store.reserve_operation(request, digest, intent)
                self._identity(operation)
                return operation
            row = store.read_domain(env.environment_id, IDENTITIES, ref.instance_id)
            if row is not None:
                raise IdentityMismatchError("node identity is already reserved; replacement requires an explicit migration contract")
            if ref.generation != 1:
                raise IdentityMismatchError("a new core node identity starts at generation 1")
            return store.reserve_operation(request, digest, intent,
                writes=(DomainWrite(IDENTITIES, ref.instance_id, 0, identity),) + tuple(writes),
                usages=usages)

    def _identity(self, operation):
        ref = decode_node_ref(operation.intent.node_ref)
        row = self._store().read_domain(ref.environment, IDENTITIES, ref.instance_id)
        expected = {"nodeRef": encode_node_ref(ref), "operationRequest": _request_ref(operation.request),
                    "operationRef": operation.intent.operation_ref, "intentDigest": _hash(operation.intent.to_dict())}
        if row is None or row["revision"] != 1 or not _same_reference(row["value"], expected):
            raise GuaranteeUnavailableError("node reservation source is inconsistent")
        return ref

    def _owner_ref(self, value, provider, *, label):
        if (not isinstance(value, Mapping) or value.get("environmentNamespace") != self._environment.environment_id
                or not _same_reference(value.get("ownerProviderRef"), provider) or not isinstance(value.get("sourceRevision"), str)
                or not value["sourceRevision"] or len(value) < 4):
            raise GuaranteeUnavailableError(f"{label} lacks complete scoped owner provenance")
        _safe_projection(value)

    def _validate_evidence(self, operation, steps, evidence):
        if type(evidence) is not NodePublicationEvidence:
            raise GuaranteeUnavailableError("actual owner publication evidence unavailable")
        intent = operation.intent
        ref = decode_node_ref(intent.node_ref)
        binding = evidence.binding
        if set(binding) != _BINDING_FIELDS:
            raise GuaranteeUnavailableError("incomplete actual AgentBinding")
        if (not _same_reference(binding["nodeRef"], intent.node_ref) or binding["operationRef"] != intent.operation_ref
                or not _same_reference(binding["profileSnapshotRef"], intent.profile_snapshot_ref)
                or not _same_reference(binding["preparationContextRef"], intent.context_ref)
                or not _same_reference(binding["harnessProviderRef"], evidence.provider_ref)):
            raise IdentityMismatchError("owner binding differs from fixed operation lineage")
        if (not isinstance(binding["harnessDefinitionRef"], Mapping)
                or binding["harnessDefinitionRef"].get("environmentNamespace") != ref.environment):
            raise IdentityMismatchError("Harness definition is unscoped")
        admitted = self._environment.agent_runtime_contribution(binding["harnessDefinitionRef"])
        if not _same_reference(admitted.provider_ref, evidence.provider_ref):
            raise IdentityMismatchError("owner provider activation differs from currently admitted provider")
        for value, label in ((binding["harnessUnitRef"], "unit"), (binding["configurationTargetRef"], "configuration target")):
            self._owner_ref(value, evidence.provider_ref, label=label)
        sessions = binding["nativeSessionRefs"]
        if not isinstance(sessions, tuple) or len(sessions) > 1:
            raise GuaranteeUnavailableError("native session mapping must be an owner single-session projection")
        for session in sessions: self._owner_ref(session, evidence.provider_ref, label="native session")
        for access in evidence.access_surface_refs: self._owner_ref(access, evidence.provider_ref, label="access surface")
        if len(evidence.step_sources) != len(steps):
            raise GuaranteeUnavailableError("publication does not cover every provider step source")
        for step, source in zip(steps, evidence.step_sources):
            frozen = step.intent
            if (set(source) != _SOURCE_FIELDS or source["stepId"] != frozen.step_id
                    or not _same_reference(source["providerRef"], frozen.pinned_provider_ref)
                    or not _same_reference(source["providerRef"], evidence.provider_ref)
                    or source["inputDigest"] != frozen.input_digest
                    or source["recoveryCorrelation"] != frozen.recovery_correlation
                    or step.outcome != "concluded" or not _same_reference(step.evidence.get("evidenceRef"), source["evidenceRef"])):
                raise IdentityMismatchError("actual step evidence differs from fixed dispatch/source correlation")
            self._owner_ref(source["evidenceRef"], evidence.provider_ref, label="step evidence")

    def publish(self, request: RequestKey, digest: str, expected_revision: int,
                usages: tuple[UsageMutation, ...]):
        env = self._environment
        with env._admission_lock:
            self._permission(request=request, action="publish")
            store = self._store()
            operation = store.read_operation(request)
            if operation is None: raise GuaranteeUnavailableError("node operation is not reserved")
            ref = self._identity(operation)
            self._permission(ref, request=request, action="publish")
            if operation.digest != digest: raise IdentityMismatchError("node publication digest changed")
            if operation.status == "published":
                projection = self.read(ref)
                row = store.read_domain(ref.environment, NODES, f"{ref.instance_id}:{ref.generation}")
                store.publish_operation(request, digest, expected_revision,
                    tuple(step.step_id for step in operation.intent.steps),
                    (DomainWrite(NODES, row["record_id"], 0, row["value"]),), usages,
                    json.loads(safe_json(projection)))
                return projection
            if operation.status in {"unknown", "refused", "cancelled"}:
                raise UnknownResultError("uncertain operation cannot publish a node")
            if self._evidence_port is None:
                raise GuaranteeUnavailableError("actual RuntimeProvider evidence adapter is absent")
            steps = tuple(store.read_operation_step(request, step.step_id) for step in operation.intent.steps)
            if any(step is None or step.outcome != "concluded" for step in steps):
                raise UnknownResultError("node publication requires concluded native step evidence")
            try:
                evidence = self._evidence_port.inspect(operation, steps)
            except Exception:
                raise GuaranteeUnavailableError("actual owner publication evidence unavailable") from None
            self._validate_evidence(operation, steps, evidence)
            if not isinstance(usages, tuple) or not usages:
                raise GuaranteeUnavailableError("node publication requires held resource Usage transfer")
            for usage in usages:
                if (not _same_reference(usage.expected_holder_ref, operation_holder(request, operation.intent.operation_ref))
                        or not _same_reference(usage.holder_ref, node_holder(ref.environment, ref.instance_id, ref.generation))
                        or usage.state != "active" or usage.expected_revision < 1):
                    raise IdentityMismatchError("publication must transfer already held Usage to the fixed node")
            if not any(_same_reference(usage.target_ref, evidence.binding["harnessUnitRef"]) and "use" in usage.rights
                       for usage in usages):
                raise GuaranteeUnavailableError("node publication requires the actual Harness unit's use relationship")
            projection = {"nodeRef": encode_node_ref(ref), "binding": json.loads(safe_json(evidence.binding)),
                "lineage": {"profileSnapshotRef": json.loads(safe_json(operation.intent.profile_snapshot_ref)),
                            "preparationContextRef": json.loads(safe_json(operation.intent.context_ref))},
                "publicationRevision": operation.revision + 1,
                "resourceUsageRefs": [{"environmentNamespace": ref.environment, "usageId": usage.usage_id} for usage in usages],
                "managementSurfaceRefs": [{"environmentNamespace": ref.environment, "surfaceId": "pacthold.agents", "nodeRef": encode_node_ref(ref)}],
                "accessSurfaceRefs": [json.loads(safe_json(value)) for value in evidence.access_surface_refs]}
            value = {"record": projection, "operationRequest": _request_ref(request),
                     "sourceSteps": [json.loads(safe_json(source)) for source in evidence.step_sources],
                     "recordDigest": _hash(projection)}
            result = dict(projection)
            store.publish_operation(request, digest, expected_revision,
                tuple(step.step_id for step in operation.intent.steps),
                (DomainWrite(NODES, f"{ref.instance_id}:{ref.generation}", 0, value),), usages, result)
            return sealed_mapping(projection)

    def _read(self, ref, row):
        try:
            if row["record_id"] != f"{ref.instance_id}:{ref.generation}" or row["revision"] != 1:
                raise ValueError("identity/revision")
            value = row["value"]
            request = RequestKey(**{ "environment_namespace": value["operationRequest"]["environmentNamespace"],
                "principal_scope": value["operationRequest"]["principalScope"], "request_id": value["operationRequest"]["requestId"]})
            operation = self._store().read_operation(request)
            if operation is None or operation.status != "published": raise ValueError("source operation")
            self._identity(operation)
            record = value["record"]
            if (not _same_reference(record["nodeRef"], encode_node_ref(ref)) or not _same_reference(record, operation.result)
                    or _hash(record) != value["recordDigest"] or record["publicationRevision"] != operation.revision):
                raise ValueError("publication provenance")
            for step, source in zip(operation.intent.steps, value["sourceSteps"]):
                actual = self._store().read_operation_step(request, step.step_id)
                if (actual is None or actual.outcome != "concluded" or set(source) != _SOURCE_FIELDS
                        or source["stepId"] != step.step_id or source["inputDigest"] != step.input_digest
                        or source["recoveryCorrelation"] != step.recovery_correlation
                        or not _same_reference(source["providerRef"], step.pinned_provider_ref)
                        or not _same_reference(source["providerRef"], record["binding"]["harnessProviderRef"])
                        or not _same_reference(actual.evidence.get("evidenceRef"), source["evidenceRef"])):
                    raise ValueError("step provenance")
            if len(value["sourceSteps"]) != len(operation.intent.steps): raise ValueError("step count")
            _safe_projection(record)
            return sealed_mapping(record)
        except (ValueError, KeyError, TypeError, AttributeError, IdentityMismatchError):
            raise GuaranteeUnavailableError("stored node publication is inconsistent") from None

    def read(self, ref: ParticipantInstanceRef):
        env = self._environment
        with env._admission_lock:
            encode_node_ref(ref)
            self._permission(ref)
            row = self._store().read_domain(ref.environment, NODES, f"{ref.instance_id}:{ref.generation}")
            return self._read(ref, row) if row is not None else None

    def list(self):
        env = self._environment
        with env._admission_lock:
            self._permission()
            result = []
            for row in self._store().list_domain(env.environment_id, NODES):
                try: ref = decode_node_ref(row["value"]["record"]["nodeRef"])
                except (ValueError, KeyError, TypeError):
                    raise GuaranteeUnavailableError("stored node identity is inconsistent") from None
                self._permission(ref)
                result.append(self._read(ref, row))
            return tuple(result)
