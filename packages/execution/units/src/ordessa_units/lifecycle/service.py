"""Manager-owned Node stop over the original operation and Unit ledgers.

Release/recovery are unavailable until their original transaction/retirement
contracts exist. Historical operation queries remain read-only. Unknown effects
retain their original holds and are never replayed through a runtime provider.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable, UnitIdentityMismatch
from ordessa_units.definitions.admission_identity import AgentNodeRef
from ordessa_units.definitions.operations import OperationIntent, StepIntent, UsageMutation, node_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json

from ordessa_units.admission.invocation import InvocationIssuer
from ordessa_units.bindings.publication import decode_node_ref, encode_node_ref

_TERMINATION_VERSION = "harness-unit-termination/1"
_PRECONDITION_KEYS = frozenset({"expectedPublicationRevision"})
_ACTION_KINDS = {"stop": ("agent-stop", True), "release": ("agent-release", True),
                 "recover": ("agent-recovery", False)}


def _plain(value):
    return json.loads(safe_json({"value": value}))["value"]


def _same(left, right):
    return json.dumps(_plain(left) if left is not None else None, sort_keys=True) == \
        json.dumps(_plain(right) if right is not None else None, sort_keys=True)


def _hashed(value):
    import hashlib
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, default=dict).encode()).hexdigest()


@dataclass(frozen=True)
class LifecycleObservation:
    """Owner-verified receipt of one original lifecycle effect."""
    step_id: str
    provider_ref: Mapping[str, Any]
    input_digest: str
    recovery_correlation: str
    evidence_ref: Mapping[str, Any]
    termination: Mapping[str, Any] | None = None
    recovered_binding: Mapping[str, Any] | None = None

    def __post_init__(self):
        if (not isinstance(self.step_id, str) or not self.step_id
                or not isinstance(self.provider_ref, Mapping)
                or not isinstance(self.input_digest, str) or not self.input_digest
                or not isinstance(self.recovery_correlation, str) or not self.recovery_correlation
                or not isinstance(self.evidence_ref, Mapping)):
            raise ValueError("invalid lifecycle observation identity")
        if self.termination is not None and not isinstance(self.termination, Mapping):
            raise ValueError("termination projection must be a mapping")
        if self.recovered_binding is not None and not isinstance(self.recovered_binding, Mapping):
            raise ValueError("recovered binding must be a mapping")


class LifecycleObservationPort(Protocol):
    """Owner proof of the original lifecycle receipt; an ACK is never enough."""
    def observe(self, operation, step, reply) -> LifecycleObservation: ...


class AgentLifecycle:
    def __init__(self, environment, nodes, *, invocation_issuer=None, observation_port=None,
                 unit_manager=None):
        self._environment, self._nodes = environment, nodes
        self._issuer, self._observation_port = invocation_issuer, observation_port
        self._unit_manager = unit_manager

    def _manager_bound(self):
        from ordessa_units.management.manager import UnitManager
        manager = self._unit_manager
        return (type(manager) is UnitManager
                and manager.records.verifier is manager.verifier
                and getattr(getattr(manager.verifier, "_verify", None), "__self__", None)
                    is self._issuer)

    def capabilities(self):
        try:
            store = self._nodes._store()
        except UnitGuaranteeUnavailable:
            return {"nodeLifecycle": False, "supportedLifecycleActions": []}
        available = (isinstance(self._issuer, InvocationIssuer)
                and self._issuer._store is store
                and self._environment._fingerprint_port is not None
                and callable(getattr(self._observation_port, "observe", None))
                and self._manager_bound())
        return {"nodeLifecycle": available,
                "supportedLifecycleActions": ["stop", "release"] if available else []}

    @staticmethod
    def operation_view(operation):
        return {"operationRef": operation.intent.operation_ref, "revision": operation.revision,
                "status": operation.status, "action": operation.intent.context_ref["lifecycleRequest"]["action"],
                "node": operation.result}

    def _permission(self, request, *, query=False, action=None):
        env = self._environment
        env._check_open()
        if not isinstance(request, RequestKey) or request.principal_scope != env._principal_scope:
            raise UnitAdmissionRefused("lifecycle principal differs from authenticated realm")
        env._check_environment(request.environment_namespace)
        self._nodes._permission(request=request, action=None if query else action)
        self._nodes._store()
        if (not isinstance(self._issuer, InvocationIssuer) or self._issuer._store is not env._store
                or env._fingerprint_port is None
                or not callable(getattr(self._observation_port, "observe", None))):
            raise UnitGuaranteeUnavailable("explicit lifecycle authorities on the same store required")

    def _admit(self, node_ref):
        env = self._environment
        if not isinstance(node_ref, AgentNodeRef):
            raise UnitIdentityMismatch("complete Node identity required")
        env._check_environment(node_ref.environment)
        if env._policy is None or not env._policy.admit_object_access(
                env._principal_scope, f"{env.environment_id}:agents.node:{node_ref.instance_id}", "read"):
            raise UnitAdmissionRefused("Node lifecycle access refused")
        node = self._nodes.read(node_ref)
        if node is None:
            raise UnitGuaranteeUnavailable("published Node unavailable")
        return node_ref, node

    def _owner(self, ref, node, action):
        if action not in ("stop", "release") or not self._manager_bound():
            raise UnitGuaranteeUnavailable("original Unit Manager stop owner required")
        from ordessa_agents.harness.providers.registry.definition_admission import HarnessAdmission
        binding = node["binding"]
        admitted = HarnessAdmission(self._environment).describe_for_cleanup(
            binding["harnessDefinitionRef"], binding["harnessProviderRef"])
        # Resolve before reservation. A cold record is never permission to
        # recreate a live Unit or replay the original factory.
        from ordessa_units.management.manager import UnitManagementRefused
        try:
            self._unit_manager.find(binding["harnessUnitRef"])
        except UnitManagementRefused as error:
            raise UnitGuaranteeUnavailable("original Unit live owner unavailable") from error
        held_rows = self._environment.read_held_node_usages(
            ref, tuple(item["usageId"] for item in node.get("resourceUsageRefs", ())),
            {"original Harness": binding["harnessProviderRef"],
             "original Unit": binding["harnessUnitRef"]},
            allowed_states=(("active", "unknown") if action == "stop" else ("active",)))
        return admitted, held_rows

    def _reserve(self, request, ref, node, preconditions, action):
        env = self._environment
        kind, cleanup = _ACTION_KINDS[action]
        if (not isinstance(preconditions, Mapping)
                or any(key not in _PRECONDITION_KEYS for key in preconditions)):
            raise UnitIdentityMismatch("fixed lifecycle preconditions required")
        if "expectedPublicationRevision" in preconditions:
            # PJ04: the stated base publication revision must match the Node's
            # current one; a stale precondition is a conflict, never an override.
            from ordessa_units.configuration.contracts import ConfigurationRevisionConflict
            if (type(node.get("publicationRevision")) is not int
                    or preconditions["expectedPublicationRevision"] != node["publicationRevision"]):
                raise ConfigurationRevisionConflict("expected Node publication revision differs")
        unit_ref = node["binding"]["harnessUnitRef"]
        fixed = {"action": action, "nodeRef": encode_node_ref(ref), "preconditions": dict(preconditions),
                 "pinnedProviderRef": _plain(node["binding"]["harnessProviderRef"]), "unitRef": _plain(unit_ref)}
        digest = env._fingerprint_port.fingerprint(request, "pacthold.agents.nodes." + action, _hashed(fixed))
        prior = env._store.read_operation(request)
        if prior is not None:
            if prior.digest != digest or prior.intent.kind != kind:
                raise UnitIdentityMismatch("spent lifecycle request differs")
            return prior, None, cleanup, True, None
        admitted, held_rows = self._owner(ref, node, action)
        epoch = node["binding"].get("managementEpoch", node.get("managementEpoch", 0))
        reconciles = (env._store.read_unknown_node_stop_refs(
            request, encode_node_ref(ref), unit_ref, admitted.provider_ref, epoch)
            if action == "stop" else ())
        identity = _hashed({"environmentNamespace": request.environment_namespace,
                            "principalScope": request.principal_scope,
                            "requestId": request.request_id})[7:55]
        operation_ref = "lifecycle-" + action + "-" + identity
        bindings = {action: {"action": action, "targetRef": encode_node_ref(ref),
                             "delegationRef": None, "cleanup": cleanup}}
        context_ref = {"environmentNamespace": env.environment_id,
                       "lifecycleRequest": fixed, "invocationBindings": bindings,
                       # A concluded stop with this marker was claimed through
                       # the original SQLite Node Usage fence, which verifies
                       # the listed unknown stops before native dispatch.
                       "nodeUsageFenceVersion": 1,
                       "nodeUsageFenceSnapshot": [self._fence_row(row) for row in held_rows],
                       "reconcilesUnknownStops": list(reconciles) if action == "stop" else None,
                       "directoryBindingRef": _plain(
                           node["binding"]["preparationContextRef"]["directoryBindingRef"])}
        steps = (StepIntent(action, admitted.provider_ref, digest, operation_ref + "." + action, (), epoch),)
        intent = OperationIntent(operation_ref, kind, unit_ref, context_ref, steps,
                                 encode_node_ref(ref), epoch)
        return env._store.reserve_operation(request, digest, intent), admitted, cleanup, False, held_rows

    def _observe(self, operation, step, reply, action, ref, node):
        observation = self._observation_port.observe(operation, step, reply)
        if (type(observation) is not LifecycleObservation or observation.step_id != step.step_id
                or not _same(observation.provider_ref, step.pinned_provider_ref)
                or observation.input_digest != step.input_digest
                or observation.recovery_correlation != step.recovery_correlation):
            raise UnitIdentityMismatch("original lifecycle receipt correlation differs")
        self._nodes._owner_ref(observation.evidence_ref, step.pinned_provider_ref,
                              label="lifecycle step evidence")
        if action in ("stop", "release"):
            term = observation.termination
            if (not isinstance(term, Mapping) or term.get("version") != _TERMINATION_VERSION
                    or term.get("action") != action or term.get("state") != "confirmed"
                    or not isinstance(term.get("identity"), Mapping)
                    or not _same(term["identity"].get("unitRef"), node["binding"]["harnessUnitRef"])
                    or term["identity"].get("inputDigest") != step.input_digest
                    or not isinstance(term.get("outcome"), Mapping) or not term["outcome"]):
                raise UnitGuaranteeUnavailable("original termination proof unavailable")
        return observation

    @staticmethod
    def _fence_row(row):
        return {"usageId": row["usageId"], "state": row["state"],
                "revision": row["revision"], "rights": list(row["rights"]),
                "targetRef": _plain(row["targetRef"])}

    def _run(self, request, node_ref, preconditions, action):
        env = self._environment
        with env._admission_lock:
            self._permission(request, action=action)
            if action not in ("stop", "release"):
                raise UnitGuaranteeUnavailable("Manager recovery is not admitted")
            ref, node = self._admit(node_ref)
            operation, admitted, cleanup, replay, held_rows = self._reserve(
                request, ref, node, preconditions, action)
            if replay:
                return self.operation_view(operation)  # original request replay, no new effect
            # _owner validated this original projection before reservation.
            # The claim transaction must compare it unchanged; rereading here
            # would silently adopt a different target/rights/revision basis.
            release_holder = node_holder(env.environment_id, ref.instance_id, ref.generation)
            node_usage_fence = {
                "holderRef": release_holder,
                "expectedUsages": tuple({
                    "usageId": row["usageId"], "state": row["state"],
                    "revision": row["revision"], "rights": list(row["rights"]),
                    "targetRef": row["targetRef"],
                } for row in held_rows),
                "allowedStates": ("active", "unknown") if action == "stop" else ("active",),
                "unknownPolicy": action,
            }
            frozen_step = operation.intent.steps[0]
            previous = env._store.read_operation_step(request, frozen_step.step_id)
            if previous is not None:
                return self.operation_view(operation)  # claimed is possibly dispatched, never resent
            if operation.status in {"published", "unknown", "refused", "cancelled"}:
                return self.operation_view(operation)
            invocation = self._issuer.issue(request, operation.digest, frozen_step.step_id,
                                            action, encode_node_ref(ref), cleanup=cleanup,
                                            node_usage_fence=node_usage_fence)
        retirement = None
        try:
            argument = node["binding"]["harnessUnitRef"]
            unit = self._unit_manager.find(argument)
            if action == "stop":
                reply = unit.stop(argument, invocation)
            else:
                reply, retirement = self._unit_manager.release_deferred(argument, invocation)
            if not self._issuer.verified_consumption(invocation):
                raise UnitGuaranteeUnavailable("Unit did not consume the original invocation")
            observed = self._observe(operation, frozen_step, reply, action, ref, node)
            original = self._unit_manager.records.owner_read_termination(argument["unitId"], action)
            if not _same(original, observed.termination):
                raise UnitIdentityMismatch("observation differs from original Unit termination record")
            evidence = {"evidenceRef": _plain(observed.evidence_ref),
                        "termination": _plain(observed.termination) if observed.termination is not None else None,
                        "recoveredBinding": (_plain(observed.recovered_binding)
                                             if observed.recovered_binding is not None else None)}
            evidence = {key: value for key, value in evidence.items() if value is not None}
        except Exception:
            self._record(operation, frozen_step, invocation, "unknown", {})
            return self.operation_view(env._store.read_operation(request))
        if action == "release":
            mutations = tuple(UsageMutation(
                row["usageId"], row["revision"], release_holder, release_holder,
                row["targetRef"], tuple(row["rights"]), "released",
                {"terminationEvidenceRef": _plain(observed.evidence_ref)})
                for row in held_rows)
            self._record(operation, frozen_step, invocation, "concluded", evidence,
                         usages=mutations, release_holder=release_holder)
            # Original Store COMMIT is verified again inside the public owner
            # retirement seam. A failed COMMIT never loses the live handle.
            self._unit_manager.finalize_release(retirement, request=request)
        else:
            self._record(operation, frozen_step, invocation, "concluded", evidence)
        return self.operation_view(env._store.read_operation(request))

    def _record(self, operation, step, invocation, outcome, evidence, usages=(), release_holder=None):
        self._environment._store.record_operation_step(
            operation.request, operation.digest, step.step_id, step.input_digest,
            invocation.facts["claimRevision"], outcome, evidence,
            usages=tuple(usages), release_holder=release_holder)

    def stop(self, request, node_ref, preconditions):
        return self._run(request, node_ref, preconditions, "stop")

    def release(self, request, node_ref, preconditions):
        return self._run(request, node_ref, preconditions, "release")

    def reconcile_release(self, request):
        """Conclude one original live release proof after Node COMMIT failure.

        No native release is repeated. Cold/unknown/changed/expired authority
        refuses; the original possibly-dispatched claim and Usage hold remain.
        """
        from ordessa_units.bindings.publication import decode_node_ref
        env = self._environment
        with env._admission_lock:
            self._permission(request, action="release")
            operation = env._store.read_operation(request)
            if operation is None or operation.intent.kind != "agent-release":
                raise UnitGuaranteeUnavailable("original release operation required")
            ref, node = self._admit(decode_node_ref(operation.intent.node_ref))
            _, rows = self._owner(ref, node, "release")
            snapshot = operation.intent.context_ref.get("nodeUsageFenceSnapshot")
            if snapshot is None or not _same(snapshot, [self._fence_row(row) for row in rows]):
                raise UnitGuaranteeUnavailable("original release Usage fence changed or unavailable")
            step = operation.intent.steps[0]
            claim = env._store.read_operation_step(request, step.step_id)
            if claim is None or claim.outcome != "possibly-dispatched" or operation.status != "running":
                raise UnitGuaranteeUnavailable("original live release claim required")
            argument = node["binding"]["harnessUnitRef"]
            invocation, reply, retirement = self._unit_manager.release_reconciliation(
                argument, request=request)
            observed = self._observe(operation, step, reply, "release", ref, node)
            original = self._unit_manager.records.owner_read_termination(argument["unitId"], "release")
            if not _same(original, observed.termination):
                raise UnitIdentityMismatch("release reconciliation differs from original Unit proof")
            evidence = {"evidenceRef": _plain(observed.evidence_ref),
                        "termination": _plain(observed.termination)}
            holder = node_holder(env.environment_id, ref.instance_id, ref.generation)
            mutations = tuple(UsageMutation(row["usageId"], row["revision"], holder, holder,
                row["targetRef"], tuple(row["rights"]), "released",
                {"terminationEvidenceRef": _plain(observed.evidence_ref)}) for row in rows)
            self._record(operation, step, invocation, "concluded", evidence,
                         usages=mutations, release_holder=holder)
            self._unit_manager.finalize_release(retirement, request=request)
            return self.operation_view(env._store.read_operation(request))

    def finalize_release(self, request):
        """Finish Manager retirement after the original Node/Usage COMMIT.

        No native effect, invocation issue, claim or Usage mutation is repeated.
        The original public Node permission and exact Manager COMMIT read-back
        are still required; unavailable cold receipts refuse.
        """
        from ordessa_units.bindings.publication import decode_node_ref
        env = self._environment
        with env._admission_lock:
            self._permission(request, action="release")
            operation = env._store.read_operation(request)
            if operation is None or operation.intent.kind != "agent-release":
                raise UnitGuaranteeUnavailable("original release operation required")
            _, node = self._admit(decode_node_ref(operation.intent.node_ref))
            if not self._manager_bound():
                raise UnitGuaranteeUnavailable("original Unit Manager release owner required")
            self._unit_manager.finalize_committed_release(
                node["binding"]["harnessUnitRef"], request=request)
            return self.operation_view(env._store.read_operation(request))

    def recover(self, request, node_ref, preconditions):
        return self._run(request, node_ref, preconditions, "recover")

    def query(self, request):
        """Read the original lifecycle operation; never dispatch a step."""
        env = self._environment
        with env._admission_lock:
            self._permission(request, query=True)
            operation = env._store.read_operation(request)
            if operation is None or operation.intent.kind not in {item[0] for item in _ACTION_KINDS.values()}:
                return None
            return self.operation_view(operation)


__all__ = ["AgentLifecycle", "LifecycleObservation", "LifecycleObservationPort"]
