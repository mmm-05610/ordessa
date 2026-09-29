"""T05 / G05 — prompt bodies never reach the log stream or error text.

contracts.md §1: "日志仅 ID/revision/摘要和诊断码，不记正文"; FR14 adds that
no assumption is made that a body contains no secret. Every operation is
driven with a canary body, then the whole captured log plus every refusal
message is searched for the canary (raw and base64 forms), and the logged
shape is pinned to the documented field set.

Gates: G05 (log/error half; XSS, remote-image and editor-scope halves are
frontend work — see specs/011-q2-prompts-commands/prompts/blocked.md).
"""
from __future__ import annotations

import ast
import base64

import pytest

from ordessa_prompts.api import InvalidContentError, PromptError, PromptScope
from ordessa_prompts.backend.service import PromptsService, _log_event

#: something that can never legitimately appear in an id/revision/digest
CANARY = "CANARY-SECRET-BODY-\U0001F525-never-log-me"
CANARY_BYTES = CANARY.encode("utf-8")
CANARY_B64 = base64.b64encode(CANARY_BYTES).decode("ascii")

#: the only fields the logging gate is allowed to emit (contracts.md §1)
ALLOWED_LOG_FIELDS = {"replay", "id", "revision", "sha256", "sourceId",
                      "metadataVersion", "snapshotId", "items", "contentDigest"}


def _exercise_everything(service: PromptsService) -> "list[str]":
    """Drive the whole public surface with canary content; return the ids."""
    created = service.create(kind="instruction", scope={"kind": "library"},
                             title=CANARY, description=CANARY,
                             body=CANARY_BYTES, operation_key="k-log-create")
    prompt_id = created["id"]
    service.update(prompt_id, expected_metadata_version=1,
                   expected_latest_revision=1,
                   patch={"body": CANARY_BYTES + b" edited"},
                   operation_key="k-log-update")
    clone = service.clone(prompt_id, target_scope={"kind": "library"},
                          title=CANARY, operation_key="k-log-clone")
    service.archive(clone["id"], expected_metadata_version=1,
                    operation_key="k-log-archive")
    service.restore(clone["id"], expected_metadata_version=2,
                    operation_key="k-log-restore")
    service.import_text(CANARY_BYTES, filename_hint=CANARY + ".md",
                        operation_key="k-log-import")
    listing = service.list()
    assert listing["items"], "the exercise stored nothing"
    service.get(prompt_id)
    service.get_revision(prompt_id, 1)
    exported = service.export_text(prompt_id, 1)
    assert CANARY_B64 in exported["bodyBase64"], (
        "export itself must still carry the content for the authorised caller")
    selection = {"instructions": [{"promptId": prompt_id}]}
    service.resolve_snapshot(selection)
    service.preview(selection)
    return [prompt_id, clone["id"]]


def test_no_log_line_carries_a_body_or_title_fragment(library_service, log_capture):
    ids = _exercise_everything(library_service)
    assert len(log_capture.records) >= 8, (
        f"the exercise produced too few log records: {log_capture.records}")
    for message in log_capture.records:
        assert CANARY not in message, f"content reached the log: {message!r}"
        assert CANARY_B64 not in message, f"b64 content reached the log: {message!r}"
        assert len(message) < 512, f"suspiciously large log line: {message!r}"
    # every positive write did get logged, by id — privacy is not silence
    logged_ids = {token for message in log_capture.records
                  for token in ids if token in message}
    assert logged_ids == set(ids), f"some record is untraceable in the log: {logged_ids}"


def test_log_lines_are_limited_to_the_documented_field_set(library_service,
                                                           log_capture):
    _exercise_everything(library_service)
    for message in log_capture.records:
        head, _, payload = message.partition(" ")
        assert head.startswith("prompts."), message
        assert head.count(".") == 1, f"unknown diagnostic name: {head}"
        facts = ast.literal_eval(payload)
        assert isinstance(facts, dict), message
        extra = set(facts) - ALLOWED_LOG_FIELDS
        assert extra == set(), f"undocumented log fields: {extra} in {message!r}"
        for key, value in facts.items():
            assert isinstance(value, (str, int, bool)), (key, value)
            if key in {"id", "sourceId"}:
                assert str(value).startswith("prompt_"), (key, value)
            if key == "sha256":
                assert str(value).startswith("sha256:") and len(value) == 71, value
            if key == "contentDigest":
                assert str(value).startswith("sha256:"), value
            if key == "snapshotId":
                assert str(value).startswith("snapshot_"), value


def test_the_logging_gate_hashes_any_bytes_value_it_is_given(log_capture):
    _log_event("probe", sha256=CANARY_BYTES, size=len(CANARY_BYTES))
    assert log_capture.records, "the probe logged nothing"
    message = log_capture.records[-1]
    assert CANARY not in message and CANARY_B64 not in message
    assert "sha256:" in message and "size" in message
    facts = ast.literal_eval(message.partition(" ")[2])
    assert facts["size"] == len(CANARY_BYTES)
    assert set(facts) == {"sha256", "size"}


def test_refusal_messages_never_quote_the_offending_content(library_service):
    offenders = (b"\xff\xfe" + CANARY_BYTES, CANARY_BYTES + b"\x00", b"   ",
                 CANARY_BYTES * 5000, b"\xef\xbb\xbf" + CANARY_BYTES)
    assert len(CANARY_BYTES * 5000) > 128 * 1024, "the oversize case must be oversize"
    created = library_service.create(kind="instruction", scope={"kind": "library"},
                                     title="target", description=None,
                                     body=b"base", operation_key="k-target")
    for index, body in enumerate(offenders):
        with pytest.raises(PromptError) as exc:
            library_service.update(created["id"], expected_metadata_version=1,
                                   expected_latest_revision=1, patch={"body": body},
                                   operation_key=f"k-off-{index}")
        assert exc.value.code in ("INVALID_CONTENT", "LIMIT_EXCEEDED"), exc.value.code
        assert CANARY not in str(exc.value), exc.value
        assert CANARY not in repr(exc.value), exc.value
        assert CANARY_B64 not in str(exc.value)
        # a refusal stays actionable without quoting content: only offsets,
        # sizes, lengths or the allowed-vocabulary may travel in `details`
        assert set(exc.value.details) <= {"start", "end", "size", "length",
                                         "allowed"}, exc.value.details
        for value in exc.value.details.values():
            assert isinstance(value, int) or value == (
                "instruction", "persona", "system-replacement"), value


def test_invalid_content_details_carry_offsets_and_sizes_only(library_service):
    created = library_service.create(kind="instruction", scope={"kind": "library"},
                                     title="target", description=None,
                                     body=b"base", operation_key="k-shape")
    with pytest.raises(InvalidContentError) as bad_encoding:
        library_service.update(created["id"], expected_metadata_version=1,
                               expected_latest_revision=1,
                               patch={"body": b"ok\x80\x80nope"},
                               operation_key="k-offset")
    assert bad_encoding.value.details["start"] == 2
    assert bad_encoding.value.details["end"] == 3
    assert "nope" not in bad_encoding.value.message

    with pytest.raises(InvalidContentError) as too_big:
        library_service.update(created["id"], expected_metadata_version=1,
                               expected_latest_revision=1,
                               patch={"body": b"q" * (128 * 1024 + 7)},
                               operation_key="k-size")
    assert too_big.value.details["size"] == 128 * 1024 + 7

    with pytest.raises(InvalidContentError) as long_title:
        library_service.create(kind="instruction", scope={"kind": "library"},
                               title="t" * 161, description=None, body=b"body",
                               operation_key="k-long-title")
    assert long_title.value.details["length"] == 161

    with pytest.raises(InvalidContentError) as bad_kind:
        library_service.create(kind=CANARY, scope={"kind": "library"},
                               title="t", description=None, body=b"body",
                               operation_key="k-bad-kind")
    assert CANARY not in str(bad_kind.value), (
        f"the unknown-kind refusal echoed the client value: {bad_kind.value}")
    assert set(bad_kind.value.details["allowed"]) == {
        "instruction", "persona", "system-replacement"}

    with pytest.raises(InvalidContentError) as bad_scope:
        library_service.create(kind="instruction", scope={"kind": CANARY},
                               title="t", description=None, body=b"body",
                               operation_key="k-bad-scope")
    assert CANARY not in str(bad_scope.value), (
        f"the unknown-scope refusal echoed the client value: {bad_scope.value}")

    # the DTO path reports the allowed vocabulary instead of the value
    with pytest.raises(InvalidContentError) as direct_scope:
        PromptScope(CANARY)
    assert CANARY not in str(direct_scope.value)
    assert set(direct_scope.value.details["allowed"]) == {"library", "profile"}


def test_a_bad_base64_wire_body_never_echoes_input(plugin_registration):
    _, _, handlers = plugin_registration
    with pytest.raises(PromptError) as exc:
        handlers["prompts.create"]({
            "requestId": "r" * 12, "kind": "instruction",
            "scope": {"kind": "library"}, "title": "t",
            "body": "@@not-base64-@@", "operationKey": "k-wire-bad"})
    assert exc.value.code == "INVALID_REQUEST"
    assert "@@not-base64@@" not in str(exc.value)


def test_prompts_error_envelope_is_machine_readable_and_body_free(
        library_service):
    """The wire maps these codes; a caller must be able to branch on
    ``code``/``details`` without parsing prose that could quote content."""
    with pytest.raises(PromptError) as exc:
        library_service.get("prompt_missing-id")
    assert exc.value.code == "NOT_FOUND"
    assert "prompt_missing-id" in exc.value.message  # ids are allowed
    assert exc.value.details == {}
    assert isinstance(exc.value, Exception)
    assert str(exc.value).startswith("NOT_FOUND: ")
