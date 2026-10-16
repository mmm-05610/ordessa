"""Typed schema-2 method and action declarations; no execution behavior."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import re

from .identity import MethodRef, ResourceRef


ValueKind = Literal[
    "source_ref", "review_contract", "registered_change", "package_ref",
    "profile_ref", "method_ref", "text", "json_object",
]
StepKind = Literal["invoke", "record", "emit"]
AdmissionKind = Literal[
    "same_scope", "exact_inputs", "method_pin", "review_complete",
    "review_passed", "baseline_available", "reviewer_independent",
]

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_VALUE_KINDS = frozenset({"source_ref", "review_contract", "registered_change",
                          "package_ref", "profile_ref", "method_ref", "text", "json_object"})
_STEP_KINDS = frozenset({"invoke", "record", "emit"})
_ADMISSION_KINDS = frozenset({"same_scope", "exact_inputs", "method_pin",
                              "review_complete", "review_passed", "baseline_available",
                              "reviewer_independent"})


def _identifier(value: object, name: str) -> None:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty method identifier")


def _unique(items: tuple, key, name: str, *, nonempty: bool = False) -> None:
    if type(items) is not tuple or (nonempty and not items):
        raise ValueError(f"{name} must be an immutable tuple" + (" with at least one item" if nonempty else ""))
    values = [key(item) for item in items]
    if len(set(values)) != len(values):
        raise ValueError(f"{name} contains duplicate identities")


@dataclass(frozen=True)
class ActionInput:
    name: str
    value_kind: ValueKind

    def __post_init__(self):
        _identifier(self.name, "input name")
        if self.value_kind not in _VALUE_KINDS:
            raise ValueError("unsupported action input value kind")


@dataclass(frozen=True)
class StepInput:
    name: str
    source_kind: Literal["action_input", "step_output", "resource"]
    source_name: str
    step_id: str | None = None

    def __post_init__(self):
        _identifier(self.name, "step input name")
        _identifier(self.source_name, "step input source")
        if self.source_kind not in {"action_input", "step_output", "resource"}:
            raise ValueError("unsupported step input binding kind")
        if (self.source_kind == "step_output") != (self.step_id is not None):
            raise ValueError("step_id is required only for step_output bindings")
        if self.step_id is not None:
            _identifier(self.step_id, "step id")


@dataclass(frozen=True)
class ActionStep:
    step_id: str
    kind: StepKind
    name: str
    inputs: tuple[StepInput, ...]
    outputs: tuple[str, ...]
    admission: tuple[AdmissionRequirement, ...] = ()

    def __post_init__(self):
        _identifier(self.step_id, "step id")
        _identifier(self.name, "step name")
        if self.kind not in _STEP_KINDS:
            raise ValueError("unsupported action step kind")
        _unique(self.inputs, lambda item: item.name, "step inputs")
        _unique(self.outputs, lambda item: item, "step outputs")
        _unique(self.admission, lambda item: (item.kind, item.inputs), "step admission")
        if any(type(item) is not AdmissionRequirement for item in self.admission):
            raise TypeError("typed immutable step admission requirements required")
        for output in self.outputs:
            _identifier(output, "step output")


@dataclass(frozen=True)
class ActionOutput:
    name: str
    value_kind: ValueKind
    step_id: str
    output: str

    def __post_init__(self):
        _identifier(self.name, "action output name")
        _identifier(self.step_id, "action output step id")
        _identifier(self.output, "action output slot")
        if self.value_kind not in _VALUE_KINDS:
            raise ValueError("unsupported action output value kind")


@dataclass(frozen=True)
class AdmissionRequirement:
    kind: AdmissionKind
    inputs: tuple[str, ...]

    def __post_init__(self):
        if self.kind not in _ADMISSION_KINDS:
            raise ValueError("unsupported admission requirement")
        _unique(self.inputs, lambda item: item, "admission inputs", nonempty=True)
        for item in self.inputs:
            _identifier(item, "admission input")


@dataclass(frozen=True)
class PreparationDocument:
    role: str
    template_resource_id: str

    def __post_init__(self):
        _identifier(self.role, "preparation document role")
        _identifier(self.template_resource_id, "preparation template resource id")


@dataclass(frozen=True)
class ActionDefinition:
    schema_version: Literal[1]
    action_id: str
    inputs: tuple[ActionInput, ...]
    steps: tuple[ActionStep, ...]
    outputs: tuple[ActionOutput, ...]
    admission: tuple[AdmissionRequirement, ...]
    resources: tuple[ResourceRef, ...]
    preparation_documents: tuple[PreparationDocument, ...] = ()

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported action schema version")
        _identifier(self.action_id, "action id")
        _unique(self.inputs, lambda item: item.name, "action inputs")
        _unique(self.steps, lambda item: item.step_id, "action steps", nonempty=True)
        _unique(self.outputs, lambda item: item.name, "action outputs")
        _unique(self.admission, lambda item: (item.kind, item.inputs), "admission requirements")
        _unique(self.resources, lambda item: item.resource_id, "action resources")
        _unique(self.preparation_documents, lambda item: item.role,
                "preparation document roles", nonempty=False)
        _unique(self.preparation_documents, lambda item: item.template_resource_id,
                "preparation template resources", nonempty=False)
        if any(type(item) is not ActionInput for item in self.inputs):
            raise TypeError("typed immutable action inputs required")
        if any(type(item) is not ActionStep for item in self.steps):
            raise TypeError("typed immutable action steps required")
        if any(type(item) is not ActionOutput for item in self.outputs):
            raise TypeError("typed immutable action outputs required")
        if any(type(item) is not AdmissionRequirement for item in self.admission):
            raise TypeError("typed immutable admission requirements required")
        if any(type(item) is not ResourceRef for item in self.resources):
            raise TypeError("typed resource references required")
        if any(type(item) is not PreparationDocument for item in self.preparation_documents):
            raise TypeError("typed preparation document declarations required")
        action_resources = {ref.resource_id: ref for ref in self.resources}
        if any(item.template_resource_id not in action_resources
               or action_resources[item.template_resource_id].kind != "template"
               for item in self.preparation_documents):
            raise ValueError("preparation templates must be action-bound template resources")
        for item in self.resources:
            _identifier(item.resource_id, "action resource id")
        declared_inputs = {item.name for item in self.inputs}
        if any(not set(item.inputs) <= declared_inputs for item in self.admission):
            raise ValueError("action admission may reference declared action inputs only")


@dataclass(frozen=True)
class MethodDefinition:
    """One exact schema-2 declaration assembled from the existing source capture."""

    schema_version: Literal[2]
    method_id: str
    release_version: str
    method_ref: MethodRef
    actions: tuple[ActionDefinition, ...]
    criteria: tuple[ResourceRef, ...]
    prompts: tuple[ResourceRef, ...]
    templates: tuple[ResourceRef, ...]
    schemas: tuple[ResourceRef, ...]
    routing: tuple[ResourceRef, ...]
    resources: tuple[ResourceRef, ...]

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise ValueError("unsupported method schema version")
        _identifier(self.method_id, "method id")
        _identifier(self.release_version, "release version")
        if type(self.method_ref) is not MethodRef:
            raise TypeError("existing MethodRef is required")
        if (self.method_ref.method_id != self.method_id
                or self.method_ref.release_version != self.release_version
                or self.method_ref.schema_version != self.schema_version):
            raise ValueError("method reference identity must match the declaration")
        _unique(self.actions, lambda item: item.action_id, "method actions", nonempty=True)
        if any(type(item) is not ActionDefinition for item in self.actions):
            raise TypeError("typed action definitions required")
        if sum(bool(action.preparation_documents) for action in self.actions) > 1:
            raise ValueError("preparation roles may be declared on at most one action")
        for name in ("criteria", "prompts", "templates", "schemas", "routing", "resources"):
            items = getattr(self, name)
            _unique(items, lambda item: item.resource_id, name)
            if any(type(item) is not ResourceRef for item in items):
                raise TypeError("typed resource references required")
            for item in items:
                _identifier(item.resource_id, "resource id")
        all_refs = {item.resource_id: item for item in self.resources}
        for group, expected in ((self.criteria, "criteria"), (self.prompts, "prompt"),
                                (self.templates, "template"), (self.schemas, "schema"),
                                (self.routing, "routing")):
            if any(all_refs.get(item.resource_id) != item or item.kind != expected for item in group):
                raise ValueError("category references must bind declared resources of the correct kind")
        if any(ref.resource_id not in all_refs or all_refs[ref.resource_id] != ref
               for action in self.actions for ref in action.resources):
            raise ValueError("action resources must bind the method's captured resource set")
        if any(not re.fullmatch(r"[0-9a-f]{64}", item.sha256) for item in self.resources):
            raise ValueError("resource references require lowercase SHA-256 digests")
        supported_resource_kinds = {"action", "criteria", "prompt", "template", "schema", "routing"}
        if any(item.kind not in supported_resource_kinds for item in self.resources):
            raise ValueError("method resource reference has an unsupported kind")
        if not re.fullmatch(r"[0-9a-f]{64}", self.method_ref.snapshot_digest):
            raise ValueError("method pin requires a lowercase SHA-256 digest")
