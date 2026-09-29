"""PB-5: the three-brand E2 controlled matrix (verification.md E2 — the DONE
necessary condition; real-model calls E3 stay forbidden).

Rows: pi / codex / claude-code. Columns: MP-03 (catalog facts never lie),
MP-06 (controlled restart-resume on the SAME native session id), MP-07
(failure never lies: refused/unknown keep the draft and never prompt), MP-10
(secret sentinel: the reference travels, content never does), MP-11 (C2
single owner: the second client is refused by the real host registry).

Every grid cell drives the FULL E2 sequence through the real application
chain — build_runtime host → adapters plugin (the package's own declaration
surface) → C4 plan/apply(permit) → adapter verify → prompt against the fake
endpoint — and proves the DOWNSTREAM ROUTE (which endpoint/model the fake
provider actually received), not an option ack. Missing cells = the brand
does not report ready; the aggregate stays PARTIAL until every cell is here.

品牌语义钉 (conformance-pinned, exercised here end to end):
- codex never writes a project-scope provider; provider-level change is
  restart-resume on the same thread; model-only change is session-local;
- pi RPC success is not effect evidence (the read-back decides);
- claude model and endpoint are two different things; a session/new that
  impersonates resume is a Mismatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from _controlled_harness import (  # noqa: E402
    RESOURCE, ControlledComposition,
)
from ordessa_harness_api import DesiredFragment  # noqa: E402

from ordessa_model_provider.harness_binding import (  # noqa: E402
    ConfigurationServiceHarnessPort,
)
from ordessa_model_provider.ports import (  # noqa: E402
    SESSION_CONFIG_OUTCOME_UNKNOWN, SESSION_CONFIG_REJECTED,
    SESSION_CONFIG_UNSUPPORTED, SessionConfigError,
)
from server_plugin_api import (  # noqa: E402
    Contribution, ContributionBatch, ServerPluginDescriptor,
    ServerPluginRegistration,
)
from ordessa_model_provider_adapters.plugin import (  # noqa: E402
    ModelProviderAdaptersPlugin,
)

BRANDS = ("pi", "codex", "claude-code")

#: brand → (session-local choice fields/model, restart-resume choice fields/model)
SEMANTICS = {
    "pi": ({"provider_in_instance": True, "credential_changed": False}, "acme/m1",
           {"provider_in_instance": False}, "acme/m2"),
    "codex": ({"before_provider": "acme"}, "m1-session",
              {"before_provider": "legacy"}, "m1-thread"),
    "claude-code": ({}, "claude-session",
                    {"endpoint_changed": True}, "claude-restart"),
}


def _fragment(comp, payload):
    return DesiredFragment("assets.model-provider", "choice-1", "1",
                           "business:choice-1", comp.runtime.revision, "set", payload)


def _apply_choice(comp, payload):
    plan = comp.service.plan(comp.service.target, (_fragment(comp, payload),),
                             comp.runtime.revision)
    assert plan.kind == "plan", plan
    result = comp.service.apply(plan.plan_id, "op-" + comp.brand,
                                comp.permit.mint("op-" + comp.brand))
    return result


# -- MP-03: 目录事实(失败报错,unknown 不冒充 supported) ------------------------

@pytest.mark.parametrize("brand", BRANDS)
def test_mp03_catalog_facts_reflect_the_brand_runtime(brand, tmp_path):
    comp = ControlledComposition(brand, tmp_path)
    try:
        capabilities = comp.service.inspect(comp.service.target)
        mine = [c for c in capabilities.capabilities
                if c.facet_id == "assets.model-provider" and c.harness_id == brand]
        assert mine, "the brand facet must be visible to the runtime"
        assert all(c.status in {"supported", "unknown"} for c in mine)
        # unknown never defaults to supported: the C4 probe carries no choice
        assert all(c.status == "unknown" for c in mine)
        # a corrupted generation is a loud typed refusal, never an empty page
        comp.instance.files[RESOURCE[brand][0]] = b"{not-json"
        plan = comp.service.plan(comp.service.target,
                                 (_fragment(comp, comp.choice_payload()),),
                                 comp.runtime.revision)
        assert plan.kind == "refused" and plan.diagnostics
    finally:
        comp.stop()


# -- MP-06: 受控重启 resume(同 native id;session/new 冒充必红) ------------------

@pytest.mark.parametrize("brand", BRANDS)
def test_mp06_full_e2_sequence_restart_resume_same_native_id(brand, tmp_path):
    """initialize → session/new → prompt(fake) → 换 choice(restart-resume,
    同 native id resume) → [pi/claude: the model switch is a follow-up
    session-local choice, per brand dialect] → 下一 prompt(fake)."""
    comp = ControlledComposition(brand, tmp_path)
    try:
        # initialize: host activated + adapter registered (composition boot)
        views = [v for v in comp.host.contributions("harness.configuration-adapters")
                 if v.owner == "ordessa.model-provider.adapters"]
        assert len(views) == 3
        # session/new + first prompt: the base generation routes to legacy/m0
        first = comp.prompt_route()
        restart_fields = SEMANTICS[brand][2]
        payload = comp.choice_payload(model=SEMANTICS[brand][3], brand_fields=restart_fields)
        assert comp.reconfiguration_mode(payload) == "restart-resume"
        session_before = comp.instance.native_session_id
        confirmed = _apply_choice(comp, payload)
        assert confirmed.kind == "confirmed", confirmed
        # resume proof: the SAME native session id, per the receipt
        assert confirmed.native_session_identity == session_before
        assert comp.instance.native_session_id == session_before
        if brand != "codex":
            # pi writes the provider object and restarts; the model itself
            # switches by a session-local set_model-style choice afterwards.
            # claude changes the endpoint env and restarts; same split.
            # codex's restart path already carries the model field.
            follow = comp.choice_payload(model=SEMANTICS[brand][3],
                                         brand_fields=SEMANTICS[brand][0]
                                         if brand == "pi" else {})
            assert comp.reconfiguration_mode(follow) == "session-local"
            operation_key = "op-" + comp.brand + "-follow"
            plan = comp.service.plan(comp.service.target,
                                     (_fragment(comp, follow),), comp.runtime.revision)
            assert plan.kind == "plan", plan
            assert comp.service.apply(plan.plan_id, operation_key,
                                      comp.permit.mint(operation_key)).kind == "confirmed"
        # next prompt: the downstream route really moved
        second = comp.prompt_route()
        assert second["routed_model"] == SEMANTICS[brand][3]
        assert second != first
    finally:
        comp.stop()


@pytest.mark.parametrize("brand", BRANDS)
def test_mp06_session_new_impersonating_resume_is_never_confirmed(brand, tmp_path):
    comp = ControlledComposition(brand, tmp_path)
    try:
        original = comp.instance.restart_onto

        def impersonating_restart(files):
            session_id = original(files)
            comp.instance.session_new()  # the negative: a fresh identity
            return comp.instance.native_session_id

        comp.instance.restart_onto = impersonating_restart
        payload = comp.choice_payload(model=SEMANTICS[brand][3],
                                      brand_fields=SEMANTICS[brand][2])
        result = _apply_choice(comp, payload)
        assert result.kind == "unknown"  # the identity chain refused to confirm
        record = comp.service.query("op-" + comp.brand)
        assert record.result.kind == "unknown"
        assert comp.service.reconcile("op-" + comp.brand) == record.result
    finally:
        comp.stop()


@pytest.mark.parametrize("brand", BRANDS)
def test_mp06_model_only_change_is_session_local_and_moves_the_route(brand, tmp_path):
    fields, model = SEMANTICS[brand][0], SEMANTICS[brand][1]
    comp = ControlledComposition(brand, tmp_path)
    try:
        payload = comp.choice_payload(model=model, brand_fields=fields)
        assert comp.reconfiguration_mode(payload) == "session-local"
        session_before = comp.instance.native_session_id
        confirmed = _apply_choice(comp, payload)
        assert confirmed.kind == "confirmed", confirmed
        assert comp.instance.native_session_id == session_before
        assert comp.prompt_route()["routed_model"] == model
    finally:
        comp.stop()


# -- MP-07: 失败不撒谎(拒绝/unknown 保草稿零 prompt,不自动重发) ---------------

@pytest.mark.parametrize("brand", BRANDS)
def test_mp07_unsupported_choice_refuses_zero_prompt_draft_intact(brand, tmp_path):
    comp = ControlledComposition(brand, tmp_path)
    try:
        before = comp.instance.readback()
        bad_protocols = {"pi": "anthropic-messages", "codex": "gemini-generate",
                         "claude-code": "openai-chat"}
        port = ConfigurationServiceHarnessPort(
            comp.service, target=comp.service.target, permit_source=comp.permit.mint,
            revision_source=lambda ref: comp.runtime.revision)
        with pytest.raises(SessionConfigError) as excinfo:
            port.apply({"serverInstanceId": "test-server", "harnessId": brand,
                        "acpSessionId": "acp-1"},
                       comp.choice_payload(protocol=bad_protocols[brand],
                                           brand_fields={"provider_in_instance": True}))
        assert excinfo.value.code in {SESSION_CONFIG_UNSUPPORTED,
                                      SESSION_CONFIG_REJECTED}
        assert comp.endpoint.requests == []  # zero prompt left the chain
        assert comp.instance.readback() == before  # the draft/state is intact
    finally:
        comp.stop()


@pytest.mark.parametrize("brand", BRANDS)
def test_mp07_unknown_outcome_never_repeats_the_effect(brand, tmp_path):
    comp = ControlledComposition(brand, tmp_path)
    try:
        comp.runtime.fail_after_effect = True
        result = _apply_choice(comp, comp.choice_payload(
            brand_fields=SEMANTICS[brand][0]))
        assert result.kind == "unknown"
        apply_count = comp.runtime.apply_count
        # a retry through the service replays the durable unknown: no new effect
        replay = comp.service.apply("missing-plan", "op-" + comp.brand, "x")
        assert replay.kind == "refused"  # the plan is gone; nothing re-fires
        assert comp.runtime.apply_count == apply_count
        assert comp.instance.readback()["model"]  # state observable, honest
    finally:
        comp.stop()


def test_mp07_double_session_interleave_routes_independently(tmp_path):
    """双会话交错: A applies X, B applies Y, interleaved prompts — each route
    is its own session's choice, never the other's."""
    comp_a = ControlledComposition("pi", tmp_path / "a")
    comp_b = ControlledComposition("pi", tmp_path / "b")
    try:
        payload_a = comp_a.choice_payload(model="acme/mA",
                                          brand_fields={"provider_in_instance": True,
                                                        "credential_changed": False})
        payload_b = comp_b.choice_payload(model="acme/mB",
                                          brand_fields={"provider_in_instance": True,
                                                        "credential_changed": False})
        assert _apply_choice(comp_a, payload_a).kind == "confirmed"
        assert _apply_choice(comp_b, payload_b).kind == "confirmed"
        assert comp_a.prompt_route()["routed_model"] == "acme/mA"
        assert comp_b.prompt_route()["routed_model"] == "acme/mB"
        assert comp_a.prompt_route("again")["routed_model"] == "acme/mA"
    finally:
        comp_a.stop()
        comp_b.stop()


# -- MP-10: 秘密哨兵(引用可走,内容零泄漏) --------------------------------------

@pytest.mark.parametrize("brand", BRANDS)
def test_mp10_secret_sentinel_zero_hits_across_the_chain(brand, tmp_path):
    sentinel = "sk-live-controlled-sentinel"
    comp = ControlledComposition(brand, tmp_path)
    try:
        # a restart-path choice so the credential actually compiles to a
        # BindSecret (the session-local shape never touches the credential)
        payload = comp.choice_payload(credential_ref=f"ref://{sentinel}",
                                      brand_fields=SEMANTICS[brand][2])
        # the C4 slice refuses secret application BEFORE anything durable:
        # preflight refuses bind-secret ("secrets need a separate controlled
        # executor") at plan time — no reservation, no effect, no leak
        plan = comp.service.plan(comp.service.target,
                                 (_fragment(comp, payload),), comp.runtime.revision)
        assert plan.kind == "refused", plan
        assert "secret" in " ".join(plan.diagnostics)
        assert comp.runtime.apply_count == 0
        assert comp.endpoint.requests == []
        journal_bytes = comp.journal.path.read_bytes()
        instance_bytes = b"".join(data for _, data in comp.instance.files.items())
        assert sentinel.encode() not in journal_bytes
        assert sentinel.encode() not in instance_bytes
        assert sentinel.encode() not in repr(comp.endpoint.requests).encode()
    finally:
        comp.stop()


# -- MP-11: C2 单 owner(真实 host;第二 client 必红) ----------------------------

@pytest.mark.parametrize("brand", BRANDS)
def test_mp11_second_client_claiming_the_brand_is_refused_by_the_host(brand, tmp_path):
    from ordessa_model_provider_adapters.bridge import BridgeConfigurationAdapter

    comp = ControlledComposition(brand, tmp_path)
    try:
        CONFIGURATION_POINT = "harness.configuration-adapters"

        class SecondClient:
            def descriptor(self):
                return ServerPluginDescriptor("second.client.probe", "Second client", "1")

            def build(self, context):
                return ServerPluginRegistration(contributions=ContributionBatch((
                    Contribution(CONFIGURATION_POINT, "v1", BridgeConfigurationAdapter(brand)),
                )))

        with pytest.raises(Exception) as excinfo:
            comp.host.activate(SecondClient())
        assert "adapter_id already registered" in str(excinfo.value)
        owners = {v.owner for v in comp.host.contributions(CONFIGURATION_POINT)
                  if getattr(v.payload, "brand", None) == brand}
        assert owners == {"ordessa.model-provider.adapters"}
    finally:
        comp.stop()
