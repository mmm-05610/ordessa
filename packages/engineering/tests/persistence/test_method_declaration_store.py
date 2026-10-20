"""Source-only schema-2 publication on the original Engineering snapshot store."""
from pathlib import Path
import hashlib
import json
import threading
from dataclasses import asdict, replace

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.method_declaration_codec import (
    decode_declaration, encode_declaration,
)
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_controls import MethodControl
from ordessa_engineering.domain.artifacts.method_binding import MethodRef as DomainMethodRef, ExactMethodResourceRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.methods.definitions.models import (
    CapturedResource, LoadLimits, MethodSource, SourceBundle,
)
from ordessa_engineering.methods.entry import compile_method, read_method_definition
from ordessa_engineering.methods.definitions.models import CompilationCapabilities
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods.loading.captured import rebuild_source_bundle


REPO_ROOT = Path(__file__).resolve().parents[4]
CANDIDATE = REPO_ROOT / "methods/incremental-engineering/candidates/2.7.0"


def _loaded():
    result = load_method(MethodSource(CANDIDATE, "method.json"), FileResourceReader())
    assert result.ok and result.value is not None, result.error
    return result.value


def _context(request_id):
    return CommandContext(Scope("declaration-test-realm", "declaration-test-project"),
        "declaration-test-principal", ActorRef("declaration-test-actor", "human", "test-only"),
        request_id, "2026-10-14T12:00:00.000000Z", "declaration-test-trace")


def _domain_ref(ref):
    return DomainMethodRef(ref.method_id, ref.release_version, ref.schema_version,
                           Digest("sha256", ref.snapshot_digest))


def _seed_test_control(library, scope, method_ref, occurred_at):
    """Seed only original control rows for mechanism tests; no adoption/grant."""
    event_ref = Digest("sha256", "a" * 64)
    control = MethodControl(scope, method_ref, True, 0, event_ref)
    with library.transaction() as connection:
        connection.execute("INSERT INTO eng_method_controls VALUES (?,?,?,?,?,?)",
            (scope.realm_id, scope.project_id, method_ref.snapshot_digest.hex, 1, 0, event_ref.hex))
        connection.execute("INSERT INTO eng_method_control_events VALUES (?,?,?,?,?)",
            (scope.realm_id, scope.project_id, method_ref.snapshot_digest.hex, 0,
             canonical_bytes({"control": asdict(control), "reason": "test-only seeded control",
                              "occurred_at": occurred_at})))


def test_source_only_publication_reopens_exact_declaration_without_compiling(tmp_path):
    path = (tmp_path / "engineering.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="declaration-store-test", schema_version=10)
    try:
        store = SQLiteSnapshotStore(library)
        loaded = _loaded()
        expected = read_method_definition(loaded)
        assert expected.ok and expected.value is not None
        compiled = compile_method(loaded, CompilationCapabilities(()), "test.compiler/1")
        assert not compiled.ok and compiled.error.code == "METHOD_EXECUTION_UNSUPPORTED"

        ref = store.publish_declaration(loaded)
        assert ref == expected.value.method_ref
        assert store.get_declaration(ref) == expected.value
        assert store.publish_declaration(loaded) == ref
        encoded = library._connection.execute(
            "SELECT canonical_bytes FROM eng_method_snapshots WHERE snapshot_digest=?",
            (ref.snapshot_digest,),
        ).fetchone()[0]
        assert b"engineering-method-declaration/1" in encoded
        assert b"compiled_plan" not in encoded
    finally:
        library.close()

    reopened = EngineeringLibrary.open(path, library_id="declaration-store-test")
    try:
        declaration = SQLiteSnapshotStore(reopened).get_declaration(ref)
        assert declaration == expected.value
        assert declaration.method_ref == ref
    finally:
        reopened.close()


def test_publication_does_not_trust_caller_widened_loaded_limits(tmp_path):
    path = (tmp_path / "engineering.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="declaration-limits-test", schema_version=10)
    try:
        store = SQLiteSnapshotStore(library)
        loaded = _loaded()
        permissive = LoadLimits(manifest_bytes=1 << 30, resource_bytes=1 << 30,
            total_resources=1 << 20, total_bytes=1 << 32, structure_depth=1 << 20,
            workflow_steps=1 << 20, question_count=1 << 20)
        bundle = SourceBundle(loaded.source_bundle.manifest_capture,
                              loaded.source_bundle.resources, permissive)
        widened = replace(loaded, source_bundle=bundle,
                          parsed_source=rebuild_source_bundle(bundle))
        assert store.publish_declaration(widened) == read_method_definition(loaded).value.method_ref
    finally:
        library.close()


def test_declaration_release_identity_is_immutable(tmp_path):
    path = (tmp_path / "engineering.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="declaration-conflict-test", schema_version=10)
    try:
        store = SQLiteSnapshotStore(library)
        loaded = _loaded()
        ref = store.publish_declaration(loaded)
        changed = _loaded()
        # Reuse the same release identity with different captured source bytes.
        from ordessa_engineering.methods.definitions.models import ResourceBytes, SourceBundle
        manifest = changed.source_bundle.manifest_capture
        manifest_value = changed.manifest
        resource = next(item for item in changed.source_bundle.resources
                        if item.resource_id == "change-review-prompt")
        changed_body = resource.captured.data + b"\n"
        next(item for item in manifest_value["resources"]
             if item["id"] == resource.resource_id)["sha256"] = hashlib.sha256(changed_body).hexdigest()
        manifest_bytes = json.dumps(manifest_value, separators=(",", ":")).encode()
        modified = ResourceBytes(manifest.logical_path, manifest.media_type, manifest_bytes)
        changed_resources = tuple(
            replace(item, captured=ResourceBytes(item.captured.logical_path,
                item.captured.media_type, changed_body)) if item.resource_id == resource.resource_id else item
            for item in changed.source_bundle.resources
        )
        changed_bundle = SourceBundle(modified, changed_resources, changed.source_bundle.limits)
        from ordessa_engineering.methods.loading.captured import rebuild_source_bundle
        forged = replace(changed, source_bundle=changed_bundle,
                         parsed_source=rebuild_source_bundle(changed_bundle))
        with pytest.raises(MethodFailure) as conflict:
            store.publish_declaration(forged)
        assert conflict.value.error.code == "RELEASE_IDENTITY_CONFLICT"
        assert store.get_declaration(ref).method_ref == ref
    finally:
        library.close()


def test_tampered_source_pin_is_rejected_on_declaration_read(tmp_path):
    path = (tmp_path / "engineering.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="declaration-tamper-test", schema_version=10)
    try:
        store = SQLiteSnapshotStore(library)
        ref = store.publish_declaration(_loaded())
        raw = library._connection.execute(
            "SELECT canonical_bytes FROM eng_method_snapshots WHERE snapshot_digest=?",
            (ref.snapshot_digest,),
        ).fetchone()[0]
        envelope = decode_json(raw)
        envelope["source_bundle"]["resources"][0]["blob_ref"]["digest"] = "d" * 64
        library._connection.execute(
            "UPDATE eng_method_snapshots SET canonical_bytes=? WHERE snapshot_digest=?",
            (canonical_bytes(envelope), ref.snapshot_digest),
        )
        with pytest.raises(MethodFailure):
            store.get_declaration(ref)
    finally:
        library.close()


def test_swapped_resource_id_path_binding_is_rejected_before_publication(tmp_path):
    path = (tmp_path / "engineering.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="declaration-binding-test", schema_version=10)
    try:
        store = SQLiteSnapshotStore(library)
        loaded = _loaded()
        first, second, *rest = loaded.source_bundle.resources
        swapped = (CapturedResource(second.resource_id, first.captured),
                   CapturedResource(first.resource_id, second.captured), *rest)
        bundle = SourceBundle(loaded.source_bundle.manifest_capture, tuple(swapped),
                              loaded.source_bundle.limits)
        forged = object.__new__(type(loaded))
        object.__setattr__(forged, "source", loaded.source)
        object.__setattr__(forged, "source_bundle", bundle)
        object.__setattr__(forged, "parsed_source", loaded.parsed_source)
        object.__setattr__(forged, "verification", None)
        with pytest.raises(MethodFailure) as error:
            store.publish_declaration(forged)
        assert error.value.error.code == "SNAPSHOT_SOURCE_MISMATCH"
        assert library._connection.execute(
            "SELECT count(*) FROM eng_method_releases WHERE method_id='ordessa.incremental-engineering'"
        ).fetchone()[0] == 0
    finally:
        library.close()


def test_swapped_stored_resource_id_path_binding_is_rejected_on_reload(tmp_path):
    path = (tmp_path / "engineering.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="declaration-reload-binding-test", schema_version=10)
    try:
        store = SQLiteSnapshotStore(library)
        ref = store.publish_declaration(_loaded())
        raw = library._connection.execute(
            "SELECT canonical_bytes FROM eng_method_snapshots WHERE snapshot_digest=?",
            (ref.snapshot_digest,),
        ).fetchone()[0]
        stored_ref, manifest_path, source = decode_declaration(raw)
        first, second, *rest = source.resources
        swapped = (replace(first, resource_id=second.resource_id),
                   replace(second, resource_id=first.resource_id), *rest)
        malformed = replace(source, resources=tuple(swapped))
        tampered = encode_declaration(stored_ref, manifest_path, malformed)
        library._connection.execute(
            "UPDATE eng_method_snapshots SET canonical_bytes=? WHERE snapshot_digest=?",
            (tampered, ref.snapshot_digest),
        )
        with pytest.raises(MethodFailure) as error:
            store.get_declaration(ref)
        assert error.value.error.code == "SNAPSHOT_SOURCE_MISMATCH"
    finally:
        library.close()


def test_declaration_guard_reads_exact_resources_and_holds_original_commit_fence(tmp_path, monkeypatch):
    path = (tmp_path / "engineering.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="declaration-control-test", schema_version=10)
    try:
        store = SQLiteSnapshotStore(library)
        factory = SQLiteUoWFactory(library)
        controls = SQLiteMethodControl(factory, store)
        loaded = _loaded()
        method_ref = store.publish_declaration(loaded)
        domain_ref = _domain_ref(method_ref)
        context = _context("guarded")
        _seed_test_control(library, context.scope, domain_ref, context.received_at)
        declaration_ref = next(item for item in loaded.source_bundle.resources
                               if item.resource_id == "action-prepare-packages")
        exact = ExactMethodResourceRef(domain_ref,
            declaration_ref.captured.logical_path,
            Digest("sha256", declaration_ref.captured.digest),
            declaration_ref.resource_id)

        original_load = store._load_declaration
        load_count = 0

        def counted_load(ref):
            nonlocal load_count
            load_count += 1
            return original_load(ref)

        monkeypatch.setattr(store, "_load_declaration", counted_load)

        with controls.guard(context, domain_ref) as definition:
            assert definition.method_ref.snapshot_digest == method_ref.snapshot_digest
            assert controls.read_resource(context, exact) == declaration_ref.captured.data
            copied_principal = replace(context, principal_id="other-principal")
            with pytest.raises(ApplicationError, match="METHOD_DECLARATION_GUARD_REQUIRED"):
                controls.read_resource(copied_principal, exact)
            equal_copy = replace(context)
            assert equal_copy == context and equal_copy is not context
            assert controls.read_resource(equal_copy, exact) == declaration_ref.captured.data
            cross_thread = []

            def read_from_other_thread():
                try:
                    controls.read_resource(context, exact)
                except ApplicationError as error:
                    cross_thread.append(error.code)

            reader = threading.Thread(target=read_from_other_thread)
            reader.start()
            reader.join(2)
            assert not reader.is_alive()
            assert cross_thread == ["METHOD_DECLARATION_GUARD_REQUIRED"]
            template_refs = tuple(
                ExactMethodResourceRef(domain_ref, item.captured.logical_path,
                    Digest("sha256", item.captured.digest), item.resource_id)
                for item in loaded.source_bundle.resources
                if item.resource_id in {"spec-kit-spec", "spec-kit-plan", "spec-kit-tasks"}
            )
            assert controls.preparation_roles(context, definition, template_refs) == (
                "spec", "plan", "tasks")
            assert load_count == 1
            with pytest.raises(ApplicationError, match="METHOD_PREPARATION_TEMPLATE_UNAVAILABLE"):
                controls.preparation_roles(context, definition, template_refs[:-1])
            wrong_digest = ExactMethodResourceRef(domain_ref, exact.logical_path,
                Digest("sha256", "b" * 64), exact.resource_id)
            with pytest.raises(ApplicationError, match="METHOD_RESOURCE_REF_MISMATCH"):
                controls.read_resource(context, wrong_digest)
            with factory.begin(context.scope) as uow:
                uow.methods.set_control(domain_ref, 0, False, Digest("sha256", "c" * 64),
                                        "test control change", context.received_at)
                with pytest.raises(ApplicationError, match="METHOD_CONTROL_CHANGED"):
                    uow.commit()

        with controls.guard(_context("after-rollback"), domain_ref):
            pass
        with pytest.raises(ApplicationError, match="METHOD_DECLARATION_GUARD_REQUIRED"):
            controls.read_resource(_context("outside"), exact)
        with pytest.raises(ApplicationError, match="METHOD_DECLARATION_GUARD_REQUIRED"):
            controls.read_resource(context, exact)
    finally:
        library.close()
