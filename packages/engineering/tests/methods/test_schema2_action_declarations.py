"""Schema-2 declarations use the bounded capture reader but have no compiler."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.methods import compile_method, load_method, read_method_definition
from ordessa_engineering.methods.definitions.models import MethodSource
from ordessa_engineering.methods.definitions.models import ActionInput, ActionStep, AdmissionRequirement


REPO_ROOT = Path(__file__).resolve().parents[4]
CANDIDATE = REPO_ROOT / "methods/incremental-engineering/candidates/2.7.0"


def _declaration(*, action: dict | None = None, routing: dict | None = None,
                 schema: dict | None = None) -> dict:
    return action or {
        "schema_version": 1, "action_id": "test.action",
        "inputs": [{"name": "source", "value_kind": "source_ref"},
                   {"name": "profile", "value_kind": "profile_ref"}],
        "steps": [{"step_id": "first", "kind": "invoke", "name": "prepare",
                   "inputs": [{"name": "source", "source_kind": "action_input", "source_name": "source"}],
                   "outputs": ["result"]}],
        "outputs": [{"name": "result", "value_kind": "json_object", "step_id": "first", "output": "result"}],
        "admission": [], "resources": [],
    }


def _load_fixture(tmp_path: Path, *, action: dict | None = None, routing: dict | None = None,
                  routing_resources: list[dict] | None = None, schema: dict | None = None):
    if routing_resources is None:
        routing_resources = [routing or {
            "schema_version": 1, "routes": [{"action_id": "test.action", "profile_ref": {"kind": "caller_input", "input": "profile"}}]}]
    values = {
        "action": ("action", "application/json", _declaration(action=action)),
        "schema": ("schema", "application/schema+json", schema or {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}),
    }
    for index, route_resource in enumerate(routing_resources):
        resource_id = "routing" if index == 0 else f"routing-{index}"
        values[resource_id] = ("routing", "application/json", route_resource)
    resources = []
    for rid, (kind, media, value) in values.items():
        raw = json.dumps(value, separators=(",", ":")).encode()
        (tmp_path / f"{rid}.json").write_bytes(raw)
        resources.append({"id": rid, "kind": kind, "path": f"{rid}.json", "media_type": media,
                          "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {
        "schema_version": 2, "contract": "ordessa.methods/actions-v1",
        "method_id": "test.method", "release_version": "1.0.0",
        "actions": ["action"], "criteria": [], "prompts": [], "templates": [],
        "schemas": ["schema"], "routing": [key for key in values if key.startswith("routing")],
        "resources": resources,
    }
    (tmp_path / "method.json").write_text(json.dumps(manifest), encoding="utf-8")
    return load_method(MethodSource(tmp_path, "method.json"), FileResourceReader())


def test_candidate_is_typed_from_the_real_bounded_capture_and_not_compilable() -> None:
    loaded = load_method(MethodSource(CANDIDATE, "method.json"), FileResourceReader())
    assert loaded.ok and loaded.value is not None
    typed = read_method_definition(loaded.value)
    assert typed.ok and typed.value is not None
    assert typed.value.release_version == "2.7.0"
    assert [item.action_id for item in typed.value.actions] == [
        "incremental.review-change", "incremental.prepare-packages", "incremental.implement-package",
    ]
    review_action = typed.value.actions[0]
    register_step = review_action.steps[-1]
    assert [gate.kind for gate in register_step.admission] == [
        "review_complete", "review_passed", "exact_inputs", "same_scope", "method_pin", "baseline_available",
    ]
    implementation_action = typed.value.actions[-1]
    assert {item.name for item in implementation_action.inputs} >= {"profile", "reviewer_profile"}
    assert any(gate.kind == "reviewer_independent"
               for gate in implementation_action.steps[2].admission)
    result = compile_method(loaded.value, object(), "test-compiler")
    assert not result.ok and result.error is not None
    assert result.error.code == "METHOD_EXECUTION_UNSUPPORTED"


@pytest.mark.parametrize("mutation", ["unknown_step", "out_of_order", "unknown_admission",
                                       "future_output_admission", "unbound_step_gate",
                                       "undeclared_resource", "unbound_method_resource",
                                       "invalid_schema", "unknown_schema_ref",
                                       "missing_action_route", "missing_profile_input",
                                       "empty_routing_declaration", "duplicate_route_resources"])
def test_schema2_closed_bindings_and_schema_closure_reject_invalid_declarations(tmp_path: Path, mutation: str) -> None:
    action = _declaration()
    routing = {"schema_version": 1, "routes": [{"action_id": "test.action", "profile_ref": {"kind": "caller_input", "input": "profile"}}]}
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
    if mutation == "unknown_step":
        action["steps"][0]["kind"] = "run_script"
    elif mutation == "out_of_order":
        action["steps"].insert(0, {"step_id": "early", "kind": "record", "name": "bad-order",
            "inputs": [{"name": "x", "source_kind": "step_output", "source_name": "result", "step_id": "later"}],
            "outputs": ["x"]})
    elif mutation == "unknown_admission":
        action["admission"] = [{"kind": "review_passed", "inputs": ["not-an-input"]}]
    elif mutation == "future_output_admission":
        action["admission"] = [{"kind": "review_passed", "inputs": ["result"]}]
    elif mutation == "unbound_step_gate":
        action["steps"][0]["admission"] = [{"kind": "review_complete", "inputs": ["review"]}]
    elif mutation == "undeclared_resource":
        action["resources"] = ["missing"]
        action["steps"][0]["inputs"] = [{"name": "prompt", "source_kind": "resource", "source_name": "missing"}]
    elif mutation == "unbound_method_resource":
        action["steps"][0]["inputs"] = [{"name": "schema", "source_kind": "resource", "source_name": "schema"}]
    elif mutation == "invalid_schema":
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "not-a-schema-type"}
    elif mutation == "unknown_schema_ref":
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": "https://example.invalid/remote.json"}
    elif mutation == "missing_action_route":
        routing["routes"][0]["action_id"] = "missing.action"
    elif mutation == "missing_profile_input":
        action["inputs"] = []
    elif mutation == "empty_routing_declaration":
        # No routing resource at all: profile_ref inputs still require exactly one route.
        loaded = _load_fixture(tmp_path, action=action, routing_resources=[] , schema=schema)
        assert loaded.ok and loaded.value is not None
        result = read_method_definition(loaded.value)
        assert not result.ok and result.error is not None
        return
    elif mutation == "duplicate_route_resources":
        first = routing
        routing_resources = [first, {"schema_version": 1, "routes": [
            {"action_id": "test.action", "profile_ref": {"kind": "caller_input", "input": "profile"}}]}]
        loaded = _load_fixture(tmp_path, action=action, routing_resources=routing_resources, schema=schema)
        assert loaded.ok and loaded.value is not None
        result = read_method_definition(loaded.value)
        assert not result.ok and result.error is not None
        return

    loaded = _load_fixture(tmp_path, action=action, routing=routing, schema=schema)
    assert loaded.ok and loaded.value is not None
    result = read_method_definition(loaded.value)
    assert not result.ok and result.error is not None


def test_schema2_rejects_caller_constructed_projection_drift() -> None:
    from dataclasses import replace
    loaded = load_method(MethodSource(CANDIDATE, "method.json"), FileResourceReader())
    assert loaded.ok and loaded.value is not None
    forged = replace(loaded.value, parsed_source=replace(loaded.value.parsed_source,
        manifest_content=replace(loaded.value.parsed_source.manifest_content,
            value_tree={"schema_version": 2})))
    result = read_method_definition(forged)
    assert not result.ok and result.error is not None
    assert result.error.code == "LOADED_PROJECTION_INVALID"


def test_schema2_source_pin_changes_when_same_release_capture_changes(tmp_path: Path) -> None:
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = _load_fixture(first_root)
    assert first.ok and first.value is not None
    first_definition = read_method_definition(first.value)
    assert first_definition.ok and first_definition.value is not None
    original_pin = first_definition.value.method_ref
    second_action = _declaration()
    second_action["steps"][0]["name"] = "different-captured-operation"
    second = _load_fixture(second_root, action=second_action)
    assert second.ok and second.value is not None
    second_definition = read_method_definition(second.value)
    assert second_definition.ok and second_definition.value is not None
    assert first_definition.value.method_ref.method_id == second_definition.value.method_ref.method_id
    assert first_definition.value.method_ref.release_version == second_definition.value.method_ref.release_version
    assert first_definition.value.method_ref.snapshot_digest != second_definition.value.method_ref.snapshot_digest
    assert first_definition.value.method_ref == original_pin


def test_schema2_typed_models_reject_unbounded_or_mutable_constructor_values() -> None:
    with pytest.raises(ValueError):
        ActionInput("", "source_ref")
    with pytest.raises(ValueError):
        ActionInput("input", "python")
    with pytest.raises(ValueError):
        ActionStep("step", "invoke", "invoke", [], (), ())
    with pytest.raises(ValueError):
        AdmissionRequirement("review_approved", ("review",))
