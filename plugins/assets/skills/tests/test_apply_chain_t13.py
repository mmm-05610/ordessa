"""T13 — the Q1 half of "下一次用户提交时先应用再发送" on published types.

Driven exclusively through the `ordessa_harness_api` DTOs and a controlled
fake implementing the published `ConfigurationService`/runtime `resume`
protocol (no real model, no spawn, no filesystem):

* A/B sessions do not cross-contaminate;
* revisions moved -> refuse-then-NO-write (permit untouched);
* a failed apply does not clear profile overrides / session state — the
  chain mutates nothing it was handed;
* a terminal execution is not revived: a refused resume stays refused,
  never a fresh session;
* unknown never reports success — the effect level caps at the evidenced
  ceiling and `may_send` stays False;
* reload vs restart-and-resume is decided from the adapter's assessed
  capability, with `unsupported` reasoned.

The plan-time cross-facet conflict pre-check (against the model/Prompts
intent sets) has NO published seam in this tree — see the `apply_chain`
module docstring; the registration-time claim guard is what exists and is
proven in `test_harness_api_registration.py`.
"""
from __future__ import annotations

import pytest

from ordessa_harness_api import (
    ApplicationTarget, Confirmed, ContractError, DesiredFragment, ErrorCode,
    NotFound, Plan, ReconfigurationDecision, Refused, ResumeRequest,
    RuntimeConfirmed, RuntimeRefused, RuntimeUnknown, Unknown,
)
from ordessa_skills.api import evidence as ladder
from ordessa_skills.harness_adapters import apply_chain
from ordessa_skills.harness_adapters.base import HarnessAdapterError
from ordessa_skills.harness_adapters.capabilities import (
    AXES, NO_EVIDENCE, SUPPORTED, UNKNOWN, CapabilityFact, statement_for,
)

TARGET_A = ApplicationTarget(server_id="srv", session_id="sess-A",
                             channel_id="ch-A", runtime_generation=7)
TARGET_B = ApplicationTarget(server_id="srv", session_id="sess-B",
                             channel_id="ch-B", runtime_generation=7)


def _fragments(revision="snap-1", items=("alpha", "beta")):
    return apply_chain.fragments_for(
        item_ids=items, schema_version="1",
        business_refs=[f"asset:{name}" for name in items],
        source_revision=revision)


class FakeConfigurationService:
    """A controlled `ConfigurationService`: revision fences are keyed per
    target, permits and applies are counted, results are scripted."""

    def __init__(self, revisions=None):
        self.revisions = dict(revisions or {})
        self.plans = {}
        self.permit_calls = []
        self.apply_calls = []
        self.scripted = None       # result for the NEXT apply()
        self.plan_counter = 0

    def inspect(self, target):
        raise NotImplementedError

    def plan(self, target, desired_fragments, expected_revision):
        key = (target.session_id, target.channel_id, target.runtime_generation)
        current = self.revisions.setdefault(key, expected_revision)
        if current != expected_revision:
            return Refused(code=ErrorCode.STALE_PLAN,
                           diagnostics=("revision moved",),
                           original_state_preserved=True)
        self.plan_counter += 1
        plan = Plan(plan_id=f"plan-{self.plan_counter}", target=target,
                    desired_digest="d" * 8, before_revision=expected_revision,
                    native_version_ref="nv", provider_generation=target.runtime_generation,
                    authorization_revision="ar-1", secret_ref_revision="sr-0",
                    expires_at_utc="2099-01-01T00:00:00Z")
        self.plans[plan.plan_id] = (key, desired_fragments)
        return plan

    def apply(self, plan_id, operation_key, submission_permit):
        self.apply_calls.append((plan_id, operation_key))
        self.permit_calls.append(submission_permit)
        return self.scripted

    def query(self, operation_key):
        raise NotImplementedError

    def reconcile(self, operation_key):
        raise NotImplementedError


class FakeRuntime:
    def __init__(self, result):
        self.result = result
        self.resume_calls = []
        self.start_calls = 0

    def resume(self, request):
        assert isinstance(request, ResumeRequest)
        self.resume_calls.append(request)
        return self.result

    def start(self, launch_plan):  # must NEVER be reached as resume fallback
        self.start_calls += 1
        raise AssertionError("resume failure may not fall back to a new session")


def _confirmed():
    return Confirmed(operation_id="op-1", applied_revision="snap-1",
                     native_session_identity="nat-1", runtime_generation=7,
                     verification_evidence_ref="evidence:readback",
                     resource_changes=("mount:alpha",))


def _unknown():
    return Unknown(operation_id="op-2", phase="applying",
                   observed_effects=("journal row",),
                   pending_checks=("native readback",),
                   allowed_next_action="query")


# -- freeze -> plan -> apply ------------------------------------------------------


def test_plan_and_apply_confirms_at_the_evidenced_ceiling():
    service = FakeConfigurationService()
    fragments = _fragments()
    plan = apply_chain.plan_at_submission(service, TARGET_A, fragments,
                                         "snap-0")
    assert isinstance(plan, Plan)
    service.scripted = _confirmed()
    outcome = apply_chain.apply_before_send(
        service, plan=plan, operation_key="opk-1", submission_permit="permit-1",
        statement=statement_for("pi"))
    assert outcome.state == "applied" and outcome.may_send
    # placement content confirmed is STILL at most projected (loaded is an
    # unevidenced brand cell — the apply receipt is not a load observation):
    assert outcome.effect_level == ladder.PROJECTED
    assert service.permit_calls == ["permit-1"]


def test_revisions_moved_refuses_before_any_write_or_permit():
    service = FakeConfigurationService(revisions={
        (TARGET_A.session_id, TARGET_A.channel_id, TARGET_A.runtime_generation):
        "snap-older"})
    result = apply_chain.plan_at_submission(service, TARGET_A, _fragments(),
                                           "snap-1")
    assert isinstance(result, Refused)
    assert result.code == ErrorCode.STALE_PLAN
    assert result.original_state_preserved is True
    # refuse-then-no-write: nothing was planned, so nothing can apply.
    assert service.apply_calls == [] and service.permit_calls == []


def test_failed_apply_does_not_clear_stored_state_and_stops_the_send():
    service = FakeConfigurationService()
    fragments = _fragments()
    plan = apply_chain.plan_at_submission(service, TARGET_A, fragments,
                                         "snap-1")
    service.scripted = Refused(code=ErrorCode.AUTHORIZATION_REFUSED,
                               diagnostics=("permit refused",),
                               original_state_preserved=True,
                               operation_id="op-3")
    outcome = apply_chain.apply_before_send(
        service, plan=plan, operation_key="opk", submission_permit="nope",
        statement=statement_for("pi"))
    assert outcome.state == "refused" and not outcome.may_send
    assert outcome.result.original_state_preserved is True
    # the chain mutated NOTHING it was handed: the frozen fragments and the
    # stored revision face are byte-identical to the inputs (profile
    # overrides / session overrides live behind these revisions and the
    # failed apply never rewound them):
    assert fragments == _fragments("snap-1")
    assert service.revisions[(TARGET_A.session_id, TARGET_A.channel_id,
                              TARGET_A.runtime_generation)] == "snap-1"
    assert outcome.effect_level == ladder.UNKNOWN


def test_unknown_apply_never_reports_success():
    service = FakeConfigurationService()
    plan = apply_chain.plan_at_submission(service, TARGET_A, _fragments(), "s1")
    service.scripted = _unknown()
    outcome = apply_chain.apply_before_send(
        service, plan=plan, operation_key="opk", submission_permit="p",
        statement=statement_for("pi"))
    assert outcome.state == "unknown"
    assert outcome.may_send is False
    assert outcome.effect_level == ladder.UNKNOWN
    assert isinstance(outcome.result, Unknown)
    # the allowed next action stays query/reconcile, never "assume applied":
    assert outcome.result.allowed_next_action in ("query", "reconcile",
                                                  "operator-review")


# -- A/B isolation ------------------------------------------------------------------


def test_two_sessions_plan_and_apply_without_cross_contamination():
    service = FakeConfigurationService()
    plan_a = apply_chain.plan_at_submission(service, TARGET_A,
                                            _fragments("snap-A"), "snap-A")
    plan_b = apply_chain.plan_at_submission(service, TARGET_B,
                                            _fragments("snap-B",
                                                       items=("gamma",)),
                                            "snap-B")
    assert isinstance(plan_a, Plan) and isinstance(plan_b, Plan)
    # each plan is bound to ITS target and its own revision fence:
    assert plan_a.target == TARGET_A and plan_b.target == TARGET_B
    assert service.plans[plan_a.plan_id][0] != service.plans[plan_b.plan_id][0]
    service.scripted = _confirmed()
    apply_chain.apply_before_send(service, plan=plan_a, operation_key="oa",
                                  submission_permit="pa",
                                  statement=statement_for("pi"))
    # applying A's plan cannot move B's fence: a stale plan for B still
    # refuses after A's confirmed apply.
    assert service.revisions[(TARGET_B.session_id, TARGET_B.channel_id,
                              TARGET_B.runtime_generation)] == "snap-B"
    moved = apply_chain.plan_at_submission(service, TARGET_B,
                                           _fragments("snap-B2",
                                                      items=("gamma",)),
                                           "wrong-revision")
    assert isinstance(moved, Refused) and moved.code == ErrorCode.STALE_PLAN


# -- decisions on the published type ------------------------------------------------


def test_decision_comes_from_the_assessed_capability_per_brand():
    decision = apply_chain.reconfiguration_for(statement_for("pi"), ("inst-1",))
    assert isinstance(decision, ReconfigurationDecision)
    assert decision.mode == "restart-resume"  # reload unknown, resume proven
    hermes = apply_chain.reconfiguration_for(statement_for("hermes"), ())
    assert hermes.mode == "unsupported" and hermes.reason


def test_reload_supported_statement_maps_to_reload_mode():
    facts = {axis: CapabilityFact(axis=axis, value=UNKNOWN,
                                  evidence=NO_EVIDENCE) for axis in AXES}
    facts["reload"] = CapabilityFact(
        axis="reload", value=SUPPORTED,
        evidence="specs/011-q1-skills/research/brand-matrix.md:40")
    from ordessa_skills.harness_adapters.capabilities import CapabilityStatement
    statement = CapabilityStatement(harness_id="probe", facts=facts)
    decision = apply_chain.reconfiguration_for(statement, ("inst-9",))
    assert decision.mode == "reload"


# -- restart-and-resume without a blank-session fallback ------------------------------


def test_restart_resume_uses_the_published_request_and_a_refusal_stays_final():
    runtime = FakeRuntime(RuntimeRefused(code=ErrorCode.RESUME_UNAVAILABLE,
                                         reason="execution is terminal"))
    decision = apply_chain.reconfiguration_for(statement_for("codex"),
                                               ("inst-4",))
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="inst-4",
        expected_native_session_identity="nat-4", expected_generation=7)
    assert outcome.state == "refused" and not outcome.may_send
    assert len(runtime.resume_calls) == 1
    assert runtime.start_calls == 0  # never revived via a fresh session


def test_an_unprovable_resume_refuses_before_reaching_the_runtime():
    runtime = FakeRuntime(None)
    decision = apply_chain.reconfiguration_for(statement_for("claude-code"),
                                               ("inst-5",))
    # an unknown/invalid expected generation cannot prove "the SAME
    # session": the published ResumeRequest refuses, and the chain turns
    # that into a refusal WITHOUT ever calling resume (or start).
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="inst-5",
        expected_native_session_identity="nat-5",
        expected_generation=-1)
    assert outcome.state == "refused"
    assert runtime.resume_calls == [] and runtime.start_calls == 0


def test_resume_identity_must_match_the_frozen_observation():
    runtime = FakeRuntime(RuntimeRefused(code=ErrorCode.RESUME_UNAVAILABLE,
                                         reason="identity moved"))
    decision = apply_chain.reconfiguration_for(statement_for("pi"),
                                               ("inst-6",))
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="inst-6",
        expected_native_session_identity="other-native",
        expected_generation=7)
    assert outcome.state == "refused"
    assert runtime.resume_calls[0].expected_native_session_identity == \
        "other-native"  # the request itself pins the expected identity
    assert runtime.start_calls == 0


def test_unsupported_decision_never_calls_resume():
    runtime = FakeRuntime(None)
    decision = apply_chain.reconfiguration_for(statement_for("hermes"), ())
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="i", expected_native_session_identity="n",
        expected_generation=0)
    assert outcome.state == "refused"
    assert runtime.resume_calls == []


def test_fragments_are_published_desired_fragments():
    fragments = _fragments()
    assert all(isinstance(f, DesiredFragment) for f in fragments)
    assert {f.facet_id for f in fragments} == {"assets.skills"}
    assert fragments[0].source_revision == "snap-1"
    # a reset fragment may not smuggle a value (typed wall, not prose):
    with pytest.raises(ContractError):
        DesiredFragment(facet_id="assets.skills", item_id="x",
                        schema_version="1", business_ref="b",
                        source_revision="s", operation="reset", value={"a": 1})


# -- applied is by published TYPE, not by shape (round-3 findings) ------------------


def test_resume_confirmed_by_the_published_type_marks_applied():
    runtime = FakeRuntime(RuntimeConfirmed(
        instance_ref="inst-7", native_session_identity="nat-7",
        runtime_generation=7, evidence_ref="evidence:resume-readback"))
    decision = apply_chain.reconfiguration_for(statement_for("pi"),
                                               ("inst-7",))
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="inst-7",
        expected_native_session_identity="nat-7", expected_generation=7)
    assert outcome.state == "applied" and outcome.may_send
    assert isinstance(outcome.result, RuntimeConfirmed)
    assert outcome.effect_level == ladder.PROJECTED


def test_resume_runtime_refused_stays_refused():
    runtime = FakeRuntime(RuntimeRefused(code=ErrorCode.RESUME_UNAVAILABLE,
                                         reason="native refused the resume"))
    decision = apply_chain.reconfiguration_for(statement_for("pi"),
                                               ("inst-8",))
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="inst-8",
        expected_native_session_identity="nat-8", expected_generation=7)
    assert outcome.state == "refused" and not outcome.may_send
    assert isinstance(outcome.result, RuntimeRefused)
    assert runtime.start_calls == 0


def test_resume_runtime_unknown_stays_unknown():
    runtime = FakeRuntime(RuntimeUnknown(
        instance_ref="inst-9", observed_effects=("restart issued",),
        pending_checks=("native session readback",)))
    decision = apply_chain.reconfiguration_for(statement_for("pi"),
                                               ("inst-9",))
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="inst-9",
        expected_native_session_identity="nat-9", expected_generation=7)
    assert outcome.state == "unknown" and not outcome.may_send
    assert outcome.effect_level == ladder.UNKNOWN
    assert runtime.start_calls == 0


def test_resume_not_found_is_not_applied_but_unknown():
    # a NotFound resume result was NEVER observed as a confirmation; the
    # fail-open fallthrough would have called it applied — contracts.md
    # §可用性最少区分 keeps it unknown.
    runtime = FakeRuntime(NotFound(operation_key="opk-missing"))
    decision = apply_chain.reconfiguration_for(statement_for("pi"),
                                               ("inst-10",))
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="inst-10",
        expected_native_session_identity="nat-10", expected_generation=7)
    assert outcome.state == "unknown" and not outcome.may_send
    assert outcome.effect_level == ladder.UNKNOWN
    assert outcome.reason and "RuntimeConfirmed" in outcome.reason
    assert runtime.start_calls == 0


def test_resume_duck_typed_confirmed_shape_is_not_applied():
    class _DuckConfirmed:  # NOT the published RuntimeConfirmed type
        kind = "confirmed"

    runtime = FakeRuntime(_DuckConfirmed())
    decision = apply_chain.reconfiguration_for(statement_for("pi"),
                                               ("inst-11",))
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="inst-11",
        expected_native_session_identity="nat-11", expected_generation=7)
    assert outcome.state == "unknown" and not outcome.may_send
    assert outcome.effect_level == ladder.UNKNOWN
    assert runtime.start_calls == 0


def test_resume_plain_object_falls_to_unknown_not_applied():
    runtime = FakeRuntime(object())
    decision = apply_chain.reconfiguration_for(statement_for("pi"),
                                               ("inst-12",))
    outcome = apply_chain.resume_after_reconfiguration(
        runtime, decision, instance_ref="inst-12",
        expected_native_session_identity="nat-12", expected_generation=7)
    assert outcome.state == "unknown" and not outcome.may_send


# -- plan argument is type-validated before the service is touched --------------------


def test_apply_before_send_refuses_non_plan_with_typed_error_and_no_service_call():
    service = FakeConfigurationService()
    service.scripted = _confirmed()
    not_a_plan = Refused(code=ErrorCode.STALE_PLAN,
                         diagnostics=("plan never issued",),
                         original_state_preserved=True)
    with pytest.raises(HarnessAdapterError):
        apply_chain.apply_before_send(
            service, plan=not_a_plan, operation_key="opk",
            submission_permit="permit-1", statement=statement_for("pi"))
    # no native write, no permit consumed, no plan ever reached apply():
    assert service.apply_calls == []
    assert service.permit_calls == []
    assert service.plan_counter == 0


def test_apply_before_send_refuses_plan_shaped_duck_object():
    class _DuckPlan:  # Plan-shaped but NOT the published Plan type
        plan_id = "plan-duck"

    service = FakeConfigurationService()
    service.scripted = _confirmed()
    with pytest.raises(HarnessAdapterError):
        apply_chain.apply_before_send(
            service, plan=_DuckPlan(), operation_key="opk",
            submission_permit="permit-1", statement=statement_for("pi"))
    assert service.apply_calls == [] and service.permit_calls == []
