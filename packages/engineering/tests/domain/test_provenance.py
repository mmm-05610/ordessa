"""Closed provenance values and byte selectors; no support or authority grant."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.artifacts.models import (
    ArtifactRevision, InlinePayload, MethodContent, MethodPayload,
)
from ordessa_engineering.domain.artifacts.provenance import (Claim, ClaimRef, EvidenceLink, ExcerptCapture, GenerationOrigin, SourceLocator, SourceRef, VersionCapture)
from ordessa_engineering.domain.common.models.selection import (ContentSelector)
from ordessa_engineering.domain.artifacts.method_binding import (ExactMethodResourceRef)
from ordessa_engineering.domain.common.mechanisms.codec import (projection)
from ordessa_engineering.domain.common.mechanisms.selection import (select_bytes, verify_selection)
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.common.models.values import (Digest, normalized_path)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.common.models.identity import (ActorRef)


SCOPE = Scope("realm-provenance", "project-provenance")
ACTOR = ActorRef("capturer-1", "human", "synthetic-provenance-test")
CAPTURED_AT = "2026-10-09T12:00:00.000000Z"
ARTIFACT_REF = ArtifactRevisionRef(
    SCOPE.realm_id, SCOPE.project_id, "artifact-1", "revision-1", Digest("sha256", "a" * 64),
)


def _digest(raw: bytes) -> Digest:
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


def _blob(raw: bytes = b"captured bytes", *, media_type: str = "application/json",
          storage_object_id: str = "blob-object-1") -> BlobRef:
    return BlobRef(_digest(raw), len(raw), media_type, storage_object_id)


def _source(*, blob: BlobRef | None = None, locator: SourceLocator | None = None,
            capture=None, media_type: str | None = None, byte_length: int | None = None,
            original_url: str | None = None, captured_by=ACTOR, captured_at=CAPTURED_AT) -> SourceRef:
    selected_blob = blob or _blob()
    selected_capture = capture or ExcerptCapture(
        selected_blob, selected_blob.digest, ContentSelector("whole_capture"), "upstream-v1",
    )
    return SourceRef(
        "source-1", (locator or SourceLocator("document", provider="provider-1", document_id="document-1")).kind,
        locator or SourceLocator("document", provider="provider-1", document_id="document-1"),
        selected_capture, captured_at, captured_by,
        media_type or selected_blob.media_type, byte_length if byte_length is not None else selected_blob.byte_length,
        original_url,
    )


def _reject(call, code: str) -> None:
    with pytest.raises(ReferenceError) as caught:
        call()
    assert caught.value.code == code


def test_whole_capture_and_byte_range_select_real_bytes_and_verify_hashes() -> None:
    raw = b"0123456789"
    whole = ContentSelector("whole_capture")
    byte_range = ContentSelector("byte_range", start=2, end=7)
    assert select_bytes(raw, whole) == raw
    assert verify_selection(raw, whole, _digest(raw)) == raw
    assert select_bytes(raw, byte_range) == b"23456"
    assert verify_selection(raw, byte_range, _digest(b"23456")) == b"23456"
    _reject(lambda: verify_selection(raw, byte_range, _digest(b"wrong")), "STATEMENT_DIGEST_MISMATCH")
    _reject(lambda: select_bytes(raw, ContentSelector("byte_range", start=2, end=11)),
            "SELECTOR_OUT_OF_RANGE")


def test_json_pointer_handles_rfc_escaping_and_canonical_array_indices() -> None:
    from ordessa_infrastructure.encoding import canonical_bytes

    raw = canonical_bytes({"a/b": {"~key": [{"value": "selected"}, {"value": "other"}]}})
    pointer = ContentSelector("json_pointer", pointer="/a~1b/~0key/0/value")
    selected = canonical_bytes("selected")
    assert select_bytes(raw, pointer) == selected
    assert verify_selection(raw, pointer, _digest(selected)) == selected

    _reject(lambda: select_bytes(raw, ContentSelector("json_pointer", pointer="/a~1b/~0key/01")),
            "SELECTOR_OUT_OF_RANGE")
    _reject(lambda: select_bytes(raw, ContentSelector("json_pointer", pointer="/a~1b/~0key/9")),
            "SELECTOR_OUT_OF_RANGE")
    _reject(lambda: select_bytes(raw, ContentSelector("json_pointer", pointer="/missing")),
            "SELECTOR_OUT_OF_RANGE")
    _reject(lambda: select_bytes(b"not-json", ContentSelector("json_pointer", pointer="/x")),
            "SELECTOR_OUT_OF_RANGE")


@pytest.mark.parametrize(
    "selector",
    (
        lambda: ContentSelector("whole_capture", start=0),
        lambda: ContentSelector("byte_range", start=True, end=2),
        lambda: ContentSelector("byte_range", start=0, end=1.0),
        lambda: ContentSelector("byte_range", start=0, end=16 * 1024 * 1024 + 1),
        lambda: ContentSelector("json_pointer", pointer="/bad~2escape"),
        lambda: ContentSelector("json_pointer", pointer="relative/path"),
        lambda: ContentSelector("whole_capture", schema_version=2),
        lambda: ContentSelector("whole_capture", schema_version=True),
        lambda: ContentSelector("unknown_selector"),
    ),
    ids=("whole-with-range", "boolean-offset", "float-offset", "range-over-limit",
         "bad-tilde-escape", "non-pointer", "future-version", "boolean-version", "unknown-kind"),
)
def test_selector_shapes_versions_and_integer_types_are_closed(selector) -> None:
    _reject(selector, "INVALID_SELECTOR")


def test_selector_rejects_nonbytes_and_nonjson_values() -> None:
    _reject(lambda: select_bytes("text", ContentSelector("whole_capture")), "INVALID_SELECTOR")
    _reject(lambda: select_bytes(b"{\"x\":1.5}", ContentSelector("json_pointer", pointer="/x")),
            "SELECTOR_OUT_OF_RANGE")


def test_source_locator_supports_exactly_six_closed_shapes() -> None:
    locators = (
        SourceLocator("chat_message", provider="chat", conversation_id="conversation-1", message_id="message-1"),
        SourceLocator("agents_file", repository_id="repo-1", path="agents/AGENTS.md"),
        SourceLocator("code", repository_id="repo-1", path="packages/core/module.py"),
        SourceLocator("document", provider="drive", document_id="document-1"),
        SourceLocator("artifact", artifact_ref=ARTIFACT_REF),
        SourceLocator("tool_observation", provider="tool-1", observation_id="observation-1"),
    )
    assert tuple(item.kind for item in locators) == (
        "chat_message", "agents_file", "code", "document", "artifact", "tool_observation",
    )

    _reject(lambda: SourceLocator("chat_message", provider="chat", conversation_id="c",
                                  message_id="m", path="extra"), "INVALID_SOURCE_LOCATOR")
    _reject(lambda: SourceLocator("document", provider="drive"), "INVALID_SOURCE_LOCATOR")
    _reject(lambda: SourceLocator("unknown"), "INVALID_SOURCE_LOCATOR")


@pytest.mark.parametrize("path", ("/absolute/file", "../escape", "a/../b", "a//b", "a/./b", "a\\b", "C:/file"))
def test_source_paths_are_normalized_and_cannot_escape(path: str) -> None:
    _reject(lambda: normalized_path(path), "INVALID_PATH")
    _reject(lambda: SourceLocator("code", repository_id="repo-1", path=path), "INVALID_PATH")


def test_source_capture_ref_length_media_actor_time_and_url_are_checked() -> None:
    blob = _blob(b"part", media_type="text/plain")
    selector = ContentSelector("byte_range", start=0, end=4)
    capture = ExcerptCapture(blob, _digest(b"part"), selector, "release-2")
    source = _source(blob=blob, capture=capture, media_type="text/plain", byte_length=blob.byte_length,
                     original_url="https://example.test/path?q=1")
    assert source.capture == capture
    assert VersionCapture("release-2", _digest(b"upstream" )).kind == "immutable_version"
    version_capture = VersionCapture("version-1", _digest(b"upstream"))
    assert len(_source(capture=version_capture, media_type="x" * 256).media_type) == 256

    _reject(lambda: _source(blob=blob, capture=capture, media_type="application/json"), "INVALID_SOURCE")
    _reject(lambda: _source(blob=blob, capture=capture, byte_length=blob.byte_length + 1), "INVALID_SOURCE")
    _reject(lambda: _source(capture=version_capture, media_type="x" * 257), "INVALID_SOURCE")
    _reject(lambda: ExcerptCapture(blob, _digest(b"x"), object()), "INVALID_SOURCE_CAPTURE")
    _reject(lambda: VersionCapture("release-2", object()), "INVALID_SOURCE_CAPTURE")
    _reject(lambda: replace(source, kind="code"), "INVALID_SOURCE")
    _reject(lambda: _source(captured_by=object()), "INVALID_SOURCE")
    _reject(lambda: _source(captured_at="2026-10-09 12:00:00Z"), "INVALID_TIME")
    _reject(lambda: _source(original_url="https://user:secret@example.test/path"), "INVALID_SOURCE_URL")
    _reject(lambda: _source(original_url="file:///private/file"), "INVALID_SOURCE_URL")


def test_claims_links_and_relations_are_typed_and_finite() -> None:
    raw = b"claim statement"
    selector = ContentSelector("byte_range", start=0, end=len(raw))
    statement_digest = _digest(raw)
    claim = Claim("claim-1", selector, statement_digest)
    claim_ref = ClaimRef(ARTIFACT_REF, claim.claim_id, claim.statement_digest)
    source = _source()
    assert claim_ref.owner_revision_ref == ARTIFACT_REF

    for relation in ("supports", "contradicts", "context"):
        link = EvidenceLink(claim.claim_id, source, ContentSelector("whole_capture"), relation,
                            "relation recorded for review")
        assert link.relation == relation
        assert "authorized" not in asdict(link)
    _reject(lambda: EvidenceLink("claim-1", source, selector, "proves", "not an allowed relation"),
            "INVALID_EVIDENCE_LINK")
    _reject(lambda: EvidenceLink("claim-1", source, selector, "supports", ""), "INVALID_EVIDENCE_LINK")
    _reject(lambda: ClaimRef(object(), "claim-1", statement_digest), "INVALID_CLAIM")


def test_exact_method_resource_and_generation_origin_shapes() -> None:
    method = MethodRef("method-1", "1.0.0", 1, _digest(b"method"))
    resource = ExactMethodResourceRef(
        method, "skills/review/SKILL.md", _digest(b"resource"), "skill-resource-1",
    )
    assert resource.logical_path == "skills/review/SKILL.md"
    assert GenerationOrigin("generator", "trace-1", None, "v1").trace_id == "trace-1"
    assert GenerationOrigin("generator", None, "execution-1", "v1").execution_id == "execution-1"
    _reject(lambda: ExactMethodResourceRef(method, "../outside", _digest(b"resource"), "resource-1"),
            "INVALID_PATH")
    _reject(lambda: ExactMethodResourceRef(method, "schemas/output.json", _digest(b"schema"), ""),
            "INVALID_METHOD_RESOURCE")
    _reject(lambda: GenerationOrigin("generator", None, None, "v1"), "INVALID_GENERATION_ORIGIN")


def test_identity_projection_omits_nested_blob_locator_but_wire_keeps_it() -> None:
    source = _source()
    moved_blob = replace(source.capture.blob_ref, storage_object_id="blob-object-moved")
    moved_capture = replace(source.capture, blob_ref=moved_blob)
    moved_source = replace(source, capture=moved_capture)

    wire = projection(source)
    moved_wire = projection(moved_source)
    identity = projection(source, identity=True)
    moved_identity = projection(moved_source, identity=True)
    assert wire["capture"]["blob_ref"]["storage_object_id"] == "blob-object-1"
    assert moved_wire["capture"]["blob_ref"]["storage_object_id"] == "blob-object-moved"
    assert wire != moved_wire
    assert identity == moved_identity
    assert "storage_object_id" not in identity["capture"]["blob_ref"]


def test_source_presence_and_evidence_links_record_provenance_without_authorizing_claims() -> None:
    source = _source()
    claim = Claim("claim-1", ContentSelector("whole_capture"), _digest(b"statement"))
    link = EvidenceLink(claim.claim_id, source, ContentSelector("whole_capture"),
                        "supports", "synthetic asserted relationship")
    assert source.source_id == link.source_ref.source_id
    assert link.relation == "supports"
    # These are provenance facts/annotations only. No adjudication or permission
    # result is created by a source existing or by the selected relation label.
    assert "authorized" not in asdict(link)
    assert not hasattr(link, "decision")
    assert claim.statement_digest == _digest(b"statement")


def test_artifact_revision_schema2_consumes_claim_source_and_evidence_link_values() -> None:
    payload = InlinePayload.from_value(
        "application/json", "urn:test:artifact-claim", {"assertion": "accepted"},
    )
    claim_selector = ContentSelector("json_pointer", pointer="/assertion")
    selected = select_bytes(payload.content_bytes(), claim_selector)
    claim = Claim("claim-1", claim_selector, _digest(selected))
    source = _source()
    evidence_link = EvidenceLink(
        claim.claim_id, source, ContentSelector("whole_capture"), "supports", "captured relation",
    )
    method_ref = MethodRef("method-1", "1.0.0", 1, _digest(b"method"))
    revision = ArtifactRevision(
        SCOPE, "artifact-with-provenance", "revision-1", CAPTURED_AT, ACTOR, payload,
        schema_version=2, sources=(source,), claims=(claim,), evidence_links=(evidence_link,),
        method_refs=(method_ref,), generation_origin=GenerationOrigin("generator-1", "trace-1", None, "v1"),
    )
    assert revision.sources == (source,)
    assert revision.claims == (claim,)
    assert revision.evidence_links == (evidence_link,)
    assert revision.method_refs == (method_ref,)
    assert revision.generation_origin.trace_id == "trace-1"
    assert "authorized" not in revision.projection()

    bad_claim = Claim("claim-1", claim_selector, _digest(canonical_bytes("different")))
    with pytest.raises(ReferenceError) as mismatch:
        ArtifactRevision(
            SCOPE, "artifact-with-provenance", "revision-bad-claim", CAPTURED_AT, ACTOR, payload,
            schema_version=2, claims=(bad_claim,),
        )
    assert mismatch.value.code == "STATEMENT_DIGEST_MISMATCH"

    unresolved_link = replace(evidence_link, claim_id="missing-claim")
    with pytest.raises(ReferenceError) as unresolved:
        ArtifactRevision(
            SCOPE, "artifact-with-provenance", "revision-bad-link", CAPTURED_AT, ACTOR, payload,
            schema_version=2, sources=(source,), claims=(claim,), evidence_links=(unresolved_link,),
        )
    assert unresolved.value.code == "UNRESOLVED_EVIDENCE_LINK"

    with pytest.raises(ReferenceError) as legacy_provenance:
        ArtifactRevision(
            SCOPE, "artifact-with-provenance", "revision-v1-source", CAPTURED_AT, ACTOR, payload,
            schema_version=1, sources=(source,),
        )
    assert legacy_provenance.value.code == "INVALID_REVISION"


def test_artifact_revision_identity_ignores_nested_blob_locators_but_wire_keeps_them() -> None:
    payload = InlinePayload.from_value("application/json", "urn:test:identity", {"x": 1})
    source = _source()
    link = EvidenceLink("claim-1", source, ContentSelector("whole_capture"),
                        "context", "source locator identity fixture")
    source_revision = ArtifactRevision(
        SCOPE, "artifact-source-identity", "source-revision", CAPTURED_AT, ACTOR, payload,
        schema_version=2, sources=(source,), claims=(Claim("claim-1", ContentSelector("whole_capture"),
        _digest(payload.content_bytes())),), evidence_links=(link,),
    )
    moved_source = replace(source, capture=replace(
        source.capture, blob_ref=replace(source.capture.blob_ref, storage_object_id="moved-source-blob"),
    ))
    moved_link = replace(link, source_ref=moved_source)
    moved_revision = ArtifactRevision(
        SCOPE, "artifact-source-identity", "source-revision", CAPTURED_AT, ACTOR, payload,
        schema_version=2, sources=(moved_source,), claims=source_revision.claims,
        evidence_links=(moved_link,),
    )
    assert moved_revision.digest == source_revision.digest
    assert moved_revision.projection() != source_revision.projection()
    assert (moved_revision.projection()["sources"][0]["capture"]["blob_ref"]["storage_object_id"]
            == "moved-source-blob")

    method_ref = MethodRef("method-render", "2.0.0", 1, _digest(b"method-render"))
    resource_ref = ExactMethodResourceRef(
        method_ref, "schemas/output.json", _digest(b"schema"), "schema-resource-1",
    )
    rendered = _blob(b"rendered body", media_type="text/markdown")
    content = MethodContent.from_value(resource_ref, {"output": "value"}, rendered_body_ref=rendered)
    method_payload = MethodPayload("application/json", "urn:test:method-content", content)
    method_revision = ArtifactRevision(
        SCOPE, "artifact-method-identity", "method-revision", CAPTURED_AT, ACTOR, method_payload,
        schema_version=2, method_refs=(method_ref,),
    )
    moved_content = replace(content, rendered_body_ref=replace(rendered, storage_object_id="moved-rendered"))
    moved_method_revision = ArtifactRevision(
        SCOPE, "artifact-method-identity", "method-revision", CAPTURED_AT, ACTOR,
        replace(method_payload, content=moved_content), schema_version=2, method_refs=(method_ref,),
    )
    assert moved_method_revision.digest == method_revision.digest
    assert moved_method_revision.projection() != method_revision.projection()
    assert (moved_method_revision.projection()["payload"]["inline_value"]["rendered_body_ref"]
            ["storage_object_id"] == "moved-rendered")
