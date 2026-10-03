"""EXT-02 (brand-narrowed) — prompts adapter conformance on the published
protocol. The registration rides `harness.configuration-adapters` like
Skills/Extensions; tonight compile is an evidenced typed refusal (AR-6):
the registry declares no instruction target anywhere."""
from __future__ import annotations

import pytest
from ordessa_harness_api import (
    ErrorCode, Installation, Match, Mismatch, VerificationUnknown,
)

from ordessa_prompts.harness_adapters import (
    CONFIGURATION_POINT, FACET_ID, POINT_API_VERSION, prompts_adapters,
)
from ordessa_prompts.harness_adapters.contribution import (
    build_payload_schema, PINS, REGISTRY_GAP,
)

from _prompts_adapter_doubles import (
    CLAUDE_INSTALLATION, CODEX_INSTALLATION, PI_INSTALLATION,
    context_for, json_file_target,
)


def desired_set(**overrides):
    payload = {
        "instructions": [
            {"promptId": "style-guide", "revision": 3,
             "digest": "a" * 64, "order": 1},
            {"promptId": "tone", "revision": 1,
             "digest": "b" * 64, "order": 2},
        ],
        "persona": None,
        "systemReplacement": None,
        "synthesis": "systemReplacement->persona->ordered-instructions",
        "separator": "\n\n",
        "runtimeGeneration": "gen-1",
        "projectId": "proj-1",
    }
    payload.update(overrides)
    return payload


def test_point_constants_match_the_harness_handler():
    # duplicated-string discipline: the TEST imports the harness plugin
    # dist (verification venv, docs/baseline.md); the package never does
    from ordessa_harness import contributions
    assert CONFIGURATION_POINT == contributions.CONFIGURATION_POINT
    assert POINT_API_VERSION == contributions.POINT_API_VERSION


def test_descriptor_shape_and_empty_claims():
    for adapter in prompts_adapters():
        d = adapter.descriptor
        assert d.facet_id == FACET_ID == "assets.prompts"
        assert d.adapter_id == f"assets.prompts.{d.harness_id}"
        assert d.entries == ("acp",)
        assert d.claims == ()  # nothing truthful to claim tonight
        assert not hasattr(adapter, "owner")
        assert callable(adapter.assess) and callable(adapter.compile)


def test_pins_carry_machine_evidence_and_claude_is_comment_grade():
    assert PINS["codex"].native_grade == "machine"
    assert PINS["claude"].native_grade == "comment"
    assert "comment-grade" in PINS["claude"].native_evidence


def test_assess_foreign_identity_is_unknown():
    adapter = prompts_adapters()[0]  # pi
    context = context_for(CODEX_INSTALLATION)
    assert adapter.assess(context, None).status == "unknown"


def test_assess_uninspected_native_version_is_unknown():
    adapter = prompts_adapters()[0]
    context = context_for(Installation("pi", None, (0, 5, 0), "x"))
    assert adapter.assess(context, None).status == "unknown"


def test_assess_machine_pin_mismatch_is_unsupported():
    adapter = prompts_adapters()[1]  # codex
    context = context_for(Installation("codex", (0, 148, 0), (1, 1, 14), "x"))
    assessment = adapter.assess(context, None)
    assert assessment.status == "unsupported"
    assert "production.py:88" in assessment.reason


def test_assess_comment_grade_mismatch_is_unknown():
    adapter = prompts_adapters()[2]  # claude
    context = context_for(Installation("claude", (9, 9, 9), (0, 81, 2), "x"))
    assessment = adapter.assess(context, None)
    assert assessment.status == "unknown"
    assert "comment" in assessment.reason


def test_assess_bad_payload_makes_no_capability_claim():
    adapter = prompts_adapters()[0]
    context = context_for(PI_INSTALLATION)
    bad = desired_set()
    bad["separator"] = " "  # schema enum refuses anything but \n\n
    assessment = adapter.assess(context, bad)
    assert assessment.status == "unknown"
    assert "caller error" in assessment.reason


def test_assess_pinned_is_projection_pending_never_supported():
    # assess never grades a status compile cannot cash (AR-6)
    for installation in (PI_INSTALLATION, CODEX_INSTALLATION,
                         CLAUDE_INSTALLATION):
        adapter = prompts_adapters()[
            ("pi", "codex", "claude").index(installation.harness_id)]
        assessment = adapter.assess(context_for(installation), None)
        assert assessment.status == "unknown", installation.harness_id
        assert "projection pending" in assessment.reason


def test_compile_refuses_when_no_target_exists():
    adapter = prompts_adapters()[1]
    refusal = adapter.compile(context_for(CODEX_INSTALLATION), None,
                              desired_set())
    assert refusal.code == ErrorCode.ADAPTER_MISSING
    assert "AR-6" in refusal.reason


def test_compile_refuses_even_when_a_runtime_offers_targets():
    # a target without a registry-declared claim is not ours to write
    adapter = prompts_adapters()[1]
    context = context_for(CODEX_INSTALLATION, json_file_target())
    refusal = adapter.compile(context, None, desired_set())
    assert refusal.code == ErrorCode.CAPABILITY_UNSUPPORTED
    assert "unclaimed target" in refusal.reason


def test_compile_refuses_synthesis_order_deviations():
    # the fixed synthesis order is part of the payload's identity (HM §3)
    adapter = prompts_adapters()[0]
    context = context_for(PI_INSTALLATION, json_file_target())
    reordered = desired_set(
        synthesis="persona->systemReplacement->ordered-instructions")
    refusal = adapter.compile(context, None, reordered)
    assert refusal.code == ErrorCode.INVALID_FRAGMENT


def test_compile_refuses_non_object_payload():
    adapter = prompts_adapters()[0]
    refusal = adapter.compile(context_for(PI_INSTALLATION), None, [1, 2])
    assert refusal.code == ErrorCode.INVALID_FRAGMENT


def test_verify_digest_match_is_observational_only():
    adapter = prompts_adapters()[0]
    context = context_for(PI_INSTALLATION)
    good = "e" * 64
    result = adapter.verify(context, {
        "source": "projection_digest", "expectedDigest": good,
        "observedDigest": good})
    assert isinstance(result, Match)
    assert "observational placement fact only" in result.evidence_ref
    assert "HM §5" in result.evidence_ref


def test_verify_mismatch_and_unknowns():
    adapter = prompts_adapters()[0]
    context = context_for(PI_INSTALLATION)
    assert isinstance(adapter.verify(context, {
        "source": "projection_digest", "expectedDigest": "f" * 64,
        "observedDigest": "0" * 64}), Mismatch)
    for observed in (
            {"source": "model_claim", "expectedDigest": "f" * 64,
             "observedDigest": "f" * 64},
            {"source": "native_load_event", "expectedDigest": "f" * 64,
             "observedDigest": "f" * 64},  # unrecognised source here
            {"source": "projection_digest", "expectedDigest": "short",
             "observedDigest": "short"},
            {"source": "projection_digest", "expectedDigest": "f" * 64},
            "not a mapping"):
        result = adapter.verify(context, observed)
        assert isinstance(result, VerificationUnknown), observed


def test_verify_foreign_identity_is_unknown():
    adapter = prompts_adapters()[0]
    assert isinstance(adapter.verify(context_for(CODEX_INSTALLATION), {
        "source": "projection_digest", "expectedDigest": "f" * 64,
        "observedDigest": "f" * 64}), VerificationUnknown)


def test_capability_rows_grade_from_the_table():
    from ordessa_harness_api import ApplicationTarget
    adapter = prompts_adapters()[0]
    rows = adapter.configuration_capabilities(
        ApplicationTarget("srv", "sess", "chan", 7))
    by_op = {row.operation: row for row in rows.capabilities}
    assert by_op["content"].status == "unknown"     # instruction cell
    assert by_op["set"].status == "unsupported"     # empty claims
    assert by_op["reset"].status == "unsupported"   # no reset evidence
    assert "HM §5" in by_op["reset"].reason


def test_plugin_contributes_three_rows_conditionally():
    from server_plugin_api import ServerPluginContext
    from ordessa_prompts.plugin import PromptsServerPlugin
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        ctx = ServerPluginContext(plugin_id="ordessa.assets.prompts",
                                  data_root=Path(tmp), ports={})
        registration = PromptsServerPlugin().build(ctx)
        rows = [c for c in registration.contributions.contributions
                if c.point_id == CONFIGURATION_POINT]
        assert {r.payload.descriptor.harness_id for r in rows} == {
            "pi", "codex", "claude"}
        assert registration.contributions.open_points == frozenset(
            {CONFIGURATION_POINT})
        bare = PromptsServerPlugin(contribute_harness_adapters=False).build(ctx)
        assert not [c for c in bare.contributions.contributions
                    if c.point_id == CONFIGURATION_POINT]
        assert bare.contributions.open_points == frozenset()


def test_payload_schema_documented_for_the_landing_day():
    schema = build_payload_schema()
    assert schema is not None  # and the fixed synthesis order is an enum
    from ordessa_harness_api import ContractError
    with pytest.raises(ContractError):
        schema.validate(desired_set(synthesis="anything-goes"))
