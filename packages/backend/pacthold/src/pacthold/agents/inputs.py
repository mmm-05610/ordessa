"""Managed input reservation on the existing operation/Usage mechanism.

No input text, native session writer, task database or native protocol lives
here. Capture remains in the consumer's existing controlled input store;
NativeSessionBinding remains with the admitted Harness owner. Missing ports
refuse, and a draft with an unresolved attempt cannot evade it with a new key.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping, Protocol, runtime_checkable

from ordessa_environment_api import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError,
    ParticipantInstanceRef, RequestKey, UnknownResultError,
)
from ordessa_environment_api.domain import DomainStorePort, DomainWrite
from ordessa_environment_api.operations import OperationIntent, OperationStorePort, StepIntent, safe_json, sealed_mapping

from .directory import DirectoryBindingRef
from .invocation import InvocationIssuer

DRAFT_ATTEMPTS = "agents.draft-attempts"


def _plain(value):
    return json.loads(safe_json(value))


def _node(value):
    if not isinstance(value, Mapping) or set(value) != {"environmentNamespace", "instanceId", "generation"}:
        raise ValueError("complete ParticipantInstanceRef required")
    return ParticipantInstanceRef(value["environmentNamespace"], value["instanceId"], value["generation"])


@dataclass(frozen=True)
class CapturedInputRef:
    environment_namespace: str
    capture_id: str
    capture_revision: int
    content_digest: str

    def __post_init__(self):
        DirectoryBindingRef(self.environment_namespace, self.capture_id,
                            self.capture_revision, self.content_digest)

    def to_dict(self):
        return {"environmentNamespace": self.environment_namespace, "captureId": self.capture_id,
                "captureRevision": self.capture_revision, "contentDigest": self.content_digest}


@dataclass(frozen=True)
class CapturedInputEvidence:
    ref: CapturedInputRef
    node_ref: Mapping
    draft_id: str
    draft_revision: int

    def __post_init__(self):
        if not isinstance(self.ref, CapturedInputRef):
            raise ValueError("captured input identity required")
        node = _node(self.node_ref)
        RequestKey(self.ref.environment_namespace, "capture", self.draft_id)
        if node.environment != self.ref.environment_namespace or type(self.draft_revision) is not int or self.draft_revision < 1:
            raise ValueError("capture scope/revision differs")
        object.__setattr__(self, "node_ref", sealed_mapping(self.node_ref))


@runtime_checkable
class ControlledInputCapturePort(Protocol):
    """Read-only projection of the existing input store; never a new ledger."""
    def inspect(self, captured_ref: CapturedInputRef, principal: str) -> CapturedInputEvidence | None: ...


@dataclass(frozen=True)
class NativeInputState:
    node_ref: Mapping
    provider_ref: Mapping
    unit_ref: Mapping
    session_ref: Mapping
    source_revision: int
    management_epoch: int
    directory_binding_ref: DirectoryBindingRef
    before_configuration_evidence: Mapping

    def __post_init__(self):
        node = _node(self.node_ref)
        if (type(self.source_revision) is not int or self.source_revision < 1
                or type(self.management_epoch) is not int or self.management_epoch < 0
                or not isinstance(self.directory_binding_ref, DirectoryBindingRef)
                or self.directory_binding_ref.environment_namespace != node.environment):
            raise ValueError("confirmed native binding evidence required")
        for field in ("node_ref", "provider_ref", "unit_ref", "session_ref", "before_configuration_evidence"):
            value = getattr(self, field)
            if not isinstance(value, Mapping) or len(value) < 2 or value.get("environmentNamespace") != node.environment:
                raise ValueError("native evidence scope differs")
            object.__setattr__(self, field, sealed_mapping(value))


@runtime_checkable
class NativeInputStatePort(Protocol):
    """Harness-owned confirmed mapping/config evidence, re-read each time."""
    def inspect(self, node_ref: ParticipantInstanceRef, principal: str) -> NativeInputState | None: ...


class ManagedInputReservations:
    def __init__(self, environment, nodes, capture_port=None, native_state_port=None):
        self._environment, self._nodes = environment, nodes
        self._capture, self._native = capture_port, native_state_port

    @staticmethod
    def _inspect(port, *args):
        try:
            return port.inspect(*args)
        except Exception:
            raise GuaranteeUnavailableError("trusted input evidence is unavailable") from None

    def _admit(self, request, node_ref):
        env = self._environment
        env._check_open()
        env._check_environment(request.environment_namespace)
        if request.principal_scope != env._principal_scope:
            raise AdmissionRefusedError("input principal differs from the authenticated realm")
        if (env._policy is None or not env._policy.admit_invoke(
                env._principal_scope, "pacthold.agents.inputs.reserve", "reliable")
                or not env._policy.admit_object_access(env._principal_scope,
                    f"{env.environment_id}:agents.node:{node_ref.instance_id}", "write")):
            raise AdmissionRefusedError("managed input admission refused")
        if (not isinstance(env._store, OperationStorePort) or not isinstance(env._store, DomainStorePort)
                or env._fingerprint_port is None or not isinstance(self._capture, ControlledInputCapturePort)
                or not isinstance(self._native, NativeInputStatePort)):
            raise GuaranteeUnavailableError("managed input requires explicit capture/native ports and durable core store")
        env._check_environment(node_ref.environment)
        node = self._nodes.read(node_ref)
        if node is None:
            raise GuaranteeUnavailableError("managed input requires an already published node")
        return node

    def reserve(self, request: RequestKey, node_ref: ParticipantInstanceRef,
                captured_ref: CapturedInputRef, native_correlation: Mapping):
        """Fix one attempt; this method never transmits or reads input text.

        Caller chooses a native correlation once. Same-key replay reads the
        old operation; it does not refresh the binding or dispatch a frame.
        """
        env = self._environment
        if not isinstance(captured_ref, CapturedInputRef) or not isinstance(node_ref, ParticipantInstanceRef):
            raise ValueError("complete node and captured-input references required")
        correlation = _plain(native_correlation)
        if set(correlation) != {"environmentNamespace", "protocol", "requestId"} or not isinstance(correlation["protocol"], str) or not correlation["protocol"] or type(correlation["requestId"]) not in (str, int) or isinstance(correlation["requestId"], str) and not correlation["requestId"]:
            raise ValueError("native correlation requires only protocol and native request identity")
        if correlation.get("environmentNamespace") != request.environment_namespace:
            raise IdentityMismatchError("native correlation must carry this Environment")
        with env._admission_lock:
            node = self._admit(request, node_ref)
            evidence = self._inspect(self._capture, captured_ref, request.principal_scope)
            exact_node = {"environmentNamespace": node_ref.environment,
                          "instanceId": node_ref.instance_id, "generation": node_ref.generation}
            if (not isinstance(evidence, CapturedInputEvidence) or evidence.ref != captured_ref
                    or evidence.node_ref != exact_node):
                raise GuaranteeUnavailableError("controlled capture is unavailable for this exact node")
            parameters = {"nodeRef": exact_node, "capturedInputRef": captured_ref.to_dict(),
                          "draftId": evidence.draft_id, "draftRevision": evidence.draft_revision,
                          "nativeCorrelation": correlation}
            digest = env._fingerprint_port.fingerprint(request, "pacthold.agents.inputs.reserve",
                "sha256:" + hashlib.sha256(safe_json(parameters).encode()).hexdigest())
            previous = env._store.read_operation(request)
            if previous is not None:
                if previous.digest != digest or previous.intent.kind != "managed-input":
                    raise IdentityMismatchError("spent input request differs from its captured intent")
                return previous
            # Fence by node+draft, never revision or request id. A caller cannot
            # escape a possibly dispatched draft by changing either field.
            fence_id = "draft-" + hashlib.sha256(safe_json({"nodeRef": exact_node,
                "draftId": evidence.draft_id}).encode()).hexdigest()[:48]
            prior = env._store.read_domain(env.environment_id, DRAFT_ATTEMPTS, fence_id)
            if prior is not None:
                frozen = prior["value"]
                old_key = RequestKey(env.environment_id, frozen["principalScope"], frozen["requestId"])
                old = env._store.read_operation(old_key)
                if (frozen.get("nodeRef") != exact_node or frozen.get("draftId") != evidence.draft_id
                        or old is not None and (old.intent.kind != "managed-input"
                            or old.intent.operation_ref != frozen.get("operationRef")
                            or old.intent.node_ref != exact_node
                            or old.intent.context_ref.get("draftId") != evidence.draft_id)):
                    raise GuaranteeUnavailableError("draft attempt source identity is damaged")
                if old is None or old.status not in {"published", "refused", "cancelled"}:
                    raise UnknownResultError("draft has an unresolved attempt; inspect its original request")
                if evidence.draft_revision <= old.intent.context_ref["draftRevision"]:
                    raise IdentityMismatchError("captured draft revision already has a spent attempt")
            state = self._inspect(self._native, node_ref, request.principal_scope)
            if (not isinstance(state, NativeInputState) or state.node_ref != exact_node
                    or state.provider_ref != node["binding"]["harnessProviderRef"]
                    or state.unit_ref != node["binding"]["harnessUnitRef"]):
                raise GuaranteeUnavailableError("current Harness-owned single-session evidence is unavailable")
            # Current trusted contribution, not a self-reported provider id.
            admitted = env.agent_runtime_contribution(node["binding"]["harnessDefinitionRef"])
            if admitted.provider_ref != state.provider_ref:
                raise AdmissionRefusedError("native provider activation changed")
            operation_id = "input-" + hashlib.sha256(safe_json({"environmentNamespace": env.environment_id,
                "principalScope": request.principal_scope, "requestId": request.request_id}).encode()).hexdigest()[:48]
            step_id = "native-input"
            context = {"environmentNamespace": env.environment_id, **parameters,
                       "directoryBindingRef": state.directory_binding_ref.to_dict(),
                       "nativeSessionRef": _plain(state.session_ref), "sessionSourceRevision": state.source_revision,
                       "beforeConfigurationEvidence": _plain(state.before_configuration_evidence),
                       "invocationBindings": {step_id: {"action": "submitInput", "targetRef": _plain(state.session_ref),
                           "delegationRef": None, "cleanup": False}}}
            step = StepIntent(step_id, state.provider_ref, digest, operation_id + ".submit",
                              management_epoch=state.management_epoch)
            intent = OperationIntent(operation_id, "managed-input", node["lineage"]["profileSnapshotRef"],
                context, (step,), exact_node, state.management_epoch)
            return env._store.reserve_operation(request, digest, intent, writes=(DomainWrite(DRAFT_ATTEMPTS,
                fence_id, prior["revision"] if prior else 0,
                {"nodeRef": exact_node, "draftId": evidence.draft_id, "principalScope": request.principal_scope,
                 "requestId": request.request_id, "operationRef": operation_id}),))

    def claim_dispatch(self, request: RequestKey, issuer: InvocationIssuer):
        """Issue the existing one-shot InvocationContext, never submit input."""
        if not isinstance(issuer, InvocationIssuer):
            raise GuaranteeUnavailableError("existing core invocation issuer required")
        env = self._environment
        with env._admission_lock:
            env._check_open()
            if issuer._store is not env._store:
                raise GuaranteeUnavailableError("invocation issuer must use this Environment's durable store")
            operation = env._store.read_operation(request)
            if operation is None or operation.intent.kind != "managed-input":
                raise GuaranteeUnavailableError("captured input attempt not reserved")
            ref = _node(operation.intent.node_ref)
            node = self._admit(request, ref)
            context = operation.intent.context_ref
            state = self._inspect(self._native, ref, request.principal_scope)
            if (not isinstance(state, NativeInputState)
                    or state.node_ref != operation.intent.node_ref
                    or state.provider_ref != operation.intent.steps[0].pinned_provider_ref
                    or state.unit_ref != node["binding"]["harnessUnitRef"]
                    or state.session_ref != context["nativeSessionRef"]
                    or state.source_revision != context["sessionSourceRevision"]
                    or state.management_epoch != operation.intent.management_epoch
                    or state.directory_binding_ref.to_dict() != context["directoryBindingRef"]
                    or state.before_configuration_evidence != context["beforeConfigurationEvidence"]):
                raise AdmissionRefusedError("native input binding changed before dispatch claim")
            admitted = env.agent_runtime_contribution(node["binding"]["harnessDefinitionRef"])
            if admitted.provider_ref != state.provider_ref:
                raise AdmissionRefusedError("native provider activation changed")
            binding = operation.intent.context_ref["invocationBindings"]["native-input"]
            return issuer.issue(request, operation.digest, "native-input", "submitInput", binding["targetRef"])
