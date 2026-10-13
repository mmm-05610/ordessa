"""Modern pure mapping into real SQLite commands; access remains admitted by host."""
import asyncio
import hashlib
import json
from dataclasses import replace

import pytest

from ordessa_engineering.application.orchestration.method_bridge import MethodBridge, command_capabilities
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.methods.definitions.models.capabilities import CapabilityBinding
from ordessa_engineering.methods.definitions.models.compiled import (
    CompiledProgram, OperationNode, OutcomeMap, OutcomeBinding, TransitionTarget,
    SlotMap, SlotBinding, WorkflowSpec, freeze_value,
)
from ordessa_engineering.application.api.service import EngineeringService, SUPPORTED_COMMANDS
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory


def program():
    descriptor = next(d for d in command_capabilities().capabilities
                      if d.capability_id == "engineering.artifacts.create")
    node = OperationNode(id="capture_document", kind="operation", operation=descriptor.capability_id,
        outcomes=OutcomeMap(entries=tuple(OutcomeBinding(outcome=x,
            target=TransitionTarget(stop=x)) for x in descriptor.contract["workflow_outcomes"])),
        inputs=SlotMap(entries=(SlotBinding("kind", "document_kind"), SlotBinding("initial", "body"))),
        config=freeze_value({"kind": "not-an-artifact-kind", "grant": "agent-text"}))
    return CompiledProgram(compiler_version="test", workflow=WorkflowSpec(schema_version=1,
        entry=node.id, steps=(node,), stop_outcomes=("completed", "rejected"), wait_kinds=()),
        document_definitions=(), schema_definitions=(), standard_definitions=(),
        decision_definitions=(), skill_definitions=(), capability_bindings=(CapabilityBinding(
            descriptor.capability_id, descriptor.kind, descriptor.interface_version,
            descriptor.contract_digest),))


def slots():
    return {"document_kind": "other", "body": {"media_type": "application/json",
        "schema_id": "urn:test:method-document", "inline_value": {"decisions": ["A"]}}}


def compile_captured_program(tmp_path):
    from ordessa_engineering.methods import compile_method
    from ordessa_engineering.methods.loading.loader import load_method
    from ordessa_engineering.methods.definitions.models import MethodSource
    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
    source = tmp_path / "captured-method"
    source.mkdir()
    descriptor = command_capabilities().capabilities[0]
    workflow = {"schema_version": 1, "entry": "capture_document",
        "context_slots": ["document_kind", "body"],
        "steps": [{"id": "capture_document", "kind": "operation",
            "operation": descriptor.capability_id,
            "inputs": {"kind": "document_kind", "initial": "body"},
            "outcomes": {name: {"stop": name} for name in descriptor.contract["workflow_outcomes"]}}],
        "stop_outcomes": ["completed", "rejected"], "wait_kinds": []}
    raw = json.dumps(workflow).encode()
    (source / "workflow.yaml").write_bytes(raw)
    manifest = {"schema_version": 1, "method_id": "test.real-command-bridge", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": [{"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
            "media_type": "application/yaml", "sha256": hashlib.sha256(raw).hexdigest()}],
        "requires": [{key: getattr(descriptor, key) for key in
            ("capability_id", "kind", "interface_version", "contract_digest")}], "documents": []}
    (source / "method.yaml").write_text(json.dumps(manifest))
    loaded = load_method(MethodSource(source), FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, command_capabilities(), "test.compiler/1")
    assert compiled.ok, compiled.error
    return compiled.value.program


def test_slot_bridge_executes_original_sqlite_journal_and_reopens(tmp_path):
    path = (tmp_path / "bridge.sqlite").resolve()
    scope = Scope("bridge-realm", "bridge-project")
    ctx = CommandContext(scope, "principal", ActorRef("test", "human", "fixture"),
                         "one-request", "2026-10-11T12:00:00.000000Z", "trace")
    class Access:
        def require(self, context, operation):
            if context is not ctx:
                raise ApplicationError("ACCESS_DENIED")
    params = MethodBridge().operation_inputs(compile_captured_program(tmp_path), "capture_document", slots())
    library = EngineeringLibrary.create(path, library_id="bridge", schema_version=7)
    try:
        facade = EngineeringService(SQLiteUoWFactory(library), Access())
        result = asyncio.run(facade.execute("engineering.artifacts.create", params, ctx))
        assert result.status == "completed"
        assert asyncio.run(facade.execute("engineering.artifacts.create", params, ctx)) == result
        assert library._connection.execute("SELECT count(*) FROM eng_artifacts").fetchone()[0] == 1
        copied = replace(ctx, request_id="another-request")
        with pytest.raises(ApplicationError, match="ACCESS_DENIED"):
            asyncio.run(facade.execute("engineering.artifacts.create", params, copied))
    finally:
        library.close()
    reopened = EngineeringLibrary.open(path, library_id="bridge")
    try:
        facade = EngineeringService(SQLiteUoWFactory(reopened), Access())
        assert asyncio.run(facade.execute("engineering.artifacts.create", params, ctx)) == result
        assert reopened._connection.execute("SELECT count(*) FROM eng_artifacts").fetchone()[0] == 1
    finally:
        reopened.close()


def test_slots_and_descriptors_are_detached_and_config_is_not_command_data():
    original = slots()
    mapped = MethodBridge().operation_inputs(program(), "capture_document", original)
    assert set(mapped) == {"kind", "initial"} and mapped["kind"] == "other"
    original["body"]["inline_value"]["decisions"].append("B")
    assert mapped["initial"]["inline_value"]["decisions"] == ["A"]
    mapped["initial"]["inline_value"]["decisions"].append("C")
    assert original["body"]["inline_value"]["decisions"] == ["A", "B"]
    descriptors = command_capabilities()
    descriptors.capabilities[0].contract["input_schema"]["type"] = "null"
    assert command_capabilities().capabilities[0].contract["input_schema"]["type"] == "object"


def test_facade_and_method_catalog_share_each_real_command_schema():
    descriptors = {item.capability_id: item for item in command_capabilities().capabilities}
    assert set(descriptors) == set(SUPPORTED_COMMANDS)
    assert len(descriptors) == len(SUPPORTED_COMMANDS)

    # Construction exposes the actual finite handler map; every advertised
    # command must have both a handler and its owning schema.
    facade = EngineeringService(object(), object())
    assert set(facade._commands) == set(SUPPORTED_COMMANDS)
    for operation, descriptor in descriptors.items():
        schema = EngineeringService.input_schema(operation)
        assert descriptor.contract["input_schema"] == schema
        if operation == "engineering.packages.freeze":
            expected_id = "urn:ordessa:engineering:implementation-content:1"
        elif operation == "engineering.submissions.record_report":
            expected_id = (
                "urn:ordessa:engineering:owner-operation:"
                "engineering.submissions.record_report:input:1"
            )
        else:
            input_kind = "command-input" if operation == "engineering.reviews.record" else "input"
            version = "2" if operation.startswith("engineering.artifacts.") else "1"
            expected_id = f"urn:ordessa:engineering:operations:{operation}:{input_kind}:{version}"
        assert schema["$id"] == expected_id


def test_facade_does_not_fall_back_to_an_unrelated_schema(monkeypatch):
    from ordessa_engineering.application.api import service as facade_module

    monkeypatch.setattr(facade_module, "SUPPORTED_COMMANDS",
        SUPPORTED_COMMANDS + ("engineering.proposals.unowned",))
    with pytest.raises(ApplicationError, match="OPERATION_SCHEMA_UNAVAILABLE"):
        EngineeringService.input_schema("engineering.proposals.unowned")


@pytest.mark.parametrize("change", [{"interface_version": "1"}, {"contract_digest": "0" * 64},
                                  {"kind": "check"}])
def test_changed_capability_never_calls_usecase(change):
    value = program()
    value = replace(value, capability_bindings=(replace(value.capability_bindings[0], **change),))
    with pytest.raises(ApplicationError, match="METHOD_CAPABILITY_CHANGED"):
        MethodBridge().operation_inputs(value, "capture_document", slots())


@pytest.mark.parametrize("inputs,code", [({}, "METHOD_INPUT_SLOT_UNAVAILABLE"),
    ({"document_kind": "decision", "body": {}}, "INVALID_ARGUMENT"),
    ({"document_kind": "other", "body": object()}, "INVALID_METHOD_SLOTS")])
def test_missing_invalid_and_live_object_slots_refuse(inputs, code):
    with pytest.raises(ApplicationError, match=code):
        MethodBridge().operation_inputs(program(), "capture_document", inputs)


def test_unknown_node_and_duplicate_node_refuse():
    value = program()
    with pytest.raises(ApplicationError, match="METHOD_OPERATION_NODE_UNAVAILABLE"):
        MethodBridge().operation_inputs(value, "absent", slots())
    value = replace(value, workflow=replace(value.workflow, steps=value.workflow.steps * 2))
    with pytest.raises(ApplicationError, match="METHOD_OPERATION_NODE_UNAVAILABLE"):
        MethodBridge().operation_inputs(value, "capture_document", slots())


def test_no_invented_review_outcomes_or_unimplemented_operation():
    value = program()
    node = replace(value.workflow.steps[0], outcomes=OutcomeMap(entries=(OutcomeBinding(
        outcome="passed", target=TransitionTarget(stop="passed")),)))
    with pytest.raises(ApplicationError, match="METHOD_OUTCOME_CONTRACT_MISMATCH"):
        MethodBridge().operation_inputs(replace(value, workflow=replace(value.workflow,
            steps=(node,))), node.id, slots())
    node = replace(node, operation="engineering.baselines.apply")
    with pytest.raises(ApplicationError, match="OPERATION_UNAVAILABLE"):
        MethodBridge().operation_inputs(replace(value, workflow=replace(value.workflow,
            steps=(node,))), node.id, slots())
