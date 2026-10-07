"""Staged effect assembly over the original preparation operation ledger.

One flow over one store, without copying any Store logic:

  reserve   the original preparation root (prepare/start) through the
            staged-operation/1 store API, with the original holds and node
            identity write; replays are read-only.
  run_root  the original claim/dispatch/observe/record loop for the root
            steps; it never publishes an unsealed recipe.
  seal      five-item field-by-field verification of a candidate
            PreparationEffectPlan against the ORIGINAL operation facts
            (preparation-effects freeze s1), then one atomic phase append,
            which seals (staged-operation/1). Typed refusals and unknown
            facts both leave the operation untouched: no phase, no seal, no
            dispatch, the original occupation is kept.
  publish   the original NodePublication transfer tail, only for a sealed
            recipe whose every step is conclusively recorded.

Effect steps are frozen into the sealed recipe as brand-free StepIntents;
their native execution and material consumption belong to later authorized
lanes. Without a real authorized-materials entry this module only delivers
the control seam: the vertical is PARTIAL (freeze s3/s6), evidenced with
controlled fixtures, never with a fabricated success.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping

from ordessa_environment_api import (
    GuaranteeUnavailableError, IdentityMismatchError, UnknownResultError,
)
from ordessa_environment_api.domain import DomainWrite
from ordessa_environment_api.operations import (
    OperationIntent, StepIntent, UsageMutation, node_holder, operation_holder,
)
from ordessa_environment_api.staged_operations import OperationRecipePhase, StagedOperationRecord

from .assembly import hashed, plain, public_parameters
from .contracts import ProfileManifest, ProfileRef, ProfileValidationError, manifest_content
from .nodes import IDENTITIES, _hash, _request_ref, _same_reference, decode_node_ref, encode_node_ref
from .preparation_effects import FixedEffectScope, PreparationEffectPlan, verify_preparation_effect


def _plain_or_none(value):
    return None if value is None else plain(value)


class StagedAgentAssembly:
    """Effect-phase orchestration reusing one AgentAssembly's authorities."""

    def __init__(self, agent_assembly):
        self._assembly = agent_assembly

    @property
    def _environment(self):
        return self._assembly._environment

    def reserve(self, request, profile_ref, context, options, profile_manifest=None):
        """Reserve the original preparation root through the staged store API.

        Same fixed facts, digest and holds as AgentAssembly.reserve; only the
        reservation API differs (staged-operation/1). A request key already
        spent outside the staged contract is refused by the store.
        """
        assembly = self._assembly
        env = assembly._environment
        with env._admission_lock:
            assembly._permission(request)
            if (profile_ref is None) == (profile_manifest is None):
                raise ProfileValidationError("exactly one configuration source required")
            if not isinstance(context, Mapping) or not isinstance(options, Mapping):
                raise IdentityMismatchError("explicit preparation parameters required")
            snapshot_write = None
            if profile_ref is None:
                if not isinstance(profile_manifest, Mapping):
                    raise ProfileValidationError("complete profile manifest body required")
                profile_ref, snapshot_write = assembly._profiles.stage_snapshot(profile_manifest)
                manifest = ProfileManifest(profile_ref,
                    manifest_content(profile_manifest, env.environment_id))
            elif type(profile_ref) is not ProfileRef:
                raise IdentityMismatchError("fixed Profile and explicit preparation parameters required")
            else:
                manifest = assembly._profiles.read(profile_ref)
            fixed = {"profileRef": profile_ref.to_dict(), "context": public_parameters(context),
                     "options": public_parameters(options)}
            digest = env._fingerprint_port.fingerprint(
                request, "pacthold.agents.nodes.prepare", hashed(fixed))
            prior = env._store.read_staged_operation(request)
            if prior is not None:
                if prior.operation.digest != digest or prior.root_intent.kind != "agent-preparation":
                    raise IdentityMismatchError("spent preparation request differs")
                return prior
            def unresolved(value):
                if isinstance(value, Mapping):
                    return ("secretRef" in value or bool(value.get("resourceRefs"))
                            or any(unresolved(item) for item in value.values()))
                if isinstance(value, (list, tuple)):
                    return any(unresolved(item) for item in value)
                return False
            if unresolved(manifest.content):
                raise GuaranteeUnavailableError(
                    "C1 material acquisition and authorized SecretRef resolution not composed")
            admitted = env.agent_runtime_contribution(manifest.content["harnessDefinitionRef"])
            if not {"plan_preparation", "prepare", "start"} <= set(admitted.descriptor.supported_methods):
                raise GuaranteeUnavailableError("required provider preparation methods unavailable")
            identity = hashed({"environmentNamespace": request.environment_namespace,
                               "principalScope": request.principal_scope,
                               "requestId": request.request_id})[7:55]
            operation_ref = "preparation-" + identity
            node = {"environmentNamespace": env.environment_id,
                    "instanceId": "agent-" + identity, "generation": 1}
            resolved, _, plan_digest = assembly._plan(
                request, manifest, admitted, node, context, options, operation_ref)
            bindings = {name: {"action": name, "targetRef": node, "delegationRef": None,
                               "cleanup": False}
                        for name in ("prepare", "start")}
            context_ref = {"environmentNamespace": env.environment_id,
                           "preparationRequest": fixed,
                           "directoryBindingRef": resolved.directory_binding_ref.to_dict(),
                           "contextSources": plain(resolved.source_refs),
                           "planDigest": plan_digest, "invocationBindings": bindings}
            steps = tuple(StepIntent(name, admitted.provider_ref, digest,
                                     operation_ref + "." + name,
                                     () if name == "prepare" else ("prepare",),
                                     resolved.management_epoch)
                          for name in ("prepare", "start"))
            intent = OperationIntent(
                operation_ref, "agent-preparation", profile_ref.to_dict(), context_ref,
                steps, node, resolved.management_epoch)
            hold = UsageMutation(operation_ref + ".provider", 0, None,
                                 operation_holder(request, operation_ref),
                                 admitted.provider_ref, ("use",), "active")
            ref = decode_node_ref(node)
            node_identity = {"nodeRef": encode_node_ref(ref),
                             "operationRequest": _request_ref(request),
                             "operationRef": operation_ref,
                             "intentDigest": _hash(intent.to_dict())}
            writes = (DomainWrite(IDENTITIES, ref.instance_id, 0, node_identity),)
            if snapshot_write is not None:
                writes = writes + (snapshot_write,)
            return env._store.reserve_staged_operation(
                request, digest, intent, writes=writes, usages=(hold,))

    def run_root(self, request):
        """Dispatch the original root steps; never publish an unsealed recipe.

        A claimed step that is not conclusively recorded is possibly
        dispatched: this loop never resends it. A failed native edge keeps
        its occupation as unknown and never fabricates success.
        """
        assembly = self._assembly
        env = assembly._environment
        while True:
            with env._admission_lock:
                assembly._permission(request)
                staged = env._store.read_staged_operation(request)
                if staged is None:
                    raise GuaranteeUnavailableError("staged preparation is not reserved")
                operation = staged.operation
                if (operation.status in {"published", "unknown", "refused", "cancelled"}
                        or staged.sealed):
                    return operation
                target_step = None
                for frozen_step in staged.root_intent.steps:
                    previous = env._store.read_operation_step(request, frozen_step.step_id)
                    if previous is None:
                        target_step = frozen_step
                        break
                    if previous.outcome != "concluded":
                        return operation
                if target_step is None:
                    return operation
                admitted, plan = assembly._current_plan(request, operation)
                argument = (plan if target_step.step_id == "prepare"
                            else env._store.read_operation_step(
                                request, "prepare").evidence["preparedUnit"])
                invocation = assembly._issuer.issue(
                    request, operation.digest, target_step.step_id, target_step.step_id,
                    operation.intent.node_ref)
            try:
                reply = getattr(admitted.provider, target_step.step_id)(argument, invocation)
                if not assembly._issuer.verified_consumption(invocation):
                    raise GuaranteeUnavailableError(
                        "provider did not consume the original invocation")
                observed = assembly._observe(operation, target_step, reply)
                if (target_step.step_id == "start"
                        and not _same_reference(observed.prepared_unit, argument)):
                    raise IdentityMismatchError(
                        "start receipt changed the original prepared Unit")
                evidence = {"evidenceRef": plain(observed.evidence_ref),
                            "preparedUnit": plain(observed.prepared_unit),
                            "acquiredUsages": [assembly._usage_source(item)
                                               for item in observed.usages]}
            except Exception:
                assembly._record_step(operation, target_step,
                                      invocation.facts["claimRevision"], "unknown", {})
                return env._store.read_operation(request)
            assembly._record_step(operation, target_step,
                                  invocation.facts["claimRevision"], "concluded",
                                  evidence, observed.usages)

    def seal(self, request, plan, *, verified_materials, declaration_digest,
             approved_action_ids):
        """Verify the candidate effect plan, then atomically append and seal.

        Every verification fact is read from the ORIGINAL operation, never
        taken from the caller's assertion: target/scope/before_revision/
        directory/epoch come from the root intent, the provider pin and step
        correlations from the root steps. ``verified_materials`` is the C-lane
        handoff set; while it is absent, any plan referencing materials is
        unknown and no phase may be appended (freeze s4).
        """
        assembly = self._assembly
        env = assembly._environment
        if type(plan) is not PreparationEffectPlan:
            raise IdentityMismatchError("a fixed PreparationEffectPlan is required")
        with env._admission_lock:
            staged = env._store.read_staged_operation(request)
            if staged is None:
                raise GuaranteeUnavailableError("staged preparation is not reserved")
            operation = staged.operation
            root = staged.root_intent
            for frozen_step in root.steps:
                record = env._store.read_operation_step(request, frozen_step.step_id)
                if record is None or record.outcome != "concluded":
                    raise UnknownResultError(
                        "root operation steps must be conclusively recorded before sealing")
            context = plain(operation.intent.context_ref)
            installation = (context.get("contextSources") or {}).get("installationRef") or {}
            scope = verify_preparation_effect(
                plan,
                target=_plain_or_none(root.node_ref),
                scope=_plain_or_none(root.profile_snapshot_ref),
                before_revision=installation.get("sourceRevision"),
                directory_binding_ref=context.get("directoryBindingRef"),
                management_epoch=root.management_epoch,
                pinned_provider_ref=plain(root.steps[0].pinned_provider_ref),
                step_correlations={step.step_id: step.recovery_correlation
                                   for step in root.steps},
                declaration_digest=declaration_digest,
                approved_action_ids=approved_action_ids,
                verified_materials=verified_materials,
            )
            phase = self._phase_for(scope, root, plan)
            intent_digest = hashlib.sha256(operation.intent_json.encode("utf-8")).hexdigest()
            return env._store.append_staged_operation_phase(
                request, operation.digest, operation.revision, intent_digest, phase)

    @staticmethod
    def _phase_for(scope: FixedEffectScope, root, plan: PreparationEffectPlan):
        """Map the fixed scope onto one complete recipe phase.

        Phase steps pin the ORIGINAL provider reference (verified equal to
        the plan pin), carry brand-free action ids as step ids and bind the
        fixed effect digest plus the full scope into new top-level context
        facts (staged contract: context facts are only new top-level keys).
        """
        pin = root.steps[0].pinned_provider_ref
        steps = tuple(StepIntent(step.action_id, pin, step.input_digest,
                                 step.recovery_correlation, step.depends_on,
                                 root.management_epoch)
                      for step in plan.steps)
        target = plain(root.node_ref)
        bindings = {}
        for step in plan.steps:
            bindings[step.action_id] = {"action": step.action_id, "targetRef": target,
                                        "delegationRef": None,
                                        "cleanup": step.action_id in {"release", "stop"}}
        context_facts = {"effectDigest": scope.effect_digest,
                         "fixedEffectScope": scope.to_dict()}
        return OperationRecipePhase("effects-" + scope.plan_id, steps, bindings, context_facts)

    def publish(self, request):
        """Original NodePublication tail for a fully concluded sealed recipe.

        Unsealed recipes are refused by the store (staged-operation/1); a
        sealed recipe whose effect steps are not conclusively recorded is
        refused here as incomplete evidence. Publication never fabricates a
        node from an unresolved step.
        """
        assembly = self._assembly
        env = assembly._environment
        with env._admission_lock:
            assembly._permission(request)
            staged = env._store.read_staged_operation(request)
            if staged is None:
                raise GuaranteeUnavailableError("staged preparation is not reserved")
            operation = staged.operation
            if operation.status in {"published", "unknown", "refused", "cancelled"}:
                return operation
            if not staged.sealed:
                raise UnknownResultError("staged operation must be sealed before publication")
            assembly._current_plan(request, operation)
            ref = decode_node_ref(operation.intent.node_ref)
            owner = operation_holder(request, operation.intent.operation_ref)
            destination = node_holder(ref.environment, ref.instance_id, ref.generation)
            transfers = [UsageMutation(
                operation.intent.operation_ref + ".provider", 1, owner, destination,
                operation.intent.steps[0].pinned_provider_ref, ("use",), "active")]
            for step in operation.intent.steps:
                record = env._store.read_operation_step(request, step.step_id)
                if record is None or record.outcome != "concluded":
                    raise UnknownResultError("publication requires complete step evidence")
                for item in record.evidence.get("acquiredUsages", ()):
                    transfers.append(UsageMutation(
                        item["usageId"], 1, owner, destination, item["targetRef"],
                        tuple(item["rights"]), "active", item["summary"]))
            return assembly._nodes.publish(request, operation.digest, operation.revision,
                                           tuple(transfers))


__all__ = ["StagedAgentAssembly"]
