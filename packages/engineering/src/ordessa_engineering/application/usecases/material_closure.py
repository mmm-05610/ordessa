"""Application material-closure coordination over the caller's transaction.

The read/blob/budget/CAS work stays in the adapter (``MaterialBudget``, which
implements ``MaterialAccessPort``). This module coordinates those reads with the
pure source/selector/content rules owned by ``domain`` and ``methods``; it does
not re-implement those rules and does not pre-read to reuse across transactions.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from urllib.parse import urljoin

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

from ...domain.artifacts.models import BlobPayload, MethodPayload
from ...domain.artifacts.provenance import SourceRef, VersionCapture
from ...domain.artifacts.method_binding import MethodRef, ExactMethodResourceRef
from ...domain.changes.models import SourceChange
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...methods.definitions.errors import MethodFailure
from ...methods.validation.schema import validate_document_schemas

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.access import MaterialAccessPort, revision_validation_key
from ordessa_engineering.application.contracts.source_materials import (
    SourceMaterialPort, MethodDeclarationGuard,
)

_MAX_METHOD_RESOURCE_BYTES = 256 * 1024


def _deny(code):
    raise ApplicationError(code)


def _no_retrieval(uri):
    # Never fetch a schema, including a declared https $id, from the network.
    raise NoSuchResource(ref=uri)


def _source_refs(sources):
    refs = []
    for source in sources:
        if type(source.capture) is VersionCapture:
            _deny('SOURCE_VERSION_UNAVAILABLE')
        if source.kind == 'artifact':
            _deny('SOURCE_OWNER_UNAVAILABLE')
        refs.append(source.capture.blob_ref)
    return tuple(refs)


def verify_sources(sources, links, budget: MaterialAccessPort):
    """Proposal sources use exactly the same byte/selector authority as revisions."""
    budget.reserve(_source_refs(sources))
    try:
        selected = {source.source_id: budget.selectors.check(budget.read(source.capture.blob_ref),
                    source.capture.selector, source.capture.excerpt_digest) for source in sources}
        for link in links:
            budget.selectors.check(selected[link.source_ref.source_id], link.source_selector)
    except ReferenceError as exc:
        _deny('MATERIAL_LIMIT' if exc.code == 'SELECTOR_WORK_LIMIT' else 'MATERIAL_CONTENT_INVALID')
    except KeyError:
        _deny('MATERIAL_CONTENT_INVALID')


def verify_external_source(context, source: SourceRef, source_materials: SourceMaterialPort):
    """Read one exact external immutable version and verify its captured bytes.

    Historical record decoding never calls this helper. Fresh create/review/
    package operations call it with the original context-scoped demand port.
    """
    if (type(source) is not SourceRef or type(source.capture) is not VersionCapture
            or source_materials is None or not callable(getattr(source_materials, 'read', None))):
        _deny('SOURCE_VERSION_UNAVAILABLE')
    try:
        raw = source_materials.read(context, source)
    except ApplicationError:
        raise
    except Exception as exc:
        raise ApplicationError('SOURCE_VERSION_UNAVAILABLE') from exc
    if (type(raw) is not bytes or len(raw) != source.byte_length
            or hashlib.sha256(raw).hexdigest() != source.capture.content_digest.hex):
        _deny('SOURCE_CONTENT_MISMATCH')
    return raw


def _method_ref_matches(definition, method_ref):
    ref = getattr(definition, 'method_ref', None)
    digest = getattr(ref, 'snapshot_digest', None)
    digest = digest.hex if hasattr(digest, 'hex') else digest
    return (getattr(ref, 'method_id', None) == method_ref.method_id
            and getattr(ref, 'release_version', None) == method_ref.release_version
            and getattr(ref, 'schema_version', None) == method_ref.schema_version
            and digest == method_ref.snapshot_digest.hex)


@contextmanager
def guard_method_resources(context, method_ref: MethodRef,
                           resource_refs: tuple[ExactMethodResourceRef, ...],
                           method_guard: MethodDeclarationGuard):
    """Hold the exact schema-2 declaration guard through the caller's COMMIT."""
    if (type(method_ref) is not MethodRef or method_ref.schema_version != 2
            or type(resource_refs) is not tuple or not resource_refs
            or method_guard is None
            or not callable(getattr(method_guard, 'guard', None))
            or not callable(getattr(method_guard, 'read_resource', None))):
        _deny('METHOD_AUTHORITY_UNAVAILABLE')
    try:
        guard = method_guard.guard(context, method_ref)
        with guard as definition:
            if not _method_ref_matches(definition, method_ref):
                _deny('METHOD_PIN_MISMATCH')
            declared = {item.resource_id: item for item in getattr(definition, 'resources', ())}
            seen = set()
            for exact in resource_refs:
                if (type(exact) is not ExactMethodResourceRef or exact.method_ref != method_ref
                        or exact.resource_id in seen):
                    _deny('METHOD_RESOURCE_MISMATCH')
                seen.add(exact.resource_id)
                resource = declared.get(exact.resource_id)
                if resource is None or resource.sha256 != exact.resource_digest.hex:
                    _deny('METHOD_RESOURCE_MISMATCH')
                raw = method_guard.read_resource(context, exact)
                if (type(raw) is not bytes or len(raw) > _MAX_METHOD_RESOURCE_BYTES
                        or hashlib.sha256(raw).hexdigest() != exact.resource_digest.hex):
                    _deny('METHOD_RESOURCE_MISMATCH')
            yield definition
    except ApplicationError:
        raise
    except Exception as exc:
        raise ApplicationError('METHOD_AUTHORITY_UNAVAILABLE') from exc


def verify_source_change(context, source_change: SourceChange,
                         source_materials: SourceMaterialPort):
    if type(source_change) is not SourceChange:
        _deny('SOURCE_CHANGE_INVALID')
    verify_external_source(context, source_change.baseline, source_materials)
    verify_external_source(context, source_change.candidate, source_materials)


def verify_material(revision, budget: MaterialAccessPort):
    if revision.schema_version == 1:
        return  # Historical decoding keeps its original semantics and bytes.
    if revision.generation_origin is not None:
        _deny('GENERATION_ORIGIN_UNAVAILABLE')
    refs = []
    payload = revision.payload
    if type(payload) is BlobPayload:
        refs.append(payload.blob_ref)
    elif type(payload) is MethodPayload and payload.content.rendered_body_ref is not None:
        refs.append(payload.content.rendered_body_ref)
    refs.extend(_source_refs(revision.sources))
    budget.reserve(refs)
    if type(payload) is BlobPayload:
        content = budget.read(payload.blob_ref)
    else:
        content = payload.content_bytes()
    try:
        for claim in revision.claims:
            budget.selectors.check(content, claim.selector, claim.statement_digest)
    except ReferenceError as exc:
        if exc.code == 'SELECTOR_WORK_LIMIT':
            _deny('MATERIAL_LIMIT')
        _deny('MATERIAL_CONTENT_INVALID')
    verify_sources(revision.sources, revision.evidence_links, budget)
    if type(payload) is MethodPayload and payload.content.rendered_body_ref is not None:
        budget.read(payload.content.rendered_body_ref)
    for method in revision.method_refs:
        budget.method(method)
    if type(payload) is MethodPayload:
        _verify_method_content(payload, budget)
    budget.mark_validated(revision_validation_key(revision))


def _verify_method_content(payload, budget: MaterialAccessPort):
    exact = payload.content.schema_ref
    snapshot, loaded = budget.method(exact.method_ref)
    resource = loaded.resources.get(exact.resource_id)
    stored = next((r for r in snapshot.resources if r.resource_id == exact.resource_id), None)
    if (resource is None or stored is None or stored.logical_path != exact.logical_path
            or stored.digest != exact.resource_digest.hex
            or resource.declaration.get('kind') != 'document_schema'):
        _deny('METHOD_RESOURCE_MISMATCH')
    if any(d.severity == 'error' for d in validate_document_schemas(loaded)):
        _deny('METHOD_SCHEMA_INVALID')
    schemas = {rid: r for rid, r in loaded.resources.items()
               if r.declaration.get('kind') == 'document_schema'}
    registry = Registry(retrieve=_no_retrieval)
    for rid, r in schemas.items():
        location = 'https://ordessa.invalid/method/' + r.captured.logical_path
        base = urljoin(location, r.value.get('$id', location))
        document = dict(r.value)
        document['$id'] = base
        resolved = Resource.from_contents(document, default_specification=DRAFT202012)
        registry = registry.with_resource(location, resolved).with_resource(base, resolved)
    location = 'https://ordessa.invalid/method/' + exact.logical_path
    schema = dict(resource.value)
    schema['$id'] = urljoin(location, schema.get('$id', location))
    if payload.schema_id != schema['$id']:
        _deny('METHOD_SCHEMA_ID_MISMATCH')
    try:
        if not Draft202012Validator(schema, registry=registry.crawl()).is_valid(payload.content.value):
            _deny('METHOD_CONTENT_INVALID')
    except ApplicationError:
        raise
    except (ValueError, TypeError, RecursionError, LookupError) as exc:
        raise ApplicationError('METHOD_SCHEMA_INVALID') from exc


__all__ = ['verify_material', 'verify_sources']
