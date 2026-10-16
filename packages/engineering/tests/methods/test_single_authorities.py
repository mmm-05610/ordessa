"""One source/program authority; properties neither store competing values nor do IO."""
from ordessa_engineering.methods.compilation.encoding import (compiled_program_from_canonical, program_documents, program_encoding, program_entry, program_nodes, program_plan_digest, program_skills, program_to_canonical, semantic_from_wire, semantic_to_wire, stored_program_from_canonical)
from dataclasses import FrozenInstanceError, fields, replace
import hashlib
import json
from pathlib import Path

import pytest

from ordessa_engineering.methods.definitions.errors import MethodError, MethodFailure
from ordessa_engineering.methods.definitions.models import (
    ParsedContent, CapturedResource, CompilationCapabilities, CompiledMethod, CompiledProgram,
    CurrentStoredProgram, FrozenObject, LoadedMethod, MethodSnapshot, MethodSource,
    ResourceBytes, SourceBundle, StoredProgram, VerificationInputs, freeze_value,
)
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods import compile_method


def _load():
    files = {
        "workflow.json": json.dumps({"schema_version": 1, "entry": "done", "steps": [
            {"id": "done", "kind": "stop", "outcome": "finished"}],
            "stop_outcomes": ["finished"], "wait_kinds": []}).encode(),
        "schema.json": json.dumps({"type": "object", "properties": {
            "field": {"type": "string", "enum": ["initial"]}}}).encode(),
    }
    manifest = {"schema_version": 1, "method_id": "test.authorities", "release_version": "1",
                "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow"},
                "requires": [], "metadata": {"nested": ["initial"]},
                "documents": [{"document_type": "test", "schema": {"resource": "schema"}}],
                "resources": [{"id": id, "kind": kind, "path": path, "media_type": "application/json",
                    "sha256": hashlib.sha256(files[path]).hexdigest()}
                    for id, kind, path in (("workflow", "workflow", "workflow.json"),
                                           ("schema", "document_schema", "schema.json"))]}
    files["method.yaml"] = json.dumps(manifest).encode()

    class Reader:
        def read(self, source, path, max_bytes):
            if path not in files:
                raise MethodFailure(MethodError("RESOURCE_NOT_FOUND", "not present"))
            return files[path]

    loaded = load_method(MethodSource(Path("not-read-by-properties")), Reader())
    assert loaded.ok, loaded.error
    return loaded.value


def _compile(loaded):
    result = compile_method(loaded, CompilationCapabilities(()), "test.authorities/1")
    assert result.ok, result.error
    return result.value


def test_only_authorities_are_constructor_fields():
    assert [f.name for f in fields(LoadedMethod)] == ["source", "source_bundle", "parsed_source", "verification"]
    assert [f.name for f in fields(CompiledMethod)] == ["source_bundle", "parsed_source", "program", "diagnostics"]
    assert [f.name for f in fields(MethodSnapshot)] == ["source_bundle", "program", "snapshot_digest"]
    loaded = _load()
    with pytest.raises(TypeError):
        LoadedMethod(loaded.source, loaded.source_bundle, loaded.parsed_source, manifest={"method_id": "contradiction"})
    compiled = _compile(loaded)
    with pytest.raises(TypeError):
        CompiledMethod(loaded.source_bundle, loaded.parsed_source, compiled.program, nodes=())
    with pytest.raises(TypeError):
        replace(compiled, compiled_plan_digest="f" * 64)


def test_nested_source_views_and_cache_cannot_change_bytes_or_identity():
    loaded = _load()
    original = loaded.manifest_bytes
    loaded.manifest["metadata"]["nested"][0] = "changed"
    loaded.resources["schema"].value["properties"]["field"]["enum"].append("changed")
    loaded.resources["schema"].declaration["sha256"] = "f" * 64
    assert loaded.manifest_bytes == original
    assert loaded.manifest["metadata"]["nested"] == ["initial"]
    assert loaded.resources["schema"].value["properties"]["field"]["enum"] == ["initial"]
    assert loaded.resources["schema"].declaration["sha256"] == loaded.resources["schema"].captured.digest
    with pytest.raises(TypeError):
        loaded.parsed_source.manifest_content.value_tree["metadata"]["nested"][0] = "changed"
    with pytest.raises(TypeError):
        ResourceBytes("x", "application/json", bytearray(b"{}"))


def test_optional_verification_has_one_captured_content_and_defensive_view():
    captured = ResourceBytes("bundle-lock.json", "application/json", b'{"nested":{"list":["initial"]}}')
    evidence = VerificationInputs(ParsedContent(captured, {"nested": {"list": ["initial"]}}))
    evidence.lock["nested"]["list"].append("changed")
    assert evidence.lock == {"nested": {"list": ["initial"]}}
    assert evidence.compiled_golden is None
    with pytest.raises(TypeError):
        VerificationInputs(captured, bundle_lock_bytes=b"different")
    loaded = _load()
    assert loaded.verification is None
    assert program_documents(_compile(loaded).program)


def test_program_input_nested_mutation_and_derived_views_are_consistent():
    compiled = _compile(_load())
    original = program_to_canonical(compiled.program)
    digest = program_plan_digest(compiled.program)
    mutable = program_to_canonical(compiled.program)
    encoding = stored_program_from_canonical(mutable)
    mutable["workflow"]["steps"][0]["outcome"] = "changed"
    mutable["documents"][0]["value_schema"]["properties"]["field"]["enum"].append("changed")
    assert program_to_canonical(encoding) == original
    assert program_plan_digest(encoding) == digest
    program_to_canonical(compiled.program)["workflow"]["entry"] = "changed"
    assert program_entry(compiled.program) == "done"
    assert program_nodes(compiled.program)[0].stop_outcome == program_to_canonical(compiled.program)["workflow"]["steps"][0]["outcome"]
    assert program_documents(compiled.program)[0].validation_target == program_to_canonical(compiled.program)["documents"][0]["validation_target"]
    with pytest.raises(FrozenInstanceError):
        program_encoding(compiled.program).workflow = freeze_value({})
    with pytest.raises(TypeError):
        FrozenObject((("mutable", {}),))


def test_lossless_encoding_preserves_absence_and_explicit_defaults():
    original = program_to_canonical(_compile(_load()).program)
    absent = stored_program_from_canonical(original)
    explicit = json.loads(json.dumps(original))
    explicit["workflow"]["context_slots"] = []
    explicit["workflow"]["semantics"] = "preserved authored content"
    different = stored_program_from_canonical(explicit)
    assert program_to_canonical(absent) == original
    assert program_to_canonical(different) == explicit
    assert program_plan_digest(different) != program_plan_digest(absent)
    assert "context_slots" not in program_to_canonical(absent)["workflow"]


def test_versioned_program_rejects_lossy_outer_fields_and_mutable_bindings():
    from ordessa_engineering.methods.definitions.models import CapabilityBinding, ProgramBindings
    value = program_to_canonical(_compile(_load()).program)
    with pytest.raises(ValueError, match="fields"):
        stored_program_from_canonical({**value, 'unexpected': 'must not be discarded'})
    with pytest.raises(ValueError, match="version"):
        stored_program_from_canonical({**value, 'schema_version': True})
    with pytest.raises(TypeError, match="strings"):
        CapabilityBinding("id", "kind", "1", {})
    with pytest.raises(ValueError, match="kind"):
        CapabilityBinding("id", "alien", "1", "a" * 64)
    with pytest.raises(ValueError, match="digest"):
        CapabilityBinding("id", "check", "1", "bad")
    with pytest.raises(TypeError, match="bindings"):
        ProgramBindings((("malformed",),), ())


def test_modern_program_constructor_has_only_explicit_semantic_authorities():
    from ordessa_engineering.methods.definitions.models import WorkflowSpec, StopNode, OperationNode
    program = _compile(_load()).program
    assert [f.name for f in fields(CompiledProgram)] == [
        "compiler_version", "workflow", "document_definitions", "schema_definitions",
        "standard_definitions", "decision_definitions", "skill_definitions", "capability_bindings"]
    assert isinstance(program.workflow, WorkflowSpec)
    assert isinstance(program.workflow.steps[0], StopNode)
    assert "encoding" not in {f.name for f in fields(program)}
    assert "bindings" not in {f.name for f in fields(program)}
    with pytest.raises(TypeError):
        replace(program, encoding=program_encoding(program))
    with pytest.raises(TypeError):
        replace(program.workflow, steps=[program.workflow.steps[0]])
    with pytest.raises(ValueError, match="literal"):
        StopNode(id="s", kind="operation", outcome="done")
    with pytest.raises(TypeError):
        OperationNode(id="s", kind="operation", operation="op", outcomes={"ok": {"stop": "done"}})
    with pytest.raises(FrozenInstanceError):
        program.workflow.steps[0].outcome = "changed"
    with pytest.raises(FrozenInstanceError):
        program.document_definitions[0].value_schema.entries = ()
    before = program_to_canonical(program)
    before["documents"][0]["value_schema"]["properties"]["field"]["enum"].append("changed")
    assert program_to_canonical(program)["documents"][0]["value_schema"]["properties"]["field"]["enum"] == ["initial"]


def test_typed_semantics_roundtrip_known_optional_workflow_fields_and_omission():
    from ordessa_engineering.methods.definitions.models import WorkflowSpec
    compiled = _compile(_load())
    wire = program_to_canonical(compiled.program)
    explicit = json.loads(json.dumps(wire))
    explicit["workflow"].update({"workflow_id": "wf", "semantics": "v1", "context_slots": [],
        "resume_contract": "resume", "cancellation": "cancel", "revision_restart": "restart",
        "automatic_side_effect_retry": "forbidden_when_outcome_unknown"})
    typed = compiled_program_from_canonical(explicit, compiled.program.bindings)
    assert program_to_canonical(typed) == explicit
    assert program_plan_digest(typed) == program_plan_digest(stored_program_from_canonical(explicit))
    assert typed.workflow.context_slots == ()
    assert compiled.program.workflow.context_slots is None
    assert "context_slots" not in program_to_canonical(compiled.program)["workflow"]
    with pytest.raises(ValueError, match="null"):
        semantic_from_wire(WorkflowSpec, {**wire['workflow'], 'context_slots': None})
    with pytest.raises(ValueError, match="unknown"):
        semantic_from_wire(WorkflowSpec, {**wire['workflow'], 'annotation': 'not a legal extension'})


def test_typed_standard_preserves_purpose_defaults_and_validates_internal_fields():
    from ordessa_engineering.methods.definitions.models import StandardDefinition, ResourceRef
    ref = ResourceRef("standard", "a" * 64, "standard")
    criterion = {"criterion_id": "c", "statement": "statement", "checks": [
        {"capability_id": "check", "interface_version": "1", "bindings": {"open": {"resource_id": "r"}}}],
        "policy": {"satisfied": "pass", "violated": "block", "insufficient": "insufficient", "unknown": "manual"}}
    raw = {"schema_version": 1, "standard_id": "s", "revision": "1", "purpose": "captured purpose",
        "criteria": [criterion], "reduction": {"required_criteria": "all_applicable", "empty_applicable_set": "error", "priority": ["block", "manual", "pass"]}}
    typed = semantic_from_wire(StandardDefinition, raw, resource_ref=ref)
    assert semantic_to_wire(typed) == raw
    assert typed.purpose == "captured purpose"
    assert typed.resource_ref == ref
    assert typed.criteria[0].required is None
    explicit = json.loads(json.dumps(raw))
    explicit["criteria"][0].update({"required": True, "blocking": True, "required_inputs": [], "applies_to": []})
    different = semantic_from_wire(StandardDefinition, explicit, resource_ref=ref)
    assert semantic_to_wire(different) == explicit
    assert different.criteria[0].required is True
    assert semantic_to_wire(different) != semantic_to_wire(typed)
    with pytest.raises(TypeError):
        replace(typed.criteria[0], required="true")
    with pytest.raises(ValueError, match="literal"):
        replace(typed.criteria[0].policy, satisfied="allow")
    with pytest.raises(ValueError, match="unknown"):
        semantic_from_wire(StandardDefinition, {**raw, 'semantic_extension': 'not legal'}, resource_ref=ref)
    with pytest.raises(TypeError):
        replace(typed.criteria[0].checks[0], bindings={"mutable": []})


@pytest.mark.parametrize("mutate", [
    lambda p: p["workflow"]["steps"][0].update(outcome=[]),
    lambda p: p["workflow"].update(schema_version=True),
    lambda p: p["documents"][0].update(validation_target="other"),
    lambda p: p["documents"][0].update(unexpected="silently dropped"),
])
def test_typed_program_rejects_invalid_internal_wire_fields_at_construction(mutate):
    compiled = _compile(_load())
    wire = program_to_canonical(compiled.program)
    mutate(wire)
    with pytest.raises((TypeError, ValueError)):
        compiled_program_from_canonical(wire, compiled.program.bindings)


def test_typed_semantic_fields_match_the_versioned_structure_contracts():
    from ordessa_engineering.methods.definitions import schemas
    from ordessa_engineering.methods.definitions.models import compiled as model
    pairs = [
        (model.WorkflowSpec, schemas.WORKFLOW_SCHEMA_V1),
        (model.StandardDefinition, schemas.STANDARD_SCHEMA_V1),
        (model.CriterionDefinition, schemas.CRITERION_SCHEMA_V1),
        (model.DecisionDefinition, schemas.QUESTION_SET_SCHEMA_V1),
        (model.QuestionDefinition, schemas.QUESTION_SET_SCHEMA_V1["properties"]["questions"]["items"]),
        (model.DecisionPolicySpec, schemas.DECISION_POLICY_SCHEMA_V1),
        (model.OperationNode, schemas.WORKFLOW_SCHEMA_V1["properties"]["steps"]["items"]["oneOf"][0]),
        (model.WaitNode, schemas.WORKFLOW_SCHEMA_V1["properties"]["steps"]["items"]["oneOf"][1]),
        (model.StopNode, schemas.WORKFLOW_SCHEMA_V1["properties"]["steps"]["items"]["oneOf"][2]),
        (model.CheckDefinition, schemas.CRITERION_SCHEMA_V1["properties"]["checks"]["items"]),
        (model.ChoiceVocabulary, schemas.CRITERION_SCHEMA_V1["properties"]["answer_vocabulary"]["oneOf"][0]),
        (model.ScoreVocabulary, schemas.CRITERION_SCHEMA_V1["properties"]["answer_vocabulary"]["oneOf"][1]),
        (model.NoulVocabulary, schemas.CRITERION_SCHEMA_V1["properties"]["answer_vocabulary"]["oneOf"][2]),
    ]
    for typ, contract in pairs:
        assert {f.name for f in fields(typ) if f.metadata.get("wire", True)} == set(contract["properties"]), typ


def test_historical_program_does_not_masquerade_as_modern_semantic_authority():
    from ordessa_engineering.methods.definitions.models import HistoricalBoundProgram, ProgramBindings
    old = {"schema_version": 1, "compiler_version": "old/1", "workflow": {}, "documents": [],
        "standards": [], "decision_templates": [], "skill_resources": [], "capability_bindings": []}
    bindings = ProgramBindings((), ())
    historical = HistoricalBoundProgram(stored_program_from_canonical(old), bindings)
    assert not isinstance(historical, CompiledProgram)
    assert program_to_canonical(historical) == old
    with pytest.raises(ValueError, match="schema2"):
        compiled_program_from_canonical(old, bindings)
    with pytest.raises(ValueError, match="historical"):
        _ = program_documents(historical)
    with pytest.raises(ValueError, match="historical"):
        _ = program_skills(historical)


def test_models_getters_never_parse_or_import_parser(monkeypatch):
    from ordessa_engineering.methods.loading import parsing
    loaded = _load()
    def forbidden(*args, **kwargs): raise AssertionError("model getter executed parser")
    monkeypatch.setattr(parsing, "decode_json", forbidden)
    monkeypatch.setattr(parsing.yaml, "load", forbidden)
    assert loaded.identity.method_id == "test.authorities"
    assert loaded.manifest["metadata"]["nested"] == ["initial"]
    assert loaded.resources["schema"].value["type"] == "object"
    assert loaded.resources["schema"].declaration["kind"] == "document_schema"
    assert not hasattr(loaded.source_bundle.manifest_capture, "value")
    assert not hasattr(loaded.source_bundle.manifest_capture, "_parsed")


def test_loading_builds_each_parsed_capture_once(monkeypatch):
    from ordessa_engineering.methods.loading import loader
    original = loader.parse_document
    paths = []
    def counted(raw, media_type, path, **kwargs):
        paths.append(path)
        return original(raw, media_type, path, **kwargs)
    monkeypatch.setattr(loader, "parse_document", counted)
    loaded = _load()
    assert sorted(paths) == ["method.yaml", "schema.json", "workflow.json"]
    for _ in range(3): _ = loaded.manifest, loaded.identity, loaded.resources["schema"].value
    assert len(paths) == 3


@pytest.mark.parametrize("target", ["manifest", "resource"])
def test_untrusted_parsed_cache_is_rebuilt_and_rejected_before_compile(target):
    from ordessa_engineering.methods.definitions.models import ParsedResource
    loaded = _load()
    if target == "manifest":
        false = loaded.manifest
        false["method_id"] = "false.cache"
        cache = replace(loaded.parsed_source, manifest_content=ParsedContent(loaded.source_bundle.manifest_capture, false))
    else:
        old = loaded.parsed_source.resources[0]
        false = old.content.value
        false["type"] = "string"
        cache = replace(loaded.parsed_source, resources=(ParsedResource(old.resource_id,
            ParsedContent(old.content.captured, false)), *loaded.parsed_source.resources[1:]))
    forged = replace(loaded, parsed_source=cache)
    assert forged.manifest_bytes == loaded.manifest_bytes
    result = compile_method(forged, CompilationCapabilities(()), "test.authorities/1")
    assert not result.ok
    assert result.error.code == "LOADED_PROJECTION_INVALID"


def test_freeze_rejects_forged_cache_before_external_ports():
    from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
    loaded = _load()
    compiled = _compile(loaded)
    false = loaded.manifest
    false["method_id"] = "false.cache"
    cache = replace(compiled.parsed_source, manifest_content=ParsedContent(compiled.source_bundle.manifest_capture, false))
    forged = replace(compiled, parsed_source=cache)
    class ForbiddenCatalog:
        def read_current(self): raise AssertionError("cache attack reached external authority")
    result = freeze_method(forged, None, None, capability_catalog=ForbiddenCatalog())
    assert not result.ok
    assert result.error.code == "COMPILED_SOURCE_PROJECTION_MISMATCH"


def test_verification_cache_tampering_is_rejected_against_its_bytes():
    loaded = _load()
    capture = ResourceBytes("bundle-lock.json", "application/json", b'{"x":1}')
    forged = replace(loaded, verification=VerificationInputs(ParsedContent(capture, {"x": 2})))
    result = compile_method(forged, CompilationCapabilities(()), "test.authorities/1")
    assert not result.ok
    assert result.error.code == "LOADED_LOCK_PROJECTION_MUTATED"


def test_immutable_parsed_data_is_not_a_trust_token_and_has_no_parser_field():
    from ordessa_engineering.methods.definitions.models import ParsedSourceBundle
    loaded = _load()
    mutable = {"nested": [{"x": 1}]}
    capture = ResourceBytes("arbitrary", "application/json", b"invalid JSON deliberately unparsed")
    view = ParsedContent(capture, mutable)
    mutable["nested"][0]["x"] = 2
    assert view.value == {"nested": [{"x": 1}]}
    with pytest.raises(TypeError): view.value_tree["nested"][0]["x"] = 3
    with pytest.raises(TypeError): ParsedContent(capture, {1: "nonstring key"})
    with pytest.raises(TypeError): ParsedContent(capture, {"float": 0.1})
    with pytest.raises(ValueError, match="binding"):
        replace(loaded.parsed_source, manifest_content=view)
    assert [f.name for f in fields(ParsedContent)] == ["captured", "value_tree"]
    assert [f.name for f in fields(ParsedSourceBundle)] == ["source_bundle", "manifest_content", "resources"]
    assert "value_tree" not in {f.name for f in fields(ResourceBytes)}
