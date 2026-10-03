"""Submission-gate wiring (T013 需求2/需求5): planForSubmission upgraded
from APPLICATION_PORT_ABSENT to the REAL ``ConfigurationService`` port
consumption — with the absence semantics kept intact.

The port doubles here are duck-typed against the published protocol; the
real ``ConfigurationApplicationService`` chain is proven in
``test_controlled_chain.py``. Counterexamples owned by this file: no permit
-> refusal BEFORE any planning work (nothing reconfigured, nothing
launched), missing expectedRevision -> refusal, placeholder + real port
together -> second-gate refusal, drift -> typed CAS refusal, adapter absent
-> typed port refusal, Unknown -> reconcile-only refusal, and the pre-T013
no-port behaviour unchanged.
"""
import pytest
from service_helpers import (
    FakeSubmissionGate, Stack, stdio_definition,
)
from wiring_helpers import (
    StubConfigurationService, make_plan, real_target, refused,
    submission_unknown,
)
from ordessa_harness_api import ErrorCode

from backend import native_binding as nb
from backend.plugin import McpAssetServerPlugin
from backend.service import (
    APPLICATION_PORT_ABSENT, EXPECTED_REVISION_REQUIRED,
    SUBMISSION_GATE_AMBIGUOUS, SUBMISSION_PERMIT_REQUIRED, McpDomainService,
)
from backend.errors import McpError

BASE = dict(server_scope="s1", principal="alice", session_ref="session-a",
            runtime_generation=7, harness="claude-code")
# the wire face of the same request (camelCase params)
WIRE = dict(serverScope="s1", principal="alice", sessionRef="session-a",
            runtimeGeneration=7, harness="claude-code")


def _planner(snapshot, harness):
    """Composition-style planner: returns a REAL domain intent set (built by
    the wiring helper through the real brand compile)."""
    from wiring_helpers import claude_planned
    assert harness == "claude-code"
    return claude_planned()


def _service(tmp_path, **over) -> McpDomainService:
    kwargs = dict(root=str(tmp_path), native_planner=_planner)
    kwargs.update(over)
    return McpDomainService(**kwargs)


# -- absence semantics unchanged (pre-T013) --------------------------------------


def test_no_ports_refuses_application_port_absent(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**BASE)
    assert info.value.code == APPLICATION_PORT_ABSENT


def test_placeholder_gate_answers_exactly_as_before(tmp_path):
    gate = FakeSubmissionGate()
    service = _service(tmp_path, submission_gate=gate)
    answer = service.plan_for_submission(**BASE)
    assert answer["submission"]["status"] == "planned-by-gate"
    assert len(gate.planned) == 1
    # the real port was never consulted
    assert service.configuration_service is None


def test_real_port_alone_still_refuses_without_permit_and_never_previews(tmp_path):
    # "有 permit 才产 plan" — and refusal happens before the snapshot is
    # even resolved: no reconfiguration input, no launch, no side effects
    class NoTouchService(StubConfigurationService):
        def plan(self, *a, **k):  # pragma: no cover - must never run
            raise AssertionError("plan ran without a permit")

    service = _service(tmp_path, configuration_service=NoTouchService())
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**BASE)
    assert info.value.code == SUBMISSION_PERMIT_REQUIRED
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**dict(BASE, submission_permit="  "))
    assert info.value.code == SUBMISSION_PERMIT_REQUIRED


def test_expected_revision_required(tmp_path):
    service = _service(tmp_path, configuration_service=StubConfigurationService())
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**dict(BASE, submission_permit="signed:x"))
    assert info.value.code == EXPECTED_REVISION_REQUIRED


def test_placeholder_plus_real_port_is_a_second_gate(tmp_path):
    service = _service(tmp_path, submission_gate=FakeSubmissionGate(),
                       configuration_service=StubConfigurationService())
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**dict(BASE, submission_permit="signed:x",
                                           expected_revision="base-1"))
    assert info.value.code == SUBMISSION_GATE_AMBIGUOUS


def test_real_port_without_planner_refuses_typed(tmp_path):
    service = _service(tmp_path, configuration_service=StubConfigurationService(),
                       native_planner=None)
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**dict(BASE, submission_permit="signed:x",
                                           expected_revision="base-1"))
    assert info.value.code == nb.NATIVE_PLANNER_ABSENT


# -- real consumption: the port answers, the domain relays ------------------------


def test_real_port_plan_success_travels_the_closed_fragment(tmp_path):
    port = StubConfigurationService()
    service = _service(tmp_path, configuration_service=port)
    answer = service.plan_for_submission(
        **dict(BASE, submission_permit="signed:permit-1",
               expected_revision="base-1"))
    target, fragments, expected = port.calls[0]
    assert target.server_id == "s1" and target.session_id == "session-a"
    assert target.runtime_generation == 7
    assert expected == "base-1"
    (fragment,) = fragments
    assert fragment.facet_id == nb.FACET_ID and fragment.operation == "set"
    assert fragment.source_revision == answer["snapshotDigest"]
    value = fragment.value
    assert value["harnessType"] == "claude-code"
    assert [e["nativeName"] for e in value["entries"]] == ["demo"]
    assert answer["submission"]["kind"] == "plan"
    assert answer["submission"]["planId"] == "plan-proof-1"
    assert answer["submission"]["planDigest"]
    # the response is ref-only: no plaintext material whatsoever
    assert "credentialReferences" in answer


def test_desired_fragment_seals_the_payload(tmp_path):
    # mutation of the caller dict after the fact cannot move the plan
    port = StubConfigurationService()
    service = _service(tmp_path, configuration_service=port)
    service.plan_for_submission(**dict(BASE, submission_permit="signed:p",
                                       expected_revision="base-1"))
    _, fragments, _ = port.calls[0]
    assert fragments[0].value["entries"][0]["command"] == "/bin/true"


def test_drift_answers_typed_cas_refusal(tmp_path):
    port = StubConfigurationService(results=[refused(ErrorCode.STALE_PLAN,
                                                     "expected revision changed")])
    service = _service(tmp_path, configuration_service=port)
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**dict(BASE, submission_permit="signed:p",
                                           expected_revision="old-rev"))
    assert info.value.code == "MCP_CAS_CONFLICT"
    assert "stale" in info.value.message.lower() or "refused" in info.value.message


def test_adapter_absent_answers_port_absent(tmp_path):
    port = StubConfigurationService(results=[refused(ErrorCode.ADAPTER_MISSING,
                                                     "configuration adapter absent")])
    service = _service(tmp_path, configuration_service=port)
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**dict(BASE, submission_permit="signed:p",
                                           expected_revision="base-1"))
    assert info.value.code == APPLICATION_PORT_ABSENT


def test_capability_unsupported_unknown_blocks_the_plan(tmp_path):
    # the honest assess state of both brands today: the REAL service refuses
    # the plan before compile because the assessment is not supported
    port = StubConfigurationService(results=[refused(ErrorCode.CAPABILITY_UNSUPPORTED,
                                                     "adapter assessment is unknown")])
    service = _service(tmp_path, configuration_service=port)
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**dict(BASE, submission_permit="signed:p",
                                           expected_revision="base-1"))
    assert info.value.code == nb.MCP_GATE_CAPABILITY_UNSUPPORTED


def test_unknown_result_keeps_reconcile_semantics(tmp_path):
    port = StubConfigurationService(results=[submission_unknown()])
    service = _service(tmp_path, configuration_service=port)
    with pytest.raises(McpError) as info:
        service.plan_for_submission(**dict(BASE, submission_permit="signed:p",
                                           expected_revision="base-1"))
    assert info.value.code == "UNKNOWN_OUTCOME"
    assert "reconcile" in info.value.message
    # the port was consulted exactly once — a refusal never re-drives it
    assert len(port.calls) == 1


# -- through the real wire face ----------------------------------------------------


def test_wire_shape_accepts_permit_and_revision_and_families_resolve(tmp_path):
    port = StubConfigurationService()
    plugin = McpAssetServerPlugin(native_planner=_planner)
    stack = Stack(tmp_path, host_ports={"harness.configuration_service": port},
                  plugin=plugin)
    caps = {entry["id"]: entry
            for entry in stack.call("server.hello", clientVersions=["wire/1"],
                                    clientPresentationSupports=["card"])
            ["capabilities"]}
    # real port composed -> the row is honestly supported in hello
    assert caps["mcp.planForSubmission"]["supported"] is True
    answer = stack.call("mcp.planForSubmission", **WIRE,
                        submissionPermit="signed:wire-1", expectedRevision="base-1")
    assert answer["submission"]["planId"] == "plan-proof-1"
    assert len(port.calls) == 1
    # no permit -> typed refusal with the published family
    stack.expect_refusal("mcp.planForSubmission", family="FORBIDDEN",
                         internal_code=SUBMISSION_PERMIT_REQUIRED, **WIRE)
    # drift -> CONFLICT_VERSION via the contributed family row
    port._results = [refused(ErrorCode.STALE_PLAN, "expected revision changed")]
    stack.expect_refusal("mcp.planForSubmission", family="CONFLICT_VERSION",
                         internal_code="MCP_CAS_CONFLICT", **WIRE,
                         submissionPermit="signed:wire-1", expectedRevision="gone")
    # unwired availability flips back with an empty composition
    plain = Stack(tmp_path / "plain")
    caps = {entry["id"]: entry
            for entry in plain.call("server.hello", clientVersions=["wire/1"],
                                    clientPresentationSupports=[])["capabilities"]}
    assert caps["mcp.planForSubmission"] == {
        "id": "mcp.planForSubmission", "supported": False,
        "reason": "MCP_SUBMISSION_GATE_UNWIRED"}
