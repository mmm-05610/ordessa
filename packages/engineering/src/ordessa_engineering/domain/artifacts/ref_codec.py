"""Closed exact artifact-reference decoder."""
from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_tuple, decode_digest, decode_actor, decode_blob_ref, decode_selector
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .refs import ArtifactRevisionRef

def decode_artifact_ref(value):
    require_object(value, {"kind", "realm_id", "project_id", "artifact_id", "revision_id", "digest"}, "INVALID_PARENT")
    if value["kind"] != "artifact_revision":
        raise ReferenceError("INVALID_PARENT")
    return ArtifactRevisionRef(value["realm_id"], value["project_id"], value["artifact_id"],
                               value["revision_id"], decode_digest(value["digest"]))
