"""Application material-closure coordination over the caller's transaction.

The read/blob/budget/CAS work stays in the adapter (``MaterialBudget``, which
implements ``MaterialAccessPort``). This module coordinates those reads with the
pure source/selector/content rules owned by ``domain`` and ``methods``; it does
not re-implement those rules and does not pre-read to reuse across transactions.
"""
from __future__ import annotations

from urllib.parse import urljoin

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

from ...domain.artifacts.models import BlobPayload, MethodPayload
from ...domain.artifacts.provenance import VersionCapture
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...methods.definitions.errors import MethodFailure
from ...methods.validation.schema import validate_document_schemas

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.access import MaterialAccessPort, revision_validation_key


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
