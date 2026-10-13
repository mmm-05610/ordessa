"""Methods loader/compiler tests using synthetic source roots and a design fixture."""
from __future__ import annotations
from ordessa_engineering.methods.compilation.encoding import (compiled_program_from_canonical, program_documents, program_plan_digest, program_to_canonical, stored_program_from_canonical)

import hashlib
import json
import os
import signal
import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from ordessa_engineering.methods.definitions.models import StoredProgram, CompiledProgram, HistoricalBoundProgram, ProgramBindings, StoredSourceBundle, StoredSnapshot, CapturedResource, SourceBundle, ResourceBytes

import pytest
import yaml

from ordessa_engineering.methods.definitions.models.identity import method_digest
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models import (
    BlobRef, CapabilityDescriptor, CompilationCapabilities, MethodRef, MethodIdentity, MethodSnapshot, MethodSource,
)
from ordessa_engineering.methods.definitions.models.compiled import StoredProgram
from ordessa_engineering.methods.definitions.errors import MethodResult, MethodFailure
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.methods import validate_method
from ordessa_engineering.methods.validation.references import validate_schema_refs


REPO_ROOT = Path(__file__).resolve().parents[4]


def _write_bundle(root: Path, *, resource_path: str = "workflow.yaml",
                  workflow: str = "schema_version: 1\nentry: done\nsteps:\n- id: done\n  kind: stop\n  outcome: finished\nstop_outcomes: [finished]\nwait_kinds: []\n",
                  extra_requires: list[dict] | None = None,
                  with_document: bool = False) -> None:
    content = workflow.encode()
    (root / "workflow.yaml").write_bytes(content)
    resources = [{
        "id": "workflow.main", "kind": "workflow", "path": resource_path,
        "media_type": "application/yaml", "sha256": hashlib.sha256(content).hexdigest(),
    }]
    manifest = {
        "schema_version": 1,
        "method_id": "test.method",
        "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1",
        "entry": {"resource": "workflow.main"},
        "resources": resources,
        "requires": extra_requires or [],
    }
    if with_document:
        schema_bytes = json.dumps({"type": "object", "additionalProperties": False},
                                  separators=(",", ":")).encode()
        (root / "document-schema.json").write_bytes(schema_bytes)
        resources.append({
            "id": "document.test.schema", "kind": "document_schema",
            "path": "document-schema.json", "media_type": "application/schema+json",
            "sha256": hashlib.sha256(schema_bytes).hexdigest(),
        })
        manifest["documents"] = [{
            "document_type": "test-document",
            "schema": {"resource": "document.test.schema"},
        }]
    (root / "method.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


class _MemoryStore:
    """Test port with the required atomic method/release identity boundary."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple[str, bytes, BlobRef]] = {}
        self.snapshots: dict[tuple[str, str], MethodSnapshot] = {}
        self.lock = threading.Lock()
        self.on_put = None

    def put_blob(self, digest: str, media_type: str, raw_bytes: bytes) -> BlobRef:
        if self.on_put is not None:
            callback, self.on_put = self.on_put, None
            callback()
        assert hashlib.sha256(raw_bytes).hexdigest() == digest
        ref = BlobRef(digest, len(raw_bytes), media_type, f"mem:{digest}")
        previous = self.blobs.get(digest)
        if previous is not None:
            assert previous[:2] == (media_type, raw_bytes)
        else:
            self.blobs[digest] = (media_type, raw_bytes, ref)
        return ref

    def publish(self, snapshot: MethodSnapshot) -> MethodRef:
        key = (snapshot.identity.method_id, snapshot.identity.release_version)
        with self.lock:
            previous = self.snapshots.get(key)
            if previous is not None and previous.snapshot_digest != snapshot.snapshot_digest:
                raise ValueError("release_identity_conflict")
            if previous is None:
                self.snapshots[key] = snapshot
        return MethodRef(*key, snapshot.identity.schema_version, snapshot.snapshot_digest)

    def get(self, ref: MethodRef) -> MethodSnapshot:
        result = self.snapshots[(ref.method_id, ref.release_version)]
        if result.snapshot_digest != ref.snapshot_digest:
            raise KeyError("snapshot_digest_mismatch")
        from copy import deepcopy

        return deepcopy(result)


class _MemoryIdentityIndex:
    def __init__(self, store: _MemoryStore) -> None:
        self.store = store

    def get_digest(self, method_id: str, release_version: str) -> str | None:
        item = self.store.snapshots.get((method_id, release_version))
        return item.snapshot_digest if item else None


class TestCatalogReader:
    """Explicit synthetic test port; it is not a production authority adapter."""

    __test__ = False

    def __init__(self, capabilities: CompilationCapabilities) -> None:
        self.capabilities = capabilities

    def read_current(self) -> CompilationCapabilities:
        return self.capabilities


def test_temp_bundle_load_compile_and_freeze_uses_captured_bytes(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    loaded_result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert loaded_result.ok
    loaded = loaded_result.value
    assert loaded is not None

    catalog = CompilationCapabilities(())
    assert validate_method(loaded, catalog).valid
    compiled_result = compile_method(loaded, catalog, "test.compiler/1")
    assert compiled_result.ok
    compiled = compiled_result.value
    assert compiled is not None

    # Changing the active source after compilation cannot affect the frozen data.
    (tmp_path / "workflow.yaml").write_text("invalid: changed\n", encoding="utf-8")
    store = _MemoryStore()
    index = _MemoryIdentityIndex(store)
    unavailable_store = _MemoryStore()
    unavailable = freeze_method(compiled, unavailable_store, _MemoryIdentityIndex(unavailable_store))
    assert not unavailable.ok and unavailable.error is not None
    assert unavailable.error.code == "CAPABILITY_AUTHORITY_UNAVAILABLE"
    assert not unavailable_store.blobs and not unavailable_store.snapshots
    frozen = freeze_method(compiled, store, index,
                           capability_catalog=TestCatalogReader(catalog))
    assert frozen.ok
    assert frozen.value is not None
    assert store.get(frozen.value.ref) == frozen.value.snapshot
    assert store.blobs[loaded.resources["workflow.main"].captured.digest][1] == loaded.resources["workflow.main"].captured.data

    # Re-publishing the identical bytes is idempotent; a second release digest
    # cannot replace the first one through the identity port.
    again = freeze_method(compiled, store, index,
                          capability_catalog=TestCatalogReader(catalog))
    assert again.ok and again.value.ref == frozen.value.ref


def test_compile_rejects_mutated_loaded_projection(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    loaded_result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert loaded_result.ok and loaded_result.value is not None
    loaded = loaded_result.value
    loaded.resources["workflow.main"].value["entry"] = "forged"
    assert loaded.resources["workflow.main"].value["entry"] == "done"
    resource = loaded.source_bundle.resources[0]
    altered = replace(resource, captured=replace(resource.captured, data=resource.captured.data + b"# forged"))
    # Bypass the pure constructor binding guard to exercise the untrusted boundary.
    object.__setattr__(loaded, "source_bundle", replace(loaded.source_bundle, resources=(altered,)))

    result = compile_method(loaded, CompilationCapabilities(()), "test.compiler/1")
    assert not result.ok and result.error is not None
    assert result.error.code == "CAPTURED_RESOURCE_DECLARATION_MISMATCH"

    fresh_result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert fresh_result.ok and fresh_result.value is not None
    fresh_result.value.manifest["method_id"] = "forged.method"
    assert fresh_result.value.identity.method_id != "forged.method"
    raw = fresh_result.value.manifest_bytes.replace(b"method_id:", b"unexpected:")
    object.__setattr__(fresh_result.value, "source_bundle", replace(fresh_result.value.source_bundle,
        manifest_capture=replace(fresh_result.value.source_bundle.manifest_capture, data=raw)))
    manifest_result = compile_method(fresh_result.value, CompilationCapabilities(()), "test.compiler/1")
    assert not manifest_result.ok and manifest_result.error is not None
    assert manifest_result.error.code == "MANIFEST_FIELDS_INVALID"


def test_freeze_detaches_program_projection_and_published_memory_reference(tmp_path: Path) -> None:
    _write_bundle(tmp_path, with_document=True)
    loaded_result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert loaded_result.ok and loaded_result.value is not None
    compiled_result = compile_method(loaded_result.value, CompilationCapabilities(()), "test.compiler/1")
    assert compiled_result.ok and compiled_result.value is not None
    compiled = compiled_result.value
    object.__setattr__(program_documents(compiled.program)[0], 'document_type', 'mutated-projection')

    store = _MemoryStore()
    host_catalog = CompilationCapabilities((), "test-empty-host-snapshot", "host")
    frozen = freeze_method(compiled, store, _MemoryIdentityIndex(store),
                           capability_catalog=TestCatalogReader(host_catalog))
    assert frozen.ok and frozen.value is not None
    assert tuple(program_to_canonical(frozen.value.snapshot.program)['documents'])[0]["document_type"] == "test-document"

    # The first store callback mutates the caller-owned compile result. Freeze
    # must already have built a complete local publication projection.
    callback_store = _MemoryStore()
    callback_store.on_put = lambda: program_to_canonical(compiled.program)['workflow'].__setitem__('entry', 'callback-forgery')
    callback_result = freeze_method(
        compiled, callback_store, _MemoryIdentityIndex(callback_store),
        capability_catalog=TestCatalogReader(host_catalog),
    )
    assert callback_result.ok and callback_result.value is not None
    assert program_to_canonical(compiled.program)["workflow"]["entry"] == "done"
    callback_snapshot = callback_store.get(callback_result.value.ref)
    assert program_to_canonical(callback_snapshot.program)['workflow']["entry"] == "done"
    assert program_to_canonical(callback_snapshot.program)["workflow"]["entry"] == "done"

    # Neither the compile result nor the returned snapshot aliases the memory
    # store's published value.
    object.__setattr__(program_documents(compiled.program)[0], 'document_type', 'mutated-after-publish')
    program_to_canonical(compiled.program)["workflow"]["entry"] = "mutated-program-after-publish"
    program_to_canonical(frozen.value.snapshot.program)['workflow']["entry"] = "mutated-return-value"
    persisted = store.get(frozen.value.ref)
    assert tuple(program_to_canonical(persisted.program)['documents'])[0]["document_type"] == "test-document"
    assert program_to_canonical(persisted.program)['workflow']["entry"] == "done"
    assert program_to_canonical(persisted.program)["workflow"]["entry"] == "done"

    # Recalculating an attacker-mutated program digest is insufficient: freeze
    # rebuilds the compiler projection from the captured manifest/resources.
    forged_program = deepcopy(program_to_canonical(compiled.program))
    forged_program["workflow"]["entry"] = "forged-entry"
    forged_digest = method_digest("compiled-method-program", forged_program)
    forged_plan = compiled_program_from_canonical(forged_program, compiled.program.bindings)
    forged_compiled = replace(
        compiled, program=forged_plan,
    )
    forged_store = _MemoryStore()
    rejected = freeze_method(
        forged_compiled, forged_store, _MemoryIdentityIndex(forged_store),
        capability_catalog=TestCatalogReader(host_catalog),
    )
    assert not rejected.ok and rejected.error is not None
    assert rejected.error.code == "COMPILED_PROGRAM_SOURCE_MISMATCH"
    assert not forged_store.snapshots


def test_loader_rejects_path_escape_symlink_and_hardlink(tmp_path: Path) -> None:
    _write_bundle(tmp_path, resource_path="../outside.yaml")
    escaped = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert not escaped.ok
    assert escaped.error is not None and escaped.error.code in {"RESOURCE_ESCAPE", "RESOURCE_PATH_INVALID"}

    _write_bundle(tmp_path)
    source = tmp_path / "workflow.yaml"
    content = source.read_bytes()
    source.unlink()
    outside = tmp_path.parent / f"{tmp_path.name}-outside.yaml"
    outside.write_bytes(content)
    source.symlink_to(outside)
    symlink_result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert not symlink_result.ok

    source.unlink()
    source.hardlink_to(outside)
    hardlink_result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert not hardlink_result.ok
    assert hardlink_result.error is not None and hardlink_result.error.code == "RESOURCE_NOT_PRIVATE_FILE"


def test_reader_rejects_fifo_without_blocking_and_closes_descriptors(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe.yaml")
    descriptor_count = len(os.listdir("/proc/self/fd"))

    class _Deadline(Exception):
        pass

    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(_Deadline()))
    signal.setitimer(signal.ITIMER_REAL, 1.0)
    try:
        with pytest.raises(MethodFailure) as failure:
            FileResourceReader().read(MethodSource(tmp_path), "pipe.yaml", 1024)
        assert getattr(failure.value, "error", None) is not None
        assert failure.value.error.code == "RESOURCE_NOT_PRIVATE_FILE"
        assert len(os.listdir("/proc/self/fd")) == descriptor_count
    except _Deadline:
        pytest.fail("FIFO resource open blocked instead of rejecting the special file")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_loader_rejects_changed_resource_bytes(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    (tmp_path / "workflow.yaml").write_text(
        "schema_version: 1\nentry: changed\nsteps: []\nstop_outcomes: []\nwait_kinds: []\n",
        encoding="utf-8",
    )
    result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert not result.ok and result.error is not None
    assert result.error.code == "RESOURCE_DIGEST_MISMATCH"


def test_loader_rejects_unsupported_compiler_contract_and_nonworkflow_entry(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    manifest = yaml.safe_load((tmp_path / "method.yaml").read_text(encoding="utf-8"))
    manifest["compiler_contract"] = "ordessa.methods/v2"
    (tmp_path / "method.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    unsupported = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert not unsupported.ok and unsupported.error is not None
    assert unsupported.error.code == "COMPILER_CONTRACT_UNSUPPORTED"

    _write_bundle(tmp_path, with_document=True)
    manifest = yaml.safe_load((tmp_path / "method.yaml").read_text(encoding="utf-8"))
    manifest["entry"] = {"resource": "document.test.schema"}
    (tmp_path / "method.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    invalid_entry = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert not invalid_entry.ok and invalid_entry.error is not None
    assert invalid_entry.error.code == "MANIFEST_ENTRY_INVALID"


@pytest.mark.parametrize("bad_yaml,code", [
    ("schema_version: 1\nschema_version: 1\n", "DUPLICATE_KEY"),
    ("schema_version: 1\nnode: &x {kind: stop}\nother: *x\n", "YAML_ALIAS_OR_ANCHOR"),
    ("schema_version: 1\nthreshold: 0.5\n", "NON_JSON_VALUE"),
])
def test_loader_rejects_ambiguous_yaml_values(tmp_path: Path, bad_yaml: str, code: str) -> None:
    raw = bad_yaml.encode()
    (tmp_path / "workflow.yaml").write_bytes(raw)
    manifest = {
        "schema_version": 1, "method_id": "test.method", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": [{"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
                       "media_type": "application/yaml", "sha256": hashlib.sha256(raw).hexdigest()}],
        "requires": [],
    }
    (tmp_path / "method.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert not result.ok and result.error is not None and result.error.code == code


def test_validation_rejects_unknown_capability_and_unsupported_workflow_edges(tmp_path: Path) -> None:
    workflow = """schema_version: 1
entry: op
steps:
- id: op
  kind: operation
  operation: missing.capability
  outcomes:
    ok: {next: op}
stop_outcomes: [finished]
wait_kinds: []
"""
    require = [{"capability_id": "missing.capability", "kind": "operation",
                "interface_version": "1.0.0", "contract_digest": "0" * 64}]
    _write_bundle(tmp_path, workflow=workflow, extra_requires=require)
    loaded_result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert loaded_result.ok
    assert loaded_result.value is not None
    report = validate_method(loaded_result.value, CompilationCapabilities(()))
    codes = {item.code for item in report.diagnostics}
    assert not report.valid
    assert "UNKNOWN_CAPABILITY" in codes
    assert "UNSUPPORTED_FLOW_CYCLE" in codes
    compiled = compile_method(loaded_result.value, CompilationCapabilities(()), "test.compiler/1")
    assert not compiled.ok


def test_validation_rejects_omitted_operation_outcome_and_remote_schema_ref(tmp_path: Path) -> None:
    contract = {"workflow_outcomes": ["done", "unknown"]}
    digest = method_digest("capability-contract", contract)
    workflow = """schema_version: 1
entry: op
steps:
- id: op
  kind: operation
  operation: demo.operation
  outcomes:
    done: {stop: finished}
stop_outcomes: [finished]
wait_kinds: []
"""
    require = [{"capability_id": "demo.operation", "kind": "operation",
                "interface_version": "1.0.0", "contract_digest": digest}]
    _write_bundle(tmp_path, workflow=workflow, extra_requires=require)
    loaded_result = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert loaded_result.ok and loaded_result.value is not None
    capability = CapabilityDescriptor("demo.operation", "operation", "1.0.0", digest, contract)
    report = validate_method(loaded_result.value, CompilationCapabilities((capability,)))
    assert not report.valid
    assert "UNHANDLED_OUTCOME" in {item.code for item in report.diagnostics}

    # A remote schema reference is rejected before any resolver can fetch it.
    schema = {"type": "object", "$ref": "https://example.invalid/schema.json"}
    schema_bytes = json.dumps(schema, separators=(",", ":")).encode()
    (tmp_path / "schema.json").write_bytes(schema_bytes)
    (tmp_path / "workflow.yaml").write_text(
        "schema_version: 1\nentry: done\nsteps:\n- id: done\n  kind: stop\n  outcome: finished\nstop_outcomes: [finished]\nwait_kinds: []\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1, "method_id": "test.schema", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": [
            {"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml", "media_type": "application/yaml",
             "sha256": hashlib.sha256((tmp_path / "workflow.yaml").read_bytes()).hexdigest()},
            {"id": "document.schema", "kind": "document_schema", "path": "schema.json", "media_type": "application/schema+json",
             "sha256": hashlib.sha256(schema_bytes).hexdigest()},
        ], "requires": [], "documents": [{"document_type": "test", "schema": {"resource": "document.schema"}}],
    }
    (tmp_path / "method.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    schema_loaded = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert schema_loaded.ok and schema_loaded.value is not None
    schema_report = validate_method(schema_loaded.value, CompilationCapabilities(()))
    assert "REMOTE_SCHEMA_REF" in {item.code for item in schema_report.diagnostics}


def test_schema_references_resolve_offline_fragments_anchors_and_nested_ids() -> None:
    pointer_schema = {"$defs": {"text": {"type": "string"}}, "$ref": "#/$defs/text"}
    anchor_schema = {
        "$defs": {"text": {"$anchor": "textValue", "type": "string"}},
        "$dynamicRef": "#textValue",
    }
    nested_id_schema = {
        "$defs": {
            "nested": {
                "$id": "nested-schema",
                "$defs": {"text": {"type": "string"}},
                "$ref": "#/$defs/text",
            },
        },
    }
    relative_root_id_schema = {
        "$id": "schemas/root.json",
        "$defs": {"text": {"type": "string"}},
        "$ref": "#/$defs/text",
    }
    for schema in (pointer_schema, anchor_schema, nested_id_schema, relative_root_id_schema):
        assert validate_schema_refs(schema, resource_id="schema", path="schema.json") == []

    unresolved = validate_schema_refs(
        {"$dynamicRef": "#missing"}, resource_id="schema", path="schema.json",
    )
    assert len(unresolved) == 1 and unresolved[0].code == "REMOTE_SCHEMA_REF"
    bad_pointer = validate_schema_refs(
        {"$ref": "#/$defs/absent"}, resource_id="schema", path="schema.json",
    )
    assert len(bad_pointer) == 1 and bad_pointer[0].code == "REMOTE_SCHEMA_REF"
    external = validate_schema_refs(
        {"$ref": "https://external.invalid/schema"}, resource_id="schema", path="schema.json",
    )
    assert len(external) == 1 and external[0].code == "REMOTE_SCHEMA_REF"


def test_schema_reference_can_use_a_separately_supplied_bundle_schema() -> None:
    source = {"$ref": "https://ordessa.invalid/method/shared.json#/$defs/name"}
    bundled = {"$defs": {"name": {"type": "string"}}}
    errors = validate_schema_refs(
        source, resource_id="source", path="source.json",
        schemas={"shared": ("shared.json", bundled)},
    )
    assert errors == []


def test_real_design_bundle_conforms_to_its_compiler_golden() -> None:
    source_root = REPO_ROOT / "methods" / "incremental-engineering"
    loaded_result = load_method(MethodSource(source_root), reader=FileResourceReader())
    assert loaded_result.ok
    loaded = loaded_result.value
    assert loaded is not None
    raw_catalog = json.loads((source_root / "contracts" / "capability-catalog.json").read_text(encoding="utf-8"))
    assert raw_catalog["fixture_only"] is True
    descriptors = tuple(
        CapabilityDescriptor(
            row["capability_id"], row["kind"], row["interface_version"],
            row["contract_digest"], row["contract"],
        ) for row in raw_catalog["capabilities"]
    )
    fixture_capabilities = CompilationCapabilities(descriptors, "test-fixture", "fixture")
    report = validate_method(loaded, fixture_capabilities)
    assert report.valid
    assert any(item.code == "FIXTURE_CAPABILITIES_ONLY" and item.severity == "warning"
               for item in report.diagnostics)
    compiled = compile_method(loaded, fixture_capabilities, "ordessa.methods/v2")
    assert compiled.ok
    assert compiled.value is not None
    assert loaded.compiled_golden == program_to_canonical(compiled.value.program)
    assert method_digest('compiled-method-program', program_to_canonical(compiled.value.program)) == program_plan_digest(compiled.value.program)
    store = _MemoryStore()
    frozen = freeze_method(
        compiled.value, store, _MemoryIdentityIndex(store),
        capability_catalog=TestCatalogReader(fixture_capabilities),
    )
    assert not frozen.ok and frozen.error is not None
    assert frozen.error.code == "CAPABILITY_CATALOG_UNTRUSTED"
    assert not store.snapshots
    forged_warning_free = replace(compiled.value, diagnostics=())
    forged = freeze_method(
        forged_warning_free, store, _MemoryIdentityIndex(store),
        capability_catalog=TestCatalogReader(fixture_capabilities),
    )
    assert not forged.ok and forged.error is not None
    assert forged.error.code == "CAPABILITY_CATALOG_UNTRUSTED"
    assert not store.snapshots


def test_snapshot_store_publish_is_an_atomic_unique_release_contract() -> None:
    store = _MemoryStore()
    encoding = stored_program_from_canonical({'schema_version': 1, 'compiler_version': 'c1', 'workflow': {}, 'documents': [], 'standards': [], 'decision_templates': [], 'skill_resources': [], 'capability_bindings': []})
    first = MethodSnapshot(StoredSourceBundle(MethodIdentity("m", "1", 1), BlobRef("a" * 64, 0, "application/yaml", "m"), ()),
        HistoricalBoundProgram(encoding, ProgramBindings((), ())), "b" * 64)
    expected = store.publish(first)
    assert store.publish(first) == expected
    changed = replace(first, snapshot_digest="c" * 64)
    with pytest.raises(ValueError, match="release_identity_conflict"):
        store.publish(changed)


def test_freeze_store_callback_mutates_real_caller_program_but_publishes_prepared_snapshot(tmp_path):
    _write_bundle(tmp_path)
    loaded = load_method(MethodSource(tmp_path), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    result = compile_method(loaded.value, CompilationCapabilities(()), "test.callback/1")
    assert result.ok and result.value is not None, result.error
    compiled = result.value
    original_program = program_to_canonical(compiled.program)
    original_digest = program_plan_digest(compiled.program)
    callbacks = []

    def mutate_actual_authority():
        callbacks.append(compiled.program.workflow.entry)
        object.__setattr__(compiled.program.workflow, "entry", "callback-forgery")
        callbacks.append(compiled.program.workflow.entry)

    store = _MemoryStore()
    store.on_put = mutate_actual_authority
    frozen = freeze_method(compiled, store, _MemoryIdentityIndex(store),
        capability_catalog=TestCatalogReader(CompilationCapabilities((), "callback-host", "host")))
    assert callbacks == ["done", "callback-forgery"]
    assert compiled.program.workflow.entry == "callback-forgery"
    assert frozen.ok and frozen.value is not None, frozen.error
    persisted = store.get(frozen.value.ref)
    assert persisted.program.workflow.entry == "done"
    assert program_to_canonical(persisted.program) == original_program
    assert program_plan_digest(persisted.program) == original_digest
    assert program_to_canonical(frozen.value.snapshot.program) == original_program

    # The forged caller object must not be accepted by a subsequent publication.
    refused_store = _MemoryStore()
    refused = freeze_method(compiled, refused_store, _MemoryIdentityIndex(refused_store),
        capability_catalog=TestCatalogReader(CompilationCapabilities((), "callback-host", "host")))
    assert not refused.ok and refused.error is not None
    assert refused.error.code == "COMPILED_PROGRAM_SOURCE_MISMATCH"
    assert not refused_store.blobs and not refused_store.snapshots


def test_unsorted_typed_maps_keep_original_sorted_consumer_views():
    from ordessa_engineering.methods.definitions.models.compiled import (
        SlotBinding, SlotMap, OutcomeMap, OutcomeBinding, TransitionTarget,
        OperationNode, WaitNode, StopNode, WorkflowSpec, OptionStatusMap, OptionStatus,
        DecisionPolicySpec, ChoiceVocabulary, AnswerOption, CheckDefinition,
        CriterionDefinition, StandardDefinition, DispositionSpec, ReductionSpec,
        FrozenObject, ResourceRef, CompiledProgram,
    )
    from ordessa_engineering.methods.compilation.encoding import program_nodes, program_criteria

    slots = SlotMap(entries=(SlotBinding("z", "slot.z"), SlotBinding("a", "slot.a")))
    outcomes = OutcomeMap(entries=(
        OutcomeBinding(outcome="z", target=TransitionTarget(stop="finished")),
        OutcomeBinding(outcome="a", target=TransitionTarget(wait="await")),
    ))
    workflow = WorkflowSpec(schema_version=1, entry="run", steps=(
        OperationNode(id="run", kind="operation", operation="operation.test", inputs=slots, outcomes=outcomes),
        WaitNode(id="wait", kind="wait", event="event.test", next="done", bind=slots, match=slots),
        StopNode(id="done", kind="stop", outcome="finished"),
    ), stop_outcomes=("finished",), wait_kinds=("await",))
    statuses = OptionStatusMap(entries=(
        OptionStatus(option_id="z", status="satisfied"),
        OptionStatus(option_id="a", status="violated"),
    ))
    policy = DecisionPolicySpec(calibration_profile_id="calibration.test",
        activation="matching_validated_evaluation_required", missing_evaluation="insufficient",
        truncation="unknown", option_statuses=statuses)
    criterion = CriterionDefinition(criterion_id="criterion.test", statement="test statement",
        checks=(CheckDefinition(capability_id="check.test", interface_version="v1", bindings=FrozenObject()),),
        policy=DispositionSpec(satisfied="pass", violated="block", insufficient="insufficient", unknown="manual"),
        answer_vocabulary=ChoiceVocabulary(kind="choice", options=(
            AnswerOption(option_id="z", description="last"), AnswerOption(option_id="a", description="first"))),
        decision_policy=policy)
    standard = StandardDefinition(schema_version=1, standard_id="standard.test", revision="1",
        criteria=(criterion,), reduction=ReductionSpec(required_criteria="all_applicable",
            empty_applicable_set="error", priority=("block", "manual", "pass")),
        resource_ref=ResourceRef("standard.test", "a" * 64, "standard"))
    program = CompiledProgram(compiler_version="test.typed/1", workflow=workflow,
        standard_definitions=(standard,), document_definitions=(), schema_definitions=(),
        decision_definitions=(), skill_definitions=(), capability_bindings=())

    # These are legal constructors, deliberately bypassing decoder sorting.
    assert [item.name for item in slots.entries] == ["z", "a"]
    assert [item.outcome for item in outcomes.entries] == ["z", "a"]
    assert [item.option_id for item in statuses.entries] == ["z", "a"]
    nodes = program_nodes(program)
    assert [item.name for item in nodes[0].inputs] == ["a", "z"]
    assert [item.outcome for item in nodes[0].transitions] == ["a", "z"]
    assert [item.name for item in nodes[1].bindings] == ["a", "z"]
    assert [item.name for item in nodes[1].matches] == ["a", "z"]
    criteria = program_criteria(program)
    assert criteria[0].decision_policy.option_statuses == (("a", "violated"), ("z", "satisfied"))
    encoded = program_to_canonical(program)
    reconstructed = compiled_program_from_canonical(encoded, program.bindings)
    assert program_nodes(reconstructed) == nodes
    assert program_criteria(reconstructed) == criteria
    assert program_plan_digest(reconstructed) == program_plan_digest(program)
