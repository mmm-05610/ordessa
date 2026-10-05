"""Process-local invocation authorization foundation, without provider dispatch.

Trusted deployment owners inject both ports. Durable claim facts are not
permissions; directory/provider/native fencing remains their owners' duty.
Losing this issuer cannot grant a replacement context for a spent claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
import math
from threading import RLock
import time
from typing import Mapping, Protocol, runtime_checkable
import uuid

from ordessa_environment_api import RequestKey
from ordessa_environment_api.errors import GuaranteeUnavailableError, IdentityMismatchError, UnknownResultError
from ordessa_environment_api.operations import OperationStorePort, safe_json, sealed_mapping

from .directory import DirectoryBindingRef


class InvocationAuthorityRefused(GuaranteeUnavailableError):
    code = "INVOCATION_AUTHORITY_REFUSED"


def _scoped(value, environment):
    if not isinstance(value, Mapping) or len(value) < 2 or value.get("environmentNamespace") != environment:
        raise InvocationAuthorityRefused("a complete reference in the request environment is required")
    return sealed_mapping(value)


def _request_fields(request):
    return {"environmentNamespace": request.environment_namespace,
            "principalScope": request.principal_scope, "requestId": request.request_id}


@dataclass(frozen=True)
class InvocationGrant:
    principal_scope: str
    delegation_ref: Mapping | None
    actions: tuple[str, ...]
    target_ref: Mapping
    authority_revision: str
    expires_at: float
    issuer_ref: Mapping

    def __post_init__(self):
        if (not isinstance(self.principal_scope, str) or not self.principal_scope
                or not isinstance(self.authority_revision, str) or not self.authority_revision
                or not isinstance(self.actions, tuple) or not self.actions
                or any(not isinstance(action, str) or not action for action in self.actions)
                or len(set(self.actions)) != len(self.actions)
                or type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at)):
            raise ValueError("invalid invocation grant facts")
        for name in ("delegation_ref", "target_ref", "issuer_ref"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, sealed_mapping(value))

    def to_dict(self):
        return json.loads(safe_json({"principalScope": self.principal_scope, "delegationRef": self.delegation_ref,
                                    "actions": self.actions, "targetRef": self.target_ref,
                                    "authorityRevision": self.authority_revision, "expiresAt": self.expires_at,
                                    "issuerRef": self.issuer_ref}))


@runtime_checkable
class InvocationAuthorityPort(Protocol):
    @property
    def issuer_ref(self) -> Mapping: ...
    def authorize(self, request: RequestKey, actions: tuple[str, ...], target_ref: Mapping,
                  delegation_ref: Mapping | None) -> InvocationGrant | None: ...
    def revalidate(self, grant: InvocationGrant, request: RequestKey, actions: tuple[str, ...],
                   target_ref: Mapping) -> InvocationGrant | None: ...


@dataclass(frozen=True)
class InvocationCurrentState:
    provider_ref: Mapping
    provider_active: bool
    management_epoch: int
    directory_binding_ref: DirectoryBindingRef
    directory_permitted: bool
    acquired_target_ref: Mapping | None = None
    acquisition_evidence_ref: Mapping | None = None

    def __post_init__(self):
        if (type(self.provider_active) is not bool or type(self.directory_permitted) is not bool
                or type(self.management_epoch) is not int or self.management_epoch < 0
                or not isinstance(self.directory_binding_ref, DirectoryBindingRef)):
            raise ValueError("invalid current-state facts")
        for name in ("provider_ref", "acquired_target_ref", "acquisition_evidence_ref"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, sealed_mapping(value))


@runtime_checkable
class InvocationCurrentStatePort(Protocol):
    def inspect(self, request: RequestKey, pinned_provider_ref: Mapping, context_ref: Mapping,
                target_ref: Mapping, action: str) -> InvocationCurrentState | None: ...


class InvocationContext:
    """Opaque in-process identity. Its visible facts are never a credential."""
    __slots__ = ("_payload",)

    def __init__(self, *args, **kwargs):
        raise TypeError("InvocationContext is issued by the core")

    def __setattr__(self, name, value):
        raise AttributeError("invocation context is immutable")

    @property
    def facts(self):
        return sealed_mapping(json.loads(self._payload))

    def __copy__(self):
        duplicate = object.__new__(type(self))
        object.__setattr__(duplicate, "_payload", self._payload)
        return duplicate

    def __deepcopy__(self, memo):
        return self.__copy__()

    def __reduce__(self):
        raise TypeError("invocation contexts cannot be serialized")


class InvocationVerifier:
    """Provider-facing capability exposing verification alone."""
    __slots__ = ("_verify", "_continue")

    def __init__(self, verify, continuation=None):
        self._verify = verify
        self._continue = continuation

    def verify_and_consume(self, context, action, provider_ref, target_ref, input_digest):
        return self._verify(context, action, provider_ref, target_ref, input_digest)

    def verify_continuation(self, context, action, provider_ref, target_ref, input_digest):
        """Recheck an already verified original invocation, without a new claim.

        This never performs IO or makes an unresolved native dispatch reusable.
        The provider's original attempt/transport writer barrier still fixes
        every actual write. A verifier lacking this explicit owner port refuses.
        """
        if not callable(self._continue):
            raise InvocationAuthorityRefused('original invocation continuation unavailable')
        return self._continue(context, action, provider_ref, target_ref, input_digest)


class InvocationIssuer:
    def __init__(self, store: OperationStorePort, authority: InvocationAuthorityPort,
                 current_state: InvocationCurrentStatePort, *, clock=time.time, max_contexts=1024):
        if (not isinstance(store, OperationStorePort) or not isinstance(authority, InvocationAuthorityPort)
                or not isinstance(current_state, InvocationCurrentStatePort) or not callable(clock)):
            raise InvocationAuthorityRefused("explicit operation store, authority and current-state ports are required")
        if type(max_contexts) is not int or not 1 <= max_contexts <= 4096:
            raise ValueError("max_contexts must be between 1 and 4096")
        self._store, self._authority, self._current_state, self._clock = store, authority, current_state, clock
        try:
            self._authority_issuer = sealed_mapping(authority.issuer_ref)
        except Exception:
            raise InvocationAuthorityRefused("authority issuer facts are unavailable") from None
        self._instance = uuid.uuid4().hex
        self._issued = {}
        self._lock = RLock()
        self._max_contexts, self._issuing = max_contexts, 0

    def verifier(self):
        return InvocationVerifier(self.verify_and_consume, self.verify_continuation)

    def _now(self):
        current = self._refused_call(self._clock)
        if type(current) not in (int, float) or not math.isfinite(current) or current < 0:
            raise InvocationAuthorityRefused("current authorization time is unavailable")
        return current

    @contextmanager
    def _capacity(self):
        now = self._now()
        for identity, entry in tuple(self._issued.items()):
            reclaim = entry[3] in {'issued', 'consumed'} and entry[2].expires_at <= now
            if entry[3] == 'consumed':
                # A verified original step remains live during multiple native
                # edges. An unrelated issuance must not discard its proof.
                reclaim = reclaim or entry[4] is not True
                if not reclaim:
                    facts = json.loads(entry[1])
                    ref = facts['request']
                    request = RequestKey(ref['environmentNamespace'], ref['principalScope'], ref['requestId'])
                    claim = self._refused_call(lambda: self._store.read_operation_step(request, facts['stepId']))
                    operation = self._refused_call(lambda: self._store.read_operation(request))
                    reclaim = (claim is None or claim.outcome != 'possibly-dispatched'
                        or claim.revision != facts['claimRevision'] or operation is None
                        or operation.status != 'running')
            if reclaim:
                del self._issued[identity]
        if len(self._issued) + self._issuing >= self._max_contexts:
            raise InvocationAuthorityRefused("invocation ticket capacity is unavailable")
        self._issuing += 1
        try:
            yield
        finally:
            self._issuing -= 1

    @staticmethod
    def _refused_call(call):
        try:
            return call()
        except Exception:
            raise InvocationAuthorityRefused("trusted authorization or current-state facts are unavailable") from None

    def _operation_binding(self, request, digest, step_id):
        operation = self._store.read_operation(request)
        if operation is None:
            raise InvocationAuthorityRefused("operation has not been durably reserved")
        if operation.digest != digest:
            raise IdentityMismatchError("operation digest differs from reserved input")
        intent = operation.intent
        step = next((candidate for candidate in intent.steps if candidate.step_id == step_id), None)
        if step is None:
            raise InvocationAuthorityRefused("step is outside the fixed recipe")
        try:
            binding = intent.context_ref["invocationBindings"][step_id]
            if set(binding) != {"action", "targetRef", "delegationRef", "cleanup"}:
                raise ValueError()
            if not isinstance(binding["action"], str) or not binding["action"] or type(binding["cleanup"]) is not bool:
                raise ValueError()
            _scoped(binding["targetRef"], request.environment_namespace)
            if binding["delegationRef"] is not None:
                _scoped(binding["delegationRef"], request.environment_namespace)
            DirectoryBindingRef.from_dict(json.loads(safe_json(intent.context_ref["directoryBindingRef"])))
            if type(step.pinned_provider_ref.get("generation")) is not int or step.pinned_provider_ref["generation"] <= 0:
                raise ValueError()
            if binding["cleanup"] and binding["action"] not in {"stop", "query", "release"}:
                raise ValueError()
            if binding["action"] in {"stop", "release"} and not binding["cleanup"]:
                raise ValueError()
        except Exception:
            raise InvocationAuthorityRefused("fixed invocation bindings are unavailable or incomplete") from None
        return operation, step, binding

    def _state(self, request, operation, step, binding, action, *, query=False, expected_epoch=None):
        state = self._refused_call(lambda: self._current_state.inspect(
            request, step.pinned_provider_ref, operation.intent.context_ref, binding["targetRef"], action))
        if not isinstance(state, InvocationCurrentState):
            raise InvocationAuthorityRefused("trusted current-state response is invalid")
        directory = operation.intent.context_ref["directoryBindingRef"]
        if (state.provider_ref != step.pinned_provider_ref or not state.provider_active
                or not state.directory_permitted or state.directory_binding_ref.to_dict() != directory
                or state.directory_binding_ref.environment_namespace != request.environment_namespace):
            raise InvocationAuthorityRefused("provider generation or directory permission changed")
        epoch = state.management_epoch
        if (expected_epoch is not None and epoch != expected_epoch) or (not query and epoch != operation.intent.management_epoch):
            raise InvocationAuthorityRefused("management epoch changed")
        if binding["cleanup"]:
            if action not in {"stop", "query", "release"} or state.acquired_target_ref != binding["targetRef"]:
                raise InvocationAuthorityRefused("cleanup lacks the exact previously acquired target")
            _scoped(state.acquired_target_ref, request.environment_namespace)
            _scoped(state.acquisition_evidence_ref, request.environment_namespace)
        return state

    def _check_grant(self, grant, request, action, binding):
        if not isinstance(grant, InvocationGrant):
            raise InvocationAuthorityRefused("authority returned no valid grant")
        _scoped(grant.issuer_ref, request.environment_namespace)
        _scoped(grant.target_ref, request.environment_namespace)
        if grant.delegation_ref is not None:
            _scoped(grant.delegation_ref, request.environment_namespace)
        current_issuer = self._refused_call(lambda: sealed_mapping(self._authority.issuer_ref))
        if (grant.principal_scope != request.principal_scope or grant.actions != (action,)
                or grant.target_ref != binding["targetRef"] or grant.delegation_ref != binding["delegationRef"]
                or grant.issuer_ref != self._authority_issuer or current_issuer != self._authority_issuer
                or grant.expires_at <= self._now()):
            raise InvocationAuthorityRefused("grant scope, issuer or expiry does not match")
        return grant

    def _revalidate(self, grant, request, action, binding):
        refreshed = self._refused_call(lambda: self._authority.revalidate(grant, request, (action,), binding["targetRef"]))
        self._check_grant(refreshed, request, action, binding)
        if safe_json(refreshed.to_dict()) != safe_json(grant.to_dict()):
            raise InvocationAuthorityRefused("authority revision or frozen grant facts changed")
        return refreshed

    def _issue(self, request, digest, step_id, action, target_ref, delegation_ref, cleanup, *, query):
        with self._lock, self._capacity():
            operation, step, binding = self._operation_binding(request, digest, step_id)
            requested = {"action": action, "targetRef": target_ref, "delegationRef": delegation_ref, "cleanup": cleanup}
            expected = json.loads(safe_json(binding))
            if query:
                expected["action"] = "query"
            try:
                matches = safe_json(requested) == safe_json(expected)
            except Exception:
                matches = False
            if not matches or (not query and action == "query"):
                raise InvocationAuthorityRefused("invocation differs from the fixed operation binding")
            state = self._state(request, operation, step, binding, action, query=query)
            grant = self._refused_call(lambda: self._authority.authorize(request, (action,), binding["targetRef"], binding["delegationRef"]))
            self._check_grant(grant, request, action, binding)
            self._revalidate(grant, request, action, binding)
            claim_revision = None
            if not query:
                claim = self._store.claim_operation_step(request, digest, step)
                if not claim.claimed:
                    raise UnknownResultError("existing step claim cannot authorize another invocation")
                claim_revision = claim.step.revision
            # Failure here deliberately preserves a possibly-dispatched durable claim.
            latest_state = self._state(request, operation, step, binding, action, query=query, expected_epoch=state.management_epoch)
            if (latest_state.acquired_target_ref != state.acquired_target_ref
                    or latest_state.acquisition_evidence_ref != state.acquisition_evidence_ref):
                raise InvocationAuthorityRefused("acquisition relationship changed during issuance")
            self._revalidate(grant, request, action, binding)
            payload = safe_json({"issuerInstance": self._instance, "request": _request_fields(request),
                                 "operationDigest": digest, "operationIntentDigest": hashlib.sha256(operation.intent_json.encode()).hexdigest(),
                                 "operationRef": operation.intent.operation_ref, "stepId": step_id,
                                 "providerRef": step.pinned_provider_ref, "contextRef": operation.intent.context_ref,
                                 "inputDigest": step.input_digest, "recoveryCorrelation": step.recovery_correlation,
                                 "managementEpoch": state.management_epoch, "action": action,
                                 "targetRef": binding["targetRef"], "delegationRef": binding["delegationRef"],
                                 "cleanup": binding["cleanup"], "query": query, "claimRevision": claim_revision,
                                 "acquiredTargetRef": state.acquired_target_ref if binding["cleanup"] else None,
                                 "acquisitionEvidenceRef": state.acquisition_evidence_ref if binding["cleanup"] else None,
                                 "grant": grant.to_dict()})
            context = object.__new__(InvocationContext)
            object.__setattr__(context, "_payload", payload)
            self._issued[id(context)] = [context, payload, grant, "issued", False]
            return context

    def issue(self, request, operation_digest, step_id, action, target_ref, *, delegation_ref=None, cleanup=False):
        return self._issue(request, operation_digest, step_id, action, target_ref, delegation_ref, cleanup, query=False)

    def issue_query(self, request, operation_digest, step_id):
        _, _, binding = self._operation_binding(request, operation_digest, step_id)
        return self._issue(request, operation_digest, step_id, "query", binding["targetRef"],
                           binding["delegationRef"], binding["cleanup"], query=True)

    def verified_consumption(self, context):
        """Read this live issuer's successful effect verification, not a grant.

        Lost or capacity-collected proof is unknown; it never authorizes a
        second dispatch or claims that native effects completed.
        """
        with self._lock:
            entry = self._issued.get(id(context))
            return (type(context) is InvocationContext and entry is not None
                    and entry[0] is context and entry[1] == context._payload
                    and entry[3] == "consumed" and entry[4] is True)

    def verified_observation(self, context):
        """Successful live query verification; conveys no effect permission."""
        with self._lock:
            entry = self._issued.get(id(context))
            return (type(context) is InvocationContext and entry is not None
                    and entry[0] is context and entry[1] == context._payload
                    and entry[3] == "issued" and entry[4] is True
                    and json.loads(entry[1])["query"] is True)

    def verify_continuation(self, context, action, provider_ref, target_ref, input_digest):
        """Current permission for the SAME active, successfully verified step.

        Reuses the live issuer entry and original frozen grant, store recipe,
        claim revision and current-state ports. No issuance, replacement claim
        or native action occurs. Failure poisons effect continuation: restoring
        an old authority value cannot reactivate a possibly dispatched input.
        Query continuations retain read-only facts and cannot grant effects.
        Revocation must additionally fence the actual native transport writer;
        this method alone is not an IO barrier or a retry permission.
        """
        with self._lock:
            registered = self._issued.get(id(context))
            if (type(context) is not InvocationContext or registered is None
                    or registered[0] is not context or registered[1] != context._payload):
                raise InvocationAuthorityRefused('continuation was not issued by this live core instance')
            facts = json.loads(registered[1])
            original_state = 'issued' if facts['query'] else 'consumed'
            if registered[3] != original_state or registered[4] is not True:
                raise InvocationAuthorityRefused('original invocation has no successful verification')
            registered[3] = 'revalidating'
            registered[4] = False
        # Never hold the issuer lock while consulting deployment current state:
        # core admission may issue another context while holding its own lock.
        try:
            verified = self._verify_registered(registered, facts, action, provider_ref, target_ref, input_digest)
            with self._lock:
                registered[4] = True
            return verified
        finally:
            with self._lock:
                registered[3] = original_state

    def verify_and_consume(self, context, action, provider_ref, target_ref, input_digest):
        """Trusted provider checks immediately before use; no native call occurs here."""
        with self._lock:
            registered = self._issued.get(id(context))
            if type(context) is not InvocationContext or registered is None or registered[0] is not context:
                raise InvocationAuthorityRefused("context was not issued by this live core instance")
            if context._payload != registered[1]:
                raise InvocationAuthorityRefused("invocation context content changed")
            if registered[3] != "issued":
                raise UnknownResultError("invocation permission has already been consumed")
            # Set before calling any trusted port, including reentrant callbacks.
            registered[3] = "verifying"
            registered[4] = False
            facts = json.loads(registered[1])
        try:
            verified = self._verify_registered(registered, facts, action, provider_ref, target_ref, input_digest)
            with self._lock:
                registered[4] = True
            return verified
        finally:
            with self._lock:
                registered[3] = "issued" if facts["query"] else "consumed"

    def _verify_registered(self, registered, facts, action, provider_ref, target_ref, input_digest):
        if safe_json(registered[2].to_dict()) != safe_json(facts["grant"]):
            raise InvocationAuthorityRefused("issued grant facts changed")
        try:
            match = (action == facts["action"] and safe_json(provider_ref) == safe_json(facts["providerRef"])
                     and safe_json(target_ref) == safe_json(facts["targetRef"]) and input_digest == facts["inputDigest"])
        except Exception:
            match = False
        if not match:
            raise InvocationAuthorityRefused("provider call differs from the issued invocation")
        ref = facts["request"]
        request = RequestKey(ref["environmentNamespace"], ref["principalScope"], ref["requestId"])
        operation, step, binding = self._operation_binding(request, facts["operationDigest"], facts["stepId"])
        if hashlib.sha256(operation.intent_json.encode()).hexdigest() != facts["operationIntentDigest"]:
            raise InvocationAuthorityRefused("fixed operation content changed")
        self._revalidate(registered[2], request, action, binding)
        state = self._state(request, operation, step, binding, action, query=facts["query"], expected_epoch=facts["managementEpoch"])
        if facts["cleanup"] and (state.acquired_target_ref != facts["acquiredTargetRef"]
                                  or state.acquisition_evidence_ref != facts["acquisitionEvidenceRef"]):
            raise InvocationAuthorityRefused("cleanup acquisition relationship changed")
        # A state callback may take time or revoke a grant. Recheck after it,
        # then read the durable claim last so a late recorded outcome cannot
        # authorize another native edge. Actual IO still needs its owner fence.
        self._revalidate(registered[2], request, action, binding)
        if not facts["query"]:
            operation = self._store.read_operation(request)
            claim = self._store.read_operation_step(request, facts["stepId"])
            if (claim is None or claim.outcome != "possibly-dispatched" or claim.revision != facts["claimRevision"]
                    or safe_json(claim.intent.to_dict()) != safe_json(step.to_dict())
                    or operation is None or operation.status != "running"
                    or operation.digest != facts["operationDigest"]
                    or hashlib.sha256(operation.intent_json.encode()).hexdigest() != facts["operationIntentDigest"]):
                raise InvocationAuthorityRefused("durable dispatch claim no longer matches")
        return sealed_mapping(facts)
