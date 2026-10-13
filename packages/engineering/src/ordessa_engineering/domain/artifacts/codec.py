"""Closed, canonical wire codec for artifact revisions.

This module is deliberately pure domain code: decoding validates the complete
wire shape and reconstructs domain values before accepting their derived hashes.
"""
from __future__ import annotations

from ordessa_infrastructure.encoding import canonical_bytes

from ordessa_engineering.domain.artifacts.provenance import (Claim, EvidenceLink, ExcerptCapture, GenerationOrigin, SourceLocator, SourceRef, VersionCapture)
from ordessa_engineering.domain.common.models.selection import (ContentSelector)
from ordessa_engineering.domain.artifacts.method_binding import (ExactMethodResourceRef)
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ..common.models.values import (Digest)
from ..common.models.identity import (Scope)
from ..common.outcomes.diagnostics import (ReferenceError)
from ..common.models.identity import (ActorRef)
from ..common.mechanisms.codec import (canonical_value)
from .models import (
    MAX_RECORD_BYTES, ArtifactRevision, BlobPayload, InlinePayload, MethodContent,
    MethodPayload,
)


from ordessa_engineering.domain.common.mechanisms.codec import (require_object, decode_tuple, decode_digest, decode_actor, decode_blob_ref, decode_selector)
from ordessa_engineering.domain.artifacts.method_codec import (decode_method_ref, decode_exact_method_resource)
from ordessa_engineering.domain.artifacts.ref_codec import (decode_artifact_ref)
from ordessa_engineering.domain.artifacts.provenance_codec import (decode_source, decode_claim, decode_evidence_link, decode_generation_origin)


def decode_provenance_fields(value) -> dict:
    """Decode the five required schema-2 provenance fields into typed values."""
    require_object(value, {"sources", "claims", "evidence_links", "method_refs", "generation_origin"}, code='INVALID_REVISION')
    return {
        "sources": decode_tuple(value["sources"], decode_source, code='INVALID_REVISION'),
        "claims": decode_tuple(value["claims"], decode_claim, code='INVALID_REVISION'),
        "evidence_links": decode_tuple(value["evidence_links"], decode_evidence_link, code='INVALID_REVISION'),
        "method_refs": decode_tuple(value["method_refs"], decode_method_ref, code='INVALID_REVISION'),
        "generation_origin": decode_generation_origin(value["generation_origin"]),
    }


def decode_payload(value):
    """Decode a closed inline, blob, or explicitly tagged method payload."""
    if type(value) is not dict:
        raise ReferenceError("INVALID_PAYLOAD")
    common = {"media_type", "schema_id"}
    if "content_kind" in value:
        require_object(value, common | {"content_kind", "inline_value"}, "INVALID_METHOD_CONTENT")
        if value["content_kind"] != "method_content":
            raise ReferenceError("INVALID_METHOD_CONTENT")
        content = value["inline_value"]
        require_object(content, {"schema_ref", "value", "rendered_body_ref"}, "INVALID_METHOD_CONTENT")
        method_data = content["schema_ref"]
        require_object(method_data, {"method_ref", "logical_path", "resource_digest", "resource_id"}, "INVALID_METHOD_RESOURCE")
        schema_ref = decode_exact_method_resource(method_data)
        rendered = content["rendered_body_ref"]
        method_content = MethodContent.from_value(
            schema_ref, content["value"], None if rendered is None else decode_blob_ref(rendered))
        return MethodPayload(value["media_type"], value["schema_id"], method_content)
    if "blob_ref" in value:
        require_object(value, common | {"blob_ref"}, "INVALID_PAYLOAD")
        return BlobPayload(value["media_type"], value["schema_id"], decode_blob_ref(value["blob_ref"]))
    require_object(value, common | {"inline_value"}, "INVALID_PAYLOAD")
    return InlinePayload.from_value(value["media_type"], value["schema_id"], value["inline_value"])


def encode_revision(record: ArtifactRevision) -> bytes:
    if type(record) is not ArtifactRevision:
        raise ReferenceError("INVALID_REVISION")
    raw = canonical_bytes(record.projection())
    if len(raw) > MAX_RECORD_BYTES:
        raise ReferenceError("REVISION_TOO_LARGE")
    return raw


def decode_revision(raw: bytes) -> ArtifactRevision:
    try:
        if type(raw) is not bytes or len(raw) > MAX_RECORD_BYTES:
            raise ReferenceError("INVALID_REVISION")
        data = canonical_value(raw, maximum=MAX_RECORD_BYTES)
        base = {"schema_version", "realm_id", "project_id", "artifact_id", "revision_id", "created_at",
                "created_by", "payload", "body_digest", "parent_revision_refs", "digest"}
        if type(data) is not dict or type(data.get("schema_version")) is not int:
            raise ReferenceError("INVALID_REVISION")
        if data["schema_version"] == 1:
            require_object(data, base, code='INVALID_REVISION')
            provenance = {}
        elif data["schema_version"] == 2:
            require_object(data, base | {"sources", "claims", "evidence_links", "method_refs", "generation_origin"}, code='INVALID_REVISION')
            provenance = decode_provenance_fields({key: data[key] for key in (
                "sources", "claims", "evidence_links", "method_refs", "generation_origin")})
        else:
            raise ReferenceError("INVALID_REVISION")
        parents = decode_tuple(data["parent_revision_refs"], decode_artifact_ref, "INVALID_PARENT",
                         maximum=None if data["schema_version"] == 1 else 4096)
        payload = decode_payload(data["payload"])
        if data["schema_version"] == 1 and type(payload) is not InlinePayload:
            raise ReferenceError("INVALID_PAYLOAD")
        revision = ArtifactRevision(
            Scope(data["realm_id"], data["project_id"]), data["artifact_id"], data["revision_id"],
            data["created_at"], decode_actor(data["created_by"]), payload, parents,
            data["schema_version"], **provenance,
        )
        decode_digest(data["body_digest"])
        decode_digest(data["digest"])
        if encode_revision(revision) != raw:
            raise ReferenceError("REVISION_DIGEST_MISMATCH")
        return revision
    except ReferenceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise ReferenceError("INVALID_REVISION") from None
