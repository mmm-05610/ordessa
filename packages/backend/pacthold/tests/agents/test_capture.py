"""T011-01 gates: the capture transaction pins draft/attachments/config
opIds/base/target/binding/schema/guarantee — and UI selection or late edits
can NEVER modify a captured snapshot."""
from __future__ import annotations

import pytest

from pacthold.agents.submissions.capture import CaptureError, CaptureTransaction
from ordessa_environment_api.guarantee import GuaranteeLevel


def make(**overrides):
    request = {
        "submission_id": "sub-1",
        "draft": {"draftId": "draft", "draftRevision": 3, "text": "已发送的版本",
                  "attachmentIds": ["a1"], "attachmentRefs": [{"kind": "file", "ref": "r1"}]},
        "config_op_ids": ("op-config-1", "op-config-2"),
        "base": "fact-42",
        "target": {"kind": "session", "sessionId": "s1"},
        "binding": {"sessionUid": "canonical-1", "nativeSessionKey": "native-1"},
        "schema": "ordessa-data/7",
        "guarantee": "reliable",
    }
    request.update(overrides)
    return CaptureTransaction.capture(**request)


def test_capture_pins_all_eight_components():
    capture = make()
    assert capture.submission_id == "sub-1"
    assert capture.draft["draftId"] == "draft"
    assert capture.draft["draftRevision"] == 3
    assert capture.config_op_ids == ("op-config-1", "op-config-2")
    assert capture.base == "fact-42"
    assert capture.target["sessionId"] == "s1"
    assert capture.binding["sessionUid"] == "canonical-1"
    assert capture.schema == "ordessa-data/7"
    assert capture.guarantee is GuaranteeLevel.RELIABLE


def test_counterexample_late_ui_edits_never_modify_the_captured_snapshot():
    source_draft = {"draftId": "draft", "draftRevision": 3, "text": "已发送的版本", "attachmentIds": ["a1"]}
    source_target = {"kind": "session", "sessionId": "s1"}
    capture = make(draft=source_draft, target=source_target)
    # a late UI edit mutates the LIVE sources after the capture
    source_draft["text"] = "用户后来又改了"
    source_draft["attachmentIds"].append("a2")
    source_target["sessionId"] = "SOMETHING-ELSE"
    assert capture.draft["text"] == "已发送的版本"  # the capture kept the sent version
    assert capture.draft["attachmentIds"] == ("a1",)
    assert capture.target["sessionId"] == "s1"


def test_counterexample_the_captured_snapshot_is_deep_frozen():
    capture = make()
    with pytest.raises(TypeError):
        capture.draft["text"] = "改不了"
    with pytest.raises(TypeError):
        capture.target["sessionId"] = "改不了"
    with pytest.raises(Exception):
        capture.draft["attachmentIds"] += ("a2",)
    with pytest.raises(Exception):
        capture.submission_id = "sub-2"


def test_validation_refuses_malformed_captures_instead_of_half_recording():
    with pytest.raises(CaptureError):
        make(submission_id="")
    with pytest.raises(CaptureError):
        make(draft={"draftRevision": 1, "text": "x", "attachmentIds": []})  # no stable draftId
    with pytest.raises(CaptureError):
        make(draft={"draftId": "d", "draftRevision": -1, "text": "x", "attachmentIds": []})
    with pytest.raises(CaptureError):
        make(config_op_ids=())
    with pytest.raises(CaptureError):
        make(config_op_ids=("op-1", "op-1"))  # one capture, one consumption
    with pytest.raises(CaptureError):
        make(base="")
    with pytest.raises(CaptureError):
        make(binding={})
    with pytest.raises(CaptureError):
        make(schema=" ")
    with pytest.raises(CaptureError):
        make(guarantee="不存在的等级")


def test_guarantee_accepts_wire_strings_and_levels():
    assert make(guarantee="raw").guarantee is GuaranteeLevel.RAW
    assert make(guarantee=GuaranteeLevel.RELIABLE).guarantee is GuaranteeLevel.RELIABLE
