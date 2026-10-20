"""Controlled tests for the DeepSeek Unit diagnostic's finite result reporting.

These tests exercise the probe's report-only surfaces with fabricated data:
the finite projection of an original receipt DTO, its bounded canonical
serialization, the preservation of the original operation ref, and the rule
that a failure is reported as a bounded category plus a fixed summary instead
of raw error text.

No test here calls a model, reads `.env`/credentials, opens a listener, touches
the process environment, retries, switches provider or changes an authority.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat

import pytest

from ordessa_infrastructure.encoding.canonical_json import CanonicalJSONError

PROBE_PATH = (Path(__file__).resolve().parents[3]
              / "tooling/checks/server_product/probe-units-deepseek.py")

REF = "unit-probe/" + "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
DIGEST = "d3" * 32
FAKE_SECRET = "sk-fake-not-a-real-credential-0123456789"
FAKE_PATH = "/home/example/projects/ordessa/.env"
FAKE_ENDPOINT = "https://api.deepseek.com"


def _load_probe():
    spec = importlib.util.spec_from_file_location("probe_units_deepseek_under_test", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


def _body(**overrides):
    """A fabricated original receipt DTO carrying unprojected private material."""
    body = {"state": "completed", "operationRef": REF, "inputDigest": DIGEST,
        "request": {"frameDigest": "f" * 64,
            "headers": {"Authorization": "Bearer " + FAKE_SECRET},
            "credentialSource": FAKE_PATH},
        "response": {"error": None, "apiKey": FAKE_SECRET},
        "responseDigest": "r" * 64,
        "events": [{"kind": "acp",
            "payload": {"authorization": FAKE_SECRET, "endpoint": FAKE_ENDPOINT}}],
        "summary": {"text": "UNIT_OK", "successfulRpcResponse": True,
            "knownRemoteFailure": False, "apiKey": FAKE_SECRET},
        "unprojected": {"credential": FAKE_SECRET}}
    body.update(overrides)
    return body


def _project(body):
    return probe.project_receipt(body, operation_ref=REF, input_digest=DIGEST)


def _without_receipt_digest(projection):
    return {key: value for key, value in projection.items() if key != "receipt_sha256"}


def _probe_source() -> str:
    return PROBE_PATH.read_text(encoding="utf-8")


# --- finite result projection -------------------------------------------------

def test_bounded_projection_keeps_only_declared_fields_in_order():
    fields = {"a": 1, "b": 2, "c": 3, "leaked": FAKE_SECRET}
    assert probe.bounded(fields, ("c", "a")) == {"c": 3, "a": 1}
    assert tuple(probe.bounded(fields, ("c", "a"))) == ("c", "a")
    assert "leaked" not in probe.bounded(fields, ("a", "b", "c"))


def test_bounded_projection_refuses_a_missing_declared_field():
    with pytest.raises(KeyError):
        probe.bounded({"a": 1}, ("a", "missing"))


def test_receipt_projection_is_exactly_the_declared_receipt_fields():
    projection = _project(_body())
    assert tuple(projection) == probe.RECEIPT_FIELDS
    assert set(projection) == set(probe.RECEIPT_FIELDS)


def test_receipt_projection_carries_the_original_ref_and_input_digest():
    body = _body()
    projection = _project(body)
    assert projection["operation_ref"] == REF == body["operationRef"]
    assert projection["input_digest"] == DIGEST == body["inputDigest"]
    assert projection["receipt_sha256"] == probe.digest(probe.encode_receipt(body))


def test_receipt_projection_drops_unprojected_receipt_content():
    text = json.dumps(_project(_body()))
    for marker in (FAKE_SECRET, FAKE_PATH, FAKE_ENDPOINT, "Authorization", "Bearer",
                   "apiKey", "credential", "events"):
        assert marker not in text


def test_receipt_projection_refuses_a_foreign_operation_ref():
    with pytest.raises(RuntimeError):
        _project(_body(operationRef="unit-probe/" + "0" * 40))


def test_receipt_projection_refuses_a_foreign_input_digest():
    with pytest.raises(RuntimeError):
        _project(_body(inputDigest="0" * 64))


def test_receipt_projection_stays_small_while_the_receipt_grows():
    small = _project(_body())
    large = _project(_body(events=[{"kind": "acp", "text": "x" * 65536}]))
    assert len(json.dumps(large)) < 1024
    assert _without_receipt_digest(large) == _without_receipt_digest(small)


# --- DTO serialization --------------------------------------------------------

def test_receipt_serialization_is_bounded_canonical_and_reconstructible():
    body = _body()
    encoded = probe.encode_receipt(body)
    assert isinstance(encoded, bytes)
    assert json.loads(encoded) == body
    assert encoded == probe.encode_receipt(body)
    shuffled = dict(reversed(list(body.items())))
    assert probe.encode_receipt(shuffled) == encoded
    assert json.dumps(json.loads(encoded), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8") == encoded


def test_receipt_serialization_refuses_a_body_beyond_the_owner_budget():
    oversized = _body(events=[{"kind": "acp", "text": "x" * (probe.RECEIPT_MAX_BYTES + 1)}])
    with pytest.raises(CanonicalJSONError):
        probe.encode_receipt(oversized)
    with pytest.raises(CanonicalJSONError):
        _project(oversized)


def test_result_serialization_is_canonical_and_reconstructible():
    result = {"status": "COMPLETED", "prompt_attempts": 1, "retry": probe.RETRY,
        "receipt": _project(_body()), "file_artifact": None}
    text = probe.serialize_result(result)
    assert json.loads(text) == result
    assert text == probe.serialize_result(result)
    assert probe.serialize_result(dict(reversed(list(result.items())))) == text
    assert len(text.encode("utf-8")) <= probe.RESULT_MAX_BYTES


def test_result_serialization_falls_back_to_a_bounded_record():
    result = {"status": "COMPLETED", "operation_ref": REF, "opaque": object()}
    text = probe.serialize_result(result)
    restored = json.loads(text)
    assert restored["status"] == "UNKNOWN"
    assert restored["operation_ref"] == REF
    assert restored["result_serialization"]["error_category"] in probe.ERROR_SUMMARIES
    assert set(restored["result_serialization"]) == {"error_category", "error_summary",
                                                     "error_class"}
    assert "0x" not in text and "object object at" not in text


# --- original operation ref preservation --------------------------------------

def test_operation_reference_is_derived_only_from_the_fresh_root(tmp_path):
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    ref_a = probe.operation_reference(root_a)
    assert ref_a == probe.operation_reference(root_a)
    assert ref_a != probe.operation_reference(root_b)
    assert ref_a == "unit-probe/" + hashlib.sha256(str(root_a).encode()).hexdigest()[:40]


def test_operation_reference_has_the_historical_shape(tmp_path):
    assert re.fullmatch(r"unit-probe/[0-9a-f]{40}", probe.operation_reference(tmp_path))


def test_saved_operation_reference_survives_a_lost_result(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    ref = probe.operation_reference(root)
    intent = probe.build_operation_intent({"unitId": "u-1"}, ref, DIGEST,
        {"prompt": [{"type": "text", "text": "Reply only UNIT_OK. Do not use tools."}],
         "sessionId": "s-1"})
    path = root / "operation-reference.json"
    probe.save_operation_reference(path, intent)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["operation_ref"] == ref
    assert saved["unit_ref"] == {"unitId": "u-1"}
    assert saved["input_digest"] == DIGEST
    assert saved["params"]["sessionId"] == "s-1"
    # With the final result lost, the root alone still yields this same one ref.
    assert probe.operation_reference(root) == saved["operation_ref"]
    assert json.loads(path.read_text(encoding="utf-8")) == saved


def test_saved_operation_reference_is_written_private(tmp_path):
    path = tmp_path / "operation-reference.json"
    probe.save_operation_reference(path, probe.build_operation_intent({}, REF, DIGEST, {}))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    result_path = tmp_path / "receipt.json"
    probe.save_result(result_path, probe.serialize_result(probe.initial_result()))
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600


# --- error reporting: category and summary only -------------------------------

@pytest.mark.parametrize("error, category", [
    (TimeoutError("t"), "timeout"),
    (ConnectionError("c"), "connection"),
    (PermissionError("p"), "permission"),
    (KeyError("k"), "missing_field"),
    (ValueError("v"), "invalid_input"),
    (RuntimeError("r"), "runtime"),
    (Exception("e"), "unexpected"),
])
def test_error_summary_reports_a_bounded_category(error, category):
    summary = probe.error_summary(error)
    assert set(summary) == {"error_category", "error_summary", "error_class"}
    assert summary["error_category"] == category
    assert summary["error_summary"] == probe.ERROR_SUMMARIES[category]
    assert summary["error_class"] == type(error).__name__


def test_error_summary_never_echoes_raw_error_text():
    error = RuntimeError(
        f"failed to reach {FAKE_ENDPOINT} while reading {FAKE_PATH} with {FAKE_SECRET}")
    summary = probe.error_summary(error)
    text = json.dumps(summary)
    for marker in (FAKE_SECRET, FAKE_PATH, FAKE_ENDPOINT, "Bearer", ".env", "RuntimeError:"):
        assert marker not in text
    assert "failed to reach" not in text


def test_error_summary_class_name_is_a_bounded_identifier():
    dynamic = type("sk-" + "FAKE" * 4, (Exception,), {})
    assert probe.error_summary(dynamic("boom"))["error_class"] == "UnclassifiedError"

    class Outer:
        class InnerError(Exception):
            pass

    assert probe.error_summary(Outer.InnerError("boom"))["error_class"] == "InnerError"

    def _local():
        class LocalError(Exception):
            pass

        return LocalError

    assert probe.error_summary(_local()("boom"))["error_class"] == "LocalError"
    assert probe.error_summary(ValueError("boom"))["error_class"] == "ValueError"


# --- the fixed outer report ---------------------------------------------------

def test_initial_result_is_the_declared_outer_shape():
    result = probe.initial_result()
    assert result["status"] == "UNKNOWN"
    assert result["prompt_attempts"] == 0
    assert result["retry"] == probe.RETRY
    for absent in ("failure", "prompt_error", "cleanup_error", "runtime_stop_error",
                   "receipt", "operation_ref"):
        assert absent not in result
    assert json.loads(probe.serialize_result(result)) == result


def test_probe_keeps_one_disabled_retry_policy_and_one_provider():
    assert probe.PROVIDER == "deepseek"
    assert probe.RETRY == {"enabled": False, "maxRetries": 0,
        "provider": {"maxRetries": 0, "maxRetryDelayMs": 0}}
    assert probe.ACTIONS == frozenset({"prepare", "start", "interaction", "stop", "release"})
    source = _probe_source()
    assert re.findall(r"'maxRetries':\s*(\d+)", source) == ["0", "0"]
    assert "OPENCODE" not in source and "opencode" not in source
    assert source.count("replace_grants(") == 1


def test_probe_source_reduces_every_caught_error_to_a_summary():
    source = _probe_source()
    for forbidden in ("str(error", "repr(error", "format(error", "{error}", "error.args",
                      "traceback", "error.__"):
        assert forbidden not in source
    assert source.count("error_summary(error)") == source.count(" as error:")
    assert source.count("error_summary(error)") >= 4


def test_probe_source_sends_at_most_one_prompt_per_run():
    source = _probe_source()
    assert source.count("interaction.prompt(") == 1
    assert source.count("prompt_attempts'] = 1") == 1
    assert "while " not in source
    assert "for attempt" not in source


def test_probe_source_writes_only_its_two_private_result_files():
    source = _probe_source()
    assert source.count("write_text(") == 2
    assert source.count("'operation-reference.json'") == 1
    assert source.count("'receipt.json'") == 1


def test_probe_source_reads_no_process_environment():
    source = _probe_source()
    for forbidden in ("os.environ", "getenv", "environ.get", "dotenv", "load_dotenv"):
        assert forbidden not in source
