"""Host-owned package pins and byte provenance for declared generation."""
import hashlib
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.steps.declared_generation_dispatch import (
    DeclaredGenerationDispatch)
from ordessa_engineering.application.orchestration.steps.declared_generation_port import (
    DeclaredGenerationPort, _OUTPUT_CONTRACT, _prompt)
from ordessa_engineering.application.contracts.declared_generation import REQUIRED_MATERIALS
from ordessa_engineering.domain.artifacts.method_binding import (
    ExactMethodResourceRef, MethodRef)
from ordessa_engineering.domain.artifacts.provenance import (
    SourceLocator, SourceRef, VersionCapture)
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_infrastructure.encoding import canonical_bytes


SCOPE = Scope("generation-scope", "generation-project")
ACTOR = ActorRef("generation-owner", "human", "controlled-local-caller")
NOW = "2026-10-17T00:00:00.000000Z"


def _source(source_id, version, body):
    return SourceRef(
        source_id, "document",
        SourceLocator("document", provider="project-files", document_id="reviewed-document"),
        VersionCapture(version, Digest("sha256", hashlib.sha256(body).hexdigest())),
        NOW, ACTOR, "text/markdown", len(body))


def _pins():
    baseline = _source("baseline-source", "baseline-v1", b"baseline")
    candidate = _source("candidate-source", "candidate-v1", b"candidate")
    method = MethodRef("incremental-engineering", "2.7.2", 1,
                       Digest("sha256", "a" * 64))
    resources = (ExactMethodResourceRef(
        method, "criteria/change-review.md", Digest("sha256", "b" * 64),
        "change-review-criteria"),)
    change = ProposalRef(SCOPE.realm_id, SCOPE.project_id, "change-a", "proposal-a",
                         Digest("sha256", "c" * 64))
    review = ReviewRef(SCOPE.realm_id, SCOPE.project_id, "review-a",
                       Digest("sha256", "d" * 64))
    return baseline, candidate, method, resources, change, review


def _context():
    return SimpleNamespace(scope=SCOPE, received_at=NOW, authenticated_actor=ACTOR)


def _output():
    return {
        "contract_version": _OUTPUT_CONTRACT,
        "package_id": "package-generated",
        "document_contents": {
            "spec": "# Spec\nExact UTF-8 bytes: café.\n",
            "plan": "# Plan\nFollow the admitted change.\n",
            "tasks": "# Tasks\n- [ ] Verify the package.\n",
        },
    }


def test_host_builds_package_pins_and_source_capture_from_exact_returned_bytes():
    baseline, candidate, method, resources, change, review = _pins()
    output = _output()
    package, document_bytes = DeclaredGenerationPort._decode_output(
        canonical_bytes(output).decode("utf-8"), _context(), change_ref=change,
        review_ref=review, method_ref=method, method_resource_refs=resources,
        baseline=baseline, candidate=candidate)

    assert package.payload.baseline == baseline
    assert package.payload.candidate == candidate
    assert package.payload.change_ref == change
    assert package.payload.review_refs == (review,)
    assert package.payload.method_ref == method
    assert package.payload.method_resource_refs == resources
    assert set(document_bytes) == {"spec", "plan", "tasks"}
    for document in package.payload.documents:
        raw = output["document_contents"][document.role].encode("utf-8")
        source = document.source_ref
        assert document_bytes[document.role] == raw
        assert source.source_id == f"package-generated-{document.role}"
        assert source.locator.provider == "ordessa-engineering"
        assert source.locator.document_id == f"package-generated/{document.role}.md"
        assert source.capture.upstream_version == f"package-generated-{document.role}-v1"
        assert source.capture.content_digest == Digest(
            "sha256", hashlib.sha256(raw).hexdigest())
        assert source.byte_length == len(raw)
        assert source.captured_at == NOW
        assert source.captured_by == ACTOR


def test_legacy_or_forged_subject_and_provenance_envelopes_are_rejected():
    baseline, candidate, method, resources, change, review = _pins()
    forged = _output()
    forged["payload"] = {
        "change_ref": {"proposal_id": "other-proposal"},
        "documents": [{"role": "spec", "source_ref": {"capture": {"content_digest":
                       {"algorithm": "sha256", "hex": "0" * 64}}}}],
    }
    with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_OUTPUT_INVALID"):
        DeclaredGenerationPort._decode_output(
            canonical_bytes(forged).decode("utf-8"), _context(), change_ref=change,
            review_ref=review, method_ref=method, method_resource_refs=resources,
            baseline=baseline, candidate=candidate)

    malformed = _output()
    malformed["document_contents"]["spec"] = {"text": "not a document string"}
    with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_OUTPUT_INVALID"):
        DeclaredGenerationPort._decode_output(
            canonical_bytes(malformed).decode("utf-8"), _context(), change_ref=change,
            review_ref=review, method_ref=method, method_resource_refs=resources,
            baseline=baseline, candidate=candidate)


def test_prompt_requires_direct_versioned_json_and_limits_optional_files():
    baseline, candidate, method, resources, change, review = _pins()
    qualified = {
        "qualified_inputs": {
            "baseline": asdict(baseline),
            "candidate": asdict(candidate),
            "scope": {"realm_id": SCOPE.realm_id, "project_id": SCOPE.project_id},
        },
        "admitted": True,
        "verdict": "pass",
    }
    params, _, _ = _prompt(
        qualified, {name: ("released:" + name).encode()
                    for name in REQUIRED_MATERIALS}, change, review, method, resources,
        received_at=NOW, authenticated_actor=ACTOR,
        source_texts={"baseline": {"content": "baseline"},
                      "candidate": {"content": "candidate"}},
        review_material={"review": "admitted"})
    text = params["prompt"][0]["text"]
    assert _OUTPUT_CONTRACT in text
    assert '"spec"' in text and '"plan"' in text and '"tasks"' in text
    assert "Do not call any tool or create files." in text
    assert "Do not use execute, shell, or system temporary paths." in text
    assert "No tool is required" in text
    assert "source references, digests, or byte lengths" in text


def test_generation_timeout_is_finite_and_bounded():
    factory, access, blobs, execution = object(), object(), object(), object()
    dispatch = DeclaredGenerationDispatch(
        factory, access, blobs=blobs, execution=execution,
        review_admission=object(), method_guard=object())
    common = dict(
        blobs=blobs, execution=execution, unit_ref_resolver=lambda *_: {},
        dispatch=dispatch, validation=lambda *_: None,
        source_materials=SimpleNamespace(factory=factory, read=lambda *_: b""))

    assert DeclaredGenerationPort(
        factory, access, **common, generation_timeout=240).generation_timeout == 240
    assert DeclaredGenerationPort(
        factory, access, **common, generation_timeout=1800).generation_timeout == 1800
    for invalid in (0, -1, 1800.1, float("inf"), True):
        with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_TRANSPORT_UNAVAILABLE"):
            DeclaredGenerationPort(factory, access, **common, generation_timeout=invalid)
