"""Optional named-step persistence on the existing Environment request ledger.

These data contracts grant no provider permission or native success. Holders
are complete scoped identities; records seal finite JSON before storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from .domain import DomainWrite
from .identity import RequestKey
from .errors import IdentityMismatchError

OPERATION_STORE_VERSION = "operation-records/1"
PRE_DISPATCH_REFUSAL_STORE_VERSION = "pre-dispatch-refusal/1"


class OperationRevisionConflict(IdentityMismatchError):
    code = "OPERATION_REVISION_CONFLICT"


def _name(value, label):
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > 256:
        raise ValueError(f"{label} must be a nonempty bounded string")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} contains control characters")


def _plain(value, depth=0):
    if depth > 32:
        raise ValueError("operation JSON exceeds depth limit")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("operation JSON keys must be strings")
        return {key: _plain(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("operation records require finite JSON values")


def safe_json(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise ValueError("operation data must be a mapping")
    text = json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
    if len(text.encode("utf-8")) > 262144:
        raise ValueError("operation JSON exceeds size limit")
    return text


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def sealed_mapping(value):
    return _freeze(json.loads(safe_json(value)))


def operation_holder(request: RequestKey, operation_id: str) -> Mapping[str, Any]:
    _name(operation_id, "operationId")
    return sealed_mapping({"kind": "operation", "environmentNamespace": request.environment_namespace,
                           "principalScope": request.principal_scope, "requestId": request.request_id,
                           "operationId": operation_id})


def node_holder(environment: str, instance_id: str, generation: int) -> Mapping[str, Any]:
    from .identity import ParticipantInstanceRef
    ParticipantInstanceRef(environment, instance_id, generation)
    return sealed_mapping({"kind": "node", "environmentNamespace": environment,
                           "instanceId": instance_id, "generation": generation})


@dataclass(frozen=True)
class StepIntent:
    step_id: str
    pinned_provider_ref: Mapping[str, Any]
    input_digest: str
    recovery_correlation: str
    prerequisite_steps: tuple[str, ...] = ()
    management_epoch: int = 0

    def __post_init__(self):
        for label in ("step_id", "input_digest", "recovery_correlation"):
            _name(getattr(self, label), label)
        if type(self.management_epoch) is not int or self.management_epoch < 0:
            raise ValueError("management epoch must be nonnegative")
        if not isinstance(self.prerequisite_steps, tuple) or len(set(self.prerequisite_steps)) != len(self.prerequisite_steps):
            raise ValueError("step prerequisites must be a unique tuple")
        for name in self.prerequisite_steps:
            _name(name, "prerequisite")
        if not self.pinned_provider_ref:
            raise ValueError("pinned provider identity is required")
        object.__setattr__(self, "pinned_provider_ref", sealed_mapping(self.pinned_provider_ref))

    def to_dict(self):
        return {"stepId": self.step_id, "pinnedProviderRef": _plain(self.pinned_provider_ref),
                "inputDigest": self.input_digest, "recoveryCorrelation": self.recovery_correlation,
                "prerequisiteSteps": list(self.prerequisite_steps), "managementEpoch": self.management_epoch}

    @classmethod
    def from_dict(cls, value):
        if set(value) != {"stepId", "pinnedProviderRef", "inputDigest", "recoveryCorrelation", "prerequisiteSteps", "managementEpoch"}:
            raise ValueError("invalid StepIntent fields")
        return cls(value["stepId"], value["pinnedProviderRef"], value["inputDigest"],
                   value["recoveryCorrelation"], tuple(value["prerequisiteSteps"]), value["managementEpoch"])


@dataclass(frozen=True)
class OperationIntent:
    operation_ref: str
    kind: str
    profile_snapshot_ref: Mapping[str, Any] | None
    context_ref: Mapping[str, Any]
    steps: tuple[StepIntent, ...]
    node_ref: Mapping[str, Any] | None = None
    management_epoch: int = 0

    def __post_init__(self):
        _name(self.operation_ref, "operationRef")
        _name(self.kind, "kind")
        if not isinstance(self.context_ref, Mapping):
            raise ValueError("operation requires a scoped context mapping")
        if type(self.management_epoch) is not int or self.management_epoch < 0:
            raise ValueError("management epoch must be nonnegative")
        if not isinstance(self.steps, tuple) or not self.steps or len(self.steps) > 256:
            raise ValueError("operation requires bounded named steps")
        preceding, correlations = set(), set()
        for step in self.steps:
            if not isinstance(step, StepIntent) or step.step_id in preceding:
                raise ValueError("duplicate or invalid step")
            if not set(step.prerequisite_steps) <= preceding or step.recovery_correlation in correlations:
                raise ValueError("prerequisites must precede the step; correlations must be unique")
            if step.management_epoch != self.management_epoch:
                raise ValueError("step epoch differs from operation")
            preceding.add(step.step_id)
            correlations.add(step.recovery_correlation)
        for name in ("profile_snapshot_ref", "context_ref", "node_ref"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, sealed_mapping(value))
        safe_json(self.to_dict())

    def to_dict(self):
        return {"operationRef": self.operation_ref, "kind": self.kind,
                "profileSnapshotRef": _plain(self.profile_snapshot_ref), "contextRef": _plain(self.context_ref),
                "steps": [step.to_dict() for step in self.steps], "nodeRef": _plain(self.node_ref),
                "managementEpoch": self.management_epoch}

    @classmethod
    def from_dict(cls, value):
        if set(value) != {"operationRef", "kind", "profileSnapshotRef", "contextRef", "steps", "nodeRef", "managementEpoch"}:
            raise ValueError("invalid OperationIntent fields")
        return cls(value["operationRef"], value["kind"], value["profileSnapshotRef"], value["contextRef"],
                   tuple(StepIntent.from_dict(step) for step in value["steps"]), value["nodeRef"], value["managementEpoch"])


@dataclass(frozen=True)
class OperationRecord:
    request: RequestKey
    digest: str
    revision: int
    outcome: str
    status: str
    intent_json: str
    current_step: str | None
    result_json: str | None
    evidence_json: str

    @property
    def intent(self):
        return OperationIntent.from_dict(json.loads(self.intent_json))

    @property
    def result(self):
        return json.loads(self.result_json) if self.result_json is not None else None


@dataclass(frozen=True)
class StepRecord:
    request: RequestKey
    intent_json: str
    revision: int
    outcome: str
    evidence_json: str

    @property
    def intent(self):
        return StepIntent.from_dict(json.loads(self.intent_json))

    @property
    def evidence(self):
        return json.loads(self.evidence_json)


@dataclass(frozen=True)
class StepClaimResult:
    claimed: bool
    step: StepRecord


@dataclass(frozen=True)
class UsageMutation:
    usage_id: str
    expected_revision: int
    expected_holder_ref: Mapping[str, Any] | None
    holder_ref: Mapping[str, Any]
    target_ref: Mapping[str, Any]
    rights: tuple[str, ...]
    state: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        _name(self.usage_id, "usageId")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("Usage revision must be nonnegative")
        if self.state not in {"active", "released", "unknown"}:
            raise ValueError("invalid Usage state")
        if not isinstance(self.rights, tuple) or not self.rights:
            raise ValueError("Usage requires rights")
        for right in self.rights:
            _name(right, "right")
        for name in ("expected_holder_ref", "holder_ref", "target_ref", "payload"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, sealed_mapping(value))


@runtime_checkable
class OperationStorePort(Protocol):
    def reserve_operation(self, request: RequestKey, digest: str, intent: OperationIntent,
                          writes: tuple[DomainWrite, ...] = (), usages: tuple[UsageMutation, ...] = ()) -> OperationRecord: ...
    def read_operation(self, request: RequestKey) -> OperationRecord | None: ...
    def claim_operation_step(self, request: RequestKey, operation_digest: str, step_intent: StepIntent,
                             usages: tuple[UsageMutation, ...] = ()) -> StepClaimResult: ...
    def read_operation_step(self, request: RequestKey, step_id: str) -> StepRecord | None: ...
    def record_operation_step(self, request: RequestKey, operation_digest: str, step_id: str,
                              step_digest: str, expected_revision: int, outcome: str, evidence: Mapping[str, Any],
                              writes: tuple[DomainWrite, ...] = (), usages: tuple[UsageMutation, ...] = (),
                              *, require_complete_usages: bool = False,
                              release_holder: Mapping | None = None) -> StepRecord:
        """Optionally conclude every retained operation Usage in this same CAS.

        The opt-in is valid only for concluded steps. All retained Usages must
        be represented by active original-operation mutations; newly acquired
        Usages may also be included. Failure must leave the step unmodified.
        Older callers retain their original per-step behavior.

        ``release_holder`` opens the controlled release seam: every Usage
        mutation of such a step must be a release whose expected and actual
        holder are exactly this holder (typically the node holder). Only
        active Usage rows can be released; unknown rows keep their hold.
        """
        ...
    def read_usages(self, environment: str, holder_ref: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
        """Read one holder's Usage rows for controlled release CAS construction."""
        ...
    def publish_operation(self, request: RequestKey, digest: str, expected_revision: int,
                          required_steps: tuple[str, ...], writes: tuple[DomainWrite, ...],
                          usages: tuple[UsageMutation, ...], result: Mapping[str, Any]) -> OperationRecord: ...
    def record_operation_outcome(self, request: RequestKey, digest: str, expected_revision: int,
                                 outcome: str, evidence: Mapping[str, Any]) -> OperationRecord: ...


@runtime_checkable
class PreDispatchRefusalStorePort(Protocol):
    """Optional same-store CAS for a positively unclaimed operation refusal.

    This is an additive capability. Implementations must persist the refused
    operation and all supplied DomainWrite CAS updates in one transaction;
    an existing refusal is replayable only for the same evidence and writes.
    """

    def refuse_unclaimed_operation(self, request: RequestKey, digest: str,
                                   expected_revision: int, evidence: Mapping[str, Any],
                                   writes: tuple[DomainWrite, ...]) -> OperationRecord: ...
