"""Public loader/compiler coverage for bounded serial workflow rework."""
from __future__ import annotations

import hashlib
import json

import yaml

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.methods import compile_method, load_method, validate_method
from ordessa_engineering.methods.compilation.encoding import (
    program_to_canonical, stored_program_from_canonical,
)
from ordessa_engineering.methods.definitions.models import (
    CapabilityDescriptor, CompilationCapabilities, MethodSource,
)
from ordessa_engineering.methods.definitions.models.identity import method_digest


CONTRACT = {"method_config_schema": None, "workflow_outcomes": ["ok"]}
CAPABILITY = CapabilityDescriptor(
    "op.review", "operation", "1.0.0",
    method_digest("capability-contract", CONTRACT), CONTRACT,
)
CAPABILITIES = CompilationCapabilities((CAPABILITY,), trust_class="host")


def _workflow(*, counted=True):
    value = {
        "schema_version": 1,
        "entry": "review",
        "context_slots": ["review_result"],
        "outputs": {"final_review": "review_result"},
        "steps": [
            {"id": "review", "kind": "operation", "operation": "op.review",
             "outcomes": {"ok": {"stop": "finished"}},
             "result_routing": {"path": "/status", "outcomes": {
                 "revise": {"next": "revise"}, "accept": {"stop": "finished"},
             }}},
            {"id": "revise", "kind": "operation", "operation": "op.review",
             "outcomes": {"ok": {"next": "review"}}},
        ],
        "stop_outcomes": ["finished"],
        "wait_kinds": [],
    }
    if counted:
        value["loops"] = [{"loop_id": "review-rework", "from_step": "revise",
                           "to_step": "review", "max_rounds": 3,
                           "on_exhausted": "finished"}]
    return value


def _load(tmp_path, workflow):
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True)
    content = yaml.safe_dump(json.loads(json.dumps(workflow)), sort_keys=False).encode()
    (bundle / "workflow.yaml").write_bytes(content)
    manifest = {
        "schema_version": 1, "method_id": "test.bounded", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": [{"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
                       "media_type": "application/yaml", "sha256": hashlib.sha256(content).hexdigest()}],
        "requires": [{"capability_id": CAPABILITY.capability_id, "kind": "operation",
                      "interface_version": CAPABILITY.interface_version,
                      "contract_digest": CAPABILITY.contract_digest}],
    }
    (bundle / "method.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return load_method(MethodSource(bundle), FileResourceReader())


def test_bounded_rework_loads_validates_compiles_and_roundtrips(tmp_path):
    loaded_result = _load(tmp_path, _workflow())
    assert loaded_result.ok, loaded_result.error
    loaded = loaded_result.value
    report = validate_method(loaded, CAPABILITIES)
    assert report.valid, report.diagnostics
    compiled_result = compile_method(loaded, CAPABILITIES, "test.compiler/1")
    assert compiled_result.ok, compiled_result.error
    canonical = program_to_canonical(compiled_result.value.program)
    workflow = canonical["workflow"]
    assert workflow["outputs"] == {"final_review": "review_result"}
    assert workflow["loops"][0]["max_rounds"] == 3
    assert workflow["steps"][0]["result_routing"]["outcomes"]["revise"] == {"next": "revise"}
    assert program_to_canonical(stored_program_from_canonical(canonical)) == canonical


def test_unmarked_cycle_remains_unsupported(tmp_path):
    loaded_result = _load(tmp_path, _workflow(counted=False))
    assert loaded_result.ok, loaded_result.error
    report = validate_method(loaded_result.value, CAPABILITIES)
    assert not report.valid
    assert any(item.code == "UNSUPPORTED_FLOW_CYCLE" for item in report.diagnostics)


def test_invalid_bounded_workflow_contracts_are_rejected(tmp_path):
    cases = []
    bad_limit = _workflow()
    bad_limit["loops"][0]["max_rounds"] = 0
    cases.append((bad_limit, {"METHOD_STRUCTURE_INVALID", "WORKFLOW_LOOP_LIMIT_INVALID"}))
    bool_limit = _workflow()
    bool_limit["loops"][0]["max_rounds"] = True
    cases.append((bool_limit, {"METHOD_STRUCTURE_INVALID", "WORKFLOW_LOOP_LIMIT_INVALID"}))
    bad_slot = _workflow()
    bad_slot["outputs"]["final_review"] = "undeclared"
    cases.append((bad_slot, {"WORKFLOW_OUTPUT_SLOT_UNKNOWN"}))
    bad_target = _workflow()
    bad_target["steps"][0]["result_routing"]["outcomes"]["revise"] = {"next": "missing"}
    cases.append((bad_target, {"WORKFLOW_TARGET_MISSING"}))

    for index, (workflow, expected_codes) in enumerate(cases):
        case_dir = tmp_path / f"case-{index}"
        case_dir.mkdir()
        loaded_result = _load(case_dir, workflow)
        assert loaded_result.ok, loaded_result.error
        report = validate_method(loaded_result.value, CAPABILITIES)
        assert not report.valid
        assert any(item.code in expected_codes for item in report.diagnostics), report.diagnostics


def test_duplicate_loop_ids_and_edges_are_rejected(tmp_path):
    duplicate_id = _workflow()
    duplicate_id["loops"].append({"loop_id": "review-rework", "from_step": "review",
                                   "to_step": "revise", "max_rounds": 2,
                                   "on_exhausted": "finished"})
    loaded_result = _load(tmp_path / "same-id", duplicate_id)
    assert loaded_result.ok, loaded_result.error
    report = validate_method(loaded_result.value, CAPABILITIES)
    assert not report.valid
    assert any(item.code == "DUPLICATE_WORKFLOW_LOOP" for item in report.diagnostics)

    duplicate_edge = _workflow()
    duplicate_edge["loops"].append({"loop_id": "second-count", "from_step": "revise",
                                    "to_step": "review", "max_rounds": 2,
                                    "on_exhausted": "finished"})
    loaded_result = _load(tmp_path / "same-edge", duplicate_edge)
    assert loaded_result.ok, loaded_result.error
    report = validate_method(loaded_result.value, CAPABILITIES)
    assert not report.valid
    assert any(item.code == "DUPLICATE_WORKFLOW_LOOP_EDGE" for item in report.diagnostics)


def test_wait_step_cannot_be_counted_loop_source(tmp_path):
    workflow = _workflow()
    workflow["wait_kinds"] = ["approval"]
    workflow["steps"][1] = {"id": "revise", "kind": "wait", "event": "approval",
                            "next": "review"}
    loaded_result = _load(tmp_path, workflow)
    assert loaded_result.ok, loaded_result.error
    report = validate_method(loaded_result.value, CAPABILITIES)
    assert not report.valid
    assert any(item.code == "WORKFLOW_LOOP_SOURCE_INVALID" for item in report.diagnostics)


def test_operation_cannot_have_multiple_counted_edges(tmp_path):
    workflow = _workflow()
    workflow["steps"][1]["result_routing"] = {
        "path": "/status", "outcomes": {"archive": {"next": "archive"}},
    }
    workflow["steps"].append({"id": "archive", "kind": "stop", "outcome": "finished"})
    workflow["loops"].append({"loop_id": "second-edge", "from_step": "revise",
                              "to_step": "archive", "max_rounds": 2,
                              "on_exhausted": "finished"})
    loaded_result = _load(tmp_path, workflow)
    assert loaded_result.ok, loaded_result.error
    report = validate_method(loaded_result.value, CAPABILITIES)
    assert not report.valid
    assert any(item.code == "WORKFLOW_LOOP_AMBIGUOUS" for item in report.diagnostics)


def test_legacy_compiled_wire_omits_new_optional_fields_and_keeps_bytes(tmp_path):
    workflow = {
        "schema_version": 1, "entry": "review", "steps": [
            {"id": "review", "kind": "operation", "operation": "op.review",
             "outcomes": {"ok": {"stop": "finished"}}},
        ], "stop_outcomes": ["finished"], "wait_kinds": [],
    }
    loaded_result = _load(tmp_path, workflow)
    assert loaded_result.ok, loaded_result.error
    compiled = compile_method(loaded_result.value, CAPABILITIES, "test.compiler/1")
    assert compiled.ok, compiled.error
    canonical = program_to_canonical(compiled.value.program)
    assert "outputs" not in canonical["workflow"]
    assert "loops" not in canonical["workflow"]
    assert all("result_routing" not in step for step in canonical["workflow"]["steps"])
    encode = lambda obj: json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    original_bytes = encode(canonical)
    restored_bytes = encode(program_to_canonical(stored_program_from_canonical(canonical)))
    assert restored_bytes == original_bytes
