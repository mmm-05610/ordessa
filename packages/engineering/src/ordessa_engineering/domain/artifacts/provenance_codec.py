"""Closed artifact provenance decoders; caller record limits remain in owner codecs."""
from ordessa_engineering.domain.common.mechanisms.codec import require_object, decode_tuple, decode_digest, decode_actor, decode_blob_ref, decode_selector
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from .refs import ArtifactRevisionRef
from .ref_codec import decode_artifact_ref
from .provenance import SourceLocator, VersionCapture, ExcerptCapture, SourceRef, Claim, ClaimRef, EvidenceLink, GenerationOrigin

def decode_locator(value):
    keys = {"kind", "provider", "conversation_id", "message_id", "repository_id", "path",
            "document_id", "artifact_ref", "observation_id"}
    require_object(value, keys, "INVALID_SOURCE_LOCATOR")
    fields = dict(value)
    if fields["artifact_ref"] is not None:
        fields["artifact_ref"] = decode_artifact_ref(fields["artifact_ref"])
    return SourceLocator(**fields)


def decode_source_capture(value):
    if type(value) is not dict or type(value.get("kind")) is not str:
        raise ReferenceError("INVALID_SOURCE_CAPTURE")
    if value["kind"] == "immutable_version":
        require_object(value, {"kind", "upstream_version", "content_digest"}, "INVALID_SOURCE_CAPTURE")
        return VersionCapture(value["upstream_version"], decode_digest(value["content_digest"]))
    if value["kind"] == "immutable_excerpt":
        require_object(value, {"kind", "blob_ref", "excerpt_digest", "selector", "upstream_version"},
                "INVALID_SOURCE_CAPTURE")
        return ExcerptCapture(decode_blob_ref(value["blob_ref"]), decode_digest(value["excerpt_digest"]),
                              decode_selector(value["selector"]), value["upstream_version"])
    raise ReferenceError("INVALID_SOURCE_CAPTURE")


def decode_source(value):
    require_object(value, {"source_id", "kind", "locator", "capture", "captured_at", "captured_by",
                    "media_type", "byte_length", "original_url"}, "INVALID_SOURCE")
    return SourceRef(value["source_id"], value["kind"], decode_locator(value["locator"]),
                     decode_source_capture(value["capture"]), value["captured_at"],
                     decode_actor(value["captured_by"]), value["media_type"], value["byte_length"],
                     value["original_url"])


def decode_claim(value):
    require_object(value, {"claim_id", "selector", "statement_digest"}, "INVALID_CLAIM")
    return Claim(value["claim_id"], decode_selector(value["selector"]), decode_digest(value["statement_digest"]))


def decode_evidence_link(value):
    require_object(value, {"claim_id", "source_ref", "source_selector", "relation", "rationale"},
            "INVALID_EVIDENCE_LINK")
    return EvidenceLink(value["claim_id"], decode_source(value["source_ref"]),
                        decode_selector(value["source_selector"]), value["relation"], value["rationale"])


def decode_claim_ref(value):
    require_object(value, {'owner_revision_ref','claim_id','statement_digest'}, 'INVALID_CLAIM')
    return ClaimRef(decode_artifact_ref(value['owner_revision_ref']), value['claim_id'], decode_digest(value['statement_digest']))


def decode_generation_origin(value):
    if value is None:
        return None
    require_object(value, {"provider", "trace_id", "execution_id", "generator_version"},
            "INVALID_GENERATION_ORIGIN")
    return GenerationOrigin(**value)
