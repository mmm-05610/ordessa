"""Closed captured method/material binding decoders; no methods stage."""
from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_tuple, decode_digest, decode_actor, decode_blob_ref, decode_selector
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .method_binding import MethodRef, ExactMethodResourceRef

def decode_method_ref(value):
    require_object(value, {"method_id", "release_version", "schema_version", "snapshot_digest"}, "INVALID_SCHEMA")
    return MethodRef(value["method_id"], value["release_version"], value["schema_version"],
                     decode_digest(value["snapshot_digest"]))


def decode_exact_method_resource(value):
    require_object(value, {"method_ref", "logical_path", "resource_digest", "resource_id"}, "INVALID_METHOD_RESOURCE")
    return ExactMethodResourceRef(decode_method_ref(value["method_ref"]), value["logical_path"],
                                  decode_digest(value["resource_digest"]), value["resource_id"])
