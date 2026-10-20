"""Bounded syntax-only input for a new, independently captured generation.

This projection never registers a repaired prior result. Its raw text, exact
patch and expected bodies become part of the new attempt's frozen prompt.
"""
from dataclasses import asdict, dataclass
import hashlib
import re

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.values import validate_id
from ordessa_infrastructure.encoding import canonical_bytes, decode_json


def validate_format_rework(value):
    if value is None:
        return None
    if (type(value) is not dict
            or set(value) != {"target_work_id", "prior_operation_ref", "raw_text_digest"}):
        raise ApplicationError("WORK_ACTION_GENERATION_REWORK_INVALID")
    try:
        validate_id(value["target_work_id"])
        validate_id(value["prior_operation_ref"])
        if (type(value["raw_text_digest"]) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", value["raw_text_digest"]) is None):
            raise ValueError("raw output digest required")
    except Exception as error:
        raise ApplicationError("WORK_ACTION_GENERATION_REWORK_INVALID") from error
    return dict(value)


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def verify_prior_native_receipt(receipt, binding, params):
    """Recheck the frozen native request/response and rebuild its text summary."""
    def digest(value):
        return _sha(canonical_bytes({"value": value}))

    try:
        unit = decode_json(binding.unit_ref_bytes)
        inputs = {"unitRef": unit, "params": params}
        summary, events = receipt["summary"], receipt["events"]
        request, response = receipt["request"], receipt["response"]
        raw, frame = request["raw"], request["frameUtf8"].encode("utf-8")
        session = receipt["nativeBinding"]["sessionId"]
        if (receipt["input"] != inputs
                or receipt["inputDigest"] != digest(inputs)
                or receipt["inputDigest"] != "sha256:" + binding.prompt_input_digest.hex
                or type(session) is not str or not session or params["sessionId"] != session
                or raw.get("jsonrpc") != "2.0" or raw.get("method") != "session/prompt"
                or type(raw.get("id")) not in (str, int) or raw.get("params") != params
                or not frame.endswith(b"\n") or frame.count(b"\n") != 1
                or decode_json(frame) != raw or request["frameDigest"] != _sha(frame)
                or response.get("jsonrpc") != "2.0" or "error" in response
                or type(response.get("result")) is not dict
                or canonical_bytes(response.get("id")) != canonical_bytes(raw["id"])
                or summary["knownRemoteFailure"] is not False
                or summary["stopReason"] != response["result"].get("stopReason")
                or receipt["eventsDigest"] != digest(events)
                or receipt["responseDigest"] != digest(response)
                or summary["textDigest"] != digest(summary["text"])
                or response not in [event["raw"] for event in events]):
            raise ValueError("prior native evidence differs from frozen request")
        texts = []
        for event in events:
            params = event["raw"].get("params", {})
            if (event["sessionMatched"] is not True or type(params) is not dict
                    or params.get("sessionId") != session):
                continue
            update = params.get("update", {})
            if type(update) is not dict or update.get("sessionUpdate") != "agent_message_chunk":
                continue
            content = update.get("content", {})
            if type(content) is dict and content.get("type") == "text":
                texts.append(content["text"])
        if summary["text"] != "".join(texts):
            raise ValueError("prior output summary differs from events")
    except Exception as error:
        raise ApplicationError("WORK_ACTION_GENERATION_REWORK_RECEIPT_INVALID") from error


@dataclass(frozen=True)
class _FormatRework:
    package_id: str
    document_bytes: tuple[tuple[str, bytes], ...]
    original_text: str
    prior_identity: dict

    def prompt_material(self):
        raw = self.original_text.encode("utf-8")
        return {
            "kind": "completed-generation-format-rework/v1",
            "prior": self.prior_identity,
            "raw_text": self.original_text,
            "raw_text_digest": _sha(raw),
            "response_object": decode_json(raw[:-1]),
            "exact_patch": {"operation": "delete", "byte_offset": len(raw) - 1,
                            "removed_hex": "7d", "inserted_hex": ""},
            "expected_patched_text_digest": _sha(raw[:-1]),
            "expected_package_id": self.package_id,
            "expected_document_digests": {role: _sha(body)
                                          for role, body in self.document_bytes},
            "instruction": (
                "Serialize response_object as one valid output_contract JSON object. "
                "raw_text is prior invalid evidence, not the response to copy. "
                "Preserve package_id and every document character. No tools or hashes."),
        }

    def verify_output(self, record, document_bytes):
        if (record.package_id != self.package_id
                or document_bytes != dict(self.document_bytes)):
            raise ApplicationError("WORK_ACTION_GENERATION_REWORK_CONTENT_CHANGED")


def prepare_format_rework(text, prior_outcome, prior_binding, selector, work_id,
                          decode_output):
    """Permit exactly one trailing 0x7d error after a complete strict envelope."""
    selection = validate_format_rework(selector)
    if (selection is None or selection["target_work_id"] != work_id
            or prior_binding.execution_operation_ref != selection["prior_operation_ref"]
            or prior_outcome.get("phase") != "completed"
            or (prior_binding.work or {}).get("work_id") == work_id
            or type(text) is not str):
        raise ApplicationError("WORK_ACTION_GENERATION_REWORK_INVALID")
    raw = text.encode("utf-8", errors="strict")
    if _sha(raw) != selection["raw_text_digest"] or not raw.endswith(b"}"):
        raise ApplicationError("WORK_ACTION_GENERATION_REWORK_INVALID")
    try:
        decode_output(text)
    except ApplicationError as error:
        if error.code != "WORK_ACTION_GENERATION_OUTPUT_INVALID":
            raise
    else:
        raise ApplicationError("WORK_ACTION_GENERATION_REWORK_NOT_REQUIRED")
    # Reuse the unmodified complete-envelope/schema decoder. No prefix parsing,
    # trimming, or permissive JSON ever feeds the package registration path.
    try:
        record, document_bytes = decode_output(raw[:-1].decode("utf-8", errors="strict"))
    except Exception as error:
        raise ApplicationError("WORK_ACTION_GENERATION_REWORK_INVALID") from error
    identity = {
        "work": prior_binding.work,
        "dispatch_identity": prior_outcome["identity"],
        "step_id": prior_binding.step_id,
        "attempt": prior_binding.attempt,
        "binding_digest": asdict(prior_binding.digest),
        "operation_ref": prior_binding.execution_operation_ref,
        "unit_ref": decode_json(prior_binding.unit_ref_bytes),
        "subject": prior_binding.subject,
        "prompt_ref": asdict(prior_binding.prompt_ref),
        "prompt_input_digest": asdict(prior_binding.prompt_input_digest),
        "result_blob_ref": (asdict(prior_outcome["result_blob_ref"])
                            if hasattr(prior_outcome["result_blob_ref"], "__dataclass_fields__")
                            else prior_outcome["result_blob_ref"]),
    }
    return _FormatRework(record.package_id, tuple(sorted(document_bytes.items())),
                         text, identity)
