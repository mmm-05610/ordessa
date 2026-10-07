"""Precise preparation effect scope and its five-item verification table.

A domain (a configuration provider plan_preparation-style output, or assembly
input after material verification) submits one candidate PreparationEffectPlan.
The core verifies every identity field against the ORIGINAL operation/step
facts and fixes one immutable FixedEffectScope before any staged phase may be
appended. Verification outcomes are three-way by construction:

  mismatch -> typed IdentityMismatchError, refused before any dispatch;
  unknown  -> UnknownResultError, the original occupation is kept: nothing is
              appended, sealed or called (preparation-effects freeze s1);
  verified -> one FixedEffectScope whose effect_digest binds the sealed phase.

The core never learns brands: effect steps carry only action_id, input_digest
and an optional material pointer. There is no brand codec, no native command
translation and no content-bearing payload in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

from ordessa_environment_api.errors import IdentityMismatchError, UnknownResultError
from ordessa_environment_api.operations import safe_json, sealed_mapping

from pacthold.agents.nodes.directory import DirectoryBindingRef

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_STEPS = 64
_MAX_MATERIALS = 256
_MAX_TEXT = 256
_MAX_PLAN_ID = 240
_POINTER_CONTENT_KEYS = frozenset({
    "payload", "content", "body", "data", "value", "secret", "token",
    "password", "executable", "command", "argv", "script", "bytes",
})


def _invalid(message: str) -> None:
    raise ValueError(message)


def _name(value: object, label: str) -> str:
    """Bounded nonempty identity string (operations._name rule family)."""
    if (type(value) is not str or not value or value.strip() != value
            or len(value) > _MAX_TEXT or any(ord(char) < 32 for char in value)):
        _invalid(f"{label} must be a nonempty bounded string")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or len(value) > 128 or not value or any(ord(char) < 32 for char in value):
        _invalid("digest must be a bounded nonempty string")
    return value


def _same(left: object, right: object) -> bool:
    """JSON identity comparison; bool/int/float stay distinct."""
    try:
        return safe_json({"value": left}) == safe_json({"value": right})
    except (TypeError, ValueError, RecursionError):
        return False


def _pin_equal(left: Mapping, right: Mapping) -> bool:
    """Field-by-field pin comparison (configuration_references._pin_equal pattern)."""
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return False
    if set(left) != set(right):
        return False
    return all(_same(left[key], right[key]) for key in left)


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(child) for child in value)
    return value


def _sealed_json(value: object, label: str) -> Any:
    try:
        return _deep_freeze(json.loads(safe_json({"v": value}))["v"])
    except (TypeError, ValueError, RecursionError):
        _invalid(f"{label} must be finite JSON")


def _plain(value: Any) -> Any:
    return json.loads(safe_json({"v": value}))["v"]


def _pointer(value: object, label: str) -> Mapping:
    """One immutable pointer pair: immutableMaterialRef + contentDigest.

    The pair is a pointer only. A reference mapping carrying payload-shaped
    keys is refused here so no caller can smuggle material content or an
    executable script through a bare reference (control boundary L11).
    """
    if not isinstance(value, Mapping) or set(value) != {"immutableMaterialRef", "contentDigest"}:
        _invalid(f"{label} requires exactly immutableMaterialRef and contentDigest")
    pointer = value["immutableMaterialRef"]
    if not isinstance(pointer, Mapping) or not pointer:
        _invalid(f"{label} requires a nonempty immutable material reference")
    def walk(item: object) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if type(key) is not str:
                    _invalid(f"{label} reference keys must be strings")
                if key.lower().replace("_", "").replace("-", "") in _POINTER_CONTENT_KEYS:
                    _invalid(f"{label} reference must stay a pointer, never content")
                walk(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child)
        elif item is not None and type(item) not in (str, bool, int, float):
            _invalid(f"{label} reference must be finite JSON")
    walk(pointer)
    return sealed_mapping({"immutableMaterialRef": sealed_mapping(pointer),
                           "contentDigest": _digest(value["contentDigest"])})


def _pointers(value: object, label: str) -> tuple[Mapping, ...]:
    if type(value) is not tuple or len(value) > _MAX_MATERIALS:
        _invalid(f"{label} must be a bounded tuple of pointer pairs")
    refs = tuple(_pointer(item, label) for item in value)
    if len({safe_json(item) for item in refs}) != len(refs):
        _invalid(f"{label} must be unique")
    return refs


def _directory(value: object) -> Mapping:
    try:
        binding = DirectoryBindingRef.from_dict(json.loads(safe_json({"v": value}))["v"])
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        _invalid("directoryBindingRef must be a complete DirectoryBindingRef")
    return sealed_mapping(binding.to_dict())


@dataclass(frozen=True)
class EffectStep:
    """One brand-free effect action, frozen before any dispatch."""

    action_id: str
    input_digest: str
    material_ref: Mapping[str, Any] | None = None
    depends_on: tuple[str, ...] = ()
    recovery_correlation: str = ""

    def __post_init__(self) -> None:
        _name(self.action_id, "actionId")
        _name(self.input_digest, "inputDigest")
        _name(self.recovery_correlation, "recoveryCorrelation")
        if self.material_ref is not None:
            object.__setattr__(self, "material_ref", _pointer(self.material_ref, "materialRef"))
        if type(self.depends_on) is not tuple or len(set(self.depends_on)) != len(self.depends_on):
            _invalid("dependsOn must be a unique tuple")
        for item in self.depends_on:
            _name(item, "dependsOn")
        object.__setattr__(self, "depends_on", tuple(self.depends_on))

    @staticmethod
    def _field_dict(step: "EffectStep") -> dict:
        return {"actionId": step.action_id,
                "inputDigest": step.input_digest,
                "materialRef": None if step.material_ref is None else _plain(step.material_ref),
                "dependsOn": list(step.depends_on),
                "recoveryCorrelation": step.recovery_correlation}

    def to_dict(self) -> dict:
        return EffectStep._field_dict(self)

    @classmethod
    def from_dict(cls, value: object) -> "EffectStep":
        if (type(value) is not dict
                or set(value) != {"actionId", "inputDigest", "materialRef", "dependsOn", "recoveryCorrelation"}
                or type(value["dependsOn"]) is not list):
            _invalid("invalid effect step fields")
        try:
            return cls(value["actionId"], value["inputDigest"], value["materialRef"],
                       tuple(value["dependsOn"]), value["recoveryCorrelation"])
        except (TypeError, ValueError, KeyError):
            _invalid("invalid effect step")


@dataclass(frozen=True)
class PreparationEffectPlan:
    """Candidate precise effect scope submitted by the domain."""

    plan_id: str
    declaration_digest: str
    provider_pin: Mapping[str, Any]
    material_refs: tuple[Mapping[str, Any], ...]
    target: Any
    scope: Any
    before_revision: str
    directory_binding_ref: Mapping[str, Any]
    management_epoch: int
    steps: tuple[EffectStep, ...]

    def __post_init__(self) -> None:
        _name(self.plan_id, "planId")
        if len(self.plan_id) > _MAX_PLAN_ID:
            _invalid("planId is too long to identify a staged phase")
        _digest(self.declaration_digest)
        _name(self.before_revision, "beforeRevision")
        if (type(self.management_epoch) is not int or isinstance(self.management_epoch, bool)
                or self.management_epoch < 0):
            _invalid("managementEpoch must be a nonnegative integer")
        if not isinstance(self.provider_pin, Mapping) or not self.provider_pin:
            _invalid("providerPin is required")
        pin = sealed_mapping(json.loads(safe_json(self.provider_pin)))
        object.__setattr__(self, "provider_pin", pin)
        object.__setattr__(self, "material_refs", _pointers(self.material_refs, "materialRefs"))
        if (type(self.steps) is not tuple or not self.steps or len(self.steps) > _MAX_STEPS
                or any(type(item) is not EffectStep for item in self.steps)):
            _invalid("effect plan requires 1..%d EffectSteps" % _MAX_STEPS)
        steps = tuple(EffectStep(step.action_id, step.input_digest, step.material_ref,
                                 step.depends_on, step.recovery_correlation)
                      for step in self.steps)
        action_ids = tuple(step.action_id for step in steps)
        if len(set(action_ids)) != len(action_ids):
            _invalid("effect action ids must be unique")
        if len({step.recovery_correlation for step in steps}) != len(steps):
            _invalid("effect recovery correlations must be unique")
        earlier: set[str] = set()
        for step in steps:
            for dependency in step.depends_on:
                if dependency in action_ids and dependency not in earlier:
                    _invalid("effect dependsOn must reference strictly earlier actions")
            earlier.add(step.action_id)
        for step in steps:
            if step.material_ref is not None and not any(
                    _same(step.material_ref, item) for item in self.material_refs):
                _invalid("effect step materialRef must be one of the plan materialRefs")
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "target", _sealed_json(self.target, "target"))
        object.__setattr__(self, "scope", _sealed_json(self.scope, "scope"))
        object.__setattr__(self, "directory_binding_ref", _directory(self.directory_binding_ref))

    @staticmethod
    def _field_dict(plan: "PreparationEffectPlan") -> dict:
        return {"planId": plan.plan_id,
                "declarationDigest": plan.declaration_digest,
                "providerPin": _plain(plan.provider_pin),
                "materialRefs": [_plain(item) for item in plan.material_refs],
                "target": _plain(plan.target),
                "scope": _plain(plan.scope),
                "beforeRevision": plan.before_revision,
                "directoryBindingRef": _plain(plan.directory_binding_ref),
                "managementEpoch": plan.management_epoch,
                "steps": [EffectStep._field_dict(step) for step in plan.steps]}

    def to_dict(self) -> dict:
        return PreparationEffectPlan._field_dict(self)

    @classmethod
    def from_dict(cls, value: object) -> "PreparationEffectPlan":
        expected = {"planId", "declarationDigest", "providerPin", "materialRefs", "target",
                    "scope", "beforeRevision", "directoryBindingRef", "managementEpoch", "steps"}
        if (type(value) is not dict or set(value) != expected
                or type(value["steps"]) is not list or type(value["materialRefs"]) is not list):
            _invalid("invalid preparation effect plan fields")
        try:
            return cls(value["planId"], value["declarationDigest"], value["providerPin"],
                       tuple(value["materialRefs"]), value["target"], value["scope"],
                       value["beforeRevision"], value["directoryBindingRef"],
                       value["managementEpoch"],
                       tuple(EffectStep.from_dict(item) for item in value["steps"]))
        except (TypeError, ValueError, KeyError):
            _invalid("invalid preparation effect plan")


def _scope_content(plan_id: str, action_ids: tuple[str, ...], input_digests: tuple[str, ...],
                   material_refs: tuple[Mapping, ...], target: Any, scope: Any,
                   before_revision: str, directory_binding_ref: Mapping,
                   management_epoch: int, recovery_correlations: tuple[str, ...]) -> dict:
    return {"planId": plan_id,
            "actionIds": list(action_ids),
            "inputDigests": list(input_digests),
            "materialRefs": [_plain(item) for item in material_refs],
            "target": _plain(target),
            "scope": _plain(scope),
            "beforeRevision": before_revision,
            "directoryBindingRef": _plain(directory_binding_ref),
            "managementEpoch": management_epoch,
            "recoveryCorrelations": list(recovery_correlations)}


def _effect_digest(content: dict) -> str:
    return hashlib.sha256(safe_json(content).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FixedEffectScope:
    """Core-fixed precise effect range bound into the staged phase facts."""

    plan_id: str
    effect_digest: str
    action_ids: tuple[str, ...]
    input_digests: tuple[str, ...]
    material_refs: tuple[Mapping[str, Any], ...]
    target: Any
    scope: Any
    before_revision: str
    directory_binding_ref: Mapping[str, Any]
    management_epoch: int
    recovery_correlations: tuple[str, ...]

    def __post_init__(self) -> None:
        _name(self.plan_id, "planId")
        _name(self.before_revision, "beforeRevision")
        if (type(self.management_epoch) is not int or isinstance(self.management_epoch, bool)
                or self.management_epoch < 0):
            _invalid("managementEpoch must be a nonnegative integer")
        for label, value in (("actionIds", self.action_ids), ("inputDigests", self.input_digests),
                             ("recoveryCorrelations", self.recovery_correlations)):
            if type(value) is not tuple or not value or any(
                    type(item) is not str or not item or item.strip() != item
                    or len(item) > _MAX_TEXT or any(ord(char) < 32 for char in item)
                    for item in value):
                _invalid(f"{label} must be a bounded nonempty tuple of strings")
        if len({len(self.action_ids), len(self.input_digests), len(self.recovery_correlations)}) != 1:
            _invalid("fixed scope parallel fields must share one length")
        if len(set(self.action_ids)) != len(self.action_ids):
            _invalid("fixed scope action ids must be unique")
        if len(set(self.recovery_correlations)) != len(self.recovery_correlations):
            _invalid("fixed scope recovery correlations must be unique")
        object.__setattr__(self, "material_refs", _pointers(self.material_refs, "materialRefs"))
        object.__setattr__(self, "target", _sealed_json(self.target, "target"))
        object.__setattr__(self, "scope", _sealed_json(self.scope, "scope"))
        object.__setattr__(self, "directory_binding_ref", _directory(self.directory_binding_ref))
        if type(self.effect_digest) is not str or not _DIGEST.fullmatch(self.effect_digest):
            _invalid("effectDigest must be a lowercase SHA-256 hex string")
        expected = _effect_digest(_scope_content(
            self.plan_id, self.action_ids, self.input_digests, self.material_refs,
            self.target, self.scope, self.before_revision, self.directory_binding_ref,
            self.management_epoch, self.recovery_correlations))
        if self.effect_digest != expected:
            _invalid("effectDigest does not match the fixed scope content")

    @staticmethod
    def _field_dict(scope: "FixedEffectScope") -> dict:
        return {"planId": scope.plan_id,
                "effectDigest": scope.effect_digest,
                "actionIds": list(scope.action_ids),
                "inputDigests": list(scope.input_digests),
                "materialRefs": [_plain(item) for item in scope.material_refs],
                "target": _plain(scope.target),
                "scope": _plain(scope.scope),
                "beforeRevision": scope.before_revision,
                "directoryBindingRef": _plain(scope.directory_binding_ref),
                "managementEpoch": scope.management_epoch,
                "recoveryCorrelations": list(scope.recovery_correlations)}

    def to_dict(self) -> dict:
        return FixedEffectScope._field_dict(self)

    @classmethod
    def from_dict(cls, value: object) -> "FixedEffectScope":
        expected = {"planId", "effectDigest", "actionIds", "inputDigests", "materialRefs",
                    "target", "scope", "beforeRevision", "directoryBindingRef",
                    "managementEpoch", "recoveryCorrelations"}
        if (type(value) is not dict or set(value) != expected
                or any(type(value[key]) is not list for key in
                       ("actionIds", "inputDigests", "materialRefs", "recoveryCorrelations"))):
            _invalid("invalid fixed effect scope fields")
        try:
            return cls(value["planId"], value["effectDigest"], tuple(value["actionIds"]),
                       tuple(value["inputDigests"]), tuple(value["materialRefs"]),
                       value["target"], value["scope"], value["beforeRevision"],
                       value["directoryBindingRef"], value["managementEpoch"],
                       tuple(value["recoveryCorrelations"]))
        except (TypeError, ValueError, KeyError):
            _invalid("invalid fixed effect scope")


def verify_preparation_effect(plan: PreparationEffectPlan, *, target, scope, before_revision,
                              directory_binding_ref, management_epoch, pinned_provider_ref,
                              step_correlations, declaration_digest, approved_action_ids,
                              verified_materials) -> FixedEffectScope:
    """Five-item field-by-field verification against original operation facts.

    Item 1 target/scope/before_revision/directory/epoch must equal the original
    Operation intent fields; item 2 provider_pin must equal the original Step
    pinned_provider_ref field by field; item 3 every material_ref must be an
    exact immutableMaterialRef+contentDigest member of the C-side verified set;
    item 4 declaration_digest must equal the current declaration summary and
    the action sequence must be an in-order subsequence of the approved set;
    item 5 recovery_correlation must match a same-action original step, and a
    new action key may not reuse any original correlation. Any known mismatch
    is a typed IdentityMismatchError refused before dispatch; any unknown fact
    is an UnknownResultError and the caller keeps its original occupation.
    """
    if type(plan) is not PreparationEffectPlan:
        raise IdentityMismatchError("a fixed PreparationEffectPlan is required")
    mismatches: list[str] = []
    unknowns: list[str] = []
    for label, plan_value, original_value in (
            ("target", plan.target, target),
            ("scope", plan.scope, scope),
            ("beforeRevision", plan.before_revision, before_revision),
            ("directoryBindingRef", plan.directory_binding_ref, directory_binding_ref),
            ("managementEpoch", plan.management_epoch, management_epoch)):
        if original_value is None:
            unknowns.append(label)
        elif not _same(plan_value, original_value):
            mismatches.append(label)
    if pinned_provider_ref is None:
        unknowns.append("providerPin")
    elif not _pin_equal(plan.provider_pin, pinned_provider_ref):
        mismatches.append("providerPin")
    if verified_materials is None:
        if plan.material_refs or any(step.material_ref is not None for step in plan.steps):
            unknowns.append("materialRefs")
    else:
        known = set()
        for item in verified_materials:
            if not isinstance(item, Mapping):
                raise UnknownResultError("verified material facts are unavailable; occupation kept")
            known.add(safe_json({"immutableMaterialRef": item.get("immutableMaterialRef"),
                                 "contentDigest": item.get("contentDigest")}))
        for item in plan.material_refs:
            if safe_json(item) not in known:
                mismatches.append("materialRefs")
    if declaration_digest is None:
        unknowns.append("declarationDigest")
    elif plan.declaration_digest != declaration_digest:
        mismatches.append("declarationDigest")
    if approved_action_ids is None:
        unknowns.append("approvedActionIds")
    else:
        approved = list(approved_action_ids)
        position = 0
        for action_id in (step.action_id for step in plan.steps):
            while position < len(approved) and approved[position] != action_id:
                position += 1
            if position >= len(approved):
                mismatches.append("approvedActionIds")
                break
            position += 1
    if step_correlations is None:
        unknowns.append("recoveryCorrelations")
    else:
        original_values = set(step_correlations.values())
        for step in plan.steps:
            if step.action_id in step_correlations:
                if step.recovery_correlation != step_correlations[step.action_id]:
                    mismatches.append("recoveryCorrelations")
            elif step.recovery_correlation in original_values:
                mismatches.append("recoveryCorrelations")
    if mismatches:
        raise IdentityMismatchError(
            "preparation effect plan differs from the fixed operation facts: "
            + ", ".join(sorted(set(mismatches))))
    if unknowns:
        raise UnknownResultError(
            "preparation effect verification is unknown; occupation kept: "
            + ", ".join(sorted(set(unknowns))))
    action_ids = tuple(step.action_id for step in plan.steps)
    input_digests = tuple(step.input_digest for step in plan.steps)
    recovery_correlations = tuple(step.recovery_correlation for step in plan.steps)
    digest = _effect_digest(_scope_content(
        plan.plan_id, action_ids, input_digests, plan.material_refs, plan.target, plan.scope,
        plan.before_revision, plan.directory_binding_ref, plan.management_epoch,
        recovery_correlations))
    return FixedEffectScope(plan.plan_id, digest, action_ids, input_digests, plan.material_refs,
                            plan.target, plan.scope, plan.before_revision,
                            plan.directory_binding_ref, plan.management_epoch,
                            recovery_correlations)


__all__ = ["EffectStep", "PreparationEffectPlan", "FixedEffectScope",
           "verify_preparation_effect"]
