"""Core lifecycle coordination: stop, release and recover on the original ledger.

One operation kind per lifecycle action over the existing operation store:
stop/release claims are cleanup invocations over the Node's original Unit,
recover claims are ordinary invocations over the persisted native binding.
Providers perform the native effects and record their original termination
evidence on their records owner; the coordinator never fabricates outcomes,
never auto-releases unknown holds and never re-dispatches a claimed step.

release opens the controlled release seam: the released set must be exactly
the Node's active publication Usages and is released in the same transaction
as the concluded step evidence. recover never picks a recent session: the
recovered binding must match the original Node binding field by field.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ordessa_environment_api import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError, RequestKey,
)
from ordessa_environment_api.identity import ParticipantInstanceRef
from ordessa_environment_api.operations import (
    OperationIntent, StepIntent, UsageMutation, node_holder,
)

from pacthold.agents.configuration.change import ConfigurationUnsupported
from pacthold.agents.access.invocation import InvocationIssuer
from pacthold.agents.nodes.publication import decode_node_ref, encode_node_ref

_TERMINATION_VERSION = "harness-unit-termination/1"
_PRECONDITION_KEYS = frozenset({"expectedPublicationRevision"})
_ACTION_KINDS = {"stop": ("agent-stop", True), "release": ("agent-release", True),
                 "recover": ("agent-recovery", False)}


def _plain(value):
    return json.loads(json.dumps(dict(value), default=dict))


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
    def __init__(self, environment, nodes, *, invocation_issuer=None, observation_port=None):
        self._environment, self._nodes = environment, nodes
        self._issuer, self._observation_port = invocation_issuer, observation_port

    def capabilities(self):
        try:
            store = self._nodes._store()
        except GuaranteeUnavailableError:
            return {"nodeLifecycle": False}
        return {"nodeLifecycle": isinstance(self._issuer, InvocationIssuer)
                and self._issuer._store is store
                and self._environment._fingerprint_port is not None
                and callable(getattr(self._observation_port, "observe", None))}

    @staticmethod
    def operation_view(operation):
        return {"operationRef": operation.intent.operation_ref, "revision": operation.revision,
                "status": operation.status, "action": operation.intent.context_ref["lifecycleRequest"]["action"],
                "node": operation.result}

    def _permission(self, request, *, query=False, action=None):
        env = self._environment
        env._check_open()
        if not isinstance(request, RequestKey) or request.principal_scope != env._principal_scope:
            raise AdmissionRefusedError("lifecycle principal differs from authenticated realm")
        env._check_environment(request.environment_namespace)
        self._nodes._permission(request=request, action=None if query else action)
        self._nodes._store()
        if (not isinstance(self._issuer, InvocationIssuer) or self._issuer._store is not env._store
                or env._fingerprint_port is None
                or not callable(getattr(self._observation_port, "observe", None))):
            raise GuaranteeUnavailableError("explicit lifecycle authorities on the same store required")

    def _admit(self, node_ref):
        env = self._environment
        if not isinstance(node_ref, ParticipantInstanceRef):
            raise IdentityMismatchError("complete Node identity required")
        env._check_environment(node_ref.environment)
        if env._policy is None or not env._policy.admit_object_access(
                env._principal_scope, f"{env.environment_id}:agents.node:{node_ref.instance_id}", "read"):
            raise AdmissionRefusedError("Node lifecycle access refused")
        node = self._nodes.read(node_ref)
        if node is None:
            raise GuaranteeUnavailableError("published Node unavailable")
        return node_ref, node

    def _owner(self, node, *methods):
        admitted = self._environment.agent_runtime_contribution(node["binding"]["harnessDefinitionRef"])
        if not _same(admitted.provider_ref, node["binding"]["harnessProviderRef"]):
            raise AdmissionRefusedError("Node owner activation differs")
        if any(method not in admitted.descriptor.supported_methods for method in methods):
            raise ConfigurationUnsupported("owner does not support the requested lifecycle operation")
        return admitted

    def _release_set(self, ref, node):
        env = self._environment
        holder = node_holder(env.environment_id, ref.instance_id, ref.generation)
        declared = {item["usageId"] for item in node.get("resourceUsageRefs", ())}
        rows = env._store.read_usages(env.environment_id, holder)
        if ({row["usageId"] for row in rows} != declared
                or any(row["state"] != "active" for row in rows)):
            raise GuaranteeUnavailableError(
                "release requires exactly the Node's active publication Usages")
        return holder, rows

    def _reserve(self, request, ref, node, preconditions, action):
        env = self._environment
        kind, cleanup = _ACTION_KINDS[action]
        admitted = self._owner(node, action)
        if (not isinstance(preconditions, Mapping)
                or any(key not in _PRECONDITION_KEYS for key in preconditions)):
            raise IdentityMismatchError("fixed lifecycle preconditions required")
        if "expectedPublicationRevision" in preconditions:
            # PJ04: the stated base publication revision must match the Node's
            # current one; a stale precondition is a conflict, never an override.
            from pacthold.agents.configuration.change import ConfigurationRevisionConflict
            if (type(node.get("publicationRevision")) is not int
                    or preconditions["expectedPublicationRevision"] != node["publicationRevision"]):
                raise ConfigurationRevisionConflict("expected Node publication revision differs")
        unit_ref = node["binding"]["harnessUnitRef"]
        fixed = {"action": action, "nodeRef": encode_node_ref(ref), "preconditions": dict(preconditions),
                 "pinnedProviderRef": _plain(admitted.provider_ref), "unitRef": _plain(unit_ref)}
        digest = env._fingerprint_port.fingerprint(request, "pacthold.agents.nodes." + action, _hashed(fixed))
        prior = env._store.read_operation(request)
        if prior is not None:
            if prior.digest != digest or prior.intent.kind != kind:
                raise IdentityMismatchError("spent lifecycle request differs")
            return prior, admitted, cleanup, True
        identity = _hashed({"environmentNamespace": request.environment_namespace,
                            "principalScope": request.principal_scope,
                            "requestId": request.request_id})[7:55]
        operation_ref = "lifecycle-" + action + "-" + identity
        bindings = {action: {"action": action, "targetRef": encode_node_ref(ref),
                             "delegationRef": None, "cleanup": cleanup}}
        context_ref = {"environmentNamespace": env.environment_id,
                       "lifecycleRequest": fixed, "invocationBindings": bindings,
                       "directoryBindingRef": _plain(
                           node["binding"]["preparationContextRef"]["directoryBindingRef"])}
        epoch = node["binding"].get("managementEpoch", node.get("managementEpoch", 0))
        steps = (StepIntent(action, admitted.provider_ref, digest, operation_ref + "." + action, (), epoch),)
        intent = OperationIntent(operation_ref, kind, unit_ref, context_ref, steps,
                                 encode_node_ref(ref), epoch)
        return env._store.reserve_operation(request, digest, intent), admitted, cleanup, False

    def _observe(self, operation, step, reply, action, ref, node):
        observation = self._observation_port.observe(operation, step, reply)
        if (type(observation) is not LifecycleObservation or observation.step_id != step.step_id
                or not _same(observation.provider_ref, step.pinned_provider_ref)
                or observation.input_digest != step.input_digest
                or observation.recovery_correlation != step.recovery_correlation):
            raise IdentityMismatchError("original lifecycle receipt correlation differs")
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
                raise GuaranteeUnavailableError("original termination proof unavailable")
        else:
            binding = observation.recovered_binding
            stored = node["binding"]
            if (not isinstance(binding, Mapping)
                    or not _same(binding.get("harnessUnitRef"), stored["harnessUnitRef"])
                    or {json.dumps(_plain(item), sort_keys=True) for item in binding.get("nativeSessionRefs", ())}
                       != {json.dumps(_plain(item), sort_keys=True) for item in stored.get("nativeSessionRefs", ())}
                    or not _same(binding.get("configurationTargetRef"), stored.get("configurationTargetRef"))
                    or not _same(binding.get("harnessProviderRef"), stored["harnessProviderRef"])):
                raise IdentityMismatchError("recovered native binding differs from the original Node binding")
        return observation

    def _run(self, request, node_ref, preconditions, action):
        env = self._environment
        release_holder = None
        with env._admission_lock:
            self._permission(request, action=action)
            ref, node = self._admit(node_ref)
            operation, admitted, cleanup, replay = self._reserve(request, ref, node, preconditions, action)
            if replay:
                return self.operation_view(operation)  # original request replay, no new effect
            if action == "release":
                # Refused before any claim or dispatch when the release set is
                # not exactly the Node's active publication Usages.
                release_holder, _ = self._release_set(ref, node)
            frozen_step = operation.intent.steps[0]
            previous = env._store.read_operation_step(request, frozen_step.step_id)
            if previous is not None:
                return self.operation_view(operation)  # claimed is possibly dispatched, never resent
            if operation.status in {"published", "unknown", "refused", "cancelled"}:
                return self.operation_view(operation)
            invocation = self._issuer.issue(request, operation.digest, frozen_step.step_id,
                                            action, encode_node_ref(ref), cleanup=cleanup)
        try:
            argument = node["binding"]["harnessUnitRef"] if action != "recover" else node["binding"]
            reply = getattr(admitted.provider, action)(argument, invocation)
            if not self._issuer.verified_consumption(invocation):
                raise GuaranteeUnavailableError("provider did not consume the original invocation")
            observed = self._observe(operation, frozen_step, reply, action, ref, node)
            evidence = {"evidenceRef": _plain(observed.evidence_ref),
                        "termination": _plain(observed.termination) if observed.termination is not None else None,
                        "recoveredBinding": (_plain(observed.recovered_binding)
                                             if observed.recovered_binding is not None else None)}
            evidence = {key: value for key, value in evidence.items() if value is not None}
        except Exception:
            self._record(operation, frozen_step, invocation, "unknown", {})
            return self.operation_view(env._store.read_operation(request))
        if action == "release":
            rows = env._store.read_usages(env.environment_id, release_holder)
            mutations = tuple(UsageMutation(
                row["usageId"], row["revision"], release_holder, release_holder,
                row["targetRef"], tuple(row["rights"]), "released",
                {"terminationEvidenceRef": _plain(observed.evidence_ref)})
                for row in rows)
            self._record(operation, frozen_step, invocation, "concluded", evidence,
                         usages=mutations, release_holder=release_holder)
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
