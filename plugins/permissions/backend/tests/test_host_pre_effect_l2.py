"""T021 (Q5): the REAL Server ACP admission fence driven to a pre-effect refusal.

This is the lane's L2 controlled Harness/ACP proof for the success criterion in
`docs/design/safety-controls/spec.md` ("at least one REAL pre-effect refusal
path") and the FR-02/04 rows of `docs/design/safety-controls/verification.md`
("ask/deny before the ACP tool actually executes; zero side effects").

What is real here, and what is not:

* the gate, the public port adapter and the relay fence are the host's own
  classes (`apps/server/src/ordessa_server/acp_admission.py`, driven exactly as
  `apps/server/src/ordessa_server/transport/http/app.py:297-306` drives them);
* the decision is this lane's: `PermissionsAcpAdmission` -> `Authorizer` ->
  `ApprovalFacts` on the real product database in a pytest tmp dir, under a
  signed admin ceiling;
* the agent is an in-process fake: a reviewed connection/transport pair whose
  `send_line` IS the effect recorder. Nothing reaches it unless the host gate
  admits the frame, so `transport.sent == []` is a direct measurement of
  "the tool never ran";
* no real model, no real ACP peer, no network, no user config, no Server
  process and no user data.

STEP-1 DETERMINATION - the seam is only HALF drivable from a plugin:

* (a) for the TOOL-EXECUTION fence: `AcpPermitAuthority.authorize_permission`
  answers a plain `bool` and the gate requires `is True`
  (`acp_admission.py:204`). A plugin can be that verifier with no host import
  at all - tests 3-5 drive it through the real gate.
* (b) for the SUBMISSION fence: the gate requires
  `isinstance(bound, BoundAdmission)` (`acp_admission.py:134`) where
  `BoundAdmission` is declared in the host module (`acp_admission.py:27-36`)
  and is NOT re-exported from `server_plugin_api` (that contract declares only
  four DTOs plus the port protocol). A structurally identical plugin-owned
  record is refused (test 8). The permit's `input_digest` must also equal the
  host's private canonicalisation (`acp_admission.py:63-90`, computed at `:120`),
  and only the host's `AcpAdmissionRefused` (`:21`, caught at `:383`) survives
  the adapter as a typed refusal - a plugin-raised exception collapses to
  `unknown` (`:385-387`, test 2b).
  So the composition, not this plugin, has to supply the permit record: the
  authority takes it as an injected binder and refuses outright when it is
  absent (tests 6, 7). The binder below is test-local and is the exact shape
  the product assembly must provide; no shipped composition installs an
  authority at all (`bootstrap/runtime.py:607`), which test 1 pins.
"""
from __future__ import annotations

import json
import re

import pytest
import server_plugin_api
from server_plugin_api import (
    ACP_ADMISSION_PORT,
    ACP_ADMISSION_PORT_VERSION,
    AcpAdmissionResult,
    AcpPermissionDecision,
    ServerPluginContext,
)

from ordessa_permissions_api import NativeReceipt
from ordessa_permissions_backend.admission import PermissionsAcpAdmission
from ordessa_permissions_backend.host_authority import (
    PermissionsHostAcpAuthority, PluginAdmissionRefused,
)

# The host's own admission classes: test-side only. Nothing under src/ imports
# them - tests/test_backend_dependency_direction.py holds that line.
from ordessa_server.acp_admission import (
    AcpAdmissionGate, AcpAdmissionPortAdapter, AcpAdmissionRefused,
    BoundAdmission, _digest, prompt_input,
)

from support import admin_ceiling, utc
from test_admission_port import (
    ALLOW_READ, NATIVE_SESSION, RUNTIME_GENERATION, binding as dto_binding,
    evidence_provider, make_adapter, make_environment, submission as dto_submission,
)

CONNECTION_ID = "conn-1"
LEDGER_SESSION = "session-1"
EXECUTION = "turn-1"
HARNESS_ID = "pi"
WORKSPACE_ID = "ws-1"
CONFIG_DIGEST = "b" * 64
GATE_NOW = 100.0
PERMIT_EXPIRES = 10_000.0


# -- the in-process ACP peer: the effect recorder --------------------------------

class RecordingTransport:
    """`send_line` is the only way a line reaches the Agent, so every entry in
    `sent` is one real side effect. The host gate is what gates it."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_line(self, text: str) -> None:
        self.sent.append(text)

    def terminate(self) -> None:
        pass


class FakeChannel:
    """Shaped like the host's live ACP connection: the identity the port
    adapter cross-checks (`acp_admission.py:327-346`) plus liveness."""

    def __init__(self, *, native: str | None = NATIVE_SESSION,
                 generation: int | None = RUNTIME_GENERATION,
                 transport: RecordingTransport | None = None) -> None:
        self.transport = transport or RecordingTransport()
        self.connection_id = CONNECTION_ID
        self.execution_id = EXECUTION
        self.session_id = LEDGER_SESSION
        self.harness_id = HARNESS_ID
        self.workspace_id = WORKSPACE_ID
        self.native_session_id = native
        self.runtime_generation = generation
        self.ended = False


class FakeRoutes:
    def __init__(self, channel: FakeChannel) -> None:
        self._channel = channel

    def resolve(self, kind: str, key: str):
        return self._channel if (kind, key) == ("acp-channel", CONNECTION_ID) else None


def relay(gate, channel: FakeChannel, frame: str) -> tuple[str, str]:
    """Mirror of the host relay (`transport/http/app.py:297-306`): admit first,
    only then hand the line to the Agent. Any non-relay outcome is zero effect."""
    try:
        gate.admit_client_frame(channel, frame)
    except AcpAdmissionRefused as exc:
        return "refused", exc.code
    except Exception as exc:  # noqa: BLE001 - the host relay also just stops
        return "dropped", type(exc).__name__
    channel.transport.send_line(frame)
    return "relayed", frame


def prompt_frame(submission_map: dict, *, request_id: int = 7) -> str:
    """The client frame the gate digests and matches against its permit."""
    session_id, blocks = prompt_input(submission_map)
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": "session/prompt",
                       "params": {"sessionId": session_id, "prompt": blocks}})


def permission_request_frame(*, request_id: int = 19,
                             options: tuple[str, ...] = ("allow", "deny")) -> str:
    """The Agent's own `session/request_permission` - the pre-effect ask."""
    return json.dumps({"jsonrpc": "2.0", "id": request_id,
                       "method": "session/request_permission",
                       "params": {"sessionId": NATIVE_SESSION,
                                  "toolCall": {"title": "run a command"},
                                  "options": [{"optionId": item, "kind": item}
                                              for item in options]}})


def permission_answer_frame(*, request_id: int = 19, option: str = "allow") -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id,
                       "result": {"outcome": {"outcome": "selected", "optionId": option}}})


def submission_map(*, sub: str = "sub-1", command: str | None = "bash",
                   text: str = "hello") -> dict:
    return {"submissionId": sub, "nativeSessionId": NATIVE_SESSION, "text": text,
            "attachments": [], "configurationDigest": CONFIG_DIGEST, "commandId": command}


class CountingAdmission(PermissionsAcpAdmission):
    """The lane's own port, with the calls the host authority made visible: a
    refusal must be provably the authorizer's, never an early bail."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[str] = []

    def authorize_submission(self, binding, submission):
        self.calls.append("submission")
        return super().authorize_submission(binding, submission)

    def authorize_permission(self, binding, decision):
        self.calls.append("permission")
        return super().authorize_permission(binding, decision)


def composition_permit_binder(*, generation: int = RUNTIME_GENERATION,
                              principal: str = "user-1"):
    """THE one test-local piece: the permit record this plugin cannot mint.

    It is exactly the job the public contract has to hand the composition: it
    binds the host's private canonicalisation (`prompt_input` + `_digest`,
    `acp_admission.py:63-90,120`) into the host-owned frozen record
    (`acp_admission.py:27-36`). Nothing under src/ builds it and no shipped
    product installs one; test 8 pins why, and test 6 pins that its absence is
    a refusal rather than a silent pass."""
    issued: list[BoundAdmission] = []

    def bind(connection, submission):
        native_id, blocks = prompt_input(submission)
        record = BoundAdmission(
            principal, connection.connection_id, native_id, generation,
            submission["submissionId"],
            _digest({"sessionId": native_id, "prompt": blocks}),
            submission["configurationDigest"], PERMIT_EXPIRES)
        issued.append(record)
        return record

    bind.issued = issued  # type: ignore[attr-defined]
    return bind


def authority_for(tmp_path, *, ceilings=(admin_ceiling(),), intent=None, binder=None):
    """Real store + real authorizer + this lane's port + the host authority."""
    database, facts, _policies, authorizer = make_environment(
        tmp_path, ceilings=ceilings, intent=intent)
    port = CountingAdmission(
        authorizer=authorizer, native_evidence=evidence_provider(),
        principal_provider=lambda _binding: "user-1", server_instance_id="srv-1")
    authority = PermissionsHostAcpAuthority(admission=port, permit_binder=binder)
    channel = FakeChannel()
    gate = AcpAdmissionGate(authority, clock=lambda: GATE_NOW)
    adapter = AcpAdmissionPortAdapter(gate, FakeRoutes(channel))
    return database, facts, authorizer, port, authority, gate, adapter, channel


def mint_pending_approval(port: CountingAdmission, facts, *, sub: str = "ask-1") -> str:
    """The ask as the §C1 chain really produces it: a submission whose ruling
    is PendingApproval records a real open fact and refuses the fence."""
    result = port.authorize_submission(dto_binding(), dto_submission(sub=sub, command="bash"))
    assert result.kind == "refused"
    assert result.code == "APPROVAL_RESULT_UNKNOWN"
    approval_id = re.search(r"(approval_[0-9a-f]{32})", result.reason).group(1)
    assert facts.open_for_execution(EXECUTION), "the ask must be a real open fact"
    return approval_id


def settle_allow(authorizer, facts, approval_id: str, *, sub: str = "ask-1",
                 receipt: bool = True) -> None:
    recorded = authorizer.decide(approval_id, 1, "allow", {"kind": "once"},
                                 f"req-{sub}", session_id=LEDGER_SESSION)
    assert recorded.kind == "recorded"
    if receipt:
        facts.record_native_receipt(approval_id, NativeReceipt.of(
            native_request_id=sub, approval_id=approval_id, confirmed=True, observed_at=utc()))


def grant_usage_count(database, approval_id: str) -> int:
    with database.read() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM server_approval_grant_usage WHERE approval_id=?",
            (approval_id,)).fetchone()[0])


def permission_map(approval_id: str, *, sub: str = "ask-1", option: str = "allow") -> dict:
    return {"nativeSessionId": NATIVE_SESSION, "interactionId": approval_id,
            "runId": sub, "optionId": option}


# -- 1. the shipped composition's own baseline: no authority, nothing passes ----

def test_absent_authority_gate_refuses_the_submission_and_the_prompt_pre_effect(tmp_path):
    """`bootstrap/runtime.py:607` installs `AcpAdmissionGate()` with no
    authority, so that absence must be fail-closed, never permissive."""
    del tmp_path
    channel = FakeChannel()
    gate = AcpAdmissionGate(clock=lambda: GATE_NOW)
    adapter = AcpAdmissionPortAdapter(gate, FakeRoutes(channel))
    assert adapter.ready is False  # the host never advertises a usable capability

    with pytest.raises(AcpAdmissionRefused) as submission:
        gate.authorize_submission(channel, submission_map())
    assert submission.value.code == "CAPABILITY_UNSUPPORTED"
    with pytest.raises(AcpAdmissionRefused) as permission:
        gate.authorize_permission(channel, permission_map("approval_whatever"))
    assert permission.value.code == "CAPABILITY_UNSUPPORTED"

    refused = adapter.authorize_submission(dto_binding(), dto_submission())
    assert refused.kind == "refused"
    assert refused.code == "CAPABILITY_UNSUPPORTED"
    assert relay(gate, channel, prompt_frame(submission_map()))[0] != "relayed"
    assert channel.transport.sent == []  # the Agent never got the prompt


# -- 2. a hard ceiling denial, decided by this lane, enforced by the host -------

def test_signed_ceiling_deny_refuses_at_the_host_fence_before_any_effect(tmp_path):
    """FR-02: the ruling happens before the tool, and a user intent that would
    widen it loses to the signed admin ceiling. The fence is the host's."""
    ceiling = admin_ceiling(deny=[{"key": "read", "action": "deny"}], maximumExposure="none")
    _database, facts, _authorizer, port, _authority, gate, _adapter, channel = authority_for(
        tmp_path, ceilings=(ceiling,), intent=ALLOW_READ)

    with pytest.raises(PluginAdmissionRefused) as refused:
        gate.authorize_submission(channel, submission_map(command="read"))
    assert refused.value.code == "POLICY_CEILING_VIOLATION"
    assert port.calls == ["submission"]  # the authorizer really was consulted

    # ...and the effect fence stayed shut: with no permit the prompt frame
    # cannot be relayed, so the Agent receives nothing at all.
    assert relay(gate, channel, prompt_frame(submission_map(command="read")))[0] != "relayed"
    assert channel.transport.sent == []
    # a hard denial writes no approval and no grant: nothing is pending either.
    assert facts.open_for_execution(EXECUTION) == []


def test_plugin_authority_refusal_loses_its_stable_code_through_the_host_adapter(tmp_path):
    """The gap named G2, measured not assumed: only the host's own refusal
    type survives the public port adapter as a typed refusal, so a plugin
    authority's coded denial is reported as `unknown` - still no admission."""
    ceiling = admin_ceiling(deny=[{"key": "read", "action": "deny"}], maximumExposure="none")
    _db, _facts, _auth, _port, _authority, _gate, adapter, _channel = authority_for(
        tmp_path, ceilings=(ceiling,), intent=ALLOW_READ)
    result = adapter.authorize_submission(
        dto_binding(), dto_submission(command="read", sub="sub-1"))
    assert result.kind == "unknown"
    assert result.code is None and result.submission_id is None
    assert result.operation_id == "sub-1"


# -- 3. the ask: refused at the fence, recorded as a real pending fact ----------

def test_ask_is_not_admitted_until_the_receipt_lands_and_the_fence_holds(tmp_path):
    database, facts, authorizer, _port, _authority, gate, _adapter, channel = authority_for(
        tmp_path)

    with pytest.raises(PluginAdmissionRefused) as refused:
        gate.authorize_submission(channel, submission_map(command="bash"))
    assert refused.value.code == "APPROVAL_RESULT_UNKNOWN"
    approval_id = re.search(r"(approval_[0-9a-f]{32})", refused.value.args[0]).group(1)
    assert [row["approvalId"] for row in facts.open_for_execution(EXECUTION)] == [approval_id]
    assert relay(gate, channel, prompt_frame(submission_map(command="bash")))[0] != "relayed"
    assert channel.transport.sent == []

    # The user said allow but the native owner confirmed nothing: the
    # permission fence still answers not-True, and the grant is NOT spent.
    settle_allow(authorizer, facts, approval_id, sub="sub-1", receipt=False)
    gate.observe_agent_frame(CONNECTION_ID, permission_request_frame())
    with pytest.raises(AcpAdmissionRefused) as unconfirmed:
        gate.authorize_permission(channel, permission_map(approval_id, sub="sub-1"))
    assert unconfirmed.value.code == "AUTHORIZATION_REFUSED"
    assert facts.grant_fields(approval_id)["consumed"] is False
    assert relay(gate, channel, permission_answer_frame())[0] != "relayed"
    assert channel.transport.sent == []

    # The receipt lands: the recorded allow becomes actionable, exactly once.
    facts.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id="sub-1", approval_id=approval_id, confirmed=True, observed_at=utc()))
    assert gate.authorize_permission(channel, permission_map(approval_id, sub="sub-1")) == {
        "kind": "accepted", "submissionId": approval_id}
    assert relay(gate, channel, permission_answer_frame())[0] == "relayed"
    assert channel.transport.sent == [permission_answer_frame()]
    assert relay(gate, channel, permission_answer_frame())[0] == "refused"
    assert len(channel.transport.sent) == 1
    assert grant_usage_count(database, approval_id) == 1


# -- 4. a permission identity the store never recorded is not-True --------------

def test_forged_interaction_id_makes_the_host_permission_fence_raise(tmp_path):
    _database, _facts, _authorizer, port, _authority, gate, _adapter, channel = authority_for(
        tmp_path)
    gate.observe_agent_frame(CONNECTION_ID, permission_request_frame())

    with pytest.raises(AcpAdmissionRefused) as refused:
        gate.authorize_permission(channel, permission_map("approval_never_minted"))
    assert refused.value.code == "AUTHORIZATION_REFUSED"
    assert "permission verifier refused" in str(refused.value)
    assert port.calls == ["permission"]
    # nothing was recorded, so the answer cannot reach the Agent at all
    assert relay(gate, channel, permission_answer_frame())[0] == "refused"
    assert channel.transport.sent == []


def test_cross_run_identity_mismatch_is_refused_before_the_tool_runs(tmp_path):
    database, facts, authorizer, port, _authority, gate, _adapter, channel = authority_for(
        tmp_path)
    approval_id = mint_pending_approval(port, facts)
    settle_allow(authorizer, facts, approval_id)
    gate.observe_agent_frame(CONNECTION_ID, permission_request_frame())

    moved = permission_map(approval_id, sub="some-other-native-request")
    with pytest.raises(AcpAdmissionRefused):
        gate.authorize_permission(channel, moved)
    assert facts.grant_fields(approval_id)["consumed"] is False
    assert grant_usage_count(database, approval_id) == 0
    assert relay(gate, channel, permission_answer_frame())[0] == "refused"
    assert channel.transport.sent == []

    # the honest answer still works after the mismatch was refused
    assert gate.authorize_permission(channel, permission_map(approval_id))["kind"] == "accepted"


def test_option_that_contradicts_the_recorded_verdict_never_admits(tmp_path):
    """The gate only checks the option was offered; the verdict this port
    records is the authority, so a contradictory option is not-True."""
    database, facts, authorizer, port, _authority, gate, _adapter, channel = authority_for(
        tmp_path)
    approval_id = mint_pending_approval(port, facts)
    settle_allow(authorizer, facts, approval_id)
    gate.observe_agent_frame(CONNECTION_ID, permission_request_frame())

    with pytest.raises(AcpAdmissionRefused):
        gate.authorize_permission(channel, permission_map(approval_id, option="deny"))
    assert facts.grant_fields(approval_id)["consumed"] is False
    assert grant_usage_count(database, approval_id) == 0
    assert relay(gate, channel, permission_answer_frame(option="deny"))[0] == "refused"
    assert channel.transport.sent == []


# -- 5. one permit, one effect, and a replay that cannot earn a second ---------

def test_full_chain_accepts_once_relays_once_and_replay_refuses_approval_stale(tmp_path):
    """The whole controlled L2 path: public port adapter -> host gate ->
    this lane's authority -> this lane's port -> Authorizer -> ApprovalFacts."""
    database, facts, authorizer, port, _authority, gate, adapter, channel = authority_for(
        tmp_path, intent=ALLOW_READ, binder=composition_permit_binder())

    # the prompt for an intent-allowed tool is admitted, then relayed once
    admitted = adapter.authorize_submission(dto_binding(), dto_submission(command="read"))
    assert admitted.kind == "accepted" and admitted.submission_id == "sub-1"
    assert relay(gate, channel, prompt_frame(submission_map(command="read")))[0] == "relayed"
    assert len(channel.transport.sent) == 1
    # the prompt request id is one use: replaying the same frame is refused
    assert relay(gate, channel, prompt_frame(submission_map(command="read")))[0] == "refused"
    assert len(channel.transport.sent) == 1

    # the Agent asks for the side-effecting tool; the user allows; the native
    # owner confirms.
    approval_id = mint_pending_approval(port, facts)
    settle_allow(authorizer, facts, approval_id)
    gate.observe_agent_frame(CONNECTION_ID, permission_request_frame())
    decision = AcpPermissionDecision(native_session_id=NATIVE_SESSION,
                                     interaction_id=approval_id, run_id="ask-1",
                                     option_id="allow")

    first = adapter.authorize_permission(dto_binding(), decision)
    assert first.kind == "accepted" and first.submission_id == approval_id
    # a second authorize on the live fence is reconciliation, not a second permit
    calls_before = port.calls.count("permission")
    assert adapter.authorize_permission(dto_binding(), decision).kind == "unknown"
    assert port.calls.count("permission") == calls_before
    assert relay(gate, channel, permission_answer_frame())[0] == "relayed"
    assert len(channel.transport.sent) == 2
    assert relay(gate, channel, permission_answer_frame())[0] == "refused"
    assert len(channel.transport.sent) == 2
    assert grant_usage_count(database, approval_id) == 1
    assert facts.grant_fields(approval_id)["consumed"] is True

    # the store's own answer to a replay is APPROVAL_STALE: no second permit
    replayed = port.authorize_permission(dto_binding(), decision)
    assert replayed.kind == "refused" and replayed.code == "APPROVAL_STALE"

    # a fence that lost its volatile facts (a restart, or a relay that re-asks)
    # cannot earn a second yes either: the host raises on not-True.
    second_gate = AcpAdmissionGate(
        PermissionsHostAcpAuthority(admission=port), clock=lambda: GATE_NOW)
    second_gate.observe_agent_frame(CONNECTION_ID, permission_request_frame())
    with pytest.raises(AcpAdmissionRefused) as restart:
        second_gate.authorize_permission(channel, permission_map(approval_id))
    assert "permission verifier refused" in str(restart.value)
    assert relay(second_gate, channel, permission_answer_frame())[0] == "refused"
    assert len(channel.transport.sent) == 2
    assert grant_usage_count(database, approval_id) == 1


# -- 6. an admitted submission needs the composition's permit record -----------

def test_policy_accept_without_a_permit_record_admits_nothing(tmp_path):
    """This lane cannot mint the host's frozen permit record, so even a tool
    the policy allows is refused outright and nothing is relayed - the seam's
    absence is never a pass-through."""
    _database, facts, _authorizer, port, _authority, gate, _adapter, channel = authority_for(
        tmp_path, intent=ALLOW_READ)

    with pytest.raises(PluginAdmissionRefused) as refused:
        gate.authorize_submission(channel, submission_map(command="read"))
    assert refused.value.code == "CAPABILITY_UNSUPPORTED"
    assert port.calls == ["submission"], "the ruling is made, then the seam refuses"
    assert relay(gate, channel, prompt_frame(submission_map(command="read")))[0] == "refused"
    assert channel.transport.sent == []
    assert facts.open_for_execution(EXECUTION) == []


def test_unmintable_permit_after_an_approval_spends_the_grant_and_still_refuses(tmp_path):
    """Registered hazard of the half-open seam, measured not hidden: the ruling
    is made before the refusal, so an approval-bound allow burns its one-use
    grant while admitting nothing. A composition must therefore never install
    this authority without a permit binder."""
    database, facts, authorizer, port, _authority, gate, _adapter, channel = authority_for(
        tmp_path)
    approval_id = mint_pending_approval(port, facts, sub="sub-1")
    settle_allow(authorizer, facts, approval_id, sub="sub-1")

    with pytest.raises(PluginAdmissionRefused) as refused:
        gate.authorize_submission(channel, submission_map(command="bash", sub="sub-1"))
    assert refused.value.code == "CAPABILITY_UNSUPPORTED"
    assert relay(gate, channel, prompt_frame(submission_map(command="bash",
                                                            sub="sub-1")))[0] == "refused"
    assert channel.transport.sent == []
    assert grant_usage_count(database, approval_id) == 1
    assert facts.grant_fields(approval_id)["consumed"] is True
    # and the spent grant cannot be re-earned by asking the port again
    assert port.authorize_permission(dto_binding(), AcpPermissionDecision(
        native_session_id=NATIVE_SESSION, interaction_id=approval_id, run_id="sub-1",
        option_id="allow")).code == "APPROVAL_STALE"


def test_approved_submission_binds_a_permit_only_the_composition_can_mint(tmp_path):
    """With the host-owned record supplied by the composition, the same policy
    ruling produces a real one-use admission; the binder is called exactly
    once and only the matching frame can consume it."""
    binder = composition_permit_binder()
    _database, _facts, _authorizer, _port, _authority, gate, _adapter, channel = authority_for(
        tmp_path, intent=ALLOW_READ, binder=binder)

    assert gate.authorize_submission(channel, submission_map(command="read")) == {
        "kind": "accepted", "submissionId": "sub-1"}
    assert len(binder.issued) == 1
    bound = binder.issued[0]
    assert (bound.connection_id, bound.submission_id, bound.runtime_generation) == (
        CONNECTION_ID, "sub-1", RUNTIME_GENERATION)
    assert relay(gate, channel, prompt_frame(submission_map(command="read")))[0] == "relayed"
    assert len(channel.transport.sent) == 1
    # a moved payload cannot ride the same permit
    assert relay(gate, channel,
                 prompt_frame(submission_map(command="read", text="changed")))[0] == "refused"
    assert len(channel.transport.sent) == 1
    # and the binder is never run twice for one admission
    assert len(binder.issued) == 1


# -- 7. unobserved channel evidence is never a pass-through --------------------

def test_channel_without_observed_native_evidence_is_refused(tmp_path):
    """The ACP owner's own binding shape (harness plugin.py:117-125) carries no
    native session and no runtime generation; the authority must refuse rather
    than invent them."""
    _database, _facts, _authorizer, port, authority, _gate, _adapter, _channel = authority_for(
        tmp_path, intent=ALLOW_READ)
    bare = FakeChannel(native=None, generation=None)
    with pytest.raises(PluginAdmissionRefused) as refused:
        authority.authorize_submission(bare, submission_map(command="read"))
    assert refused.value.code == "POLICY_SCOPE_UNVERIFIED"
    assert port.calls == ["submission"]
    assert authority.authorize_permission(bare, json.loads(permission_request_frame())["params"],
                                          permission_map("approval_x")) is False


def test_authority_answers_no_permit_when_the_port_is_unavailable(tmp_path):
    """A port that cannot answer (no authority installed) is never a yes: the
    submission half raises, the permission half answers not-True."""
    del tmp_path
    broken = PermissionsAcpAdmission(authorizer=None)
    authority = PermissionsHostAcpAuthority(admission=broken)
    channel = FakeChannel()
    with pytest.raises(PluginAdmissionRefused) as refused:
        authority.authorize_submission(channel, submission_map(command="read"))
    assert refused.value.code == "POLICY_ADAPTER_MISSING"
    assert authority.authorize_permission(channel, json.loads(permission_request_frame())["params"],
                                          permission_map("approval_x")) is False


# -- 8. the blocker, pinned so it cannot be silently assumed fixed --------------

def test_permit_record_and_authority_are_still_host_owned(tmp_path):
    """G1 (submission half): a plugin cannot be the submission authority.

    Pinned two ways, because a silent relaxation would otherwise let a later
    change claim this as already proven."""
    del tmp_path
    for name in ("BoundAdmission", "AcpPermitAuthority", "AcpAdmissionRefused"):
        assert not hasattr(server_plugin_api, name), name

    class LookAlikeAuthority:
        """Structurally complete, semantically correct - and refused."""

        def authorize_submission(self, connection, submission):
            native_id, blocks = prompt_input(submission)
            return type("Permit", (), {
                "principal": "user-1", "connection_id": connection.connection_id,
                "native_session_id": native_id, "runtime_generation": RUNTIME_GENERATION,
                "submission_id": submission["submissionId"],
                "input_digest": _digest({"sessionId": native_id, "prompt": blocks}),
                "configuration_digest": submission["configurationDigest"],
                "expires_at": PERMIT_EXPIRES})()

        def authorize_permission(self, connection, request, decision):
            del connection, request, decision
            return True

    channel = FakeChannel()
    gate = AcpAdmissionGate(LookAlikeAuthority(), clock=lambda: GATE_NOW)
    with pytest.raises(AcpAdmissionRefused) as refused:
        gate.authorize_submission(channel, submission_map(command="read"))
    assert refused.value.code == "AUTHORIZATION_REFUSED"
    assert "permit binding is invalid" in str(refused.value)
    assert relay(gate, channel, prompt_frame(submission_map(command="read")))[0] == "refused"
    assert channel.transport.sent == []


def test_the_authority_module_imports_no_host_internals() -> None:
    """The dependency direction holds the line: `src/` may not even name the
    host, so the permit record can only ever be injected by the composition."""
    import ast
    import pathlib

    path = (pathlib.Path(__file__).resolve().parents[1]
            / "src" / "ordessa_permissions_backend" / "host_authority.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    assert roots <= {"__future__", "typing", "server_plugin_api"}, roots


# -- 9. the ACP owner accepts this lane's port by its version marker -----------

def test_harness_acp_owner_admits_this_lanes_port_and_refuses_pre_effect(tmp_path):
    from ordessa_harness.server_acp.plugin import (
        AcpChannelServerPlugin, PLUGIN_ID as ACP_OWNER_ID)

    class Ledger:
        def create_session(self, **_kwargs):
            return "accepted", {"session_id": LEDGER_SESSION}

        def create_turn(self, **_kwargs):
            return True, "accepted", {"turn_id": EXECUTION}

        def finish_cancelled(self, *_args, **_kwargs):
            pass

    class Profiles:
        def get(self, _profile_id):
            return {"config_revision": 0, "config_object_digest": "sha256:profile"}

    database, facts, policies, authorizer = make_environment(tmp_path, intent=ALLOW_READ)
    del facts, policies
    port = make_adapter(authorizer)
    assert type(port.public_acp_admission_port_version) is int
    assert port.public_acp_admission_port_version == ACP_ADMISSION_PORT_VERSION
    assert port.ready is True

    channel_transport = RecordingTransport()

    def launch(**_kwargs):
        return channel_transport

    plugin = AcpChannelServerPlugin(launch=launch)
    registration = plugin.build(ServerPluginContext(
        plugin_id=ACP_OWNER_ID, data_root=None,
        ports={"workspace.service": object(), "sessions.records": Ledger(),
               "profiles.records": Profiles(), ACP_ADMISSION_PORT: port}))
    registry = registration.provided_ports["acp.channels"]
    opened = registry.acquire(harness_id=HARNESS_ID, workspace_id="workspace-1",
                              profile_id="profile-1", cwd=str(tmp_path))
    methods = {descriptor.method_id: descriptor for descriptor in registration.methods}
    submit = methods["acp.submission.authorize"]
    # the owner's version + readiness gate accepts this lane's port object
    assert submit.availability() == (True, None)

    answer = submit.handler({"connectionId": opened["connectionId"], "submission": {
        "submissionId": "sub-1", "nativeSessionId": NATIVE_SESSION, "text": "hello",
        "attachments": [], "configurationDigest": CONFIG_DIGEST, "commandId": "read"}})
    # ... and refuses before anything is relayed: the owner's own binding
    # carries no observed native session or generation (registered G5).
    assert answer["kind"] == "refused"
    assert answer["code"] == "POLICY_SCOPE_UNVERIFIED"
    assert "no observed native session" in answer["reason"]
    assert channel_transport.sent == []
    plugin._dispose()
    assert submit.availability()[0] is False
    del database


def test_the_public_port_alone_grants_no_authority() -> None:
    """A version marker is not an authority: the host gate takes only the
    Mapping-shaped authority surface, never this lane's DTO port."""
    channel = FakeChannel()
    gate = AcpAdmissionGate(clock=lambda: GATE_NOW)
    port = PermissionsAcpAdmission(authorizer=None)
    with pytest.raises(AcpAdmissionRefused):
        gate.authorize_submission(channel, submission_map())
    assert port.ready is False
    assert isinstance(port.authorize_submission(dto_binding(), dto_submission()),
                      AcpAdmissionResult)
