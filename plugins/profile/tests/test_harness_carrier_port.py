"""G09-G12 chain through the real harness-api carrier DTOs.

These tests drive the same switch flow as the controlled-fixture port, but
across ``HarnessApiConfigPort`` — i.e. through ``ordessa_harness_api``
`ConfigurationService` carrier DTOs (DesiredFragment/Plan/Confirmed/Refused/
Unknown) as delivered via chat-api-r3.  The *service behind the carrier* is
still a controlled double: a real native adapter needs the published
``codex/011-harness-api-ready`` checkpoint plus a live Harness.
"""
from __future__ import annotations

import pytest

from conftest import ScriptedProvider, make_core
from ordessa_profile import ProfileError
from ordessa_profile.harness_port_adapter import (
    HarnessApiConfigPort,
    PermitUnavailable,
)

MODEL = ScriptedProvider(
    "model_selection", ("model",), applies=frozenset({"pi"}),
    valid={"m1", "m2", "m3"},
)


class CarrierServiceDouble:
    """``ordessa_harness_api.ConfigurationService`` double: validates real
    carrier DTOs on every call and scripts the verdict."""

    def __init__(self, *, apply_outcome="confirmed", reconcile_outcome="confirmed"):
        from ordessa_harness_api import ApplicationTarget
        self.target = ApplicationTarget("fixture-server", "S", "fixture-channel", 7)
        self.apply_outcome = apply_outcome
        self.reconcile_outcome = reconcile_outcome
        self.calls: list[tuple[str, int]] = []
        self._plans: dict[str, int] = {}
        self._n = 0

    def inspect(self, target):
        from ordessa_harness_api import ConfigurationCapabilities
        self.calls.append(("inspect", target.runtime_generation))
        return ConfigurationCapabilities(target=target, capabilities=())

    def plan(self, target, desired_fragments, expected_revision):
        from ordessa_harness_api import Plan
        self.calls.append(("plan", target.runtime_generation))
        assert desired_fragments, "plan without fragments is meaningless"
        for fragment in desired_fragments:
            assert fragment.schema_version
            assert fragment.source_revision.startswith("profile@")
        self._n += 1
        plan_id = f"plan-{self._n}"
        self._plans[plan_id] = self._n
        return Plan(
            plan_id=plan_id, target=target,
            desired_digest=f"sha256:plan-{self._n}",
            before_revision="before-r1", native_version_ref="native-ref-1",
            provider_generation=self._n, authorization_revision="auth-r1",
            secret_ref_revision="secret-r1", expires_at_utc="2026-12-31T00:00:00Z",
        )

    def apply(self, plan_id, operation_key, submission_permit):
        from ordessa_harness_api import (
            Confirmed, Refused, Unknown, ErrorCode,
        )
        self.calls.append(("apply", self._plans.get(plan_id, -1)))
        assert submission_permit == "permit-1", "carrier requires a host permit"
        if self.apply_outcome == "confirmed":
            return Confirmed(
                operation_id=operation_key, applied_revision="rev-after-1",
                native_session_identity="native-sess-1", runtime_generation=7,
                verification_evidence_ref="evidence-ref-1",
                resource_changes=("config-1",))
        if self.apply_outcome == "refused":
            return Refused(
                code=ErrorCode.ISOLATION_UNPROVEN,
                diagnostics=("shared process isolation unproven",),
                original_state_preserved=True, operation_id=operation_key)
        return Unknown(
            operation_id=operation_key, phase="applying",
            observed_effects=("partial-1",),
            pending_checks=("native-verify",))

    def query(self, operation_key):
        raise NotImplementedError

    def reconcile(self, operation_key):
        from ordessa_harness_api import (
            Confirmed, Refused, Unknown, ErrorCode,
        )
        self.calls.append(("reconcile", 0))
        if self.reconcile_outcome == "confirmed":
            return Confirmed(
                operation_id=operation_key, applied_revision="rev-after-2",
                native_session_identity="native-sess-1", runtime_generation=8,
                verification_evidence_ref="evidence-ref-2",
                resource_changes=("config-2",))
        if self.reconcile_outcome == "refused":
            return Refused(
                code=ErrorCode.VERIFICATION_MISMATCH,
                diagnostics=("mismatch",), original_state_preserved=True,
                operation_id=operation_key)
        return Unknown(
            operation_id=operation_key, phase="reconciling",
            observed_effects=(), pending_checks=("still-checking",))


_DEFAULT_PERMIT = object()


def carrier_world(tmp_path, *, service, permit_provider=_DEFAULT_PERMIT):
    core = make_core(
        tmp_path, providers=(MODEL,),
        config_port=HarnessApiConfigPort(
            service,
            target_resolver=lambda ref: service.target,
            permit_provider=(lambda ref, plan_id: "permit-1")
            if permit_provider is _DEFAULT_PERMIT else permit_provider,
            schema_version_of=lambda facet_id: "1.0.0",
            revision_provider=lambda ref: "base-1",
        ),
    )
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m2"}])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    return core, a, b


def test_carrier_confirmed_switch_records_carrier_receipt(tmp_path):
    service = CarrierServiceDouble()
    core, a, b = carrier_world(tmp_path, service=service)
    core.sessions.select_profile("s1", session_id="S", profile_id=b["profile_id"])
    ticket = core.sessions.begin_turn("t1", session_id="S")
    assert ticket["applied_switch"] is True
    receipt = ticket["receipt"]
    assert receipt["evidence_kind"] == "harness-api-confirmed"
    assert receipt["runtime_generation"] == "gen-7"
    assert receipt["config_digest"] == "applied-revision:rev-after-1"
    assert receipt["execution_id"] == "native-sess-1"
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == b["profile_id"]
    assert config["evidence"]["journal"]["state"] == "confirmed"
    ops = [op for op, _ in service.calls]
    assert ops == ["inspect", "plan", "apply"]  # full C4 chain, in order


def test_carrier_refusal_is_retriable_and_preserves_state_g08(tmp_path):
    service = CarrierServiceDouble(apply_outcome="refused")
    core, a, b = carrier_world(tmp_path, service=service)
    core.sessions.select_profile("s1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "pending"  # retriable, not recovery
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["evidence"]["journal"]["state"] == "rejected"
    # a healthy retry on a fresh carrier applies cleanly
    retry_service = CarrierServiceDouble()
    core.config_port = HarnessApiConfigPort(
        retry_service,
        target_resolver=lambda ref: retry_service.target,
        permit_provider=lambda ref, plan_id: "permit-1",
        schema_version_of=lambda facet_id: "1.0.0",
        revision_provider=lambda ref: "base-1",
    )
    ticket = core.sessions.begin_turn("t2", session_id="S")
    assert ticket["applied_switch"] is True


def test_carrier_unknown_blocks_and_reconcile_settles_g10_g11(tmp_path):
    service = CarrierServiceDouble(apply_outcome="unknown")
    core, a, b = carrier_world(tmp_path, service=service)
    core.sessions.select_profile("s1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SESSION_NEEDS_RECOVERY"
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "needs_recovery"
    assert config["evidence"]["journal"]["state"] == "unknown"
    assert core.sessions.turns("S") == []
    # reconcile through the same carrier settles with carrier evidence
    service.reconcile_outcome = "confirmed"
    result = core.sessions.reconcile("r1", session_id="S")
    assert result["state"] == "confirmed-current"
    assert result["receipt"]["config_digest"] == "applied-revision:rev-after-2"
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "settled"
    assert config["current"]["profile_id"] == b["profile_id"]


def test_carrier_reconcile_refused_restores_previous_binding(tmp_path):
    service = CarrierServiceDouble(apply_outcome="unknown",
                                   reconcile_outcome="refused")
    core, a, b = carrier_world(tmp_path, service=service)
    core.sessions.select_profile("s1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError):
        core.sessions.begin_turn("t1", session_id="S")
    result = core.sessions.reconcile("r1", session_id="S")
    assert result["state"] == "rejected-unchanged"
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["switch_state"] == "settled"


def test_missing_host_permit_is_retriable_refusal_not_unknown(tmp_path):
    service = CarrierServiceDouble()
    core, a, b = carrier_world(tmp_path, service=service, permit_provider=None)
    core.sessions.select_profile("s1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    assert "permit" in str(exc.value)
    config = core.sessions.session_config("S")
    # nothing attempted: journal rejected, session retriable (not recovery)
    assert config["switch_state"] == "pending"
    assert config["evidence"]["journal"]["state"] == "rejected"
    assert core.sessions.turns("S") == []


@pytest.mark.parametrize("operation", ["inspect", "plan", "apply", "reconcile"])
@pytest.mark.parametrize("resolution", ["absent", "wrong-type", "wrong-session"])
def test_owner_resolution_refuses_before_any_service_call(operation, resolution):
    from ordessa_harness_api import ApplicationTarget
    from ordessa_profile.contracts import PlanResult, SessionRef
    service = CarrierServiceDouble()
    ref = SessionRef("profile-realm", "pi", "native-session", "S")
    resolver = None if resolution == "absent" else (
        lambda _: object() if resolution == "wrong-type" else
        ApplicationTarget("owner-server", "other-session", "owner-channel", 19))
    port = HarnessApiConfigPort(service, target_resolver=resolver,
                               revision_provider=lambda _: "before-r1")
    plan = PlanResult(ref, "operation-1", "live-update", fence={"plan_id": "plan-1"})
    with pytest.raises(ProfileError) as exc:
        if operation == "inspect":
            port.inspect(ref)
        elif operation == "plan":
            port.plan(ref, (), "operation-1")
        elif operation == "apply":
            port.apply(plan, ())
        else:
            port.reconcile("operation-1", ref)
    assert exc.value.code == ("APPLICATION_PORT_ABSENT" if resolution == "absent" else "SWITCH_BLOCKED")
    assert service.calls == []


def test_inspect_preserves_owner_channel_server_and_nonzero_generation():
    from ordessa_harness_api import ApplicationTarget, ConfigurationCapabilities
    from ordessa_profile.contracts import SessionRef
    ref = SessionRef("profile-realm", "pi", "native-session", "canonical-uid")
    target = ApplicationTarget("server-instance", ref.session_uid, "canonical-channel", 23)
    seen = []

    class Service:
        def inspect(self, actual):
            seen.append(actual)
            return ConfigurationCapabilities(actual, ())

    port = HarnessApiConfigPort(Service(), target_resolver=lambda actual: target)
    result = port.inspect(ref)
    assert seen == [target]
    assert seen[0] is target
    assert seen[0].channel_id != ref.native_session_key
    assert seen[0].server_id != ref.realm
    assert result.target.runtime_generation == "gen-23"


def test_inspect_reads_updated_owner_generation_without_confirmation_cache():
    from ordessa_harness_api import ApplicationTarget
    from ordessa_profile.contracts import SessionRef
    ref = SessionRef("realm", "pi", "native", "S")
    service = CarrierServiceDouble()
    port = HarnessApiConfigPort(service, target_resolver=lambda _: service.target)
    assert port.inspect(ref).target.runtime_generation == "gen-7"
    service.target = ApplicationTarget("fixture-server", "S", "next-channel", 31)
    assert port.inspect(ref).target.runtime_generation == "gen-31"
    assert service.calls == [("inspect", 7), ("inspect", 31)]


@pytest.mark.parametrize("changed", ["server", "channel", "generation"])
def test_apply_refuses_changed_owner_target_before_permit_or_effect(changed):
    from types import SimpleNamespace
    from ordessa_harness_api import ApplicationTarget
    from ordessa_profile.contracts import SessionRef
    service = CarrierServiceDouble()
    permits = []
    port = HarnessApiConfigPort(
        service, target_resolver=lambda _: service.target,
        revision_provider=lambda _: "before-r1",
        permit_provider=lambda *args: permits.append(args) or "permit-1")
    desired = (SimpleNamespace(op="set", value="m2", facet_id="model_selection",
                               item_id="model", source="profile@2"),)
    plan = port.plan(SessionRef("realm", "pi", "native", "S"), desired, "op-1")
    service.target = ApplicationTarget(
        "new-server" if changed == "server" else "fixture-server", "S",
        "new-channel" if changed == "channel" else "fixture-channel",
        8 if changed == "generation" else 7)
    with pytest.raises(ProfileError) as exc:
        port.apply(plan, desired)
    assert exc.value.code == "SWITCH_BLOCKED"
    assert permits == []
    assert service.calls == [("plan", 7)]
