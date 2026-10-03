"""G13 — per-brand update/reset DECISIONS on the PUBLISHED decision type.

The live half of G13 ("同会话更新确认或重启恢复", "resume 变 session/new")
is executed by the Harness behind `ConfigurationService`/`RuntimeAdapter`;
what is delivered here is the deterministic Skills-side decision of WHICH
strategy a change declares, per brand, from the evidenced capability
statement — now returned as the published
`ordessa_harness_api.ReconfigurationDecision`, and applied through the
`apply_chain` (T13) transaction.

Rules encoded (harness-adapters.md 映射步骤 5): 支持安全 reload 用 reload;
不支持则由 Harness 重启并恢复原会话; 恢复失败不另起空会话代替 — so a brand
without evidenced resume gets `unsupported` rather than a blank-session
"update".
"""
from __future__ import annotations

import pytest

from ordessa_harness_api import MountContent, ReconfigurationDecision
from ordessa_skills.harness_adapters import base
from ordessa_skills.harness_adapters.capabilities import statement_for
from ordessa_skills.harness_adapters.intent import (
    GenerationBounds, ManagedContentRef,
)

DIGEST = "sha256:" + "a" * 64
CONTROLLED = ("pi", "codex", "claude-code")


def _bounds():
    return GenerationBounds("gen-9", "proj-x", 1, 1)


def _target(harness_id, native, adapter):
    return base.AdapterTarget(harness_id, native, adapter, "acp")


def _ref(name="solo"):
    return ManagedContentRef("solo-skill", 1, DIGEST, name, size_bytes=64)


def test_reload_is_unevidenced_so_every_controlled_brand_declares_restart_resume():
    # `reload` cells are all `unknown` (vendor docs only, brand-matrix.md),
    # while `resume` is `supported` (observed same-native-id rows) ->
    # restart-and-resume, never a bare session/new.
    for harness_id in CONTROLLED:
        strategy = base.decide_update_strategy(statement_for(harness_id))
        assert strategy == base.RESTART_RESUME, harness_id


def test_a_brand_without_evidenced_resume_refuses_the_update():
    # "恢复失败不另起空会话代替": refusing the plan beats a fake resume.
    strategy = base.decide_update_strategy(statement_for("hermes"))
    assert strategy == base.REFUSE


def test_the_domain_decision_maps_onto_the_published_decision_type():
    for harness_id in CONTROLLED:
        decision = base.decide_reconfiguration(
            statement_for(harness_id), affected_instance_refs=("inst-1",))
        assert isinstance(decision, ReconfigurationDecision)
        assert decision.mode == "restart-resume"
        assert decision.affected_instance_refs == ("inst-1",)


def test_unsupported_decision_carries_a_reason_on_the_published_type():
    decision = base.decide_reconfiguration(statement_for("hermes"),
                                           affected_instance_refs=("inst-9",))
    assert decision.mode == "unsupported"
    assert "resume" in decision.reason


def test_reset_stays_owned_removal_only_for_every_registered_brand():
    # No brand has an evidenced reset control; the strategy must not claim
    # native ambient content was reset/closed (G11 honesty).
    for harness_id in CONTROLLED + ("hermes",):
        assert base.decide_reset_strategy(statement_for(harness_id)) == \
            base.OWNED_REMOVAL_ONLY


def test_compiled_projections_carry_the_decision_and_only_content_intents():
    from ordessa_skills.harness_adapters import pi

    compiled = pi.compile([_ref()], _target("pi", "0.84.2", "0.5.0"),
                          bounds=_bounds())
    assert isinstance(compiled, base.SkillProjection)
    assert compiled.update_strategy == base.RESTART_RESUME
    assert compiled.reset_strategy == base.OWNED_REMOVAL_ONLY
    assert compiled.evidence_ceiling == "projected"
    # the published intents are content mounts only — no per-skill field
    # edits, no fabricated native actions:
    assert all(isinstance(item, MountContent) for item in compiled.intents.intents)
    # the decision names the frozen generation face as the affected ref:
    decision = base.decide_reconfiguration(
        statement_for("pi"),
        affected_instance_refs=(compiled.bounds.runtime_generation,))
    assert decision.mode == "restart-resume"
    assert decision.affected_instance_refs == ("gen-9",)


def test_unregistered_brand_compile_refuses_before_any_intent():
    with pytest.raises(base.HarnessAdapterError) as exc:
        base.compile_intent_set([_ref()], _target("kilo", "7.7.2", "0.0.0"),
                                harness_id="kilo", target_slot="skills",
                                bounds=_bounds())
    assert exc.value.code == "HARNESS_BRAND_UNREGISTERED"


def test_evidence_ceiling_for_all_controlled_brands_is_projected():
    # All `loaded_evidence` cells are unknown today, so no compile result
    # may promise more than placement — the live-verification half is a
    # brand-capability question the merged API does not answer.
    for harness_id in CONTROLLED:
        assert base.evidence_ceiling(statement_for(harness_id)) == "projected"


def test_decision_layer_is_pure_data(tmp_path):
    # Decisions touch no filesystem: a sentinel around the calls proves the
    # vocabulary is pure data (no spawn, no write, no network).
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("x")
    base.decide_update_strategy(statement_for("codex"))
    base.decide_reset_strategy(statement_for("claude-code"))
    base.decide_reconfiguration(statement_for("pi"),
                                affected_instance_refs=("inst",))
    assert sentinel.read_text() == "x"
    assert list(tmp_path.iterdir()) == [sentinel]
