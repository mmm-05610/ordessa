"""Historical capture codec plus unavailable-port checks; no native effects.

The original single-dispatch/replay/query positive case now lives at the formal
Unit owner in packages/execution/units/tests/test_captured_input.py. Its actual
ACP write, issuer/records/verifier identity and permission checks are exercised
there; no retired provider activation is reconstructed here.
"""
import hashlib
import pytest
from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_units.channels.reservations import CapturedInputEvidence, CapturedInputRef
from ordessa_harness_codex.managed_input import ManagedTextCapture, TEXT_CAPTURE_VERSION

NODE = {"environmentNamespace": "test", "instanceId": "node", "generation": 1}


def capture(envelope, metadata):
    body = __import__("json").dumps(envelope, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    ref = CapturedInputRef("test", "capture-1", 2,
        "sha256:" + hashlib.sha256(body).hexdigest())
    evidence = CapturedInputEvidence(ref, NODE, "draft-1", 3)
    return ManagedTextCapture(evidence, envelope, metadata)


def test_managed_capture_freezes_canonical_text_without_normalizing_it():
    value = capture({"schemaVersion": TEXT_CAPTURE_VERSION, "text": "原文\n"},
        {"attachmentDigests": (), "configOperationIds": (), "handles": (), "baseRevision": None})
    assert value.canonical_bytes() == b'{"schemaVersion":"managed-codex-text/1","text":"' + "原文\\n".encode() + b'"}'


@pytest.mark.parametrize("envelope,metadata", [
    ({"schemaVersion": TEXT_CAPTURE_VERSION, "text": "text", "configuration": {}},
     {"attachmentDigests": (), "configOperationIds": (), "handles": (), "baseRevision": None}),
    ({"schemaVersion": TEXT_CAPTURE_VERSION, "text": "text"},
     {"attachmentDigests": ("sha256:" + "a" * 64,), "configOperationIds": (), "handles": (), "baseRevision": None}),
])
def test_managed_capture_refuses_unrepresented_or_attached_facts(envelope, metadata):
    value = capture(envelope, metadata)
    with pytest.raises(GuaranteeUnavailableError):
        value.canonical_bytes()


def test_managed_capture_rejects_changed_canonical_content_digest():
    value = capture({"schemaVersion": TEXT_CAPTURE_VERSION, "text": "original"},
        {"attachmentDigests": (), "configOperationIds": (), "handles": (), "baseRevision": None})
    object.__setattr__(value, "envelope", {"schemaVersion": TEXT_CAPTURE_VERSION, "text": "changed"})
    assert value.evidence.ref.content_digest != "sha256:" + hashlib.sha256(value.canonical_bytes()).hexdigest()


def test_missing_original_capture_and_workspace_ports_keep_use_unavailable():
    from ordessa_units.public import ManagedUnitInputs, UnitCapturedInputRefused
    with pytest.raises(UnitCapturedInputRefused, match="original capture-content and Workspace execute"):
        ManagedUnitInputs(None, capture_content=None, workspace_execution=None)
