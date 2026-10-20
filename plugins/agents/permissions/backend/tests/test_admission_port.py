"""T07 (Q5 half): the Permissions authorizer bound to the public ACP admission
port (`acp.admission.gate`), verified positively AND negatively at the port
boundary (the seam the harness-api checkpoint registered as G1).

The port contract is unforgiving and these tests hold it to the letter:

* `ready` is derived, never assumed - false unless an authority AND an
  authoritative native-session/runtime-generation evidence source are wired
  (the checkpoint's limitation states the default product has neither, so the
  plugin-composed port must answer `ready=False` too);
* `accepted` only for an `AllowedOnce` whose grant binds this exact operation
  digest, target, ceiling/policy revision and native generation;
* a missing binding observation is a refusal, never a pass-through;
* an outcome that cannot be resolved is the `unknown` shape only - and the
  DTO itself makes the three shapes mutually exclusive.
"""
from __future__ import annotations

import re

import pytest
from server_plugin_api import (
    ACP_ADMISSION_PORT,
    ACP_ADMISSION_PORT_VERSION,
    AcpAdmissionResult,
    AcpChannelBinding,
    AcpPermissionDecision,
    AcpSubmissionRequest,
    ServerPluginContext,
)

from ordessa_permissions_api import (
    NativeReceipt,
    PermissionIntent,
    approval_id_for,
    build_operation_request,
)
from ordessa_permissions_backend import Authorizer, PermissionsBackendPlugin
from ordessa_permissions_backend.admission import (
    PermissionsAcpAdmission,
    submission_argument_digest,
)
from ordessa_permissions_backend.facts import ApprovalFacts
from ordessa_permissions_backend.policies import PolicyRepository

from support import admin_ceiling, clock_at, seeded_database, seed_session, utc

CONFIG_DIGEST = "b" * 64
NATIVE_SESSION = "native-1"
RUNTIME_GENERATION = 3


def evidence_provider(native: str = NATIVE_SESSION, generation: int = RUNTIME_GENERATION):
    def _provider():
        return {"nativeSessionId": native, "runtimeGeneration": generation}
    return _provider


def make_environment(tmp_path, *, ceilings=(admin_ceiling(),), intent=None):
    database = seeded_database(tmp_path)
    seed_session(database)
    facts = ApprovalFacts(database)
    facts.ensure_schema()
    policies = PolicyRepository(database)
    policies.ensure_schema()
    for ceiling in ceilings:
        policies.store_ceiling(ceiling)
    if intent is not None:
        policies.store_intent(intent)
    authorizer = Authorizer(
        facts=facts, policies=policies,
        ceiling_provider=policies.ceilings_current,
        intent_provider=(lambda: intent) if intent is not None else (lambda: None),
        clock=clock_at(utc()))
    return database, facts, policies, authorizer


def make_adapter(authorizer, *, evidence=evidence_provider(), principal="user-1",
                 instance="srv-1"):
    return PermissionsAcpAdmission(
        authorizer=authorizer,
        native_evidence=evidence,
        principal_provider=(None if principal is None else (lambda _binding: principal)),
        server_instance_id=instance,
    )


def binding(*, native=NATIVE_SESSION, generation=RUNTIME_GENERATION,
            session="session-1", execution="turn-1"):
    return AcpChannelBinding(
        connection_id="conn-1", execution_id=execution, ledger_session_id=session,
        harness_id="pi", workspace_id="ws-1",
        native_session_id=native, runtime_generation=generation)


def submission(*, sub="sub-1", native=NATIVE_SESSION, command="bash", text="hello",
               config=CONFIG_DIGEST):
    return AcpSubmissionRequest(
        submission_id=sub, native_session_id=native, text=text, attachments=(),
        configuration_digest=config, command_id=command)


def expected_approval_id(*, intent=None, sub="sub-1", tool="bash",
                         generation=RUNTIME_GENERATION):
    """The §C1 approval id the port's documented translation must produce:
    principal/server instance/session/native session from the binding and the
    composition, command_id -> tool key, configuration digest -> target,
    submission id -> native request id, str(runtime generation) -> native
    generation. Computed independently of the adapter - this IS the contract."""
    operation = build_operation_request(
        principal="user-1", server_instance_id="srv-1", session_id="session-1",
        native_session_id=NATIVE_SESSION, execution_id="turn-1",
        native_generation=str(generation), tool_key=tool, target=CONFIG_DIGEST,
        argument_digest=submission_argument_digest(submission(sub=sub)),
        native_request_id=sub, ceilings=[admin_ceiling()], intent=intent)
    return approval_id_for(operation_digest=operation.operation_digest,
                           native_request_id=sub)


ALLOW_READ = PermissionIntent.of(
    intent_id="intent-allow-read", revision=1, harness_id="pi", scope="user",
    rules=[{"key": "read", "action": "allow"}])


# -- ready is derived, never assumed ------------------------------------------

def test_ready_false_without_an_authority(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)
    del authorizer  # the authority is absent: composition wired no authorizer
    adapter = PermissionsAcpAdmission(
        authorizer=None, native_evidence=evidence_provider(),
        principal_provider=lambda _b: "user-1", server_instance_id="srv-1")
    assert adapter.ready is False
    result = adapter.authorize_submission(binding(), submission())
    assert result.kind == "refused"
    assert result.code == "POLICY_ADAPTER_MISSING"


def test_ready_false_without_native_evidence_source(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)
    adapter = make_adapter(authorizer, evidence=None)
    assert adapter.ready is False
    assert adapter.authorize_submission(
        binding(), submission(command="read")).kind != "accepted"


def test_ready_false_when_evidence_source_answers_nothing(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)
    assert make_adapter(authorizer, evidence=lambda: None).ready is False


def test_ready_false_when_evidence_source_raises(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)

    def boom():
        raise RuntimeError("native owner is down")

    assert make_adapter(authorizer, evidence=boom).ready is False


def test_ready_false_on_partial_or_malformed_evidence(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)
    for bad in (
        lambda: {"nativeSessionId": "", "runtimeGeneration": 1},
        lambda: {"nativeSessionId": NATIVE_SESSION, "runtimeGeneration": None},
        lambda: {"nativeSessionId": NATIVE_SESSION, "runtimeGeneration": -1},
        lambda: {"nativeSessionId": None, "runtimeGeneration": 1},
    ):
        assert make_adapter(authorizer, evidence=bad).ready is False


def test_ready_true_only_with_authority_and_authoritative_evidence(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)
    adapter = make_adapter(authorizer)
    assert adapter.ready is True
    assert type(adapter.public_acp_admission_port_version) is int
    assert adapter.public_acp_admission_port_version == ACP_ADMISSION_PORT_VERSION == 1


# -- authorize_submission: positive -------------------------------------------

def test_accepted_only_for_an_allowed_once_bound_to_this_submission(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path, intent=ALLOW_READ)
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(binding(),
                                          submission(command="read", sub="sub-ok"))
    assert result.kind == "accepted"
    assert result.submission_id == "sub-ok"
    assert result.code is None and result.operation_id is None and result.reason is None


def test_translation_carries_the_documented_c1_identity(tmp_path):
    # The approval id a pending answer names must equal the id the §C1
    # operation digest derives from the documented translation - proof the
    # binding/submission fields land where C1 says, not approximately.
    _, _, _, authorizer = make_environment(tmp_path)
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(binding(), submission(command="bash"))
    assert result.kind == "refused"
    assert expected_approval_id() in (result.reason or "")


# -- authorize_submission: negative, observed at the port ---------------------

def test_unobserved_native_session_in_the_binding_is_never_accepted(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path, intent=ALLOW_READ)
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(binding(native=None),
                                          submission(command="read"))
    assert result.kind == "refused"
    assert result.code == "POLICY_SCOPE_UNVERIFIED"


def test_unobserved_runtime_generation_in_the_binding_is_never_accepted(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path, intent=ALLOW_READ)
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(binding(generation=None),
                                          submission(command="read"))
    assert result.kind == "refused"
    assert result.code == "POLICY_SCOPE_UNVERIFIED"


def test_binding_evidence_disagreeing_with_the_authoritative_source_is_refused(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path, intent=ALLOW_READ)
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(
        binding(native="other-session"), submission(native="other-session", command="read"))
    assert result.kind == "refused"
    assert result.code == "POLICY_SCOPE_UNVERIFIED"


def test_submission_naming_another_native_session_is_refused(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path, intent=ALLOW_READ)
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(binding(),
                                          submission(native="elsewhere", command="read"))
    assert result.kind == "refused"
    assert result.code == "POLICY_SCOPE_UNVERIFIED"


def test_a_command_without_a_declared_tool_identity_is_refused(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(binding(), submission(command=None))
    assert result.kind == "refused"
    assert result.code == "PERMISSION_UNKNOWN_TOOL"


def test_pending_approval_is_refused_with_a_stable_code_never_accepted(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(binding(), submission(command="bash"))
    assert result.kind == "refused"
    assert result.code == "APPROVAL_RESULT_UNKNOWN"
    assert re.search(r"approval_[0-9a-f]{32}", result.reason)


def test_no_trusted_ceiling_in_force_is_refused(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path, ceilings=())
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(binding(), submission(command="bash"))
    assert result.kind == "refused"
    assert result.code == "POLICY_ADAPTER_MISSING"


def test_unattributable_principal_or_instance_is_refused(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path, intent=ALLOW_READ)
    no_principal = PermissionsAcpAdmission(
        authorizer=authorizer, native_evidence=evidence_provider(),
        principal_provider=None, server_instance_id="srv-1")
    assert no_principal.authorize_submission(
        binding(), submission(command="read")).code == "POLICY_SCOPE_UNVERIFIED"
    no_instance = PermissionsAcpAdmission(
        authorizer=authorizer, native_evidence=evidence_provider(),
        principal_provider=lambda _b: "user-1", server_instance_id=None)
    assert no_instance.authorize_submission(
        binding(), submission(command="read")).code == "POLICY_SCOPE_UNVERIFIED"


def test_intent_allow_never_widens_under_a_ceiling_deny(tmp_path):
    ceiling = admin_ceiling(deny=[{"key": "read", "action": "deny"}], maximumExposure="none")
    _, _, _, authorizer = make_environment(tmp_path, ceilings=(ceiling,), intent=ALLOW_READ)
    adapter = make_adapter(authorizer)
    result = adapter.authorize_submission(binding(), submission(command="read"))
    assert result.kind == "refused"
    assert result.code == "POLICY_CEILING_VIOLATION"


# -- authorize_permission -------------------------------------------------------

def pending_approval_id(adapter, *, sub="sub-1"):
    result = adapter.authorize_submission(binding(), submission(command="bash", sub=sub))
    assert result.kind == "refused"
    assert result.code == "APPROVAL_RESULT_UNKNOWN"
    return re.search(r"(approval_[0-9a-f]{32})", result.reason).group(1)


def settle_allow(tmp_path, *, facts, authorizer, sub="sub-1"):
    """Drive the real flow: submission -> pending approval -> UI decide(allow)
    -> native receipt observed. Returns (adapter, approval_id, decision DTO)."""
    adapter = make_adapter(authorizer)
    approval_id = pending_approval_id(adapter, sub=sub)
    recorded = authorizer.decide(approval_id, 1, "allow", {"kind": "once"},
                                 f"req-{sub}", session_id="session-1")
    assert recorded.kind == "recorded"
    facts.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id=sub, approval_id=approval_id, confirmed=True,
        observed_at=utc()))
    decision = AcpPermissionDecision(native_session_id=NATIVE_SESSION,
                                     interaction_id=approval_id, run_id=sub,
                                     option_id="allow")
    return adapter, approval_id, decision


def test_permission_answer_accepted_once_and_replay_refused(tmp_path):
    _, facts, _, authorizer = make_environment(tmp_path)
    adapter, approval_id, decision = settle_allow(tmp_path, facts=facts,
                                                  authorizer=authorizer)
    first = adapter.authorize_permission(binding(), decision)
    assert first.kind == "accepted"
    assert first.submission_id == approval_id  # the harness wire compares this id
    assert first.code is None and first.operation_id is None
    replay = adapter.authorize_permission(binding(), decision)
    assert replay.kind == "refused"
    assert replay.code == "APPROVAL_STALE"
    assert replay.submission_id is None


def test_permission_missing_native_receipt_is_refused(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)
    adapter = make_adapter(authorizer)
    approval_id = pending_approval_id(adapter)
    recorded = authorizer.decide(approval_id, 1, "allow", {"kind": "once"}, "req-x",
                                 session_id="session-1")
    assert recorded.kind == "recorded"
    decision = AcpPermissionDecision(native_session_id=NATIVE_SESSION,
                                     interaction_id=approval_id, run_id="sub-1",
                                     option_id="allow")
    result = adapter.authorize_permission(binding(), decision)
    assert result.kind == "refused"
    assert result.code == "APPROVAL_RESULT_UNKNOWN"


def test_permission_forged_option_is_refused_and_spends_nothing(tmp_path):
    _, facts, _, authorizer = make_environment(tmp_path)
    adapter, _, decision = settle_allow(tmp_path, facts=facts, authorizer=authorizer)
    forged = AcpPermissionDecision(native_session_id=decision.native_session_id,
                                   interaction_id=decision.interaction_id,
                                   run_id=decision.run_id, option_id="deny")
    result = adapter.authorize_permission(binding(), forged)
    assert result.kind == "refused"
    assert result.code == "APPROVAL_STALE"
    bogus = AcpPermissionDecision(native_session_id=decision.native_session_id,
                                  interaction_id=decision.interaction_id,
                                  run_id=decision.run_id, option_id="allow-always-yolo")
    assert adapter.authorize_permission(binding(), bogus).kind == "refused"
    # and the forgery did not spend the real permit - the honest answer still works
    assert adapter.authorize_permission(binding(), decision).kind == "accepted"


def test_permission_cross_session_and_cross_run_are_refused(tmp_path):
    _, facts, _, authorizer = make_environment(tmp_path)
    adapter, approval_id, decision = settle_allow(tmp_path, facts=facts,
                                                  authorizer=authorizer)
    cross_session = adapter.authorize_permission(binding(session="session-OTHER"), decision)
    assert cross_session.kind == "refused"
    assert cross_session.code == "APPROVAL_STALE"
    cross_run = adapter.authorize_permission(binding(), AcpPermissionDecision(
        native_session_id=NATIVE_SESSION, interaction_id=approval_id,
        run_id="some-other-request", option_id="allow"))
    assert cross_run.kind == "refused"
    assert cross_run.code == "APPROVAL_STALE"


def test_permission_generation_move_is_refused(tmp_path):
    # The authoritative source still observes generation 3; a binding claiming
    # a newer one carries unbound evidence, never a second yes.
    _, facts, _, authorizer = make_environment(tmp_path)
    adapter, _, decision = settle_allow(tmp_path, facts=facts, authorizer=authorizer)
    moved = adapter.authorize_permission(
        binding(generation=RUNTIME_GENERATION + 1), decision)
    assert moved.kind == "refused"
    assert moved.code == "POLICY_SCOPE_UNVERIFIED"


def test_permission_after_restart_of_native_runtime_refused(tmp_path):
    # Rebuild the environment on the SAME store with the authoritative source
    # now observing a new generation: the old permit's stored generation no
    # longer agrees, so nothing is accepted.
    _, facts, _, authorizer = make_environment(tmp_path)
    adapter, _, decision = settle_allow(tmp_path, facts=facts, authorizer=authorizer)
    restarted = make_adapter(authorizer, evidence=evidence_provider(
        native="native-2", generation=RUNTIME_GENERATION + 1))
    result = restarted.authorize_permission(
        binding(native="native-2", generation=RUNTIME_GENERATION + 1),
        AcpPermissionDecision(native_session_id="native-2",
                              interaction_id=decision.interaction_id,
                              run_id=decision.run_id, option_id="allow"))
    assert result.kind == "refused"
    assert result.code == "APPROVAL_STALE"


def test_recorded_denial_is_final_never_resolves_to_accepted(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path)
    adapter = make_adapter(authorizer)
    approval_id = pending_approval_id(adapter)
    recorded = authorizer.decide(approval_id, 1, "deny", {"kind": "once"}, "req-deny",
                                 session_id="session-1")
    assert recorded.kind == "recorded"
    decision = AcpPermissionDecision(native_session_id=NATIVE_SESSION,
                                     interaction_id=approval_id, run_id="sub-1",
                                     option_id="deny")
    result = adapter.authorize_permission(binding(), decision)
    assert result.kind == "refused"
    assert result.code == "policy_deny"
    forged_yes = AcpPermissionDecision(native_session_id=NATIVE_SESSION,
                                       interaction_id=approval_id, run_id="sub-1",
                                       option_id="allow")
    denial = adapter.authorize_permission(binding(), forged_yes)
    assert denial.kind == "refused"
    assert denial.code == "APPROVAL_STALE"


# -- unknown is its own shape, enforced by the DTO ------------------------------

class _ExplodingAuthorizer:
    facts = None
    ceiling_provider = staticmethod(lambda: (admin_ceiling(),))
    intent_provider = staticmethod(lambda: None)

    def evaluate(self, **_kwargs):
        raise RuntimeError("the store vanished mid-decision")


def test_unresolvable_outcome_answers_unknown_shape_only(tmp_path):
    del tmp_path
    adapter = make_adapter(_ExplodingAuthorizer())
    result = adapter.authorize_submission(binding(), submission())
    assert result.kind == "unknown"
    assert result.operation_id == "sub-1"
    assert result.submission_id is None and result.code is None
    assert result.reason


def test_unknown_shape_cannot_carry_a_code_and_accepted_cannot_carry_both():
    with pytest.raises(ValueError):
        AcpAdmissionResult(kind="unknown", code="X", operation_id="op", reason="r")
    with pytest.raises(ValueError):
        AcpAdmissionResult(kind="accepted", submission_id="s", code="X")
    with pytest.raises(ValueError):
        AcpAdmissionResult(kind="refused", code="X", reason="r", submission_id="s")


def test_non_dto_input_never_reaches_accepted(tmp_path):
    _, _, _, authorizer = make_environment(tmp_path, intent=ALLOW_READ)
    adapter = make_adapter(authorizer)
    fake = type("FakeBinding", (), {"connection_id": "conn-1"})()
    result = adapter.authorize_submission(fake, submission(command="read"))
    assert result.kind in {"refused", "unknown"}
    result = adapter.authorize_permission(binding(), {"native_session_id": NATIVE_SESSION,
                                                      "interaction_id": "x",
                                                      "run_id": "y", "option_id": "allow"})
    assert result.kind in {"refused", "unknown"}


# -- plugin registration ---------------------------------------------------------

def test_plugin_registers_the_admission_port_and_keeps_the_authorizer(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    plugin = PermissionsBackendPlugin()
    registration = plugin.build(ServerPluginContext(
        plugin_id="permissions-backend", data_root=tmp_path, ports={"database": database}))
    port = registration.provided_ports[ACP_ADMISSION_PORT]
    assert isinstance(port, PermissionsAcpAdmission)
    assert type(port.public_acp_admission_port_version) is int
    assert port.public_acp_admission_port_version == ACP_ADMISSION_PORT_VERSION
    # Honest default: the current product composes NO authoritative native
    # session/generation source, so the port must NOT advertise readiness
    # (the checkpoint limitation stays true until composition wires one).
    assert port.ready is False
    assert port.authorize_submission(binding(), submission()).kind == "refused"
    # the §C1 authorizer port keeps existing consumers whole
    assert isinstance(registration.provided_ports["permissions.authorizer@1"], Authorizer)


def test_plugin_port_ready_only_when_composition_injects_evidence(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    plugin = PermissionsBackendPlugin(
        admission_native_evidence=evidence_provider(),
        admission_principal_provider=lambda _binding: "user-1",
        admission_server_instance_id="srv-1")
    registration = plugin.build(ServerPluginContext(
        plugin_id="permissions-backend", data_root=tmp_path, ports={"database": database}))
    port = registration.provided_ports[ACP_ADMISSION_PORT]
    assert port.ready is True
    result = port.authorize_permission(
        binding(), AcpPermissionDecision(native_session_id=NATIVE_SESSION,
                                         interaction_id="approval_missing",
                                         run_id="sub-9", option_id="allow"))
    assert result.kind == "refused"
    assert result.code == "APPROVAL_RESULT_UNKNOWN"
