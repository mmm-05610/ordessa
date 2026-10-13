"""Real external-method inputs compile to neutral types and bounded selectors."""
from __future__ import annotations
from ordessa_engineering.methods.compilation.encoding import (compiled_program_from_canonical, program_criteria, program_decisions, program_documents, program_nodes, program_plan_digest, program_skills, program_to_canonical)

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

from ordessa_engineering.methods.definitions.models import StoredProgram, CompiledProgram, ProgramBindings, StoredSourceBundle, StoredSnapshot, CapturedResource, SourceBundle, ResourceBytes

import pytest
import yaml

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.compilation.decisions import expand_questions, select_targets
from ordessa_engineering.methods.definitions.models.compiled import (
    CompiledNode, CriteriaSpec, DecisionSpec, DocumentSpec, SkillSpec, TargetSelector,
)
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.methods.definitions.models import (
    CapabilityDescriptor, CompilationCapabilities, MethodSource,
)
from ordessa_engineering.methods.loading.loader import load_method


REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def real_bundle(tmp_path):
    root = tmp_path / "method"
    shutil.copytree(REPO_ROOT / "methods/incremental-engineering", root)
    # A schema2 compilation is a new output, not the historical schema1 golden.
    (root / "bundle-lock.json").unlink()
    raw = json.loads((root / "contracts/capability-catalog.json").read_text())
    assert raw["fixture_only"] is True
    catalog = CompilationCapabilities(tuple(CapabilityDescriptor(
        row["capability_id"], row["kind"], row["interface_version"],
        row["contract_digest"], row["contract"],
    ) for row in raw["capabilities"]), "typed-test-fixture", "fixture")
    return root, catalog


def compile_bundle(root, catalog):
    loaded = load_method(MethodSource(root), FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, catalog, "test.typed/2")
    assert compiled.ok, compiled.error
    return loaded.value, compiled.value


def test_real_external_method_generates_all_typed_public_descriptions(real_bundle):
    root, catalog = real_bundle
    loaded, compiled = compile_bundle(root, catalog)
    for values, expected in (
        (program_nodes(compiled.program), CompiledNode), (program_criteria(compiled.program), CriteriaSpec),
        (program_decisions(compiled.program), DecisionSpec), (program_documents(compiled.program), DocumentSpec),
        (program_skills(compiled.program), SkillSpec),
    ):
        assert values
        assert all(isinstance(item, expected) for item in values)
        assert expected.__module__ == "ordessa_engineering.methods.definitions.models.compiled"
    program = program_to_canonical(compiled.program)
    assert program["schema_version"] == 2
    documents = {item["document_type"]: item for item in program["documents"]}
    for typed in program_documents(compiled.program):
        declaration = next(item for item in loaded.manifest["documents"]
                           if item["document_type"] == typed.document_type)
        resource = loaded.resources[declaration["template"]["resource"]]
        assert typed.template_ref.resource_id == resource.declaration["id"]
        assert typed.template_ref.sha256 == resource.captured.digest
        assert typed.validation_target == "method_content"
        assert documents[typed.document_type]["template_resource"]["sha256"] == resource.captured.digest
        assert documents[typed.document_type]["validation_target"] == "method_content"
    bindings = loaded.manifest["skills"]
    assert {item.role: item.resource_ref.resource_id for item in program_skills(compiled.program)} == {
        role: ref["resource"] for role, ref in bindings.items()
    }


def test_declaring_an_unbound_skill_does_not_enable_it(real_bundle):
    root, catalog = real_bundle
    manifest = yaml.safe_load((root / "method.yaml").read_text())
    existing = next(item for item in manifest["resources"] if item["kind"] == "skill")
    raw = (root / existing["path"]).read_bytes()
    extra_path = "skills/unbound-test.md"
    (root / extra_path).write_bytes(raw)
    manifest["resources"].append({"id": "skill.unbound_test", "kind": "skill",
        "path": extra_path, "media_type": existing["media_type"],
        "sha256": hashlib.sha256(raw).hexdigest()})
    (root / "method.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    loaded, compiled = compile_bundle(root, catalog)
    assert "skill.unbound_test" in loaded.resources
    assert len(program_skills(compiled.program)) == len(manifest["skills"])
    assert all((item.resource_ref.resource_id != 'skill.unbound_test' for item in program_skills(compiled.program)))
    assert all((item['resource_ref']['resource_id'] != 'skill.unbound_test' for item in program_to_canonical(compiled.program)['skill_resources']))


def test_selector_selects_only_matching_neutral_document_types():
    assert select_targets(TargetSelector(("did",)), (("a", "did"), ("b", "submission"))) == ("a",)
    assert select_targets(TargetSelector(), (("a", "did"), ("b", "submission"))) == ("a", "b")


@pytest.mark.parametrize("candidates", [
    tuple((str(index), "did") for index in range(513)),
    (("same", "did"), ("same", "submission")),
])
def test_selector_rejects_oversize_and_duplicate_target_identities(candidates):
    with pytest.raises(MethodFailure) as caught:
        select_targets(TargetSelector(("did",)), candidates)
    assert caught.value.error.code == "SELECTOR_TARGET_SET_INVALID"


def test_question_expansion_has_explicit_bounded_instances(real_bundle):
    _, compiled = compile_bundle(*real_bundle)
    each = next((item for item in program_decisions(compiled.program) if item.iteration == 'each_evidence_required_claim'))
    once = next((item for item in program_decisions(compiled.program) if item.iteration == 'once'))
    assert expand_questions(each, ("claim.a", "claim.b")) == tuple(
        (instance, question.question_id) for instance in ("claim.a", "claim.b") for question in each.questions)
    assert expand_questions(once, ("once",)) == tuple(("once", item.question_id) for item in once.questions)
    with pytest.raises(MethodFailure) as caught:
        expand_questions(each, tuple(str(index) for index in range(513)))
    assert caught.value.error.code == "QUESTION_EXPANSION_LIMIT"
    with pytest.raises(MethodFailure) as caught:
        expand_questions(each, ("duplicate", "duplicate"))
    assert caught.value.error.code == "QUESTION_INSTANCE_INVALID"
    with pytest.raises(MethodFailure) as caught:
        expand_questions(replace(each, iteration="unknown_iteration"), ("claim",))
    assert caught.value.error.code == "QUESTION_ITERATION_UNSUPPORTED"


@pytest.mark.parametrize("instances", [(), ("implicit",), ("once", "once")])
def test_once_requires_exact_explicit_single_instance(real_bundle, instances):
    _, compiled = compile_bundle(*real_bundle)
    once = next((item for item in program_decisions(compiled.program) if item.iteration == 'once'))
    with pytest.raises(MethodFailure) as caught:
        expand_questions(once, instances)
    assert caught.value.error.code == "QUESTION_INSTANCE_INVALID"


def captured_snapshot_for_content_test(loaded, compiled):
    """Build consumer input only: no host authority or publication is simulated."""
    from ordessa_engineering.methods.definitions.models.identity import method_digest
    from ordessa_engineering.methods.definitions.models import BlobRef, MethodSnapshot, ResourceSnapshot

    blobs = {}
    resources = []
    for resource_id, item in sorted(loaded.resources.items()):
        captured = item.captured
        ref = BlobRef(captured.digest, len(captured.data), captured.media_type, "test:" + captured.digest)
        blobs[ref.storage_object_id] = captured.data
        resources.append(ResourceSnapshot(resource_id, captured.logical_path, ref))
    manifest_ref = BlobRef(loaded.manifest_digest, len(loaded.manifest_bytes), "application/yaml",
                           "test:" + loaded.manifest_digest)
    blobs[manifest_ref.storage_object_id] = loaded.manifest_bytes
    program = program_to_canonical(compiled.program)
    digest = method_digest('method-snapshot', {'schema_version': loaded.identity.schema_version, 'method_id': loaded.identity.method_id, 'release_version': loaded.identity.release_version, 'manifest_sha256': loaded.manifest_digest, 'resource_digests': [{'id': item.resource_id, 'sha256': item.digest} for item in resources], 'required_capabilities': program['capability_bindings'], 'compiler_version': compiled.compiler_version, 'compiled_plan_digest': {'algorithm': 'sha256', 'hex': program_plan_digest(compiled.program)}})
    snapshot = MethodSnapshot(StoredSourceBundle(loaded.identity, manifest_ref, tuple(resources)), compiled.program, digest)

    class CapturedBlobReader:
        def read_blob(self, ref):
            return blobs[ref.storage_object_id]

    return snapshot, CapturedBlobReader(), blobs


def test_template_and_role_skill_consumers_use_exact_captured_bytes(real_bundle):
    from ordessa_engineering.application.orchestration.method_content import document_spec, template_bytes, skill_bytes

    root, catalog = real_bundle
    loaded, compiled = compile_bundle(root, catalog)
    snapshot, reader, _ = captured_snapshot_for_content_test(loaded, compiled)
    # Mutating the active template cannot alter a consumer's saved blob reference.
    document = program_documents(compiled.program)[0]
    template = loaded.resources[document.template_ref.resource_id]
    (root / template.captured.logical_path).write_bytes(b"changed active template")
    retrieved = document_spec(snapshot, document.document_type)
    assert isinstance(retrieved, DocumentSpec)
    assert retrieved.template_ref == document.template_ref
    actual = template_bytes(snapshot, document.document_type, reader)
    assert actual == template.captured.data
    assert hashlib.sha256(actual).hexdigest() == retrieved.template_ref.sha256
    for skill in program_skills(compiled.program):
        actual_skill = skill_bytes(snapshot, skill.role, reader)
        assert actual_skill == loaded.resources[skill.resource_ref.resource_id].captured.data
        assert hashlib.sha256(actual_skill).hexdigest() == skill.resource_ref.sha256


def test_template_consumer_rejects_corrupt_saved_content(real_bundle):
    from ordessa_engineering.application.orchestration.method_content import template_bytes

    loaded, compiled = compile_bundle(*real_bundle)
    snapshot, reader, blobs = captured_snapshot_for_content_test(loaded, compiled)
    document = program_documents(compiled.program)[0]
    resource = next(item for item in snapshot.resources if item.resource_id == document.template_ref.resource_id)
    blobs[resource.blob_ref.storage_object_id] = b"corrupt stored template"
    with pytest.raises(MethodFailure):
        template_bytes(snapshot, document.document_type, reader)


@pytest.mark.parametrize("limit", [513, 1024])
def test_selector_and_expansion_cannot_raise_platform_maximum(real_bundle, limit):
    _, compiled = compile_bundle(*real_bundle)
    spec = next((item for item in program_decisions(compiled.program) if item.iteration == 'each_evidence_required_claim'))
    with pytest.raises(MethodFailure) as caught:
        select_targets(TargetSelector(), (("valid", "did"),), limit=limit)
    assert caught.value.error.code == "SELECTOR_LIMIT_INVALID"
    with pytest.raises(MethodFailure) as caught:
        expand_questions(spec, ("valid",), limit=limit)
    assert caught.value.error.code == "QUESTION_EXPANSION_LIMIT_INVALID"


@pytest.mark.parametrize("candidates", [
    (("", "did"),), ((None, "did"),), ((123, "did"),),
    (("target", ""),), (("target", None),), (("target", 123),),
])
def test_selector_rejects_invalid_candidate_identity_or_type(candidates):
    with pytest.raises(MethodFailure) as caught:
        select_targets(TargetSelector(), candidates)
    assert caught.value.error.code == "SELECTOR_TARGET_SET_INVALID"


def test_document_content_checks_only_wrapper_value_against_method_schema(real_bundle):
    from ordessa_engineering.application.orchestration.method_content import validate_document_content

    root, catalog = real_bundle
    loaded, compiled = compile_bundle(root, catalog)
    snapshot, _, _ = captured_snapshot_for_content_test(loaded, compiled)
    fixture = json.loads((root / "examples/minimal-change/method-content-envelopes.json").read_text())
    value = next(item["value"] for item in fixture["method_contents"]
                 if item["value"]["document_type"] == "did")
    wrapper = {"value": value,
               "schema_ref": {"resource_id": "document.did.schema"},
               "rendered_body_ref": "test-ref",
               "wrapper_only_field": "not a document field"}
    # DID forbids additional document properties; envelope fields must not be
    # included in the document schema's validation target.
    good = validate_document_content(snapshot, "did", wrapper)
    assert good.ok, good.error
    bad = validate_document_content(snapshot, "did", {**wrapper, "value": {"unexpected": "invalid"}})
    assert not bad.ok
    assert bad.error.code == "METHOD_CONTENT_INVALID"
    missing = validate_document_content(snapshot, "did", {"schema_ref": {}})
    assert not missing.ok
    assert missing.error.code == "METHOD_CONTENT_INVALID"


def test_template_consumer_converts_reader_failure_to_path_safe_typed_error(real_bundle):
    from ordessa_engineering.application.orchestration.method_content import template_bytes

    loaded, compiled = compile_bundle(*real_bundle)
    snapshot, _, _ = captured_snapshot_for_content_test(loaded, compiled)

    class FailedReader:
        def read_blob(self, ref):
            raise OSError("secret absolute /host/private/path")

    with pytest.raises(MethodFailure) as caught:
        template_bytes(snapshot, program_documents(compiled.program)[0].document_type, FailedReader())
    assert "secret" not in caught.value.error.message
    assert "/host/private/path" not in caught.value.error.message


def test_template_consumer_rejects_wrong_resource_kind_binding(real_bundle):
    from copy import deepcopy
    from ordessa_engineering.methods.definitions.models.identity import method_digest
    from ordessa_engineering.application.orchestration.method_content import template_bytes

    loaded, compiled = compile_bundle(*real_bundle)
    snapshot, reader, _ = captured_snapshot_for_content_test(loaded, compiled)
    program = deepcopy(program_to_canonical(snapshot.program))
    document = program["documents"][0]
    document["template_resource"]["kind"] = "skill"
    digest = method_digest("compiled-method-program", program)
    changed = replace(snapshot, program=compiled_program_from_canonical(program, snapshot.program.bindings))
    with pytest.raises(MethodFailure) as caught:
        template_bytes(changed, document["document_type"], reader)
    assert caught.value.error.code == "METHOD_RESOURCE_MISMATCH"


def bundle_with_unbound_schema_dependency(root):
    """DID depends on a captured schema not itself declared as a document."""
    manifest = yaml.safe_load((root / "method.yaml").read_text())
    did_decl = next(item for item in manifest["resources"] if item["id"] == "document.did.schema")
    did_path = root / did_decl["path"]
    schema = json.loads(did_path.read_text())
    # The bundled DID uses a URN ID. Relative file references must resolve
    # against the supplied logical bundle location, not a nonhierarchical URN.
    schema.pop("$id", None)
    schema["properties"]["test_shared"] = {"$ref": "../test-shared.json#/$defs/shared"}
    raw = json.dumps(schema, ensure_ascii=False).encode()
    did_path.write_bytes(raw)
    did_decl["sha256"] = hashlib.sha256(raw).hexdigest()
    dependency = {"$defs": {"shared": {"type": "string", "enum": ["accepted"]}}}
    dependency_raw = json.dumps(dependency).encode()
    dependency_path = "documents/test-shared.json"
    (root / dependency_path).write_bytes(dependency_raw)
    manifest["resources"].append({"id": "document.test_shared.schema", "kind": "document_schema",
        "path": dependency_path, "media_type": "application/schema+json",
        "sha256": hashlib.sha256(dependency_raw).hexdigest()})
    (root / "method.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    fixture = json.loads((root / "examples/minimal-change/method-content-envelopes.json").read_text())
    return next(item["value"] for item in fixture["method_contents"]
                if item["value"]["document_type"] == "did")


def test_document_validation_uses_full_captured_schema_dependency_closure(real_bundle):
    from ordessa_engineering.application.orchestration.method_content import validate_document_content

    root, catalog = real_bundle
    value = bundle_with_unbound_schema_dependency(root)
    loaded, compiled = compile_bundle(root, catalog)
    program = program_to_canonical(compiled.program)
    assert "document.test_shared.schema" not in {
        item["schema_resource"]["resource_id"] for item in program["documents"]
    }
    assert "document.test_shared.schema" in {
        item["schema_resource"]["resource_id"] for item in program["schema_resources"]
    }
    snapshot, _, _ = captured_snapshot_for_content_test(loaded, compiled)
    good = validate_document_content(snapshot, "did", {"value": {**value, "test_shared": "accepted"}})
    assert good.ok, good.error
    bad = validate_document_content(snapshot, "did", {"value": {**value, "test_shared": "rejected"}})
    assert not bad.ok
    assert bad.error.code == "METHOD_CONTENT_INVALID"


def test_missing_schema_anchor_returns_typed_failure_without_exception_leak(real_bundle):
    from copy import deepcopy
    from ordessa_engineering.methods.definitions.models.identity import method_digest
    from ordessa_engineering.application.orchestration.method_content import validate_document_content

    root, catalog = real_bundle
    value = bundle_with_unbound_schema_dependency(root)
    loaded, compiled = compile_bundle(root, catalog)
    snapshot, _, _ = captured_snapshot_for_content_test(loaded, compiled)
    program = deepcopy(program_to_canonical(snapshot.program))
    # Consumer negative: inject a missing anchor into a canonical test input.
    # It is not presented as a successfully published production method.
    for item in [*program["documents"], *program["schema_resources"]]:
        if item["schema_resource"]["resource_id"] == "document.did.schema":
            item["value_schema"]["properties"]["test_shared"] = {"$ref": "../test-shared.json#missing-anchor"}
    digest = method_digest("compiled-method-program", program)
    changed = replace(snapshot, program=compiled_program_from_canonical(program, snapshot.program.bindings))
    result = validate_document_content(changed, "did", {"value": {**value, "test_shared": "accepted"}})
    assert not result.ok
    assert result.error.code == "METHOD_SCHEMA_INVALID"
    assert "missing-anchor" not in result.error.message


@pytest.mark.parametrize("kind", ["template", "skill"])
@pytest.mark.parametrize("field", ["digest", "byte_length", "media_type", "storage_object_id"])
def test_content_reader_cannot_rebind_metadata_in_callback(real_bundle, kind, field):
    from ordessa_engineering.application.orchestration.method_content import template_bytes, skill_bytes

    loaded, compiled = compile_bundle(*real_bundle)
    snapshot, reader, blobs = captured_snapshot_for_content_test(loaded, compiled)
    if kind == "template":
        binding = program_documents(compiled.program)[0]
        invoke = lambda port: template_bytes(snapshot, binding.document_type, port)
    else:
        binding = program_skills(compiled.program)[0]
        invoke = lambda port: skill_bytes(snapshot, binding.role, port)

    class RebindingReader:
        def read_blob(self, ref):
            original = blobs[ref.storage_object_id]
            forged = b"reader-forged-content"
            replacement = {
                "digest": hashlib.sha256(forged).hexdigest(),
                "byte_length": len(forged), "media_type": "application/forged",
                "storage_object_id": "forged-location",
            }[field]
            object.__setattr__(ref, field, replacement)
            # Digest and size attacks return forged content; metadata-only
            # attacks return real bytes and still must not rebind the locator.
            return forged if field in {"digest", "byte_length"} else original

    with pytest.raises(MethodFailure) as refused:
        invoke(RebindingReader())
    assert refused.value.error.code == "METHOD_RESOURCE_BYTES_MISMATCH"
    # The consumer's saved references remain usable after the failed callback.
    assert invoke(reader)
