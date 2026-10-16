"""Application publish/freeze coordination for one method release.

This is business coordination over the pure method kernels: rebuild the source
projection, verify compiled identity, read the injected capability catalog,
validate compatibility, prepare blobs and atomically publish the snapshot. It
holds no method *interpretation* (that stays in ``methods``) and no storage
implementation (that stays in adapters).
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

from ...methods.compilation.compiler import bind_program, compile_program_from_source
from ...methods.compilation.encoding import (
    program_plan_digest, program_to_canonical, stored_program_from_canonical,
)
from ...methods.definitions.errors import MethodError, MethodFailure, MethodResult
from ...methods.definitions.models import (
    BlobRef, CompiledMethod, FreezeResult, LoadedMethod,
    MethodRef, MethodSnapshot, MethodSource, ResourceSnapshot, StoredSourceBundle,
)
from ...methods.definitions.models.identity import method_digest
from ...methods.loading.captured import rebuild_source_bundle
from ...methods.validation.compatibility import validate_compatibility
from ordessa_engineering.application.contracts.access import CapabilityCatalogReader
from ordessa_engineering.application.contracts.snapshots import ReleasedIdentityIndex, SnapshotStore


def _checked_blob(store: SnapshotStore, digest: str, media_type: str, data: bytes) -> BlobRef:
    ref = store.put_blob(digest, media_type, data)
    if not isinstance(ref, BlobRef):
        raise MethodFailure(MethodError("SNAPSHOT_STORE_INVALID", "blob store returned an invalid BlobRef"))
    if ref.digest != digest or ref.byte_length != len(data) or ref.media_type != media_type or not ref.storage_object_id:
        raise MethodFailure(MethodError("SNAPSHOT_STORE_INVALID", "blob store returned mismatched content metadata"))
    return ref


def freeze_method(compiled: CompiledMethod, store: SnapshotStore,
                  existing: ReleasedIdentityIndex, *,
                  capability_catalog: CapabilityCatalogReader | None = None) -> MethodResult[FreezeResult]:
    if capability_catalog is None:
        return MethodResult.failure(MethodError(
            "CAPABILITY_AUTHORITY_UNAVAILABLE",
            "method publication requires an application-injected capability catalog reader",
        ))
    try:
        # Capture references before invoking any injected port. The verified
        # values below are rebuilt from immutable bytes and detached containers.
        source_bundle = compiled.source_bundle
        compiled_identity = compiled.identity
        compiled_manifest_digest = compiled.source_manifest_digest
        compiler_version = compiled.compiler_version
        compiled_plan_digest = program_plan_digest(compiled.program)
        frozen_envelope = compiled.program
        source_manifest_bytes = bytes(source_bundle.manifest_bytes)
        parsed_source = rebuild_source_bundle(source_bundle)
        if compiled.parsed_source != parsed_source:
            raise MethodFailure(MethodError("COMPILED_SOURCE_PROJECTION_MISMATCH", "compiled parsed view differs from captured bytes"))
        manifest, identity = parsed_source.manifest, parsed_source.identity
        source_resources, manifest_digest = parsed_source.resource_views, source_bundle.manifest_digest
        if manifest_digest != compiled_manifest_digest or identity != compiled_identity:
            raise MethodFailure(MethodError("COMPILED_SOURCE_IDENTITY_MISMATCH", "compiled method identity no longer matches captured source bytes"))
        program = program_to_canonical(frozen_envelope)
        if (frozen_envelope.compiler_version != compiler_version
                or program.get("compiler_version") != compiler_version
                or program_plan_digest(frozen_envelope) != compiled_plan_digest):
            raise MethodFailure(MethodError("COMPILED_PLAN_METADATA_MISMATCH", "compiled program metadata does not match its frozen envelope"))
        if method_digest("compiled-method-program", program) != compiled_plan_digest:
            raise MethodFailure(MethodError("COMPILED_PLAN_DIGEST_MISMATCH", "compiled program no longer matches its digest"))
        source_loaded = LoadedMethod(MethodSource(Path(".")), source_bundle, parsed_source)
        expected_program = compile_program_from_source(source_loaded, compiler_version)
        if expected_program != program or compiled.program.bindings != bind_program(stored_program_from_canonical(expected_program), source_loaded).bindings:
            raise MethodFailure(MethodError(
                "COMPILED_PROGRAM_SOURCE_MISMATCH",
                "compiled program projection does not match the captured source bytes",
            ))

        catalog = capability_catalog.read_current()
        if catalog.trust_class != "host":
            raise MethodFailure(MethodError(
                "CAPABILITY_CATALOG_UNTRUSTED",
                "fixture or unknown capability catalogs cannot publish a method release",
            ))
        report = validate_compatibility(source_loaded, catalog)
        if not report.valid:
            first_error = next(item for item in report.diagnostics if item.severity == "error")
            raise MethodFailure(MethodError(first_error.code, first_error.message,
                                            first_error.resource_id, first_error.path,
                                            first_error.pointer))

        # Freeze every projection used below before the first store call. Store
        # callbacks may re-enter application code and mutate the caller's
        # CompiledMethod while blobs are being written.
        prepared_resources: list[tuple[str, str, str, str, bytes]] = []
        for resource in sorted(source_resources.values(),
                               key=lambda item: item.declaration["id"]):
            raw = bytes(resource.captured.data)
            digest = resource.captured.digest
            if hashlib.sha256(raw).hexdigest() != digest:
                raise MethodFailure(MethodError("RESOURCE_DIGEST_MISMATCH", "captured resource bytes changed", resource_id=resource.declaration["id"], path=resource.captured.logical_path))
            if resource.declaration.get("sha256") != digest:
                raise MethodFailure(MethodError("RESOURCE_DIGEST_MISMATCH", "compiled source declaration does not bind captured resource bytes", resource_id=resource.declaration["id"], path=resource.captured.logical_path))
            prepared_resources.append((
                resource.declaration["id"], resource.captured.logical_path,
                resource.captured.media_type, digest, raw,
            ))
        resource_projection = [
            {"id": resource_id, "sha256": digest}
            for resource_id, _, _, digest, _ in prepared_resources
        ]
        required_capabilities = deepcopy(program["capability_bindings"])
        snapshot_identity = identity
        snapshot_digest = method_digest("method-snapshot", {
            "schema_version": identity.schema_version,
            "method_id": identity.method_id,
            "release_version": identity.release_version,
            "manifest_sha256": manifest_digest,
            "resource_digests": resource_projection,
            "required_capabilities": required_capabilities,
            "compiler_version": compiler_version,
            "compiled_plan_digest": {"algorithm": "sha256", "hex": compiled_plan_digest},
        })
        expected_ref = MethodRef(identity.method_id, identity.release_version,
                                 identity.schema_version, snapshot_digest)
        existing_digest = existing.get_digest(identity.method_id, identity.release_version)
        if existing_digest is not None and existing_digest != snapshot_digest:
            raise MethodFailure(MethodError(
                "RELEASE_IDENTITY_CONFLICT",
                "method ID and release version are already bound to different snapshot bytes",
            ))

        resource_snapshots: list[ResourceSnapshot] = []
        for resource_id, logical_path, media_type, digest, raw in prepared_resources:
            blob_ref = _checked_blob(store, digest, media_type, raw)
            resource_snapshots.append(ResourceSnapshot(resource_id, logical_path, blob_ref))

        manifest_ref = _checked_blob(
            store, manifest_digest, "application/yaml",
            source_manifest_bytes,
        )
        snapshot = MethodSnapshot(StoredSourceBundle(snapshot_identity, manifest_ref, tuple(resource_snapshots)), bind_program(stored_program_from_canonical(program), source_loaded), snapshot_digest)

        # This is the authority boundary: the store must atomically enforce the
        # release identity binding. The preflight index is only an optimization.
        published_ref = store.publish(snapshot)
        if published_ref != expected_ref:
            raise MethodFailure(MethodError("SNAPSHOT_PUBLISH_MISMATCH", "snapshot store published a different release identity"))
        # Do not expose the object handed to a memory adapter: callers may hold
        # and mutate result values even though the protocol models immutable data.
        return MethodResult.success(FreezeResult(snapshot=deepcopy(snapshot)))
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (AttributeError, OSError, TypeError, ValueError, KeyError):
        return MethodResult.failure(MethodError("METHOD_FREEZE_FAILED", "method snapshot could not be frozen safely"))


__all__ = ["freeze_method"]
