"""Brand compile semantics, byte-stable golden rendering and verify
discipline (RA-2/RA-3/RA-4/RA-7 surface behavior).

Every compiled intent in this file traces to a cited key in
``ordessa_runtime_preferences.keys``; every refusal carries the honest
reason. The golden pins hold the byte-stable renderers to exact outputs.
"""
from __future__ import annotations

import pytest

from ordessa_harness_api import AdapterRefusal

from ordessa_runtime_preferences import bridge, common, engine, keys
from ordessa_runtime_preferences.types import (
    AdapterContext, CompileIntent, IntentSet, PreferenceRequest, Refusal,
    TargetHandle, Verdict,
)

from test_adapters_conformance import _harness_ctx


def _ctx(brand: str, scope: str = "instance") -> AdapterContext:
    target = keys.BRAND_TARGETS[brand][0] or f"{brand}.fixture.json"
    return AdapterContext(TargetHandle(brand, scope, target), "1.0.0",
                          capabilities={"native_session_id": "nat-7"})


def _compile(brand: str, group: str, scope: str = "instance", **params):
    return engine.compile(brand, _ctx(brand, scope), PreferenceRequest(group, dict(params)))

# -- compiled mappings per brand (documented keys only) --------------------------

def test_pi_compaction_maps_the_documented_settings_keys():
    result = _compile("pi", "compaction", enabled=True, reserveTokens=4096,
                      keepRecentTokens=1024)
    assert isinstance(result, IntentSet)
    paths = {i.field_path: i.typed_value for i in result.intents}
    assert paths[("compaction", "enabled")] is True
    assert paths[("compaction", "reserveTokens")] == 4096
    assert paths[("compaction", "keepRecentTokens")] == 1024
    assert result.reconfiguration == "unverified"  # no documented apply mode


def test_pi_summary_model_ref_is_refused_unmapped():
    refusal = _compile("pi", "compaction", summaryModelRef="acme/m1")
    assert isinstance(refusal, Refusal)
    assert refusal.code == "capability-unsupported"
    assert "summaryModelRef" in refusal.details["unmapped"]


def test_codex_compaction_maps_token_limit():
    result = _compile("codex", "compaction", thresholdTokens=100000)
    paths = {i.field_path: i.typed_value for i in result.intents}
    assert paths == {("model_auto_compact_token_limit",): 100000}


def test_codex_memory_maps_extraction_switch_and_model():
    result = _compile("codex", "memory", enabled=True,
                      extractionModelRef="acme/m1")
    paths = {i.field_path: i.typed_value for i in result.intents}
    assert paths == {("memories", "generate_memories"): True,
                     ("memories", "extract_model"): "acme/m1"}


def test_codex_token_budget_is_refused_shape_unfaithful():
    refusal = _compile("codex", "memory", budgetTokens=2000)
    assert isinstance(refusal, Refusal)
    assert "budgetTokens" in refusal.details["unmapped"]


def test_claude_compaction_and_memory_and_shell_map_enabled_flags():
    compaction = _compile("claude-code", "compaction", enabled=True)
    assert {i.field_path: i.typed_value for i in compaction.intents} == {
        ("autoCompactEnabled",): True}
    memory = _compile("claude-code", "memory", enabled=False)
    assert {i.field_path: i.typed_value for i in memory.intents} == {
        ("autoMemoryEnabled",): False}
    shell = _compile("claude-code", "shell", shellPath="/bin/bash")
    assert {i.field_path: i.typed_value for i in shell.intents} == {
        ("defaultShell",): "/bin/bash"}


def test_opencode_compaction_maps_auto_reserved_preserve():
    result = _compile("opencode", "compaction", enabled=True, reserveTokens=20000,
                      keepRecentTokens=4000)
    paths = {i.field_path: i.typed_value for i in result.intents}
    assert paths == {("compaction", "auto"): True,
                     ("compaction", "reserved"): 20000,
                     ("compaction", "preserve_recent_tokens"): 4000}


def test_qwen_threshold_percent_converts_to_documented_fraction():
    result = _compile("qwen", "compaction", thresholdPercent=85)
    paths = {i.field_path: i.typed_value for i in result.intents}
    assert paths == {("context", "autoCompactThreshold"): 0.85}
    # boundary of the documented 1-99 percent vocabulary
    assert isinstance(_compile("qwen", "compaction", thresholdPercent=100), Refusal)


def test_qwen_memory_switch_maps_managed_auto_memory():
    result = _compile("qwen", "memory", enabled=False)
    assert {i.field_path: i.typed_value for i in result.intents} == {
        ("memory", "enableManagedAutoMemory"): False}


def test_qwen_shell_timeout_maps_tools_shell_default_timeout():
    result = _compile("qwen", "shell", timeoutMs=30000)
    assert {i.field_path: i.typed_value for i in result.intents} == {
        ("tools", "shell", "defaultTimeoutMs"): 30000}


def test_kilo_compaction_maps_and_declares_restart():
    result = _compile("kilo", "compaction", enabled=True, reserveTokens=8000)
    assert result.reconfiguration == "restart-resume"
    assert (("compaction", "auto"), "restart") in result.apply_modes
    paths = {i.field_path: i.typed_value for i in result.intents}
    assert paths[("compaction", "auto")] is True
    assert paths[("compaction", "reserved")] == 8000


def test_hermes_available_cells_refuse_until_key_paths_are_pinned():
    """Document-level verdict is 'available' but the YAML key paths were not
    extracted this round: compile refuses honestly instead of guessing."""
    for group in ("compaction", "memory", "shell"):
        refusal = _compile("hermes", group, enabled=True)
        assert isinstance(refusal, Refusal)
        assert refusal.code == "capability-unsupported"


def test_dsh_refuses_without_a_pinnable_target():
    for group in ("compaction", "shell", "retry"):
        refusal = _compile("dsh", group, enabled=True)
        assert isinstance(refusal, Refusal)
        assert "not pinnable" in refusal.message


def test_unsupported_cells_refuse_with_evidence_backed_reasons():
    for brand, group in (("pi", "memory"), ("kilo", "memory"), ("codex", "retry"),
                         ("dsh", "memory")):
        refusal = _compile(brand, group, enabled=True)
        assert isinstance(refusal, Refusal), (brand, group)
        assert refusal.code == "capability-unsupported"


def test_unknown_cells_refuse_as_unknown():
    for brand, group in (("opencode", "memory"), ("claude-code", "retry"),
                         ("hermes", "retry"), ("qwen", "retry"), ("kilo", "retry")):
        refusal = _compile(brand, group, enabled=True)
        assert isinstance(refusal, Refusal), (brand, group)
        assert refusal.code == "capability-unsupported"


# -- RA-4: admin-only exclusions --------------------------------------------------

def test_admin_entangled_values_refuse_with_admin_reason():
    # codex shell_environment_policy family is the F8 permission-row entangle:
    # it is not a canonical param, so a request cannot even name it — the
    # closed vocabulary refusal is the first wall.
    refusal = _compile("codex", "shell", shell_environment_policy={"set": {"X": "1"}})
    assert refusal.code == "invalid-request"
    # claude envRefs: the env object is admin-entangled; envRefs is a canonical
    # param for other brands but has no claude mapping -> unmapped refusal that
    # surfaces the admin-only register (including the ("env",) object).
    refusal = _compile("claude-code", "shell", envRefs={"EDITOR": "ref://editor"})
    assert refusal.code == "capability-unsupported"
    assert ("env",) in refusal.details["admin_only"]


def test_admin_only_keys_are_listed_for_the_editor():
    assert {key.path for key in keys.admin_only_keys("codex", "shell")} >= {
        ("shell_environment_policy",)}
    assert ("env",) in {key.path for key in keys.admin_only_keys("claude-code", "shell")}
    assert ("tools", "executionSandbox") in {
        key.path for key in keys.admin_only_keys("qwen", "shell")}
    for brand, group in (("codex", "shell"), ("claude-code", "shell"),
                         ("qwen", "shell"), ("claude-code", "compaction"),
                         ("qwen", "retry")):
        for key in keys.admin_only_keys(brand, group):
            assert key.note, (brand, group)  # the editor's disabled-with-reason text


def test_admin_only_keys_never_compile():
    for (brand, group), cell in keys.CELLS.items():
        for key in cell.keys:
            if key.admin_only:
                assert key.canonical is None or key.canonical not in \
                    keys.compiled_keys(brand, group), (brand, group, key.path)


# -- closed vocabulary and value discipline ---------------------------------------

def test_unknown_group_is_invalid_request():
    refusal = engine.compile("pi", _ctx("pi"),
                             PreferenceRequest("teleportation", {"enabled": True}))
    assert refusal.code == "invalid-request"


def test_unknown_param_is_invalid_request():
    refusal = _compile("pi", "compaction", teleportThresholds=True)
    assert refusal.code == "invalid-request"


def test_wrong_value_types_are_invalid_request():
    assert _compile("pi", "compaction", enabled="yes").code == "invalid-request"
    assert _compile("pi", "retry", maxRetries=-1).code == "invalid-request"
    assert _compile("qwen", "compaction", thresholdPercent=0).code == "invalid-request"
    assert _compile("pi", "shell", envRefs={"A": "plaintext-secret"}).code == "invalid-request"


def test_empty_preference_refuses():
    refusal = _compile("pi", "compaction")
    assert refusal.code == "invalid-request"


def test_project_scope_never_writes_runtime_preferences():
    refusal = _compile("codex", "compaction", scope="project", thresholdTokens=1000)
    assert refusal.code == "target-conflict"
    assert "project" in refusal.message


def test_references_travel_as_references_only():
    result = _compile("codex", "memory", enabled=True, extractionModelRef="acme/m1")
    blob = repr(result)
    assert "sk-" not in blob  # no secret content ever travels
    assert "acme/m1" in blob  # the reference itself does


# -- golden byte-stable rendering --------------------------------------------------

def test_json_rendering_is_byte_stable_and_sorted():
    golden = ('{"compaction.auto":true,"compaction.preserve_recent_tokens":4000,'
              '"compaction.reserved":20000}\n')
    value = {"compaction.reserved": 20000, "compaction.auto": True,
             "compaction.preserve_recent_tokens": 4000}
    assert common.render_json_object(value) == golden
    assert common.render_json_object(dict(reversed(list(value.items())))) == golden


def test_codex_rendering_is_byte_stable_toml_lines():
    assert common.render_codex_compaction_lines(token_limit=100000) == (
        "model_auto_compact_token_limit = 100000\n")
    assert (common.render_codex_compaction_lines(token_limit=100000)
            == common.render_codex_compaction_lines(token_limit=100000))


def test_render_preference_document_routes_by_brand_codec():
    assert common.render_preference_document(
        "codex", "compaction", {"token_limit": 1000}) == (
        "model_auto_compact_token_limit = 1000\n")
    assert common.render_preference_document(
        "opencode", "compaction", {"compaction.auto": True}) == (
        '{"compaction.auto":true}\n')
    with pytest.raises(common.GroupUnsupported):
        common.render_preference_document("dsh", "compaction", {})


# -- verify read-back discipline ---------------------------------------------------

def _compiled_expected(brand: str, group: str, **params) -> dict:
    result = _compile(brand, group, **params)
    assert isinstance(result, IntentSet)
    return {".".join(i.field_path): i.typed_value for i in result.intents}


def test_projected_digest_without_readback_is_never_match():
    verdict = engine.verify("kilo", _ctx("kilo"),
                            {"expected": _compiled_expected("kilo", "compaction",
                                                            enabled=True)})
    assert verdict.verdict == "unknown"


def test_readback_match_requires_equal_values():
    expected = _compiled_expected("kilo", "compaction", enabled=True, reserveTokens=8000)
    verdict = engine.verify("kilo", _ctx("kilo"),
                            {"expected": expected, "readback": dict(expected),
                             "native_session_id": "nat-7"})
    assert verdict.verdict == "match"
    mismatch_verdict = engine.verify("kilo", _ctx("kilo"),
                                     {"expected": expected,
                                      "readback": {**expected, "compaction.auto": False},
                                      "native_session_id": "nat-7"})
    assert mismatch_verdict.verdict == "mismatch"
    assert "differing" in mismatch_verdict.evidence


def test_session_identity_change_is_mismatch():
    expected = _compiled_expected("codex", "memory", enabled=True)
    verdict = engine.verify("codex", _ctx("codex"),
                            {"expected": expected, "readback": dict(expected),
                             "native_session_id": "nat-OTHER"})
    assert verdict.verdict == "mismatch"
    assert "session" in verdict.reason


def test_bridge_verify_maps_to_harness_outcomes():
    expected = _compiled_expected("kilo", "compaction", enabled=True)
    adapter = bridge.BridgeConfigurationAdapter("kilo")
    from ordessa_harness_api import Match, Mismatch, VerificationUnknown
    assert isinstance(adapter.verify(_harness_ctx("kilo"),
                                     {"expected": expected, "readback": dict(expected)}), Match)
    assert isinstance(adapter.verify(_harness_ctx("kilo"),
                                     {"expected": expected, "readback": {}}), Mismatch)
    assert isinstance(adapter.verify(_harness_ctx("kilo"), {"expected": expected}), VerificationUnknown)


# -- bridge payload plumbing -------------------------------------------------------

def test_bridge_compiles_group_payload_into_set_fields():
    adapter = bridge.BridgeConfigurationAdapter("opencode")
    result = adapter.compile(_harness_ctx("opencode"), {},
                             {"compaction": {"enabled": True, "reserveTokens": 20000}})
    assert {i.field_path.segments: i.typed_value for i in result.intents} == {
        ("compaction", "auto"): True, ("compaction", "reserved"): 20000}


def test_bridge_refuses_when_any_group_is_not_available():
    adapter = bridge.BridgeConfigurationAdapter("pi")
    refusal = adapter.compile(_harness_ctx("pi"), {},
                              {"compaction": {"enabled": True},
                               "memory": {"enabled": True}})
    assert isinstance(refusal, AdapterRefusal)  # no partial application


def test_bridge_empty_payload_is_invalid_fragment():
    adapter = bridge.BridgeConfigurationAdapter("pi")
    refusal = adapter.compile(_harness_ctx("pi"), {}, {})
    assert refusal.code.name == "INVALID_FRAGMENT"


def test_bridge_assess_probe_is_unknown():
    adapter = bridge.BridgeConfigurationAdapter("pi")
    assert adapter.assess(_harness_ctx("pi"), {}).status == "unknown"


def test_payload_schema_validates_closed_groups():
    schema = bridge.payload_schema()
    ok = {"compaction": {"enabled": True}, "memory": None, "shell": None, "retry": None}
    schema.validate(ok)
    from ordessa_harness_api.errors import ContractError
    with pytest.raises(ContractError):
        schema.validate({"teleportation": {}})
    with pytest.raises(ContractError):
        schema.validate({"compaction": {"nope": True}})
