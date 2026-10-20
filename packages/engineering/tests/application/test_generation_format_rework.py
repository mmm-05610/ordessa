"""A syntax-only rework must retain the prior completed generation lineage."""
import hashlib
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.orchestration.steps.declared_generation_port import (
    DeclaredGenerationPort,
    _OUTPUT_CONTRACT,
    _prompt,
)
from ordessa_engineering.application.contracts.declared_generation import REQUIRED_MATERIALS
from ordessa_engineering.application.orchestration.steps.generation_format_rework import (
    prepare_format_rework,
    verify_prior_native_receipt,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
from ordessa_engineering.domain.artifacts.method_binding import (
    ExactMethodResourceRef,
    MethodRef,
)
from ordessa_engineering.domain.artifacts.provenance import SourceLocator, SourceRef, VersionCapture
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.refs import ReviewRef


SCOPE = Scope("format-rework-realm", "format-rework-project")
ACTOR = ActorRef("format-rework-actor", "human", "controlled-test")
OLD_WORK = "prior-format-work"
NEW_WORK = "new-format-work"
ACTION = "incremental.prepare-packages"
STEP = "draft"
DISPATCH_KEY = work_dispatch_key(OLD_WORK, ACTION, STEP)
OPERATION_REF = "prior-format-operation"
NOW = "2026-10-17T00:00:00.000000Z"
SESSION_ID = "prior-format-session"
PRIOR_PARAMS = {
    "sessionId": SESSION_ID,
    "prompt": [{"type": "text", "text": "the original completed request"}],
}


def _native_digest(value):
    return "sha256:" + hashlib.sha256(canonical_bytes({"value": value})).hexdigest()


def _unit_ref():
    return {
        "environmentNamespace": "format-rework-environment",
        "unitId": "prior-format-unit",
        "ownerProviderRef": {"provider": "controlled-local"},
        "sourceRevision": "format-rework-revision",
    }


def _source(source_id, body):
    return SourceRef(
        source_id,
        "document",
        SourceLocator("document", provider="project-files", document_id="reviewed-document"),
        VersionCapture("v1", Digest("sha256", hashlib.sha256(body).hexdigest())),
        NOW,
        ACTOR,
        "text/markdown",
        len(body),
    )


def _pins():
    baseline = _source("baseline", b"baseline source\n")
    candidate = _source("candidate", b"candidate source\n")
    method = MethodRef("incremental-engineering", "2.7.2", 1, Digest("sha256", "a" * 64))
    method_resources = (
        ExactMethodResourceRef(
            method,
            "criteria/change-review.md",
            Digest("sha256", "b" * 64),
            "change-review-criteria",
        ),
    )
    change = ProposalRef(
        SCOPE.realm_id,
        SCOPE.project_id,
        "change-format-rework",
        "proposal-format-rework",
        Digest("sha256", "c" * 64),
    )
    review = ReviewRef(
        SCOPE.realm_id,
        SCOPE.project_id,
        "review-format-rework",
        Digest("sha256", "d" * 64),
    )
    return baseline, candidate, method, method_resources, change, review


def _output(*, package_id="format-rework-package", documents=None):
    return {
        "contract_version": _OUTPUT_CONTRACT,
        "package_id": package_id,
        "document_contents": documents or {
            "spec": "# Specification\nThe exact prior body.\n",
            "plan": "# Plan\nThe exact prior plan.\n",
            "tasks": "# Tasks\n- [ ] Preserve all three bodies.\n",
        },
    }


def _prior_binding_and_outcome(raw_text, params=PRIOR_PARAMS):
    baseline, candidate, method, _resources, change, review = _pins()
    prompt_bytes = canonical_bytes({"prompt": "the original completed attempt"})
    prompt_ref = BlobRef(
        Digest("sha256", hashlib.sha256(prompt_bytes).hexdigest()),
        len(prompt_bytes),
        "application/json",
        "prior-format-prompt",
    )
    unit_ref = _unit_ref()
    inputs = {"unitRef": unit_ref, "params": params}
    binding = DispatchBinding(
        SCOPE,
        DISPATCH_KEY,
        STEP,
        1,
        1,
        None,
        None,
        None,
        None,
        (("generate_package", "prior-generation-instance"),),
        canonical_bytes(unit_ref),
        OPERATION_REF,
        prompt_ref,
        Digest("sha256", _native_digest(inputs).removeprefix("sha256:")),
        "format-rework-query",
        ("submission",),
        binding_version=2,
        work={
            "work_id": OLD_WORK,
            "action_id": ACTION,
            "step_id": STEP,
            "dispatch_key": DISPATCH_KEY,
        },
        subject={
            "subject_kind": "reviewed_change",
            "subject_ref": {
                "review_ref": asdict(review),
                "change_ref": asdict(change),
                "method_ref": asdict(method),
                "inputs_digest": asdict(Digest("sha256", "f" * 64)),
            },
        },
    )
    binding_bytes = encode_dispatch(binding)
    result_ref = BlobRef(
        Digest("sha256", hashlib.sha256(b"captured native receipt").hexdigest()),
        len(b"captured native receipt"),
        "application/json",
        "prior-format-result",
    )
    outcome = {
        "identity": DISPATCH_KEY,
        "step_id": STEP,
        "attempt": 1,
        "phase": "completed",
        "binding_digest": asdict(binding.digest),
        "binding_bytes": binding_bytes,
        "result_blob_ref": asdict(result_ref),
        "already_dispatched": True,
    }
    return binding, outcome


def _decode_output(text):
    baseline, candidate, method, resources, change, review = _pins()
    return DeclaredGenerationPort._decode_output(
        text,
        SimpleNamespace(scope=SCOPE, received_at=NOW, authenticated_actor=ACTOR),
        change_ref=change,
        review_ref=review,
        method_ref=method,
        method_resource_refs=resources,
        baseline=baseline,
        candidate=candidate,
    )


def _selector(raw_text, *, digest=None):
    raw_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return {
        "target_work_id": NEW_WORK,
        "prior_operation_ref": OPERATION_REF,
        "raw_text_digest": "sha256:" + (digest or raw_digest),
    }


def _prepare(raw_text, *, selector=None):
    binding, outcome = _prior_binding_and_outcome(raw_text)
    return prepare_format_rework(
        raw_text,
        outcome,
        binding,
        selector or _selector(raw_text),
        NEW_WORK,
        _decode_output,
    )


def test_format_rework_records_exact_prior_text_patch_and_lineage():
    raw_text = canonical_bytes(_output()).decode("utf-8") + "}"
    rework = _prepare(raw_text)

    material = rework.prompt_material()
    prior = material["prior"]
    assert prior["work"]["work_id"] == OLD_WORK
    assert prior["operation_ref"] == OPERATION_REF
    assert prior["dispatch_identity"] == DISPATCH_KEY
    assert prior["unit_ref"]["unitId"] == "prior-format-unit"
    assert prior["subject"]["subject_ref"]["review_ref"] == asdict(_pins()[-1])
    assert material["raw_text"] == raw_text
    assert material["raw_text_digest"] == "sha256:" + hashlib.sha256(
        raw_text.encode("utf-8")).hexdigest()
    assert material["exact_patch"] == {
        "operation": "delete",
        "byte_offset": len(raw_text.encode("utf-8")) - 1,
        "removed_hex": "7d",
        "inserted_hex": "",
    }
    repaired = raw_text[:-1]
    expected_object = decode_json(repaired)
    assert material["response_object"] == expected_object
    assert material["response_object"]["document_contents"] == _output()["document_contents"]
    assert material["expected_patched_text_digest"] == "sha256:" + hashlib.sha256(
        repaired.encode("utf-8")).hexdigest()
    expected, expected_bytes = _decode_output(repaired)
    assert material["expected_package_id"] == expected.package_id
    assert material["expected_document_digests"] == {
        role: "sha256:" + hashlib.sha256(body).hexdigest()
        for role, body in expected_bytes.items()
    }

    record, document_bytes = _decode_output(repaired)
    rework.verify_output(record, document_bytes)


def test_format_rework_prompt_serializes_validated_object_once_and_keeps_lineage():
    raw_text = canonical_bytes(_output()).decode("utf-8") + "}"
    rework = _prepare(raw_text)
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
        qualified,
        {name: ("controlled:" + name).encode("utf-8") for name in REQUIRED_MATERIALS},
        change,
        review,
        method,
        resources,
        received_at=NOW,
        authenticated_actor=ACTOR,
        source_texts={"baseline": {"content": "baseline"},
                      "candidate": {"content": "candidate"}},
        review_material={"review": "admitted"},
        format_rework=rework,
    )
    prompt = decode_json(params["prompt"][0]["text"])
    material = rework.prompt_material()
    rework_prompt = prompt["format_rework"]

    assert prompt["task"].startswith(
        "Serialize response_object as one valid output_contract JSON object.")
    assert "raw_text is prior invalid evidence, not the response to copy" in prompt["task"]
    assert "instruction" not in rework_prompt
    assert rework_prompt["response_object"] == decode_json(raw_text[:-1])
    assert rework_prompt["raw_text"] == raw_text
    assert rework_prompt["raw_text_digest"] == material["raw_text_digest"]
    assert rework_prompt["exact_patch"] == material["exact_patch"]
    assert rework_prompt["expected_patched_text_digest"] == material[
        "expected_patched_text_digest"]
    assert rework_prompt["expected_package_id"] == material["expected_package_id"]
    assert rework_prompt["expected_document_digests"] == material[
        "expected_document_digests"]
    assert rework_prompt["prior"] == material["prior"]
    assert rework_prompt["response_object"]["document_contents"] == _output()[
        "document_contents"]


@pytest.mark.parametrize("raw_text", [
    canonical_bytes(_output()).decode("utf-8"),
    canonical_bytes(_output()).decode("utf-8") + "x}",
    canonical_bytes(_output()).decode("utf-8") + "}}",
])
def test_format_rework_rejects_valid_or_non_single_brace_syntax(raw_text):
    with pytest.raises(ApplicationError) as error:
        _prepare(raw_text)
    expected_code = ("WORK_ACTION_GENERATION_REWORK_NOT_REQUIRED"
                     if raw_text == canonical_bytes(_output()).decode("utf-8")
                     else "WORK_ACTION_GENERATION_REWORK_INVALID")
    assert error.value.code == expected_code


def test_format_rework_rejects_raw_digest_mismatch():
    raw_text = canonical_bytes(_output()).decode("utf-8") + "}"
    wrong_selector = _selector(raw_text, digest="0" * 64)
    with pytest.raises(ApplicationError) as error:
        _prepare(raw_text, selector=wrong_selector)
    assert error.value.code == "WORK_ACTION_GENERATION_REWORK_INVALID"


@pytest.mark.parametrize("selector_changes", [
    {"target_work_id": "some-other-work"},
    {"prior_operation_ref": "some-other-operation"},
])
def test_format_rework_requires_exact_new_work_and_prior_operation(selector_changes):
    raw_text = canonical_bytes(_output()).decode("utf-8") + "}"
    selector = _selector(raw_text)
    selector.update(selector_changes)

    with pytest.raises(ApplicationError) as error:
        _prepare(raw_text, selector=selector)
    assert error.value.code == "WORK_ACTION_GENERATION_REWORK_INVALID"


@pytest.mark.parametrize("changed", [
    {"package_id": "different-package"},
    {"documents": {
        "spec": "# Specification\nChanged body.\n",
        "plan": "# Plan\nThe exact prior plan.\n",
        "tasks": "# Tasks\n- [ ] Preserve all three bodies.\n",
    }},
])
def test_format_rework_rejects_changed_package_identity_or_document_bytes(changed):
    raw_text = canonical_bytes(_output()).decode("utf-8") + "}"
    rework = _prepare(raw_text)
    if "package_id" in changed:
        different = _output(package_id=changed["package_id"])
    else:
        different = _output(documents=changed["documents"])
    record, document_bytes = _decode_output(canonical_bytes(different).decode("utf-8"))

    with pytest.raises(ApplicationError) as error:
        rework.verify_output(record, document_bytes)
    assert error.value.code == "WORK_ACTION_GENERATION_REWORK_CONTENT_CHANGED"


def _native_receipt(binding, params=PRIOR_PARAMS):
    params = decode_json(canonical_bytes(params))
    unit_ref = _unit_ref()
    inputs = {"unitRef": unit_ref, "params": params}
    request_raw = {
        "jsonrpc": "2.0",
        "id": "prior-request-1",
        "method": "session/prompt",
        "params": params,
    }
    frame = canonical_bytes(request_raw).decode("utf-8") + "\n"
    response = {
        "jsonrpc": "2.0",
        "id": request_raw["id"],
        "result": {"stopReason": "end_turn"},
    }
    text = "The exact captured prior output."
    events = [
        {
            "sessionMatched": True,
            "raw": {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": SESSION_ID,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": text},
                    },
                },
            },
        },
        {"sessionMatched": True, "raw": response},
    ]
    return {
        "input": inputs,
        "inputDigest": _native_digest(inputs),
        "nativeBinding": {"sessionId": SESSION_ID},
        "request": {
            "raw": request_raw,
            "frameUtf8": frame,
            "frameDigest": "sha256:" + hashlib.sha256(frame.encode("utf-8")).hexdigest(),
        },
        "events": events,
        "eventsDigest": _native_digest(events),
        "response": response,
        "responseDigest": _native_digest(response),
        "summary": {
            "text": text,
            "textDigest": _native_digest(text),
            "knownRemoteFailure": False,
            "stopReason": "end_turn",
        },
    }


def test_prior_native_receipt_rebuilds_text_from_complete_frozen_exchange():
    raw_text = canonical_bytes(_output()).decode("utf-8") + "}"
    binding, _outcome = _prior_binding_and_outcome(raw_text)
    receipt = _native_receipt(binding)

    assert verify_prior_native_receipt(receipt, binding, PRIOR_PARAMS) is None


@pytest.mark.parametrize("damage", [
    "summary_text", "session", "request", "frame_digest", "response_digest", "input_digest",
])
def test_prior_native_receipt_rejects_inconsistent_native_evidence(damage):
    raw_text = canonical_bytes(_output()).decode("utf-8") + "}"
    binding, _outcome = _prior_binding_and_outcome(raw_text)
    receipt = _native_receipt(binding)

    if damage == "summary_text":
        receipt["summary"]["text"] += " changed"
        receipt["summary"]["textDigest"] = _native_digest(receipt["summary"]["text"])
    elif damage == "session":
        receipt["nativeBinding"]["sessionId"] = "substituted-session"
    elif damage == "request":
        receipt["request"]["raw"]["params"]["sessionId"] = "substituted-session"
    elif damage == "frame_digest":
        receipt["request"]["frameDigest"] = "sha256:" + "0" * 64
    elif damage == "response_digest":
        receipt["responseDigest"] = "sha256:" + "0" * 64
    elif damage == "input_digest":
        receipt["inputDigest"] = "sha256:" + "0" * 64

    with pytest.raises(ApplicationError) as error:
        verify_prior_native_receipt(receipt, binding, PRIOR_PARAMS)
    assert error.value.code == "WORK_ACTION_GENERATION_REWORK_RECEIPT_INVALID"
