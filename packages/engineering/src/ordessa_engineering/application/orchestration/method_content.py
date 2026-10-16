"""Read method-bound content and validate neutral method_content.value.

No renderer, domain object, authorization or execution is inferred here.
Application supplies the snapshot and a reader for its immutable content refs.
"""
from ...methods.compilation.encoding import program_to_canonical
from copy import deepcopy
import hashlib
from collections.abc import Mapping


from ...methods.definitions.models.compiled import DocumentSpec, ResourceRef, freeze_value
from ...methods.definitions.errors import MethodError, MethodFailure, MethodResult
from ...methods.definitions.models import MethodSnapshot
from ordessa_engineering.application.contracts.access import ResourceContentReader
from ordessa_engineering.application.contracts.errors import ApplicationError


def _program(snapshot: MethodSnapshot) -> dict:
    program = deepcopy(program_to_canonical(snapshot.program))
    if program.get("schema_version") != 2:
        raise MethodFailure(MethodError("METHOD_CONTENT_CONTRACT_UNSUPPORTED", "content bindings require program version 2"))
    return program


def document_spec(snapshot: MethodSnapshot, document_type: str) -> DocumentSpec:
    matches = [item for item in _program(snapshot)["documents"] if item["document_type"] == document_type]
    if len(matches) != 1:
        raise MethodFailure(MethodError("DOCUMENT_TYPE_UNAVAILABLE", "document type has no unique method binding"))
    item = matches[0]
    if item["validation_target"] != "method_content":
        raise MethodFailure(MethodError("VALIDATION_TARGET_UNSUPPORTED", "only method_content.value is supported"))
    return DocumentSpec(document_type, ResourceRef(**item["schema_resource"]), freeze_value(item["value_schema"]),
                        ResourceRef(**item["template_resource"]) if item["template_resource"] else None)


def _read_bound(snapshot: MethodSnapshot, ref: ResourceRef, reader: ResourceContentReader, kind: str) -> bytes:
    matches = [item for item in snapshot.resources if item.resource_id == ref.resource_id and item.digest == ref.sha256]
    if len(matches) != 1 or ref.kind != kind:
        raise MethodFailure(MethodError("METHOD_RESOURCE_MISMATCH", "content binding does not resolve to an exact resource"))
    resource = deepcopy(matches[0])
    blob = resource.blob_ref
    if blob.digest != resource.digest or blob.byte_length != resource.byte_length or blob.media_type != resource.media_type:
        raise MethodFailure(MethodError("METHOD_RESOURCE_MISMATCH", "stored resource metadata differs from its content reference"))
    expected = (blob.digest, blob.byte_length, blob.media_type, blob.storage_object_id)
    try:
        raw = reader.read_blob(blob)
    except (OSError, ValueError, TypeError) as exc:
        raise MethodFailure(MethodError("METHOD_RESOURCE_UNAVAILABLE", "stored method resource could not be read")) from exc
    if (tuple(getattr(blob, name, None) for name in ("digest", "byte_length", "media_type", "storage_object_id")) != expected
            or type(raw) is not bytes or len(raw) != expected[1]
            or hashlib.sha256(raw).hexdigest() != expected[0]):
        raise MethodFailure(MethodError("METHOD_RESOURCE_BYTES_MISMATCH", "stored method resource bytes differ from the binding"))
    return raw


def template_bytes(snapshot: MethodSnapshot, document_type: str, reader: ResourceContentReader) -> bytes:
    spec = document_spec(snapshot, document_type)
    if spec.template_ref is None:
        raise MethodFailure(MethodError("DOCUMENT_TEMPLATE_UNAVAILABLE", "document type has no template binding"))
    return _read_bound(snapshot, spec.template_ref, reader, "document_template")


def skill_bytes(snapshot: MethodSnapshot, role: str, reader: ResourceContentReader) -> bytes:
    matches = [item for item in _program(snapshot)["skill_resources"] if item["role"] == role]
    if len(matches) != 1:
        raise MethodFailure(MethodError("SKILL_ROLE_UNAVAILABLE", "role has no unique skill binding"))
    return _read_bound(snapshot, ResourceRef(**matches[0]["resource_ref"]), reader, "skill")




from ...methods.validation.schema import validate_document_content_data

def validate_document_content(snapshot: MethodSnapshot, document_type: str, method_content: Mapping) -> MethodResult[None]:
    try:
        return validate_document_content_data(snapshot, document_type, method_content, _program(snapshot))
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return MethodResult.failure(MethodError("METHOD_SCHEMA_INVALID", "document content could not be validated safely"))


def document_type_for_payload(snapshot: MethodSnapshot, payload) -> str:
    """Resolve a material label from its exact released schema, never kind text.

    The snapshot must come from the original SnapshotStore / method guard.
    This pure resource/content check does not authenticate a caller or material;
    actual ArtifactRevision reads and material validation stay with their UoW.
    """
    from urllib.parse import urljoin
    from ...domain.artifacts.models import MethodPayload
    from ...domain.artifacts.method_binding import MethodRef
    from ...domain.common.models.values import Digest
    from ...methods.definitions.models.compiled import CompiledProgram
    if (type(snapshot) is not MethodSnapshot or type(payload) is not MethodPayload
            or type(snapshot.program) is not CompiledProgram):
        raise ApplicationError('METHOD_DOCUMENT_TYPE_UNAVAILABLE')
    exact = payload.content.schema_ref
    ref = snapshot.ref
    method = MethodRef(ref.method_id, ref.release_version, ref.schema_version, Digest('sha256',ref.snapshot_digest))
    if exact.method_ref != method:
        raise ApplicationError('METHOD_RESOURCE_MISMATCH')
    stored = [r for r in snapshot.resources if r.resource_id == exact.resource_id]
    if (len(stored) != 1 or stored[0].logical_path != exact.logical_path
            or stored[0].digest != exact.resource_digest.hex):
        raise ApplicationError('METHOD_RESOURCE_MISMATCH')
    matches = [d for d in snapshot.program.document_definitions
               if d.schema_resource.resource_id == exact.resource_id
               and d.schema_resource.sha256 == exact.resource_digest.hex
               and d.schema_resource.kind == 'document_schema']
    if len(matches) != 1 or matches[0].validation_target != 'method_content':
        raise ApplicationError('METHOD_DOCUMENT_TYPE_UNAVAILABLE')
    from ...methods.definitions.models.compiled import thaw_value
    schema = thaw_value(matches[0].value_schema)
    location = 'https://ordessa.invalid/method/' + exact.logical_path
    if payload.schema_id != urljoin(location, schema.get('$id', location)):
        raise ApplicationError('METHOD_SCHEMA_ID_MISMATCH')
    result = validate_document_content(snapshot, matches[0].document_type, {'value':payload.content.value})
    if not result.ok:
        raise ApplicationError(result.error.code)
    return matches[0].document_type
