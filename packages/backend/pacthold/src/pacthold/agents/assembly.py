"""Fixed Profile to Unit to Node coordination on the original operation store.

Deployment ports resolve authorized preparation context and observe original
owner receipts. They do not dispatch, choose providers, allocate core identity
or replace the operation ledger. Native plans remain private and ephemeral.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from collections.abc import Mapping
from typing import Protocol

from ordessa_environment_api import AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError, RequestKey
from ordessa_environment_api.operations import OperationIntent, StepIntent, UsageMutation, OperationRevisionConflict, operation_holder, node_holder, safe_json, sealed_mapping
from .contracts import ProfileRef
from .directory import DirectoryBindingRef
from .invocation import InvocationIssuer
from .nodes import decode_node_ref, _safe_projection, _same_reference


def plain(value): return json.loads(safe_json(value))
def hashed(value): return "sha256:" + hashlib.sha256(safe_json(value).encode()).hexdigest()


def public_parameters(value):
    result = _safe_projection(value)
    private = {"cwd", "path", "normalizedpath", "executable", "privaterootfacts", "argv", "command", "runtimeroot", "userroot"}
    def inspect(item):
        if isinstance(item, dict):
            for name, child in item.items():
                if name.lower().replace("_", "").replace("-", "") in private:
                    raise IdentityMismatchError("preparation accepts owner references, not caller host paths or commands")
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
                 context_port=None, observation_port=None):
        self._environment, self._profiles, self._nodes = environment, profiles, nodes
        self._issuer, self._context_port, self._observation_port = invocation_issuer, context_port, observation_port

    def capabilities(self):
        try:
            store = self._nodes._store()
        except GuaranteeUnavailableError:
            return {"nodePreparation": False}
        return {"nodePreparation": isinstance(self._issuer, InvocationIssuer) and self._issuer._store is store
                and self._environment._fingerprint_port is not None
                and callable(getattr(self._nodes._evidence_port, "inspect", None))
                and callable(getattr(self._context_port, "resolve", None))
                and callable(getattr(self._observation_port, "observe", None))}

    @staticmethod
    def operation_view(operation):
        return {"operationRef": operation.intent.operation_ref, "revision": operation.revision,
                "status": operation.status, "node": operation.result}

    def _permission(self, request, *, query=False):
        env = self._environment
        env._check_open()
        if not isinstance(request, RequestKey) or request.principal_scope != env._principal_scope:
            raise AdmissionRefusedError("preparation principal differs from authenticated realm")
        env._check_environment(request.environment_namespace)
        self._nodes._permission(request=request, action=None if query else "prepare")
        self._nodes._store()
        if (not isinstance(self._issuer, InvocationIssuer) or self._issuer._store is not env._store
                or env._fingerprint_port is None
                or not callable(getattr(self._nodes._evidence_port, "inspect", None))
                or not callable(getattr(self._context_port, "resolve", None))
                or not callable(getattr(self._observation_port, "observe", None))):
            raise GuaranteeUnavailableError("explicit preparation authorities on the same store required")

    def _resolve(self, request, manifest, admitted, node, context, options):
        try:
            resolved = self._context_port.resolve(request, manifest, admitted, node, context, options)
        except Exception:
            raise GuaranteeUnavailableError("authorized preparation context unavailable") from None
        if (type(resolved) is not PreparationContext
                or resolved.directory_binding_ref.environment_namespace != request.environment_namespace
                or not _same_reference(resolved.private_context.get("nodeRef"), node)):
            raise IdentityMismatchError("trusted preparation context identity differs")
        if "directoryBindingRef" in context and not _same_reference(context["directoryBindingRef"], resolved.directory_binding_ref.to_dict()):
            raise IdentityMismatchError("resolved DirectoryBinding differs from requested reference")
        return resolved

    def _plan(self, request, manifest, admitted, node, context, options, operation_ref):
        resolved = self._resolve(request, manifest, admitted, node, context, options)
        correlation = {"operationRef": operation_ref, "prepareCorrelation": operation_ref + ".prepare",
                       "startCorrelation": operation_ref + ".start"}
        try:
            plan = admitted.provider.plan_preparation(
                {"ref": manifest.ref.to_dict(), "manifest": manifest.content}, resolved.private_context, correlation)
            digest = self._environment._fingerprint_port.fingerprint(
                request, "pacthold.agents.nodes.plan", hashed(plan))
        except Exception:
            raise GuaranteeUnavailableError("fixed provider preparation plan unavailable") from None
        return resolved, plan, digest

    def reserve(self, request, profile_ref, context, options):
        env = self._environment
        with env._admission_lock:
            self._permission(request)
            if type(profile_ref) is not ProfileRef or not isinstance(context, Mapping) or not isinstance(options, Mapping):
                raise IdentityMismatchError("fixed Profile and explicit preparation parameters required")
            fixed = {"profileRef": profile_ref.to_dict(), "context": public_parameters(context),
                     "options": public_parameters(options)}
            digest = env._fingerprint_port.fingerprint(request, "pacthold.agents.nodes.prepare", hashed(fixed))
            prior = env._store.read_operation(request)
            if prior is not None:
                if prior.digest != digest or prior.intent.kind != "agent-preparation":
                    raise IdentityMismatchError("spent preparation request differs")
                return prior
            manifest = self._profiles.read(profile_ref)
            def unresolved(value):
                if isinstance(value, Mapping):
                    return ("secretRef" in value or bool(value.get("resourceRefs"))
                            or any(unresolved(item) for item in value.values()))
                if isinstance(value, (list, tuple)): return any(unresolved(item) for item in value)
                return False
            if unresolved(manifest.content):
                raise GuaranteeUnavailableError("C1 material acquisition and authorized SecretRef resolution not composed")
            admitted = env.agent_runtime_contribution(manifest.content["harnessDefinitionRef"])
            if not {"plan_preparation", "prepare", "start"} <= set(admitted.descriptor.supported_methods):
                raise GuaranteeUnavailableError("required provider preparation methods unavailable")
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
            intent = OperationIntent(operation_ref, "agent-preparation", profile_ref.to_dict(), context_ref,
                                     steps, node, resolved.management_epoch)
            hold = UsageMutation(operation_ref + ".provider", 0, None, operation_holder(request, operation_ref),
                                 admitted.provider_ref, ("use",), "active")
            return self._nodes.reserve(request, digest, intent, usages=(hold,))

    def _current_plan(self, request, operation):
        manifest = self._profiles.read(ProfileRef.from_dict(plain(operation.intent.profile_snapshot_ref)))
        admitted = self._environment.agent_runtime_contribution(manifest.content["harnessDefinitionRef"])
        if not _same_reference(admitted.provider_ref, operation.intent.steps[0].pinned_provider_ref):
            raise AdmissionRefusedError("prepared provider activation changed")
        fixed = operation.intent.context_ref["preparationRequest"]
        resolved, plan, digest = self._plan(request, manifest, admitted, operation.intent.node_ref,
                                          fixed["context"], fixed["options"], operation.intent.operation_ref)
        original = operation.intent.context_ref
        if (digest != original["planDigest"] or not _same_reference(resolved.source_refs, original["contextSources"])
                or not _same_reference(resolved.directory_binding_ref.to_dict(), original["directoryBindingRef"])
                or resolved.management_epoch != operation.intent.management_epoch):
            raise AdmissionRefusedError("fixed preparation sources changed before dispatch")
        return admitted, plan

    def _observe(self, operation, step, reply):
        observation = self._observation_port.observe(operation, step, reply)
        if (type(observation) is not PreparationObservation or observation.step_id != step.step_id
                or not _same_reference(observation.provider_ref, step.pinned_provider_ref)
                or observation.input_digest != step.input_digest
                or observation.recovery_correlation != step.recovery_correlation):
            raise IdentityMismatchError("original preparation receipt correlation differs")
        self._nodes._owner_ref(observation.evidence_ref, step.pinned_provider_ref, label="preparation step evidence")
        if not isinstance(observation.prepared_unit.get("unitRef"), Mapping):
            raise GuaranteeUnavailableError("original prepared Unit reference unavailable")
        unit_ref = observation.prepared_unit["unitRef"]
        self._nodes._owner_ref(unit_ref, step.pinned_provider_ref, label="prepared Unit")
        if step.step_id == "prepare" and not any(_same_reference(usage.target_ref, unit_ref) and "use" in usage.rights
                                                 for usage in observation.usages):
            raise GuaranteeUnavailableError("prepared Unit must be held before native start")
        for usage in observation.usages:
            if (usage.expected_revision != 0 or usage.expected_holder_ref is not None or usage.state != "active"
                    or not _same_reference(usage.holder_ref, operation_holder(operation.request, operation.intent.operation_ref))):
                raise IdentityMismatchError("preparation observation must acquire original operation holds")
            _safe_projection(usage.target_ref)
        return observation

    def prepare(self, request, profile_ref, context, options):
        operation = self.reserve(request, profile_ref, context, options)
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
                reply = getattr(admitted.provider, frozen_step.step_id)(argument, invocation)
                if not self._issuer.verified_consumption(invocation):
                    raise GuaranteeUnavailableError("provider did not consume the original invocation")
                observed = self._observe(operation, frozen_step, reply)
                if frozen_step.step_id == "start" and not _same_reference(observed.prepared_unit, argument):
                    raise IdentityMismatchError("start receipt changed the original prepared Unit")
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
        """Reconcile claimed original steps; never dispatch missing steps."""
        env = self._environment
        with env._admission_lock:
            self._permission(request, query=True)
            operation = env._store.read_operation(request)
            if operation is None: return None
            if operation.intent.kind != "agent-preparation":
                raise IdentityMismatchError("request belongs to another operation")
            if operation.status in {"published", "refused", "cancelled"}: return operation
            manifest = self._profiles.read(ProfileRef.from_dict(plain(operation.intent.profile_snapshot_ref)))
            admitted = env.agent_runtime_contribution(manifest.content["harnessDefinitionRef"])
            if (not _same_reference(admitted.provider_ref, operation.intent.steps[0].pinned_provider_ref)
                    or "query_step" not in admitted.descriptor.supported_methods):
                raise GuaranteeUnavailableError("original owner query capability unavailable")
        for step in operation.intent.steps:
            with env._admission_lock:
                record = env._store.read_operation_step(request, step.step_id)
                if record is None: break
                if record.outcome == "concluded": continue
                invocation = self._issuer.issue_query(request, operation.digest, step.step_id)
            try:
                reply = admitted.provider.query_step(step.recovery_correlation, invocation)
                if not self._issuer.verified_observation(invocation):
                    raise GuaranteeUnavailableError("owner did not verify original read invocation")
                observed = self._observe(operation, step, reply)
                if step.step_id == "start":
                    original = env._store.read_operation_step(request, "prepare").evidence["preparedUnit"]
                    if not _same_reference(observed.prepared_unit, original):
                        raise IdentityMismatchError("query receipt changed original Unit")
            except Exception:
                return env._store.read_operation(request)
            evidence = {"evidenceRef": plain(observed.evidence_ref), "preparedUnit": plain(observed.prepared_unit),
                        "acquiredUsages": [self._usage_source(item) for item in observed.usages]}
            self._record_step(operation, step, record.revision, "concluded", evidence, observed.usages)
        return env._store.read_operation(request)

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
