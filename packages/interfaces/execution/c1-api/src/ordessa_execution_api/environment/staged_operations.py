"""Optional two-phase recipe sealing over the original operation ledger.

The root operation is immutable. One complete, root-bound follow-up
recipe may be appended and sealed after every root step is conclusively
recorded. These DTOs carry no invocation authority or native handles.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Protocol, runtime_checkable

from ordessa_infrastructure.database.records import DomainWrite as _DomainWrite
from ordessa_infrastructure.identifiers import RequestKey as _RequestKey
from .operations import (
    OperationIntent, OperationRecord, StepIntent, UsageMutation,
    _name, _plain, safe_json, sealed_mapping,
)

STAGED_OPERATION_STORE_VERSION = "staged-operation/1"


def _invalid(message: str = "staged operation data is invalid") -> None:
    raise ValueError(message)


def staged_operation_intent_dict(intent: OperationIntent) -> dict[str, Any]:
    """Canonicalize by trusted class methods and direct frozen fields."""
    if type(intent) is not OperationIntent:
        _invalid("root intent must be OperationIntent")
    return {
        "operationRef": intent.operation_ref,
        "kind": intent.kind,
        "profileSnapshotRef": _plain(intent.profile_snapshot_ref),
        "contextRef": _plain(intent.context_ref),
        "steps": [StepIntent.to_dict(step) for step in intent.steps],
        "nodeRef": _plain(intent.node_ref),
        "managementEpoch": intent.management_epoch,
    }


def staged_operation_phase_dict(phase: "OperationRecipePhase") -> dict[str, Any]:
    if type(phase) is not OperationRecipePhase:
        _invalid("recipe phase must be OperationRecipePhase")
    return {
        "phaseId": phase.phase_id,
        "steps": [StepIntent.to_dict(step) for step in phase.steps],
        "invocationBindings": _plain(phase.invocation_bindings),
        "contextFacts": _plain(phase.context_facts),
    }


def _copy_step(step: StepIntent) -> StepIntent:
    return StepIntent.from_dict(StepIntent.to_dict(step))


def combine_staged_operation_intent(root: OperationIntent, phase: "OperationRecipePhase | None",
             environment_namespace: str) -> OperationIntent:
    if phase is None:
        return OperationIntent(
            root.operation_ref, root.kind, root.profile_snapshot_ref, root.context_ref,
            tuple(_copy_step(step) for step in root.steps), root.node_ref, root.management_epoch,
        )
    context = _plain(root.context_ref)
    if type(context) is not dict:
        _invalid("root operation context is invalid")
    existing_bindings = context.get("invocationBindings")
    if not isinstance(existing_bindings, Mapping):
        _invalid("root invocation bindings are unavailable")
    bindings = _plain(existing_bindings)
    phase_bindings = _plain(phase.invocation_bindings)
    if set(bindings).intersection(phase_bindings):
        _invalid("recipe phase changes an existing invocation binding")
    for binding in phase_bindings.values():
        target = binding["targetRef"]
        delegation = binding["delegationRef"]
        if target.get("environmentNamespace") != environment_namespace:
            _invalid("phase target reference belongs to another environment")
        if (delegation is not None
                and delegation.get("environmentNamespace") != environment_namespace):
            _invalid("phase delegation reference belongs to another environment")
    facts = _plain(phase.context_facts)
    if set(context).intersection(facts):
        _invalid("recipe phase changes an existing operation fact")
    context.update(facts)
    bindings.update(phase_bindings)
    context["invocationBindings"] = bindings
    return OperationIntent(
        root.operation_ref, root.kind, root.profile_snapshot_ref, context,
        tuple(_copy_step(step) for step in root.steps)
        + tuple(_copy_step(step) for step in phase.steps),
        root.node_ref, root.management_epoch,
    )


@dataclass(frozen=True)
class OperationRecipePhase:
    phase_id: str
    steps: tuple[StepIntent, ...]
    invocation_bindings: Mapping[str, Mapping[str, Any]]
    context_facts: Mapping[str, Any]

    def __post_init__(self) -> None:
        _name(self.phase_id, "phaseId")
        if (type(self.steps) is not tuple or not self.steps or len(self.steps) > 256
                or any(type(step) is not StepIntent for step in self.steps)):
            _invalid("phase requires a bounded nonempty tuple of StepIntent")
        steps = tuple(_copy_step(step) for step in self.steps)
        object.__setattr__(self, "steps", steps)
        step_ids = tuple(step.step_id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            _invalid("phase step identities must be unique")
        if not isinstance(self.invocation_bindings, Mapping):
            _invalid("phase invocation bindings must be a mapping")
        if (any(type(key) is not str for key in self.invocation_bindings)
                or set(self.invocation_bindings) != set(step_ids)):
            _invalid("phase bindings must exactly cover its steps")
        bindings: dict[str, Any] = {}
        for step_id in step_ids:
            binding = self.invocation_bindings[step_id]
            if not isinstance(binding, Mapping) or set(binding) != {
                "action", "targetRef", "delegationRef", "cleanup"
            }:
                _invalid("phase binding has an invalid shape")
            action = binding["action"]
            _name(action, "action")
            cleanup = binding["cleanup"]
            if type(cleanup) is not bool:
                _invalid("phase binding cleanup must be boolean")
            if (action in {"release", "stop"} and cleanup is not True
                    or cleanup and action not in {"release", "stop", "query"}):
                _invalid("phase cleanup action is invalid")
            if not isinstance(binding["targetRef"], Mapping):
                _invalid("phase target reference must be a mapping")
            if binding["delegationRef"] is not None and not isinstance(binding["delegationRef"], Mapping):
                _invalid("phase delegation reference must be a mapping")
            for ref_name in ("targetRef", "delegationRef"):
                if binding[ref_name] is None:
                    continue
                if not isinstance(binding[ref_name], Mapping):
                    _invalid("phase binding references must be mappings")
                safe_json(binding[ref_name])
            bindings[step_id] = sealed_mapping(dict(binding))
        if not isinstance(self.context_facts, Mapping):
            _invalid("phase context facts must be a mapping")
        if any(type(key) is not str for key in self.context_facts):
            _invalid("phase context fact keys must be strings")
        if {"environmentNamespace", "invocationBindings"}.intersection(self.context_facts):
            _invalid("phase context facts contain a reserved key")
        facts = sealed_mapping(dict(self.context_facts))
        safe_json(facts)
        object.__setattr__(self, "invocation_bindings", sealed_mapping(bindings))
        object.__setattr__(self, "context_facts", facts)

    def to_dict(self) -> dict[str, Any]:
        return staged_operation_phase_dict(self)

    @property
    def digest(self) -> str:
        return hashlib.sha256(safe_json(staged_operation_phase_dict(self)).encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> "OperationRecipePhase":
        if type(value) is not dict or set(value) != {
            "phaseId", "steps", "invocationBindings", "contextFacts"
        } or type(value.get("steps")) is not list:
            _invalid("invalid recipe phase fields")
        try:
            return cls(value["phaseId"], tuple(StepIntent.from_dict(item) for item in value["steps"]),
                       value["invocationBindings"], value["contextFacts"])
        except (TypeError, ValueError, KeyError):
            _invalid("invalid recipe phase")


@dataclass(frozen=True)
class StagedOperationRecord:
    operation: OperationRecord
    root_intent_json: str
    phase_json: str | None

    def __post_init__(self) -> None:
        if type(self.operation) is not OperationRecord or type(self.root_intent_json) is not str:
            _invalid("staged operation record fields are invalid")
        if self.phase_json is not None and type(self.phase_json) is not str:
            _invalid("staged phase JSON is invalid")
        try:
            root_value = json.loads(self.root_intent_json)
            root = OperationIntent.from_dict(root_value)
            if safe_json(staged_operation_intent_dict(root)) != self.root_intent_json:
                _invalid("root intent JSON is not canonical")
            phase = None
            if self.phase_json is not None:
                phase_value = json.loads(self.phase_json)
                phase = OperationRecipePhase.from_dict(phase_value)
                if safe_json(staged_operation_phase_dict(phase)) != self.phase_json:
                    _invalid("phase JSON is not canonical")
            current = OperationIntent.from_dict(json.loads(self.operation.intent_json))
            if safe_json(staged_operation_intent_dict(combine_staged_operation_intent(
                    root, phase, self.operation.request.environment_namespace))) != self.operation.intent_json:
                _invalid("staged recipe differs from the stored operation")
            if safe_json(staged_operation_intent_dict(current)) != self.operation.intent_json:
                _invalid("stored operation intent is not canonical")
        except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
            _invalid("staged operation record is inconsistent")

    @property
    def root_intent(self) -> OperationIntent:
        return OperationIntent.from_dict(json.loads(self.root_intent_json))

    @property
    def root_intent_digest(self) -> str:
        return hashlib.sha256(self.root_intent_json.encode("utf-8")).hexdigest()

    @property
    def phase(self) -> OperationRecipePhase | None:
        return None if self.phase_json is None else OperationRecipePhase.from_dict(json.loads(self.phase_json))

    @property
    def sealed(self) -> bool:
        return self.phase_json is not None

    @property
    def contract_version(self) -> str:
        return STAGED_OPERATION_STORE_VERSION


@runtime_checkable
class StagedOperationStorePort(Protocol):
    @property
    def staged_operation_contract_version(self) -> str: ...

    def reserve_staged_operation(self, request: _RequestKey, digest: str, root_intent: OperationIntent,
                                 writes: tuple[_DomainWrite, ...] = (),
                                 usages: tuple[UsageMutation, ...] = ()) -> StagedOperationRecord: ...

    def read_staged_operation(self, request: _RequestKey) -> StagedOperationRecord | None: ...

    def append_staged_operation_phase(self, request: _RequestKey, digest: str, expected_revision: int,
                                      expected_intent_digest: str,
                                      phase: OperationRecipePhase) -> StagedOperationRecord: ...


__all__ = [
    "STAGED_OPERATION_STORE_VERSION", "OperationRecipePhase",
    "StagedOperationRecord", "StagedOperationStorePort",
]
