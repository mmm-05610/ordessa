"""Frozen preparation-effect DTOs and the five-item verification table.

Gate 1 (preparation-effects freeze s6.1): a changed target, version,
declaration, material digest, provider pin, an inserted or reordered action
is refused before dispatch, typed, item by item.
Gate 5 (s6.5): the core never learns brands: effect steps carry only
action_id/input_digest/material_ref; every serialized output is scanned.
Unknown verification facts raise UnknownResultError so the caller keeps its
original occupation (no append, no seal, no call).
"""
from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

from ordessa_environment_api.errors import IdentityMismatchError, UnknownResultError
from ordessa_environment_api.operations import safe_json
from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.preparation_effects import (
    EffectStep, FixedEffectScope, PreparationEffectPlan, verify_preparation_effect,
)


def _digest(character):
    return character * 64


def _material(resource="material-1", digest_char="d"):
    return {"immutableMaterialRef": {"environmentNamespace": "env", "resourceId": resource},
            "contentDigest": "sha256:" + _digest(digest_char)}


def _pin(generation=1):
    return {"environmentNamespace": "env", "providerId": "fixture.runtime",
            "version": "1.0", "generation": generation}


def _binding(revision=1, character="a"):
    return DirectoryBindingRef("env", "directory", revision,
                               "sha256:" + character * 64).to_dict()


TARGET = {"environmentNamespace": "env", "instanceId": "agent-1", "generation": 1}
SCOPE = {"environmentNamespace": "env", "profileId": "profile",
         "manifestRevision": 1, "contentDigest": "sha256:" + "b" * 64}


def _step(action="configure-unit", *, material=None, depends=(), correlation=None):
    return EffectStep(action, "input-" + action, material, tuple(depends),
                      correlation or "correlation-" + action)


def _plan(*, steps=None, materials=None, pin=None, declaration_char="c",
          target=TARGET, scope=SCOPE, before="native-1", directory=None, epoch=0):
    return PreparationEffectPlan(
        plan_id="effects-1",
        declaration_digest="sha256:" + _digest(declaration_char),
        provider_pin=pin if pin is not None else _pin(),
        material_refs=tuple(materials) if materials is not None else (),
        target=target,
        scope=scope,
        before_revision=before,
        directory_binding_ref=directory if directory is not None else _binding(),
        management_epoch=epoch,
        steps=tuple(steps) if steps is not None else (_step(),),
    )


def _facts(plan, **overrides):
    values = dict(
        target=plan.target,
        scope=plan.scope,
        before_revision=plan.before_revision,
        directory_binding_ref=plan.directory_binding_ref,
        management_epoch=plan.management_epoch,
        pinned_provider_ref=plan.provider_pin,
        step_correlations={"prepare": "operation.prepare", "start": "operation.start"},
        declaration_digest=plan.declaration_digest,
        approved_action_ids=tuple(step.action_id for step in plan.steps),
        verified_materials=plan.material_refs,
    )
    values.update(overrides)
    return values


def test_plan_dto_roundtrips_frozen_and_closed():
    plan = _plan(steps=(_step(material=_material()),
                        _step("restart-unit", depends=("configure-unit",))),
                 materials=(_material(),))
    assert PreparationEffectPlan.from_dict(plan.to_dict()) == plan
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        plan.plan_id = "other"
    source = plan.to_dict()
    source["extra"] = True
    with pytest.raises(ValueError):
        PreparationEffectPlan.from_dict(source)
    missing = {key: value for key, value in plan.to_dict().items() if key != "scope"}
    with pytest.raises(ValueError):
        PreparationEffectPlan.from_dict(missing)
    # Deep freeze: mutating the caller's source after construction changes nothing.
    mutable_target = {"environmentNamespace": "env", "instanceId": "agent-1", "generation": 1}
    other = _plan(target=mutable_target)
    mutable_target["instanceId"] = "mutated"
    assert _plain(other.target)["instanceId"] == "agent-1"


def _plain(value):
    return json.loads(safe_json({"v": value}))["v"]


def test_plan_dto_bounds_and_dependency_order():
    with pytest.raises(ValueError):
        _plan(steps=tuple(_step("action-%d" % index) for index in range(65)))
    with pytest.raises(ValueError):
        _plan(steps=())
    with pytest.raises(ValueError):
        _plan(materials=tuple(_material("resource-%d" % index) for index in range(257)))
    with pytest.raises(ValueError):
        _plan(steps=(_step("self", depends=("self",)),))
    with pytest.raises(ValueError):
        _plan(steps=(_step("later", depends=("after",)), _step("after")))
    with pytest.raises(ValueError):
        _plan(steps=(_step("same-action"), _step("same-action")))
    with pytest.raises(ValueError):
        _plan(steps=(_step("alpha", correlation="same"),
                     _step("beta", correlation="same")))
    # A step may only point at one of the plan's own material pointers.
    with pytest.raises(ValueError):
        _plan(steps=(_step(material=_material("resource-elsewhere")),),
              materials=(_material(),))
    # The plan's own pointer pairs refuse content-shaped keys.
    with pytest.raises(ValueError):
        _plan(materials=({"immutableMaterialRef": {"environmentNamespace": "env",
                                                   "payload": "script"},
                          "contentDigest": "sha256:" + _digest("d")},))


def test_effect_step_dto_is_closed_and_bounded():
    step = _step(material=_material())
    assert EffectStep.from_dict(step.to_dict()) == step
    without_material = _step("plain-action")
    restored = EffectStep.from_dict(without_material.to_dict())
    assert restored.material_ref is None and restored == without_material
    with pytest.raises(ValueError):
        EffectStep.from_dict({**step.to_dict(), "extra": True})
    with pytest.raises(ValueError):
        EffectStep.from_dict({key: value for key, value in step.to_dict().items()
                              if key != "recoveryCorrelation"})


def test_verification_accepts_the_exact_original_facts():
    material = _material()
    plan = _plan(steps=(_step("configure-unit", material=material),
                        _step("restart-unit", depends=("configure-unit",))),
                 materials=(material,))
    scope = verify_preparation_effect(plan, **_facts(plan))
    assert scope.action_ids == ("configure-unit", "restart-unit")
    assert scope.input_digests == ("input-configure-unit", "input-restart-unit")
    assert scope.recovery_correlations == ("correlation-configure-unit",
                                           "correlation-restart-unit")
    assert scope.material_refs == (material,)
    assert scope.target == plan.target and scope.management_epoch == 0
    assert FixedEffectScope.from_dict(scope.to_dict()) == scope
    # The digest is recomputable from the frozen content, not a second planDigest.
    recomputed = json.loads(safe_json({"v": scope.to_dict()}))["v"]
    del recomputed["effectDigest"]
    assert scope.effect_digest == hashlib.sha256(
        safe_json(recomputed).encode("utf-8")).hexdigest()


def test_fixed_scope_rejects_tampered_content():
    plan = _plan()
    scope = verify_preparation_effect(plan, **_facts(plan))
    tampered = scope.to_dict()
    tampered["actionIds"] = ["other-action"]
    with pytest.raises(ValueError):
        FixedEffectScope.from_dict(tampered)
    broken = scope.to_dict()
    broken["effectDigest"] = "0" * 64
    with pytest.raises(ValueError):
        FixedEffectScope.from_dict(broken)


@pytest.mark.parametrize(
    "case",
    ["target", "scope", "before", "directory", "epoch", "pin",
     "material-digest", "material-set", "declaration", "insert-action",
     "reorder", "correlation-mismatch", "correlation-reuse"],
)
def test_gate1_changed_facts_are_refused_before_dispatch(case):
    material = _material()
    plan = _plan(steps=(_step("alpha", material=material),
                        _step("beta", depends=("alpha",))),
                 materials=(material,))
    facts = _facts(plan)
    if case == "target":
        facts["target"] = {"environmentNamespace": "env", "instanceId": "other", "generation": 1}
    elif case == "scope":
        facts["scope"] = {"environmentNamespace": "env", "profileId": "other",
                          "manifestRevision": 1, "contentDigest": "sha256:" + "b" * 64}
    elif case == "before":
        facts["before_revision"] = "native-2"
    elif case == "directory":
        facts["directory_binding_ref"] = _binding(revision=2)
    elif case == "epoch":
        facts["management_epoch"] = 1
    elif case == "pin":
        facts["pinned_provider_ref"] = _pin(generation=2)
    elif case == "material-digest":
        facts["verified_materials"] = (_material(digest_char="e"),)
    elif case == "material-set":
        facts["verified_materials"] = ()
    elif case == "declaration":
        facts["declaration_digest"] = "sha256:" + _digest("x")
    elif case == "insert-action":
        facts["approved_action_ids"] = ("alpha",)
    elif case == "reorder":
        facts["approved_action_ids"] = ("beta", "alpha")
    elif case == "correlation-mismatch":
        facts["step_correlations"] = {"prepare": "operation.prepare",
                                      "start": "operation.start",
                                      "alpha": "operation.alpha"}
    elif case == "correlation-reuse":
        plan = _plan(steps=(_step("alpha", material=material, correlation="operation.start"),
                            _step("beta", depends=("alpha",))),
                     materials=(material,))
    with pytest.raises(IdentityMismatchError):
        verify_preparation_effect(plan, **facts)


@pytest.mark.parametrize(
    "case",
    ["target", "scope", "before", "directory", "epoch", "pin",
     "materials", "declaration", "approved", "correlations"],
)
def test_unknown_verification_facts_keep_occupation(case):
    material = _material()
    plan = _plan(steps=(_step("alpha", material=material),), materials=(material,))
    facts = _facts(plan)
    if case == "target":
        facts["target"] = None
    elif case == "scope":
        facts["scope"] = None
    elif case == "before":
        facts["before_revision"] = None
    elif case == "directory":
        facts["directory_binding_ref"] = None
    elif case == "epoch":
        facts["management_epoch"] = None
    elif case == "pin":
        facts["pinned_provider_ref"] = None
    elif case == "materials":
        facts["verified_materials"] = None
    elif case == "declaration":
        facts["declaration_digest"] = None
    elif case == "approved":
        facts["approved_action_ids"] = None
    elif case == "correlations":
        facts["step_correlations"] = None
    with pytest.raises(UnknownResultError):
        verify_preparation_effect(plan, **facts)


def test_material_free_plan_passes_without_a_verified_set():
    # No claimed materials: the C-side set is vacuously satisfied, never faked.
    plan = _plan(steps=(_step("restart-unit"),))
    scope = verify_preparation_effect(plan, **_facts(plan, verified_materials=None))
    assert scope.material_refs == ()


def test_non_mapping_verified_material_is_unknown_not_passed():
    plan = _plan(materials=(_material(),))
    with pytest.raises(UnknownResultError):
        verify_preparation_effect(plan, **_facts(plan, verified_materials=("raw",)))


BRAND_KEYS = frozenset({
    "command", "argv", "executable", "codec", "brand", "providercommand",
    "nativecommand", "shell", "script", "binary", "path", "cwd",
})


def _scan_brands(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("_", "").replace("-", "")
            assert normalized not in BRAND_KEYS, "brand-shaped key survived: %s" % key
            _scan_brands(child)
    elif isinstance(value, list):
        for child in value:
            _scan_brands(child)


def test_gate5_effect_steps_carry_no_brand_fields():
    material = _material()
    plan = _plan(steps=(_step("configure-unit", material=material),
                        _step("restart-unit", depends=("configure-unit",))),
                 materials=(material,))
    scope = verify_preparation_effect(plan, **_facts(plan))
    for payload in (plan.to_dict(), scope.to_dict(),
                    EffectStep._field_dict(plan.steps[0]),
                    FixedEffectScope._field_dict(scope)):
        _scan_brands(payload)
    assert set(plan.to_dict()) == {
        "planId", "declarationDigest", "providerPin", "materialRefs", "target",
        "scope", "beforeRevision", "directoryBindingRef", "managementEpoch", "steps"}
    assert set(plan.steps[0].to_dict()) == {
        "actionId", "inputDigest", "materialRef", "dependsOn", "recoveryCorrelation"}
    assert set(scope.to_dict()) == {
        "planId", "effectDigest", "actionIds", "inputDigests", "materialRefs",
        "target", "scope", "beforeRevision", "directoryBindingRef",
        "managementEpoch", "recoveryCorrelations"}
