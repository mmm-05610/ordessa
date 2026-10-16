"""Strict common value/canonical helpers; no business type catalog or decoder registry."""
from dataclasses import fields, is_dataclass
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ..models.refs import BlobRef
from ..models.values import Digest
from ..models.identity import Scope, ActorRef
from ..models.selection import ContentSelector
from ..outcomes.diagnostics import ReferenceError

def projection(value, *, identity=False):
    if type(value) is BlobRef and identity:
        return value.identity_projection()
    canonical_projection = getattr(type(value), "__canonical_projection__", None)
    if callable(canonical_projection):
        return canonical_projection(value, identity=identity)
    if is_dataclass(value):
        return {f.name: projection(getattr(value, f.name), identity=identity) for f in fields(value)}
    if type(value) is tuple:
        return [projection(item, identity=identity) for item in value]
    return value


def canonical_value(raw: bytes, *, maximum: int = 2 * 1024 * 1024):
    """Decode strict canonical bytes without rewriting their representation."""
    try:
        if type(raw) is not bytes or len(raw) > maximum:
            raise ReferenceError("INVALID_RECORD_BYTES")
        value = decode_json(raw)
        if canonical_bytes(value) != raw:
            raise ReferenceError("INVALID_RECORD_BYTES")
        return value
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise ReferenceError("INVALID_RECORD_BYTES") from None


def require_object(value, keys, code):
    if type(value) is not dict or set(value) != set(keys):
        raise ReferenceError(code)
    return value


def decode_tuple(value, parser, code, *, maximum=4096):
    if type(value) is not list or maximum is not None and len(value) > maximum:
        raise ReferenceError(code)
    return tuple(parser(item) for item in value)


def decode_digest(value):
    require_object(value, {"algorithm", "hex"}, "INVALID_SCHEMA")
    return Digest(value["algorithm"], value["hex"])


def decode_actor(value):
    require_object(value, {"actor_id", "actor_kind", "issuer"}, "INVALID_SCHEMA")
    return ActorRef(**value)


def decode_blob_ref(value):
    require_object(value, {"digest", "byte_length", "media_type", "storage_object_id"}, "INVALID_BLOB_REF")
    return BlobRef(decode_digest(value["digest"]), value["byte_length"], value["media_type"],
                   value["storage_object_id"])


def decode_selector(value):
    require_object(value, {"kind", "start", "end", "pointer", "schema_version"}, "INVALID_SELECTOR")
    return ContentSelector(**value)


def decode_scope(value):
    require_object(value, {'realm_id','project_id'}, 'INVALID_SCHEMA')
    return Scope(value['realm_id'], value['project_id'])
