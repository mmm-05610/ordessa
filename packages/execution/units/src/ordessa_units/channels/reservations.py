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

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable, UnitIdentityMismatch, UnitOperationUnknown
from ordessa_units.definitions.admission_identity import AgentNodeRef
from ordessa_infrastructure.database.records import (
    DomainStorePort,
    DomainWrite,
)
from ordessa_units.definitions.operations import OperationIntent, OperationStorePort, StepIntent, UsageMutation, node_holder, operation_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping

from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import InvocationAuthorityRefused, InvocationIssuer
from ordessa_execution_agents.harness.providers.registry.definition_admission import HarnessAdmission

DRAFT_ATTEMPTS = "agents.draft-attempts"
FIRST_SESSION_ATTEMPTS = "agents.first-session-attempts"
SESSIONLESS_INPUT_VERSION = "harness-sessionless-input/1"
FIRST_INPUT_RESULT_VERSION = "managed-first-input-result/1"


def _plain(value):
    return json.loads(safe_json(value))


def _node(value):
    if not isinstance(value, Mapping) or set(value) != {"environmentNamespace", "instanceId", "generation"}:
        raise ValueError("complete AgentNodeRef required")
    return AgentNodeRef(value["environmentNamespace"], value["instanceId"], value["generation"])


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


@dataclass(frozen=True)
class SessionlessNativeInputState:
    """Owner-observed confirmed Unit with no Session, never a fake SessionRef.

    The trusted owner re-verifies the original Unit confirmation and absence
    at every inspection. Provenance shape alone does not establish those facts.
    A Unit submitInput grant covers the whole native input, including Session
    creation; Session/start grants cannot be substituted by the consumer.
    """
    node_ref: Mapping
    provider_ref: Mapping
    unit_ref: Mapping
    unit_confirmation_ref: Mapping
    session_absence_ref: Mapping
    management_epoch: int
    directory_binding_ref: DirectoryBindingRef
    before_configuration_evidence: Mapping

    def __post_init__(self):
        node = _node(self.node_ref)
        if (type(self.management_epoch) is not int or self.management_epoch < 0
                or not isinstance(self.directory_binding_ref, DirectoryBindingRef)
                or self.directory_binding_ref.environment_namespace != node.environment):
            raise ValueError("current sessionless Unit evidence required")
        for field in ("node_ref", "provider_ref", "unit_ref", "unit_confirmation_ref",
                      "session_absence_ref", "before_configuration_evidence"):
            value = getattr(self, field)
            if not isinstance(value, Mapping) or len(value) < 2 or value.get("environmentNamespace") != node.environment:
                raise ValueError("sessionless evidence scope differs")
            object.__setattr__(self, field, sealed_mapping(value))
        if (set(self.unit_ref) != {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}
                or not isinstance(self.unit_ref["unitId"], str) or not self.unit_ref["unitId"]
                or safe_json(self.unit_ref["ownerProviderRef"]) != safe_json(self.provider_ref)
                or not isinstance(self.unit_ref["sourceRevision"], str) or not self.unit_ref["sourceRevision"]):
            raise ValueError("complete original Unit source reference required")
        for ref in (self.unit_confirmation_ref, self.session_absence_ref):
            if (set(ref) != {"environmentNamespace", "ownerProviderRef", "sourceRevision", "ref"}
                    or safe_json(ref["ownerProviderRef"]) != safe_json(self.provider_ref)
                    or any(not isinstance(ref[key], str) or not ref[key] or len(ref[key]) > 256
                           or any(ord(c) < 32 for c in ref[key]) for key in ("sourceRevision", "ref"))):
                raise ValueError("original Unit confirmation and Session absence sources required")

    def binding(self):
        return {"contractVersion": SESSIONLESS_INPUT_VERSION, "unitRef": _plain(self.unit_ref),
                "unitConfirmationRef": _plain(self.unit_confirmation_ref),
                "sessionAbsenceRef": _plain(self.session_absence_ref)}


@runtime_checkable
class NativeInputStatePort(Protocol):
    """Harness-owned confirmed mapping/config evidence, re-read each time."""
    def inspect(self, node_ref: AgentNodeRef, principal: str) -> NativeInputState | SessionlessNativeInputState | None: ...


@dataclass(frozen=True)
class FirstInputObservation:
    """Two independently verified original-owner facts, never a task status.

    The deployment owner observes the original claimed input receipt and the
    original journal association. References alone are not native proof.
    Usages describe the original receipt's frozen mutations, including after
    a concluded-step/publication crash; they are not a new Usage registry.
    """
    identity: Mapping
    association_ref: Mapping
    session_ref: Mapping
    session_source_revision: int
    effect_evidence_ref: Mapping
    usages: tuple[UsageMutation, ...] = ()

    def __post_init__(self):
        if type(self.session_source_revision) is not int or self.session_source_revision < 2:
            raise ValueError("original Session association revision required")
        if not isinstance(self.usages, tuple) or any(type(item) is not UsageMutation for item in self.usages):
            raise ValueError("original Usage mutations required")
        for name in ("identity", "association_ref", "session_ref", "effect_evidence_ref"):
            object.__setattr__(self, name, sealed_mapping(getattr(self, name)))


@runtime_checkable
class FirstInputObservationPort(Protocol):
    """Explicit read-only owner; missing/unknown facts return None or refuse.

    Verify the opaque original query, original journal association and actual
    input effect separately, including capture/native correlation, receipt,
    Unit/process/transport/root and current authority. Never send/start here.
    """
    def observe(self, operation, query_context) -> FirstInputObservation | None: ...


class ManagedInputReservations:
    def __init__(self, environment, nodes, capture_port=None, native_state_port=None,
                 first_input_observation_port=None, invocation_issuer=None):
        self._environment, self._nodes = environment, nodes
        self._capture, self._native = capture_port, native_state_port
        self._first_observation = first_input_observation_port
        # The deployment issuer is fixed when the Agent services are composed.
        # Per-call issuer arguments below are retained for compatibility, but
        # can never be used to late-bind an authority after reservation.
        self._issuer = invocation_issuer

    def _require_issuer(self, supplied):
        env = self._environment
        configured = self._issuer
        if (not isinstance(configured, InvocationIssuer) or configured._store is not env._store
                or not isinstance(supplied, InvocationIssuer)):
            raise UnitGuaranteeUnavailable("managed input requires its configured core invocation issuer")
        if supplied._store is not env._store:
            raise UnitGuaranteeUnavailable("invocation issuer must use this Environment's durable store")
        if supplied is not configured:
            raise InvocationAuthorityRefused("managed input issuer differs from its deployment binding")
        return configured

    @staticmethod
    def _first_identity(operation):
        intent, request = operation.intent, operation.request
        context = intent.context_ref
        if intent.kind != "managed-input" or not isinstance(context.get("sessionlessInputBinding"), Mapping):
            raise UnitGuaranteeUnavailable("original sessionless managed input required")
        binding = context["sessionlessInputBinding"]
        if (set(binding) != {"contractVersion", "unitRef", "unitConfirmationRef", "sessionAbsenceRef"}
                or len(intent.steps) != 1
                or intent.steps[0].step_id != "native-input"
                or intent.steps[0].input_digest != operation.digest
                or binding.get("contractVersion") != SESSIONLESS_INPUT_VERSION
                or safe_json(context["invocationBindings"]["native-input"]) != safe_json(
                    {"action": "submitInput", "targetRef": binding["unitRef"],
                     "delegationRef": None, "cleanup": False})):
            raise UnitGuaranteeUnavailable("original Unit submitInput identity unavailable")
        return {"request": {"environmentNamespace": request.environment_namespace,
                    "principalScope": request.principal_scope, "requestId": request.request_id},
                "operationRef": intent.operation_ref, "stepId": "native-input",
                "inputDigest": operation.digest, "providerRef": intent.steps[0].pinned_provider_ref,
                "unitRef": binding["unitRef"], "nodeRef": intent.node_ref,
                "managementEpoch": intent.management_epoch, "nativeCorrelation": context["nativeCorrelation"],
                "unitConfirmationRef": binding["unitConfirmationRef"],
                "sessionAbsenceRef": binding["sessionAbsenceRef"],
                "capturedInputRef": context["capturedInputRef"]}

    @staticmethod
    def _first_result(evidence):
        return {"contractVersion": FIRST_INPUT_RESULT_VERSION,
                "nodeRef": evidence["identity"]["nodeRef"],
                "operationRef": evidence["identity"]["operationRef"],
                "inputDigest": evidence["identity"]["inputDigest"],
                "associationRef": evidence["associationRef"], "sessionRef": evidence["sessionRef"],
                "sessionSourceRevision": evidence["sessionSourceRevision"],
                "effectEvidenceRef": evidence["effectEvidenceRef"]}

    def _observation_evidence(self, operation, observation):
        if not isinstance(observation, FirstInputObservation):
            raise UnitOperationUnknown("original input effect and Session association are not both known")
        identity = self._first_identity(operation)
        if safe_json(observation.identity) != safe_json(identity):
            raise UnitIdentityMismatch("first-input observation differs from its original input")
        for ref in (observation.association_ref, observation.session_ref, observation.effect_evidence_ref):
            if (set(ref) != {"environmentNamespace", "ownerProviderRef", "sourceRevision", "ref"}
                    or ref["environmentNamespace"] != operation.request.environment_namespace
                    or safe_json(ref["ownerProviderRef"]) != safe_json(identity["providerRef"])
                    or any(not isinstance(ref[key], str) or not ref[key] or len(ref[key]) > 256
                           or any(ord(c) < 32 for c in ref[key]) for key in ("sourceRevision", "ref"))):
                raise UnitGuaranteeUnavailable("original owner evidence source unavailable")
        if safe_json(observation.association_ref) == safe_json(observation.effect_evidence_ref):
            raise UnitGuaranteeUnavailable("Session identity cannot substitute for input effect evidence")
        owner = operation_holder(operation.request, operation.intent.operation_ref)
        usages = []
        for usage in observation.usages:
            if (safe_json(usage.holder_ref) != safe_json(owner) or usage.state != "active"
                    or safe_json({"ref": usage.expected_holder_ref}) != safe_json(
                        {"ref": owner if usage.expected_revision else None})):
                raise UnitIdentityMismatch("original input Usage must remain with its original operation")
            usages.append({"usageId": usage.usage_id, "revision": usage.expected_revision + 1,
                           "targetRef": usage.target_ref, "rights": list(usage.rights), "payload": usage.payload})
        if len({item["usageId"] for item in usages}) != len(usages):
            raise UnitIdentityMismatch("duplicate original input Usage")
        return _plain({"contractVersion": FIRST_INPUT_RESULT_VERSION, "identity": identity,
                       "associationRef": observation.association_ref, "sessionRef": observation.session_ref,
                       "sessionSourceRevision": observation.session_source_revision,
                       "effectEvidenceRef": observation.effect_evidence_ref, "acquiredUsages": usages})

    def _stored_first_evidence(self, operation, evidence):
        """Validate the frozen recipe, including JSON types, without refreshing CAS."""
        try:
            owner = operation_holder(operation.request, operation.intent.operation_ref)
            acquisitions = tuple(UsageMutation(item["usageId"], item["revision"] - 1,
                owner if item["revision"] > 1 else None, owner, item["targetRef"],
                tuple(item["rights"]), "active", item["payload"]) for item in evidence["acquiredUsages"])
            observation = FirstInputObservation(evidence["identity"], evidence["associationRef"],
                evidence["sessionRef"], evidence["sessionSourceRevision"], evidence["effectEvidenceRef"], acquisitions)
            verified = self._observation_evidence(operation, observation)
            if safe_json(verified) != safe_json(evidence):
                raise ValueError()
            return verified
        except Exception:
            raise UnitGuaranteeUnavailable("stored first-input publication evidence is inconsistent") from None

    @staticmethod
    def _inspect(port, *args):
        try:
            return port.inspect(*args)
        except Exception:
            raise UnitGuaranteeUnavailable("trusted input evidence is unavailable") from None

    @staticmethod
    def _first_fence_id(node_ref, unit_ref):
        return "first-session-" + hashlib.sha256(safe_json(
            {"nodeRef": node_ref, "unitRef": unit_ref}).encode()).hexdigest()[:48]

    def _first_fence(self, node_ref, unit_ref):
        """Read original held or published reservation, never infer from Session."""
        env = self._environment
        fence_id = self._first_fence_id(node_ref, unit_ref)
        prior = env._store.read_domain(env.environment_id, FIRST_SESSION_ATTEMPTS, fence_id)
        if prior is None:
            return fence_id, None
        frozen = prior["value"]
        try:
            old = env._store.read_operation(RequestKey(env.environment_id,
                frozen["principalScope"], frozen["requestId"]))
            context = old.intent.context_ref
            fields = {"nodeRef", "unitRef", "state", "principalScope", "requestId", "operationRef",
                      "inputDigest", "binding", "providerRef", "managementEpoch", "nativeCorrelation"}
            if frozen["state"] == "resolved":
                fields.add("publicationResult")
            valid = (set(frozen) == fields and old.intent.kind == "managed-input" and old.digest == frozen["inputDigest"]
                and old.intent.operation_ref == frozen["operationRef"]
                and old.intent.management_epoch == frozen["managementEpoch"]
                and safe_json(old.intent.node_ref) == safe_json(node_ref)
                and safe_json(context["sessionlessInputBinding"]["unitRef"]) == safe_json(unit_ref)
                and safe_json(frozen["nodeRef"]) == safe_json(node_ref)
                and safe_json(frozen["unitRef"]) == safe_json(unit_ref)
                and safe_json(context["sessionlessInputBinding"]) == safe_json(frozen["binding"])
                and safe_json(context["nativeCorrelation"]) == safe_json(frozen["nativeCorrelation"])
                and safe_json(old.intent.steps[0].pinned_provider_ref) == safe_json(frozen["providerRef"])
                and type(frozen["managementEpoch"]) is int and type(prior["revision"]) is int)
            self._first_identity(old)
            if frozen["state"] == "held":
                valid = (valid and prior["revision"] == 1 and "publicationResult" not in frozen
                         and old.status != "published")
            elif frozen["state"] == "resolved":
                step = env._store.read_operation_step(old.request, "native-input")
                evidence = self._stored_first_evidence(old, step.evidence)
                result = self._first_result(evidence)
                valid = (valid and prior["revision"] == 2 and old.status == "published"
                    and step.outcome == "concluded" and safe_json(old.result) == safe_json(result)
                    and safe_json(frozen["publicationResult"]) == safe_json(result))
            else:
                valid = False
        except Exception:
            valid = False
        if not valid:
            raise UnitGuaranteeUnavailable("first Session attempt source identity is damaged")
        return fence_id, prior

    @staticmethod
    def _admit_after_first(prior, state):
        if prior is None:
            return
        if prior["value"]["state"] == "held":
            raise UnitOperationUnknown("Unit first input retains its original association fence; inspect the original request")
        result = prior["value"]["publicationResult"]
        if (not isinstance(state, NativeInputState)
                or safe_json(state.session_ref) != safe_json(result["sessionRef"])
                or state.source_revision != result["sessionSourceRevision"]):
            raise UnitGuaranteeUnavailable("current Session differs from the original published input association")

    def _first_publication_permission(self, request, identity):
        env = self._environment
        env._check_open()
        env._check_environment(request.environment_namespace)
        ref = _node(identity["nodeRef"])
        if (request.principal_scope != env._principal_scope or env._policy is None
                or not env._policy.admit_invoke(env._principal_scope, "pacthold.agents.inputs.query", "reliable")
                or not env._policy.admit_object_access(env._principal_scope,
                    f"{env.environment_id}:agents.node:{ref.instance_id}", "write")):
            raise UnitAdmissionRefused("original input observation/publication admission refused")
        node = self._nodes.read(ref)
        if (node is None or safe_json(node["binding"]["harnessUnitRef"]) != safe_json(identity["unitRef"])
                or safe_json(HarnessAdmission(env).describe(node["binding"]["harnessDefinitionRef"]).provider_ref)
                != safe_json(identity["providerRef"])):
            raise UnitAdmissionRefused("original published Unit/provider unavailable")

    def reconcile_first_input(self, request: RequestKey, issuer: InvocationIssuer):
        """Read the original owner, conclude two facts, publish the original recipe.

        No dispatch/start/claim. Step conclusion and publication are separate
        transactions: a crash between them leaves the first fence held. The
        original step recipe survives cold recovery and published replay.
        """
        env = self._environment
        with env._admission_lock:
            env._check_open()
            env._check_environment(request.environment_namespace)
            if request.principal_scope != env._principal_scope:
                raise UnitAdmissionRefused("input principal differs from the authenticated realm")
            if (env._policy is None or not env._policy.admit_invoke(
                    env._principal_scope, "pacthold.agents.inputs.query", "reliable")):
                raise UnitAdmissionRefused("original input observation admission refused")
            issuer = self._require_issuer(issuer)
            if (not isinstance(env._store, OperationStorePort) or not isinstance(env._store, DomainStorePort)
                    or not isinstance(self._first_observation, FirstInputObservationPort)):
                raise UnitGuaranteeUnavailable("original input observation requires explicit owner and core issuer")
            operation = env._store.read_operation(request)
            if operation is None:
                raise UnitGuaranteeUnavailable("original input attempt unavailable")
            identity = self._first_identity(operation)
            ref = _node(identity["nodeRef"])
            self._first_publication_permission(request, identity)
            fence_id, fence = self._first_fence(identity["nodeRef"], identity["unitRef"])
            if (fence is None or fence["value"]["principalScope"] != request.principal_scope
                    or fence["value"]["requestId"] != request.request_id):
                raise UnitGuaranteeUnavailable("original first-input reservation unavailable")
            step = env._store.read_operation_step(request, "native-input")
            if step is None or step.outcome == "refused" or operation.status in {"refused", "cancelled"}:
                raise UnitOperationUnknown("original input has no reconcilable claim")
            query = issuer.issue_query(request, operation.digest, "native-input")
        try:
            observation = self._first_observation.observe(operation, query)
        except Exception:
            raise UnitGuaranteeUnavailable("original input owner observation unavailable") from None
        if not issuer.verified_observation(query):
            raise UnitGuaranteeUnavailable("original owner did not verify its read-only invocation")
        verifier = issuer.verifier()
        verifier.verify_claimed_query(query, identity["providerRef"], identity["unitRef"],
                                      operation.digest, operation_kind="managed-input")
        evidence = self._observation_evidence(operation, observation)
        with env._admission_lock:
            self._first_publication_permission(request, identity)
            verifier.verify_claimed_query(query, identity["providerRef"], identity["unitRef"],
                                          operation.digest, operation_kind="managed-input")
            if step.outcome == "concluded":
                frozen = self._stored_first_evidence(operation, step.evidence)
                if safe_json(frozen) != safe_json(evidence):
                    raise UnitIdentityMismatch("original concluded input observation changed")
            else:
                # Original revision, never refresh a stale reply into a newer write.
                env._store.record_operation_step(request, operation.digest, "native-input", operation.digest,
                    step.revision, "concluded", evidence, usages=observation.usages, require_complete_usages=True)
            current = env._store.read_operation(request)
            result = self._first_result(evidence)
            # Both new publication and replay carry exactly the original CAS1 write.
            marker = {key: value for key, value in fence["value"].items() if key != "publicationResult"}
            marker.update(state="resolved", publicationResult=result)
            write = DomainWrite(FIRST_SESSION_ATTEMPTS, fence_id, 1, marker)
            owner = operation_holder(request, operation.intent.operation_ref)
            destination = node_holder(ref.environment, ref.instance_id, ref.generation)
            transfers = tuple(UsageMutation(item["usageId"], item["revision"], owner, destination,
                item["targetRef"], tuple(item["rights"]), "active", item["payload"]) for item in evidence["acquiredUsages"])
            self._first_publication_permission(request, identity)
            verifier.verify_claimed_query(query, identity["providerRef"], identity["unitRef"],
                                          operation.digest, operation_kind="managed-input")
            return env._store.publish_operation(request, operation.digest, current.revision,
                ("native-input",), (write,), transfers, result)

    def _admit_request(self, request):
        env = self._environment
        env._check_open()
        env._check_environment(request.environment_namespace)
        if request.principal_scope != env._principal_scope:
            raise UnitAdmissionRefused("input principal differs from the authenticated realm")
        if (env._policy is None or not env._policy.admit_invoke(
                env._principal_scope, "pacthold.agents.inputs.reserve", "reliable")):
            raise UnitAdmissionRefused("managed input admission refused")

    def _admit_node(self, request, node_ref):
        env = self._environment
        if (not env._policy.admit_object_access(env._principal_scope,
                f"{env.environment_id}:agents.node:{node_ref.instance_id}", "write")):
            raise UnitAdmissionRefused("managed input admission refused")
        if (not isinstance(env._store, OperationStorePort) or not isinstance(env._store, DomainStorePort)
                or env._fingerprint_port is None or not isinstance(self._capture, ControlledInputCapturePort)
                or not isinstance(self._native, NativeInputStatePort)):
            raise UnitGuaranteeUnavailable("managed input requires explicit capture/native ports and durable core store")
        env._check_environment(node_ref.environment)
        node = self._nodes.read(node_ref)
        if node is None:
            raise UnitGuaranteeUnavailable("managed input requires an already published node")
        return node

    def _admit(self, request, node_ref):
        self._admit_request(request)
        return self._admit_node(request, node_ref)

    def reserve(self, request: RequestKey, node_ref: AgentNodeRef,
                captured_ref: CapturedInputRef, native_correlation: Mapping, *,
                managed_context: Mapping | None = None):
        """Fix one attempt; this method never transmits or reads input text.

        Caller chooses a native correlation once. Same-key replay reads the
        old operation; it does not refresh the binding or dispatch a frame.
        """
        env = self._environment
        if not isinstance(captured_ref, CapturedInputRef) or not isinstance(node_ref, AgentNodeRef):
            raise ValueError("complete node and captured-input references required")
        correlation = _plain(native_correlation)
        if set(correlation) != {"environmentNamespace", "protocol", "requestId"} or not isinstance(correlation["protocol"], str) or not correlation["protocol"] or type(correlation["requestId"]) not in (str, int) or isinstance(correlation["requestId"], str) and not correlation["requestId"]:
            raise ValueError("native correlation requires only protocol and native request identity")
        if managed_context is not None:
            if (not isinstance(managed_context, Mapping)
                    or set(managed_context) != {"managedDispatchBinding", "workspaceExecutionEvidence"}
                    or not isinstance(managed_context["managedDispatchBinding"], Mapping)
                    or not isinstance(managed_context["workspaceExecutionEvidence"], Mapping)):
                raise ValueError("complete managed dispatch and Workspace evidence required")
            managed_context = _plain(managed_context)
        if correlation.get("environmentNamespace") != request.environment_namespace:
            raise UnitIdentityMismatch("native correlation must carry this Environment")
        with env._admission_lock:
            node = self._admit(request, node_ref)
            evidence = self._inspect(self._capture, captured_ref, request.principal_scope)
            exact_node = {"environmentNamespace": node_ref.environment,
                          "instanceId": node_ref.instance_id, "generation": node_ref.generation}
            if (not isinstance(evidence, CapturedInputEvidence) or evidence.ref != captured_ref
                    or evidence.node_ref != exact_node):
                raise UnitGuaranteeUnavailable("controlled capture is unavailable for this exact node")
            parameters = {"nodeRef": exact_node, "capturedInputRef": captured_ref.to_dict(),
                          "draftId": evidence.draft_id, "draftRevision": evidence.draft_revision,
                          "nativeCorrelation": correlation}
            if managed_context is not None:
                parameters.update(managed_context)
            digest = env._fingerprint_port.fingerprint(request, "pacthold.agents.inputs.reserve",
                "sha256:" + hashlib.sha256(safe_json(parameters).encode()).hexdigest())
            previous = env._store.read_operation(request)
            if previous is not None:
                if previous.digest != digest or previous.intent.kind != "managed-input":
                    raise UnitIdentityMismatch("spent input request differs from its captured intent")
                return previous
            fence_id, prior = self._check_draft_attempt_fence(exact_node, evidence)
            state = self._inspect(self._native, node_ref, request.principal_scope)
            if (not isinstance(state, (NativeInputState, SessionlessNativeInputState))
                    or safe_json(state.node_ref) != safe_json(exact_node)
                    or safe_json(state.provider_ref) != safe_json(node["binding"]["harnessProviderRef"])
                    or safe_json(state.unit_ref) != safe_json(node["binding"]["harnessUnitRef"])):
                raise UnitGuaranteeUnavailable("current Harness-owned input binding evidence is unavailable")
            first_fence_id, first_prior = self._first_fence(exact_node, state.unit_ref)
            self._admit_after_first(first_prior, state)
            # The role catalog checks the current fixed pin; native state and
            # dispatch remain with the separately bound original Unit owner.
            admitted = HarnessAdmission(env).describe(node["binding"]["harnessDefinitionRef"])
            if safe_json(admitted.provider_ref) != safe_json(state.provider_ref):
                raise UnitAdmissionRefused("native provider activation changed")
            operation_id = "input-" + hashlib.sha256(safe_json({"environmentNamespace": env.environment_id,
                "principalScope": request.principal_scope, "requestId": request.request_id}).encode()).hexdigest()[:48]
            step_id = "native-input"
            first_input = isinstance(state, SessionlessNativeInputState)
            target = state.unit_ref if first_input else state.session_ref
            binding_evidence = ({"sessionlessInputBinding": state.binding()} if first_input else
                                {"nativeSessionRef": _plain(state.session_ref), "sessionSourceRevision": state.source_revision})
            context = {"environmentNamespace": env.environment_id, **parameters,
                       "directoryBindingRef": state.directory_binding_ref.to_dict(),
                       **binding_evidence,
                       "beforeConfigurationEvidence": _plain(state.before_configuration_evidence),
                       "invocationBindings": {step_id: {"action": "submitInput", "targetRef": _plain(target),
                           "delegationRef": None, "cleanup": False}}}
            step = StepIntent(step_id, state.provider_ref, digest, operation_id + ".submit",
                              management_epoch=state.management_epoch)
            intent = OperationIntent(operation_id, "managed-input", node["lineage"]["profileSnapshotRef"],
                context, (step,), exact_node, state.management_epoch)
            writes = (DomainWrite(DRAFT_ATTEMPTS,
                fence_id, prior["revision"] if prior else 0,
                {"nodeRef": exact_node, "draftId": evidence.draft_id, "principalScope": request.principal_scope,
                 "requestId": request.request_id, "operationRef": operation_id}),)
            if first_input:
                writes += (DomainWrite(FIRST_SESSION_ATTEMPTS, first_fence_id, 0,
                    {"nodeRef": exact_node, "unitRef": _plain(state.unit_ref), "state": "held",
                     "principalScope": request.principal_scope, "requestId": request.request_id,
                     "operationRef": operation_id, "inputDigest": digest, "binding": state.binding(),
                     "providerRef": _plain(state.provider_ref), "managementEpoch": state.management_epoch,
                     "nativeCorrelation": correlation}),)
            return env._store.reserve_operation(request, digest, intent, writes=writes)

    def check_draft_attempt(self, request: RequestKey, node_ref: AgentNodeRef,
                            captured_ref: CapturedInputRef):
        """Reject an unresolved draft before any provider prepares a native frame."""
        env = self._environment
        if not isinstance(captured_ref, CapturedInputRef) or not isinstance(node_ref, AgentNodeRef):
            raise ValueError("complete node and captured-input references required")
        with env._admission_lock:
            self._admit_request(request)
            node = self._admit_node(request, node_ref)
            evidence = self._inspect(self._capture, captured_ref, request.principal_scope)
            exact_node = {"environmentNamespace": node_ref.environment,
                          "instanceId": node_ref.instance_id, "generation": node_ref.generation}
            if (not isinstance(evidence, CapturedInputEvidence) or evidence.ref != captured_ref
                    or evidence.node_ref != exact_node):
                raise UnitGuaranteeUnavailable("controlled capture is unavailable for this exact node")
            self._check_draft_attempt_fence(exact_node, evidence)
            return node

    def _check_draft_attempt_fence(self, exact_node, evidence):
        env = self._environment
        fence_id = "draft-" + hashlib.sha256(safe_json({"nodeRef": exact_node,
            "draftId": evidence.draft_id}).encode()).hexdigest()[:48]
        prior = env._store.read_domain(env.environment_id, DRAFT_ATTEMPTS, fence_id)
        if prior is None:
            return fence_id, None
        frozen = prior["value"]
        old_key = RequestKey(env.environment_id, frozen["principalScope"], frozen["requestId"])
        old = env._store.read_operation(old_key)
        if (frozen.get("nodeRef") != exact_node or frozen.get("draftId") != evidence.draft_id
                or old is not None and (old.intent.kind != "managed-input"
                    or old.intent.operation_ref != frozen.get("operationRef")
                    or old.intent.node_ref != exact_node
                    or old.intent.context_ref.get("draftId") != evidence.draft_id)):
            raise UnitGuaranteeUnavailable("draft attempt source identity is damaged")
        if old is None or old.status not in {"published", "refused", "cancelled"}:
            raise UnitOperationUnknown("draft has an unresolved attempt; inspect its original request")
        if evidence.draft_revision <= old.intent.context_ref["draftRevision"]:
            raise UnitIdentityMismatch("captured draft revision already has a spent attempt")
        return fence_id, prior

    def read_existing(self, request: RequestKey):
        """Read an exact request before touching capture content or native frames.

        This is only an idempotency lookup. It issues no invocation, refreshes
        no owner evidence, and cannot authorize dispatch.
        """
        env = self._environment
        with env._admission_lock:
            self._admit_request(request)
            if not isinstance(env._store, OperationStorePort):
                raise UnitGuaranteeUnavailable("durable operation lookup is unavailable")
            operation = env._store.read_operation(request)
            if operation is not None and operation.intent.kind != "managed-input":
                raise UnitIdentityMismatch("request key belongs to a different operation")
            return operation

    def claim_dispatch(self, request: RequestKey, issuer: InvocationIssuer):
        """Issue the existing one-shot InvocationContext, never submit input."""
        env = self._environment
        with env._admission_lock:
            env._check_open()
            self._admit_request(request)
            issuer = self._require_issuer(issuer)
            operation = env._store.read_operation(request)
            if operation is None or operation.intent.kind != "managed-input":
                raise UnitGuaranteeUnavailable("captured input attempt not reserved")
            ref = _node(operation.intent.node_ref)
            node = self._admit_node(request, ref)
            context = operation.intent.context_ref
            state = self._inspect(self._native, ref, request.principal_scope)
            first_input = "sessionlessInputBinding" in context
            matching_binding = (isinstance(state, SessionlessNativeInputState)
                and safe_json(state.binding()) == safe_json(context["sessionlessInputBinding"])) if first_input else (
                isinstance(state, NativeInputState)
                and safe_json(state.session_ref) == safe_json(context["nativeSessionRef"])
                and state.source_revision == context["sessionSourceRevision"])
            if (not matching_binding
                    or safe_json(state.node_ref) != safe_json(operation.intent.node_ref)
                    or safe_json(state.provider_ref) != safe_json(operation.intent.steps[0].pinned_provider_ref)
                    or safe_json(state.unit_ref) != safe_json(node["binding"]["harnessUnitRef"])
                    or state.management_epoch != operation.intent.management_epoch
                    or state.directory_binding_ref.to_dict() != context["directoryBindingRef"]
                    or safe_json(state.before_configuration_evidence) != safe_json(context["beforeConfigurationEvidence"])):
                raise UnitAdmissionRefused("native input binding changed before dispatch claim")
            _, first_fence = self._first_fence(operation.intent.node_ref, state.unit_ref)
            if (first_input and (first_fence is None
                    or first_fence["value"]["principalScope"] != request.principal_scope
                    or first_fence["value"]["requestId"] != request.request_id)):
                raise UnitGuaranteeUnavailable("original Unit first-input fence unavailable")
            if first_input and first_fence["value"]["state"] != "held":
                raise UnitOperationUnknown("published original first input cannot be dispatched again")
            if not first_input:
                self._admit_after_first(first_fence, state)
            admitted = HarnessAdmission(env).describe(node["binding"]["harnessDefinitionRef"])
            if safe_json(admitted.provider_ref) != safe_json(state.provider_ref):
                raise UnitAdmissionRefused("native provider activation changed")
            binding = operation.intent.context_ref["invocationBindings"]["native-input"]
            return issuer.issue(request, operation.digest, "native-input", "submitInput", binding["targetRef"])
