"""Fixed Profile to Unit to Node coordination on the original operation store.

Deployment ports resolve authorized preparation context and observe original
owner receipts. They do not dispatch, choose providers, allocate core identity
or replace the operation ledger. Native plans remain private and ephemeral.
"""
from __future__ import annotations
from ordessa_agents.profiles.definitions.codec import decode_revision_ref, encode_content, encode_revision_ref

from dataclasses import dataclass, field
import hashlib
import json
from collections.abc import Mapping
from typing import Protocol

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable, UnitIdentityMismatch
from ordessa_units.definitions.operations import OperationIntent, StepIntent, UsageMutation, OperationRevisionConflict, operation_holder, node_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_agents.profiles.definitions.models import ProfileRevision, ProfileRevisionRef
from ordessa_agents.profiles.definitions.codec import decode_content
from ordessa_agents.profiles.definitions.validation import ProfileValidationError, canonical_content
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import InvocationIssuer
from ordessa_units.bindings.publication import decode_node_ref, _safe_projection, _same_reference


def plain(value): return json.loads(safe_json(value))
def hashed(value): return "sha256:" + hashlib.sha256(safe_json(value).encode()).hexdigest()


def public_parameters(value):
    result = _safe_projection(value)
    private = {"cwd", "path", "normalizedpath", "executable", "privaterootfacts", "argv", "command", "runtimeroot", "userroot"}
    def inspect(item):
        if isinstance(item, dict):
            for name, child in item.items():
                if name.lower().replace("_", "").replace("-", "") in private:
                    raise UnitIdentityMismatch("preparation accepts owner references, not caller host paths or commands")
                inspect(child)
        elif isinstance(item, list):
            for child in item: inspect(child)
    inspect(result)
    return result


@dataclass(frozen=True)
class PreparationContext:
    directory_binding_ref: DirectoryBindingRef
    source_refs: Mapping
    private_context: Mapping = field(repr=False)
    management_epoch: int = 0

    def __post_init__(self):
        if type(self.directory_binding_ref) is not DirectoryBindingRef:
            raise ValueError("trusted DirectoryBinding required")
        if type(self.management_epoch) is not int or self.management_epoch < 0:
            raise ValueError("preparation management epoch required")
        sources = _safe_projection(self.source_refs)
        installation = sources.get("installationRef")
        if (not isinstance(installation, dict) or not installation.get("sourceRevision")
                or installation.get("environmentNamespace") != self.directory_binding_ref.environment_namespace):
            raise ValueError("verified installation source reference required")
        object.__setattr__(self, "source_refs", sealed_mapping(sources))
        object.__setattr__(self, "private_context", sealed_mapping(self.private_context))


@dataclass(frozen=True)
class PreparationObservation:
    """Trusted original-step evidence, not a provider ACK or caller assertion."""
    step_id: str
    provider_ref: Mapping
    input_digest: str
    recovery_correlation: str
    evidence_ref: Mapping
    prepared_unit: Mapping
    usages: tuple[UsageMutation, ...] = ()

    def __post_init__(self):
        if not isinstance(self.prepared_unit, Mapping) or set(self.prepared_unit) != {"unitRef"}:
            raise ValueError("only the original prepared Unit reference may be retained")
        for name in ("provider_ref", "evidence_ref", "prepared_unit"):
            object.__setattr__(self, name, sealed_mapping(_safe_projection(getattr(self, name))))
        if not isinstance(self.usages, tuple) or any(type(item) is not UsageMutation for item in self.usages):
            raise ValueError("original acquired Usage mutations required")


class PreparationContextPort(Protocol):
    """Existing Workspace/installation owners verify sources and startup scope.

    Resolve must reject unapproved model/hook effects, unresolved material,
    caller host paths and unsupported omission/guarantee options. It neither
    starts a process nor issues invocation permission.
    """
    def resolve(self, request, manifest, admitted_provider, node_ref, context, options) -> PreparationContext: ...


class PreparationObservationPort(Protocol):
    """Owner proof of the original correlation; ACK alone must be rejected."""
    def observe(self, operation, step, reply) -> PreparationObservation: ...


class AgentAssembly:
    def __init__(self, environment, profiles, nodes, *, invocation_issuer=None,
                 context_port=None, observation_port=None, unit_manager=None):
        self._environment, self._profiles, self._nodes = environment, profiles, nodes
        self._issuer, self._context_port, self._observation_port = invocation_issuer, context_port, observation_port
        self._unit_manager = unit_manager

    def _manager_bound(self):
        from ordessa_units.management.manager import UnitManager
        manager = self._unit_manager
        return (type(manager) is UnitManager
                and manager.records.verifier is manager.verifier
                and getattr(getattr(manager.verifier, "_verify", None), "__self__", None)
                    is self._issuer)

    def _admitted(self, definition_ref):
        from ordessa_agents.harness.providers.registry.definition_admission import HarnessAdmission
        if not self._manager_bound():
            raise UnitGuaranteeUnavailable("original Unit Manager preparation owner required")
        return HarnessAdmission(self._environment).describe(definition_ref)

    def _dispatch(self, step, argument, invocation):
        if step.step_id == "prepare":
            return self._unit_manager.create(argument, invocation).prepared_unit
        if step.step_id == "start":
            return self._unit_manager.start(argument, invocation)
        raise UnitGuaranteeUnavailable("Manager root step is unavailable")

    def capabilities(self):
        try:
            store = self._nodes._store()
        except UnitGuaranteeUnavailable:
            return {"nodePreparation": False}
        return {"nodePreparation": isinstance(self._issuer, InvocationIssuer) and self._issuer._store is store
                and self._environment._fingerprint_port is not None
                and callable(getattr(self._nodes._evidence_port, "inspect", None))
                and callable(getattr(self._context_port, "resolve", None))
                and callable(getattr(self._observation_port, "observe", None))
                and self._manager_bound()}

    @staticmethod
    def operation_view(operation):
        return {"operationRef": operation.intent.operation_ref, "revision": operation.revision,
                "status": operation.status, "node": operation.result}

    def staged_assembly(self):
        """Delegation entry for staged effect assembly (freeze §5).

        The staged coordinator reuses this assembly's permissions, planning,
        observation and publication authorities. The original _plan, reserve
        and prepare semantics are unchanged.
        """
        from ordessa_units.bindings.staged_assembly import StagedAgentAssembly
        return StagedAgentAssembly(self)

    def _permission(self, request, *, query=False):
        env = self._environment
        env._check_open()
        if not isinstance(request, RequestKey) or request.principal_scope != env._principal_scope:
            raise UnitAdmissionRefused("preparation principal differs from authenticated realm")
        env._check_environment(request.environment_namespace)
        self._nodes._permission(request=request, action=None if query else "prepare")
        self._nodes._store()
        if (not isinstance(self._issuer, InvocationIssuer) or self._issuer._store is not env._store
                or env._fingerprint_port is None
                or not callable(getattr(self._nodes._evidence_port, "inspect", None))
                or not callable(getattr(self._context_port, "resolve", None))
                or not callable(getattr(self._observation_port, "observe", None))):
            raise UnitGuaranteeUnavailable("explicit preparation authorities on the same store required")

    def _resolve(self, request, manifest, admitted, node, context, options):
        try:
            resolved = self._context_port.resolve(request, manifest, admitted, node, context, options)
        except Exception:
            raise UnitGuaranteeUnavailable("authorized preparation context unavailable") from None
        if (type(resolved) is not PreparationContext
                or resolved.directory_binding_ref.environment_namespace != request.environment_namespace
                or not _same_reference(resolved.private_context.get("nodeRef"), node)):
            raise UnitIdentityMismatch("trusted preparation context identity differs")
        if "directoryBindingRef" in context and not _same_reference(context["directoryBindingRef"], resolved.directory_binding_ref.to_dict()):
            raise UnitIdentityMismatch("resolved DirectoryBinding differs from requested reference")
        return resolved

    def _plan(self, request, manifest, admitted, node, context, options, operation_ref):
        resolved = self._resolve(request, manifest, admitted, node, context, options)
        correlation = {"operationRef": operation_ref, "prepareCorrelation": operation_ref + ".prepare",
                       "startCorrelation": operation_ref + ".start"}
        try:
            plan = self._unit_manager.plan_preparation(
                {"ref": encode_revision_ref(manifest.ref), "manifest": encode_content(manifest.content)}, resolved.private_context, correlation)
            digest = self._environment._fingerprint_port.fingerprint(
                request, "pacthold.agents.nodes.plan", hashed(plan))
        except Exception:
            raise UnitGuaranteeUnavailable("fixed provider preparation plan unavailable") from None
        return resolved, plan, digest

    def reserve(self, request, profile_ref, context, options, profile_manifest=None):
        """Reserve one fixed preparation under exactly one configuration source.

        A complete profile manifest body and an exact ProfileRef are mutually
        exclusive (interfaces.md 3.1): both together, neither, or a bare name
        are refused before any provider call. A body is frozen into a
        deterministic immutable snapshot in the same transaction as this
        reservation and never enters the named catalog. The request digest is
        computed from the normalized snapshot reference, so the same body and
        its equivalent reference stay one idempotent request.
        """
        env = self._environment
        with env._admission_lock:
            self._permission(request)
            if (profile_ref is None) == (profile_manifest is None):
                raise ProfileValidationError("exactly one configuration source required")
            if not isinstance(context, Mapping) or not isinstance(options, Mapping):
                raise UnitIdentityMismatch("explicit preparation parameters required")
            snapshot_write = None
            if profile_ref is None:
                if not isinstance(profile_manifest, Mapping):
                    raise ProfileValidationError("complete profile manifest body required")
                profile_ref, snapshot_write = self._profiles.stage_snapshot(profile_manifest)
                # The immutable snapshot write is intentionally deferred to the
                # atomic operation reservation below. Planning consumes the
                # canonical in-memory value and never performs an early write.
                manifest = ProfileRevision(profile_ref,
                    decode_content(profile_manifest, env.environment_id))
            elif type(profile_ref) is not ProfileRevisionRef:
                raise UnitIdentityMismatch("fixed Profile and explicit preparation parameters required")
            else:
                manifest = self._profiles.get_revision(profile_ref)
            fixed = {"profileRef": encode_revision_ref(profile_ref), "context": public_parameters(context),
                     "options": public_parameters(options)}
            digest = env._fingerprint_port.fingerprint(request, "pacthold.agents.nodes.prepare", hashed(fixed))
            prior = env._store.read_operation(request)
            if prior is not None:
                if prior.digest != digest or prior.intent.kind != "agent-preparation":
                    raise UnitIdentityMismatch("spent preparation request differs")
                return prior
            def unresolved(value):
                if isinstance(value, Mapping):
                    return ("secretRef" in value or bool(value.get("resourceRefs"))
                            or any(unresolved(item) for item in value.values()))
                if isinstance(value, (list, tuple)): return any(unresolved(item) for item in value)
                return False
            if unresolved(encode_content(manifest.content)):
                raise UnitGuaranteeUnavailable("C1 material acquisition and authorized SecretRef resolution not composed")
            admitted = self._admitted(encode_content(manifest.content)["harnessDefinitionRef"])
            identity = hashed({"environmentNamespace": request.environment_namespace,
                               "principalScope": request.principal_scope, "requestId": request.request_id})[7:55]
            operation_ref = "preparation-" + identity
            node = {"environmentNamespace": env.environment_id, "instanceId": "agent-" + identity, "generation": 1}
            resolved, _, plan_digest = self._plan(request, manifest, admitted, node, context, options, operation_ref)
            bindings = {name: {"action": name, "targetRef": node, "delegationRef": None, "cleanup": False}
                        for name in ("prepare", "start")}
            context_ref = {"environmentNamespace": env.environment_id, "preparationRequest": fixed,
                           "directoryBindingRef": resolved.directory_binding_ref.to_dict(),
                           "contextSources": plain(resolved.source_refs), "planDigest": plan_digest,
                           "invocationBindings": bindings}
            steps = tuple(StepIntent(name, admitted.provider_ref, digest, operation_ref + "." + name,
                                    () if name == "prepare" else ("prepare",), resolved.management_epoch)
                          for name in ("prepare", "start"))
            intent = OperationIntent(operation_ref, "agent-preparation", encode_revision_ref(profile_ref), context_ref,
                                     steps, node, resolved.management_epoch)
            hold = UsageMutation(operation_ref + ".provider", 0, None, operation_holder(request, operation_ref),
                                 admitted.provider_ref, ("use",), "active")
            return self._nodes.reserve(request, digest, intent, usages=(hold,),
                                       writes=() if snapshot_write is None else (snapshot_write,))

    def _current_plan(self, request, operation):
        manifest = self._profiles.get_revision(decode_revision_ref(plain(operation.intent.profile_snapshot_ref)))
        admitted = self._admitted(encode_content(manifest.content)["harnessDefinitionRef"])
        if not _same_reference(admitted.provider_ref, operation.intent.steps[0].pinned_provider_ref):
            raise UnitAdmissionRefused("prepared provider activation changed")
        fixed = operation.intent.context_ref["preparationRequest"]
        resolved, plan, digest = self._plan(request, manifest, admitted, operation.intent.node_ref,
                                          fixed["context"], fixed["options"], operation.intent.operation_ref)
        original = operation.intent.context_ref
        if (digest != original["planDigest"] or not _same_reference(resolved.source_refs, original["contextSources"])
                or not _same_reference(resolved.directory_binding_ref.to_dict(), original["directoryBindingRef"])
                or resolved.management_epoch != operation.intent.management_epoch):
            raise UnitAdmissionRefused("fixed preparation sources changed before dispatch")
        return admitted, plan

    def _observe(self, operation, step, reply):
        observation = self._observation_port.observe(operation, step, reply)
        if (type(observation) is not PreparationObservation or observation.step_id != step.step_id
                or not _same_reference(observation.provider_ref, step.pinned_provider_ref)
                or observation.input_digest != step.input_digest
                or observation.recovery_correlation != step.recovery_correlation):
            raise UnitIdentityMismatch("original preparation receipt correlation differs")
        self._nodes._owner_ref(observation.evidence_ref, step.pinned_provider_ref, label="preparation step evidence")
        if not isinstance(observation.prepared_unit.get("unitRef"), Mapping):
            raise UnitGuaranteeUnavailable("original prepared Unit reference unavailable")
        unit_ref = observation.prepared_unit["unitRef"]
        self._nodes._owner_ref(unit_ref, step.pinned_provider_ref, label="prepared Unit")
        if step.step_id == "prepare" and not any(_same_reference(usage.target_ref, unit_ref) and "use" in usage.rights
                                                 for usage in observation.usages):
            raise UnitGuaranteeUnavailable("prepared Unit must be held before native start")
        for usage in observation.usages:
            if (usage.expected_revision != 0 or usage.expected_holder_ref is not None or usage.state != "active"
                    or not _same_reference(usage.holder_ref, operation_holder(operation.request, operation.intent.operation_ref))):
                raise UnitIdentityMismatch("preparation observation must acquire original operation holds")
            _safe_projection(usage.target_ref)
        return observation

    def prepare(self, request, profile_ref, context, options, profile_manifest=None):
        operation = self.reserve(request, profile_ref, context, options, profile_manifest)
        env = self._environment
        for frozen_step in operation.intent.steps:
            with env._admission_lock:
                self._permission(request)
                operation = env._store.read_operation(request)
                if operation.status in {"published", "unknown", "refused", "cancelled"}:
                    return operation
                previous = env._store.read_operation_step(request, frozen_step.step_id)
                if previous is not None:
                    if previous.outcome == "concluded": continue
                    return operation  # Claimed is possibly dispatched, never a resend permission.
                admitted, plan = self._current_plan(request, operation)
                argument = plan if frozen_step.step_id == "prepare" else env._store.read_operation_step(request, "prepare").evidence["preparedUnit"]
                invocation = self._issuer.issue(request, operation.digest, frozen_step.step_id,
                                                frozen_step.step_id, operation.intent.node_ref)
            try:
                reply = self._dispatch(frozen_step, argument, invocation)
                if not self._issuer.verified_consumption(invocation):
                    raise UnitGuaranteeUnavailable("provider did not consume the original invocation")
                observed = self._observe(operation, frozen_step, reply)
                if frozen_step.step_id == "start" and not _same_reference(observed.prepared_unit, argument):
                    raise UnitIdentityMismatch("start receipt changed the original prepared Unit")
                evidence = {"evidenceRef": plain(observed.evidence_ref), "preparedUnit": plain(observed.prepared_unit),
                            "acquiredUsages": [self._usage_source(item) for item in observed.usages]}
            except Exception:
                self._record_step(operation, frozen_step, invocation.facts["claimRevision"], "unknown", {})
                return env._store.read_operation(request)
            self._record_step(operation, frozen_step, invocation.facts["claimRevision"],
                              "concluded", evidence, observed.usages)
        with env._admission_lock:
            operation = env._store.read_operation(request)
            if operation.status in {"published", "unknown", "refused", "cancelled"}:
                return operation
            self._permission(request)
            self._current_plan(request, operation)
            ref = decode_node_ref(operation.intent.node_ref)
            owner, destination = operation_holder(request, operation.intent.operation_ref), node_holder(ref.environment, ref.instance_id, ref.generation)
            initial = UsageMutation(operation.intent.operation_ref + ".provider", 1, owner, destination,
                                    operation.intent.steps[0].pinned_provider_ref, ("use",), "active")
            transfers = [initial]
            for step in operation.intent.steps:
                record = env._store.read_operation_step(request, step.step_id)
                for item in record.evidence["acquiredUsages"]:
                    transfers.append(UsageMutation(item["usageId"], 1, owner, destination,
                                                   item["targetRef"], tuple(item["rights"]), "active", item["summary"]))
            self._nodes.publish(request, operation.digest, operation.revision, tuple(transfers))
            return env._store.read_operation(request)

    def query(self, request):
        """Read the original operation only; never replay or upgrade uncertainty."""
        env = self._environment
        with env._admission_lock:
            self._permission(request, query=True)
            operation = env._store.read_operation(request)
            if operation is not None and operation.intent.kind != "agent-preparation":
                raise UnitIdentityMismatch("request belongs to another operation")
            return operation

    def _record_step(self, operation, step, expected_revision, outcome, evidence, usages=()):
        """An older observation cannot overwrite a newer original-step fact."""
        env = self._environment
        with env._admission_lock:
            current = env._store.read_operation_step(operation.request, step.step_id)
            latest = env._store.read_operation(operation.request)
            if (current is None or current.revision != expected_revision
                    or current.outcome in {"concluded", "refused"}
                    or latest.status in {"published", "refused", "cancelled"}):
                return
            try:
                env._store.record_operation_step(operation.request, operation.digest, step.step_id, step.input_digest,
                                                expected_revision, outcome, evidence, usages=usages)
            except OperationRevisionConflict:
                # The same durable store remains authoritative if another
                # owner recorder advanced this original step concurrently.
                return

    @staticmethod
    def _usage_source(usage):
        return {"usageId": usage.usage_id, "targetRef": _safe_projection(usage.target_ref),
                "rights": list(usage.rights), "summary": _safe_projection(usage.payload)}
