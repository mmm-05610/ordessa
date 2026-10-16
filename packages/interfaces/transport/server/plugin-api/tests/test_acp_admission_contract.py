"""Public ACP port shape and refusal controls; no host or Harness import."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import get_type_hints

import pytest

from server_plugin_api import (
    ACP_ADMISSION_PORT,
    ACP_ADMISSION_PORT_VERSION,
    AcpAdmissionPort,
    AcpAdmissionResult,
    AcpAttachmentReference,
    AcpChannelBinding,
    AcpPermissionDecision,
    AcpSubmissionRequest,
    ServerPluginContext,
)


def binding(**changes):
    values = dict(connection_id="conn-1", execution_id="turn-1",
                  ledger_session_id="session-1", harness_id="pi", workspace_id="project-1")
    values.update(changes)
    return AcpChannelBinding(**values)


def submission(**changes):
    values = dict(submission_id="submit-1", native_session_id="native-1", text="/literal",
                  attachments=(AcpAttachmentReference("brief", "file:///brief", "a" * 64),),
                  configuration_digest="b" * 64, command_id="catalog-1")
    values.update(changes)
    return AcpSubmissionRequest(**values)


def test_owned_binding_keeps_unknown_evidence_absent_and_rejects_forged_shape():
    observed = binding()
    assert observed.native_session_id is None and observed.runtime_generation is None
    assert binding(native_session_id="native-1", runtime_generation=7).runtime_generation == 7
    with pytest.raises(FrozenInstanceError):
        observed.connection_id = "other"
    for changes in ({"connection_id": ""}, {"runtime_generation": -1},
                    {"runtime_generation": True}, {"native_session_id": ""}):
        with pytest.raises(ValueError):
            binding(**changes)


def test_submission_copies_only_typed_immutable_values_and_keeps_slash_literal():
    request = submission()
    assert request.text == "/literal"
    assert isinstance(request.attachments, tuple)
    with pytest.raises(FrozenInstanceError):
        request.attachments[0].uri = "file:///other"
    for changes in ({"attachments": []}, {"configuration_digest": "wrong"},
                    {"command_id": ""}, {"native_session_id": ""}):
        with pytest.raises(ValueError):
            submission(**changes)
    with pytest.raises(ValueError):
        AcpAttachmentReference("x", "file:///x", "A" * 64)


def test_permission_and_three_outcome_shapes_are_exclusive():
    decision = AcpPermissionDecision("native-1", "ask-1", "run-1", "allow")
    assert decision.option_id == "allow"
    with pytest.raises(ValueError):
        AcpPermissionDecision("native-1", "ask-1", "", "allow")
    assert AcpAdmissionResult("accepted", submission_id="submit-1").kind == "accepted"
    assert AcpAdmissionResult("refused", code="AUTHORIZATION_REFUSED", reason="denied").kind == "refused"
    assert AcpAdmissionResult("unknown", operation_id="op-1", reason="reconcile").kind == "unknown"
    for invalid in (
        {"kind": "accepted", "submission_id": "submit-1", "reason": "done"},
        {"kind": "refused", "code": "AUTHORIZATION_REFUSED"},
        {"kind": "unknown", "operation_id": "op-1", "submission_id": "submit-1"},
        {"kind": "complete", "submission_id": "submit-1"},
    ):
        with pytest.raises(ValueError):
            AcpAdmissionResult(**invalid)


def test_context_port_is_typed_but_runtime_shape_is_not_authority():
    class Authority:
        public_acp_admission_port_version = ACP_ADMISSION_PORT_VERSION

        @property
        def ready(self):
            return True

        def authorize_submission(self, channel, request):
            assert channel == binding() and request == submission()
            return AcpAdmissionResult("accepted", submission_id=request.submission_id)

        def authorize_permission(self, channel, decision):
            assert channel == binding() and decision.option_id == "allow"
            return AcpAdmissionResult("unknown", operation_id="op-1", reason="reconcile")

    authority = Authority()
    typed_port: AcpAdmissionPort = authority
    context = ServerPluginContext(plugin_id="sample.acp", data_root=None,
                                  ports={ACP_ADMISSION_PORT: typed_port})
    assert context.ports[ACP_ADMISSION_PORT] is authority
    assert typed_port.authorize_submission(binding(), submission()).submission_id == "submit-1"
    assert typed_port.authorize_permission(binding(), AcpPermissionDecision(
        "native-1", "ask-1", "run-1", "allow")).kind == "unknown"
    assert ACP_ADMISSION_PORT_VERSION == 1
    assert typed_port.public_acp_admission_port_version == 1
    assert typed_port.ready is True
    class IncompatibleGate:
        # Same method names, but dict/host-object signatures and results.
        def authorize_submission(self, connection, request):
            return {"kind": "accepted", "submissionId": "submit-1"}

        def authorize_permission(self, connection, decision):
            return {"kind": "accepted", "submissionId": "ask-1"}

    for candidate in (authority, IncompatibleGate(), object()):
        with pytest.raises(TypeError, match="runtime_checkable"):
            isinstance(candidate, AcpAdmissionPort)
    assert set(get_type_hints(AcpAdmissionPort.authorize_submission)) >= {"binding", "submission", "return"}
    assert str(get_type_hints(AcpAdmissionPort.public_acp_admission_port_version.fget)["return"]) == "typing.Literal[1]"
    assert get_type_hints(AcpAdmissionPort.ready.fget)["return"] is bool


def test_version_marker_alone_never_claims_configured_authority():
    class ShapeOnly:
        public_acp_admission_port_version = ACP_ADMISSION_PORT_VERSION
        ready = False

    candidate = ShapeOnly()
    assert candidate.public_acp_admission_port_version == 1
    assert getattr(candidate, "ready", False) is False
    assert getattr(object(), "ready", False) is False
