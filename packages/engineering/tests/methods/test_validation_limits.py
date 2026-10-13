"""Offline parser and check-binding counterexamples, without production trust.

Capability descriptors below are synthetic fixture inputs. These tests do not
establish a real registry adapter, owner schema or executable handler binding.
"""
from __future__ import annotations
from ordessa_engineering.methods.loading import parsing

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader

import hashlib
from pathlib import Path

import pytest
import yaml

from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models.identity import method_digest
from ordessa_engineering.methods.definitions import schemas
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.methods.definitions.models import (
    CapabilityDescriptor, CompilationCapabilities, LoadLimits, MethodSource,
)
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods import validate_method


def _nested_yaml(depth: int, kind: str) -> bytes:
    value = "0"
    for index in range(depth):
        sequence = kind == "sequence" or (kind == "mixed" and index % 2 == 0)
        value = f"[{value}]" if sequence else f"{{k: {value}}}"
    return value.encode("utf-8")


@pytest.mark.parametrize("kind", ["sequence", "mapping", "mixed"])
def test_yaml_depth_64_remains_accepted(kind):
    value = parsing.parse_document(_nested_yaml(64, kind), "application/yaml", "resource.yaml")
    assert isinstance(value, (list, dict))


@pytest.mark.parametrize("kind", ["sequence", "mapping", "mixed"])
def test_yaml_depth_65_is_rejected_before_object_construction(kind, monkeypatch):
    def forbidden_load(*args, **kwargs):
        raise AssertionError("over-deep YAML must not reach object construction")

    monkeypatch.setattr(parsing.yaml, "load", forbidden_load)
    with pytest.raises(MethodFailure) as failure:
        parsing.parse_document(_nested_yaml(65, kind), "application/yaml", "resource.yaml")
    assert failure.value.error.code == "STRUCTURE_TOO_DEEP"
    assert failure.value.error.path == "resource.yaml"


def test_yaml_event_limit_prevents_parser_recursion_for_very_deep_input(monkeypatch):
    def forbidden_load(*args, **kwargs):
        raise AssertionError("unbounded YAML must not reach object construction")

    monkeypatch.setattr(parsing.yaml, "load", forbidden_load)
    with pytest.raises(MethodFailure) as failure:
        parsing.parse_document(b"[" * 2000 + b"0" + b"]" * 2000,
                               "application/yaml", "resource.yaml")
    assert failure.value.error.code == "STRUCTURE_TOO_DEEP"


def test_json_parser_recursion_is_a_controlled_method_failure(monkeypatch):
    def recursive_decode(*args, **kwargs):
        raise RecursionError("synthetic decoder recursion limit")

    monkeypatch.setattr(parsing, "decode_json", recursive_decode)
    with pytest.raises(MethodFailure) as failure:
        parsing.parse_document(b"[]", "application/json", "resource.json")
    assert failure.value.error.code == "STRUCTURE_TOO_DEEP"
    assert failure.value.error.path == "resource.json"
    assert isinstance(failure.value.__cause__, RecursionError)


def test_actual_deep_json_never_leaks_recursion_error():
    with pytest.raises(MethodFailure):
        parsing.parse_document(b"[" * 2000 + b"0" + b"]" * 2000,
                               "application/json", "resource.json")


@pytest.mark.parametrize("media_type,path", [
    ("application/yaml", "resource.yaml"), ("application/json", "resource.json"),
])
def test_real_resource_loader_returns_failure_for_extreme_nesting(tmp_path, media_type, path):
    raw = b"[" * 2000 + b"0" + b"]" * 2000
    (tmp_path / path).write_bytes(raw)
    manifest = {
        "schema_version": 1, "method_id": "fixture.depth", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.fixture"},
        "resources": [{"id": "workflow.fixture", "kind": "workflow", "path": path,
                       "media_type": media_type, "sha256": hashlib.sha256(raw).hexdigest()}],
        "requires": [],
    }
    (tmp_path / "method.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert not result.ok and result.error is not None
    assert result.error.path == path
    assert result.error.code in {"STRUCTURE_TOO_DEEP", "METHOD_PARSE_ERROR"}


def test_parser_changes_preserve_resource_reader_byte_limit(tmp_path):
    (tmp_path / "method.yaml").write_bytes(b"x" * 9)
    result = load_method(MethodSource(tmp_path), reader=FileResourceReader(), limits=LoadLimits(manifest_bytes=8))
    assert not result.ok and result.error is not None
    assert result.error.code == "RESOURCE_TOO_LARGE"


@pytest.mark.parametrize("raw,code", [
    (b"value: 1\nvalue: 2\n", "DUPLICATE_KEY"),
    (b"value: &item [1]\nother: *item\n", "YAML_ALIAS_OR_ANCHOR"),
    (b"value: 0.5\n", "NON_JSON_VALUE"),
])
def test_yaml_depth_preflight_preserves_strict_value_rejections(raw, code):
    with pytest.raises(MethodFailure) as failure:
        parsing.parse_document(raw, "application/yaml", "resource.yaml")
    assert failure.value.error.code == code


def _check_bundle(root: Path, *, descriptor_kind="check", check_version="1.0.0",
                  requirement_version="1.0.0", declare_requirement=True):
    contract = {
        "input_type": "FixtureCheckInput", "output_type": "FixtureCheckResult",
        "effects": "read", "idempotency": "request_id_and_payload_digest",
        "trusted_ingress": "authenticated-system-access",
        "workflow_outcomes": ["completed"],
    }
    digest = method_digest("capability-contract", contract)
    descriptor = CapabilityDescriptor("fixture.check", descriptor_kind, "1.0.0", digest, contract)
    check = {"capability_id": "fixture.check", "bindings": {}}
    if check_version is not None:
        check["interface_version"] = check_version
    workflow = {
        "schema_version": 1, "entry": "done",
        "steps": [{"id": "done", "kind": "stop", "outcome": "finished"}],
        "stop_outcomes": ["finished"], "wait_kinds": [],
    }
    standard = {
        "schema_version": 1, "standard_id": "fixture", "revision": "1.0.0",
        "criteria": [{
            "criterion_id": "fixture-criterion", "statement": "Synthetic check",
            "checks": [check],
            "policy": {"satisfied": "pass", "violated": "block",
                       "insufficient": "block", "unknown": "manual"},
        }],
        "reduction": {"required_criteria": "all_applicable", "empty_applicable_set": "error",
                      "priority": ["block", "manual", "pass"]},
    }
    resources = []
    for resource_id, kind, path, value in (
        ("workflow.fixture", "workflow", "workflow.yaml", workflow),
        ("standard.fixture", "standard", "standard.yaml", standard),
    ):
        raw = yaml.safe_dump(value, sort_keys=False).encode("utf-8")
        (root / path).write_bytes(raw)
        resources.append({"id": resource_id, "kind": kind, "path": path,
                          "media_type": "application/yaml", "sha256": hashlib.sha256(raw).hexdigest()})
    requirement = {"capability_id": descriptor.capability_id, "kind": descriptor_kind,
                   "interface_version": requirement_version, "contract_digest": digest}
    manifest = {
        "schema_version": 1, "method_id": "fixture.validation-limits", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.fixture"},
        "resources": resources, "requires": [requirement] if declare_requirement else [],
    }
    (root / "method.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    loaded = load_method(MethodSource(root), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    return loaded.value, CompilationCapabilities((descriptor,), "synthetic-fixture", "fixture")


def test_exact_check_kind_and_version_pass_offline_fixture_validation(tmp_path):
    loaded, catalog = _check_bundle(tmp_path)
    report = validate_method(loaded, catalog)
    assert report.valid
    assert any(item.code == "FIXTURE_CAPABILITIES_ONLY" for item in report.diagnostics)
    compiled = compile_method(loaded, catalog, "fixture.compiler/1")
    assert compiled.ok and compiled.value is not None
    assert any(item.code == "FIXTURE_CAPABILITIES_ONLY" for item in compiled.value.diagnostics)


@pytest.mark.parametrize("arguments,code", [
    ({"descriptor_kind": "operation"}, "CAPABILITY_KIND_MISMATCH"),
    ({"check_version": "99.0.0"}, "CHECK_INTERFACE_VERSION_MISMATCH"),
    ({"check_version": None}, "CHECK_INTERFACE_VERSION_INVALID"),
    ({"check_version": ""}, "CHECK_INTERFACE_VERSION_INVALID"),
    ({"check_version": 1}, "CHECK_INTERFACE_VERSION_INVALID"),
])
def test_standard_check_rejects_wrong_kind_or_nonexact_version(tmp_path, arguments, code):
    loaded, catalog = _check_bundle(tmp_path, **arguments)
    report = validate_method(loaded, catalog)
    assert not report.valid
    errors = [item for item in report.diagnostics if item.severity == "error"]
    assert [item.code for item in errors] == [code]
    assert errors[0].resource_id == "standard.fixture"
    assert errors[0].path == "standard.yaml"
    field = "capability_id" if code == "CAPABILITY_KIND_MISMATCH" else "interface_version"
    assert errors[0].pointer == f"/criteria/0/checks/0/{field}"
    compiled = compile_method(loaded, catalog, "fixture.compiler/1")
    assert not compiled.ok and compiled.error is not None
    assert compiled.error.code == code


@pytest.mark.parametrize("arguments,code", [
    ({"requirement_version": "99.0.0"}, "CAPABILITY_REQUIREMENT_MISMATCH"),
    ({"declare_requirement": False}, "CAPABILITY_NOT_DECLARED"),
])
def test_check_validation_keeps_manifest_exact_requirement_binding(tmp_path, arguments, code):
    loaded, catalog = _check_bundle(tmp_path, **arguments)
    report = validate_method(loaded, catalog)
    assert not report.valid
    assert code in {item.code for item in report.diagnostics if item.severity == "error"}
