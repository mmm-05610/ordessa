"""Wire-shape, identity, and provenance checks for artifact records."""
from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.domain.artifacts.codec import (
    decode_payload, decode_provenance_fields, decode_revision, encode_revision,
)
from ordessa_engineering.domain.artifacts.models import (
    MAX_RECORD_BYTES,
    ArtifactRevision, BlobPayload, InlinePayload, MethodContent, MethodPayload,
)
from ordessa_engineering.domain.artifacts.provenance import (Claim, EvidenceLink, ExcerptCapture, GenerationOrigin, SourceLocator, SourceRef, VersionCapture)
from ordessa_engineering.domain.common.models.selection import (ContentSelector)
from ordessa_engineering.domain.artifacts.method_binding import (ExactMethodResourceRef)
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.common.models.identity import (ActorRef)


SCOPE = Scope("realm-codec", "project-codec")
ACTOR = ActorRef("author-codec", "human", "test-artifact-codec")
CREATED_AT = "2026-10-09T12:00:00.000000Z"


def _digest(raw: bytes) -> Digest:
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


def _blob(raw: bytes = b"blob bytes", *, locator: str = "object-1") -> BlobRef:
    return BlobRef(_digest(raw), len(raw), "application/json", locator)


def _revision(payload=None, **kwargs) -> ArtifactRevision:
    return ArtifactRevision(
        SCOPE, "artifact-1", "revision-1", CREATED_AT, ACTOR,
        payload or InlinePayload.from_value("application/json", "urn:test:artifact", {"value": "ok"}),
        **kwargs,
    )


def _reject(call, code: str | None = None) -> None:
    with pytest.raises(ReferenceError) as caught:
        call()
    if code:
        assert caught.value.code == code


def test_schema1_wire_and_hash_match_pre_provenance_golden() -> None:
    """Golden was computed from the schema-1 model at f9897f; bytes are frozen."""
    record = ArtifactRevision(
        Scope("realm-golden", "project-golden"), "artifact-golden", "revision-golden",
        "2026-10-09T12:00:00.000000Z", ActorRef("author-golden", "human", "test-golden"),
        InlinePayload.from_value("application/json", "urn:test:artifact-golden",
                                 {"title": "Golden", "items": [1, 2]}),
    )
    assert record.body_digest.hex == "0a0e2a8da6065ed91abb0f6e4ba712ae39fa7f3e487e27a55654e0ddd82ac7c6"
    assert record.digest.hex == "fcef47d215fb92ed3d5e712fe005edff782d79846bb655ef9f0fbb93c1f49ead"
    golden = (b'{"artifact_id":"artifact-golden","body_digest":{"algorithm":"sha256","hex":"'
              b'0a0e2a8da6065ed91abb0f6e4ba712ae39fa7f3e487e27a55654e0ddd82ac7c6"},"created_at":"'
              b'2026-10-09T12:00:00.000000Z","created_by":{"actor_id":"author-golden","actor_kind":"human",'
              b'"issuer":"test-golden"},"digest":{"algorithm":"sha256","hex":"'
              b'fcef47d215fb92ed3d5e712fe005edff782d79846bb655ef9f0fbb93c1f49ead"},"parent_revision_refs":[],"payload":'
              b'{"inline_value":{"items":[1,2],"title":"Golden"},"media_type":"application/json",'
              b'"schema_id":"urn:test:artifact-golden"},"project_id":"project-golden","realm_id":"realm-golden",'
              b'"revision_id":"revision-golden","schema_version":1}')
    assert encode_revision(record) == golden
    assert decode_revision(golden) == record


@pytest.mark.parametrize("payload", [
    InlinePayload.from_value("application/json", "urn:test:inline", {"items": [1, 2]}),
    BlobPayload("application/json", "urn:test:blob", _blob()),
    MethodPayload(
        "application/json", "urn:test:method-content",
        MethodContent.from_value(
            ExactMethodResourceRef(MethodRef("method-1", "2.0", 1, _digest(b"method")),
                                   "schemas/input.json", _digest(b"resource"), "resource-1"),
            {"answer": 42}, _blob(b"rendered", locator="rendered-1"),
        ),
    ),
], ids=["inline", "blob", "method-content"])
def test_schema2_payload_union_roundtrips_with_all_provenance_fields(payload) -> None:
    method_refs = ()
    if type(payload) is MethodPayload:
        method_refs = (payload.content.schema_ref.method_ref,)
    record = _revision(payload, schema_version=2, method_refs=method_refs)
    wire = decode_json(encode_revision(record))
    assert set(wire) == {
        "schema_version", "realm_id", "project_id", "artifact_id", "revision_id", "created_at",
        "created_by", "payload", "body_digest", "parent_revision_refs", "digest", "sources", "claims",
        "evidence_links", "method_refs", "generation_origin",
    }
    assert wire["generation_origin"] is None
    assert decode_revision(encode_revision(record)) == record
    assert type(decode_payload(wire["payload"])) is type(payload)


def test_schema2_provenance_roundtrip_checks_evidence_membership_and_method_refs() -> None:
    # Claims select the payload's actual canonical content bytes (the Inline
    # envelope is not part of content_bytes()).
    raw = canonical_bytes({"value": "ok"})
    source = SourceRef(
        "source-1", "document", SourceLocator("document", provider="provider-1", document_id="doc-1"),
        VersionCapture("release-1", _digest(b"upstream")), CREATED_AT, ACTOR,
        "application/json", len(raw), "https://example.test/source",
    )
    claim = Claim("claim-1", ContentSelector("whole_capture"), _digest(raw))
    link = EvidenceLink(claim.claim_id, source, ContentSelector("whole_capture"),
                        "supports", "captured relation")
    method = MethodRef("method-1", "1.0", 1, _digest(b"method"))
    origin = GenerationOrigin("provider-1", "trace-1", None, "v1")
    record = _revision(schema_version=2, sources=(source,), claims=(claim,), evidence_links=(link,),
                       method_refs=(method,), generation_origin=origin)
    decoded = decode_revision(encode_revision(record))
    assert decoded.sources == (source,)
    assert decoded.claims == (claim,)
    assert decoded.evidence_links == (link,)
    assert decoded.method_refs == (method,)
    assert decoded.generation_origin == origin
    fields = decode_provenance_fields({key: decode_json(encode_revision(record))[key] for key in (
        "sources", "claims", "evidence_links", "method_refs", "generation_origin")})
    assert fields == {"sources": (source,), "claims": (claim,), "evidence_links": (link,),
                      "method_refs": (method,), "generation_origin": origin}

    bad = decode_json(encode_revision(record))
    bad["evidence_links"][0]["claim_id"] = "missing-claim"
    _reject(lambda: decode_revision(canonical_bytes(bad)))
    wrong_digest = replace(claim, statement_digest=_digest(b"not the payload content"))
    _reject(lambda: _revision(schema_version=2, claims=(wrong_digest,)), "STATEMENT_DIGEST_MISMATCH")


def test_locator_is_wire_data_but_not_nested_blob_identity() -> None:
    captured = b"provenance capture"
    source_for = lambda locator: SourceRef(
        "source-1", "document", SourceLocator("document", provider="provider-1", document_id="doc-1"),
        ExcerptCapture(_blob(captured, locator=locator), _digest(captured), ContentSelector("whole_capture")),
        CREATED_AT, ACTOR, "application/json", len(captured),
    )
    first = _revision(BlobPayload("application/json", "urn:test:blob", _blob(locator="object-one")),
                      schema_version=2, sources=(source_for("capture-one"),))
    second = _revision(BlobPayload("application/json", "urn:test:blob", _blob(locator="object-two")),
                       schema_version=2, sources=(source_for("capture-two"),))
    assert first.body_digest == second.body_digest
    assert first.digest == second.digest
    first_wire = encode_revision(first)
    second_wire = encode_revision(second)
    assert first_wire != second_wire
    assert b'"storage_object_id":"object-one"' in first_wire
    assert b'"storage_object_id":"object-two"' in second_wire
    assert b'"storage_object_id":"capture-one"' in first_wire
    assert b'"storage_object_id":"capture-two"' in second_wire


@pytest.mark.parametrize("shape", ["revision", "payload", "actor", "bool-version"])
def test_revision_unknown_fields_and_versions_are_rejected(shape) -> None:
    wire = decode_json(encode_revision(_revision(schema_version=2)))
    if shape == "revision":
        wire["extra"] = True
    elif shape == "payload":
        wire["payload"]["extra"] = True
    elif shape == "actor":
        wire["created_by"]["extra"] = True
    else:
        wire["schema_version"] = True
    _reject(lambda: decode_revision(canonical_bytes(wire)))


def test_nested_closed_shapes_selector_booleans_and_method_content_tag() -> None:
    wire = decode_json(encode_revision(_revision(schema_version=2)))
    wire["sources"] = [{"source_id": "s", "extra": "unknown"}]
    _reject(lambda: decode_revision(canonical_bytes(wire)))
    _reject(lambda: decode_payload({"media_type": "application/json", "schema_id": "x",
                                   "content_kind": "method_content", "inline_value": {
                                       "schema_ref": {}, "value": {}, "rendered_body_ref": None,
                                       "extra": 1}}))
    _reject(lambda: decode_payload({"media_type": "application/json", "schema_id": "x",
                                   "content_kind": "unknown", "inline_value": {}}))
    _reject(lambda: decode_provenance_fields({"sources": [], "claims": [], "evidence_links": [],
                                               "method_refs": [], "generation_origin": None, "extra": 1}))

    invalid = decode_json(encode_revision(_revision(schema_version=2)))
    invalid["claims"] = [{"claim_id": "c", "selector": {
        "kind": "byte_range", "start": True, "end": 1, "pointer": None, "schema_version": 1,
    }, "statement_digest": asdict_digest(_digest(b"x"))}]
    _reject(lambda: decode_revision(canonical_bytes(invalid)))


def test_method_resource_requires_closed_nonempty_resource_id() -> None:
    method_payload = MethodPayload(
        "application/json", "urn:test:method-content",
        MethodContent.from_value(
            ExactMethodResourceRef(MethodRef("method-1", "1.0", 1, _digest(b"method")),
                                   "schemas/output.json", _digest(b"resource"), "resource-1"),
            {"output": True},
        ),
    )
    wire = method_payload.projection()
    del wire["inline_value"]["schema_ref"]["resource_id"]
    _reject(lambda: decode_payload(wire), "INVALID_METHOD_RESOURCE")

    wire = method_payload.projection()
    wire["inline_value"]["schema_ref"]["resource_id"] = ""
    _reject(lambda: decode_payload(wire), "INVALID_METHOD_RESOURCE")


def asdict_digest(digest: Digest) -> dict:
    return {"algorithm": digest.algorithm, "hex": digest.hex}


def test_digest_tampering_and_schema1_non_inline_payload_are_rejected() -> None:
    wire = decode_json(encode_revision(_revision()))
    wire["body_digest"]["hex"] = "0" * 64
    _reject(lambda: decode_revision(canonical_bytes(wire)), "REVISION_DIGEST_MISMATCH")

    schema1 = decode_json(encode_revision(_revision()))
    schema1["payload"] = BlobPayload("application/json", "urn:test:blob", _blob()).projection()
    # A schema-1 record cannot silently opt into a newer payload encoding.
    _reject(lambda: decode_revision(canonical_bytes(schema1)))


def test_historical_parent_count_keeps_original_byte_bound_without_new_v2_limit():
    parents = tuple(ArtifactRevisionRef('realm-golden', 'project-golden', 'artifact-golden',
        f'parent-{i}', Digest('sha256', f'{i:064x}')) for i in range(4097))
    record = ArtifactRevision(Scope('realm-golden', 'project-golden'), 'artifact-golden',
        'revision-golden', '2026-10-09T12:00:00.000000Z',
        ActorRef('author-golden', 'human', 'test-golden'),
        InlinePayload.from_value('application/json', 'urn:test:artifact-golden', {'v': 1}),
        parents, schema_version=1)
    assert len(encode_revision(record)) < MAX_RECORD_BYTES
    # Independently reproduced using the preceding preserved installed wheel.
    assert hashlib.sha256(encode_revision(record)).hexdigest() == '2ae8ae1c030f0a7d886b37973035abb2a05ebdbe0255ea1b71242f8abc73209e'
    assert record.digest.hex == 'e59a316896d1196fd932675f8e2d80f712a8b192b2d747b0831644f403bc91eb'
    assert decode_revision(encode_revision(record)) == record
    _reject(lambda: ArtifactRevision(record.scope, record.artifact_id, record.revision_id,
        record.created_at, record.created_by, record.payload, parents, schema_version=2), 'INVALID_PARENT')
