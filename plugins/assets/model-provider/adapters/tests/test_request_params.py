"""016 MPX: the four request-level param families (plan F12) projected
through the EXISTING three-brand adapters — no new facet, no new package.

Every projection cites a first-hand pin in this tree; a family without one
refuses with that exact reason. Absence (``params=None`` or all-None) keeps
the pre-MPX compile behavior byte-for-byte (regression-pinned here).
"""
from __future__ import annotations

import pytest
from ordessa_model_provider_adapters import common
from ordessa_model_provider_adapters.codex import CodexAdapter
from ordessa_model_provider_adapters.claude import ClaudeAdapter
from ordessa_model_provider_adapters.pi import PiAdapter
from ordessa_model_provider_adapters.types import (
    AdapterContext, ChoiceRequest, IntentSet, Refusal, RequestParams,
    TargetHandle,
)

PIN = common.SUPPORTED_VERSION_RANGES["codex"][0]


def _context(brand: str, identity: str) -> AdapterContext:
    return AdapterContext(
        target_handle=TargetHandle(harness_id=brand, scope="instance",
                                   identity=identity),
        harness_version=common.SUPPORTED_VERSION_RANGES[brand][0])


def _choice(brand: str, *, provider="openai", model="gpt-5.1", params=None,
            protocol="openai-responses", brand_fields=None):
    return ChoiceRequest(
        provider_config_id=provider, model_id=model, endpoint=None,
        protocol=protocol, credential_ref=None, provider_name=provider,
        brand_fields=dict(brand_fields or {}), params=params)


def _request_params(**kwargs) -> RequestParams:
    return RequestParams(**kwargs)


# -- the DTO -------------------------------------------------------------------


def test_request_params_dto_is_closed_and_typed():
    assert _request_params().has_any() is False
    assert _request_params(reasoning_effort="high").has_any() is True
    with pytest.raises(ValueError):
        RequestParams.from_record({"effort": "high"})  # unknown key
    with pytest.raises(ValueError):
        RequestParams.from_record({"maxTokens": 0})  # positive integer
    with pytest.raises(ValueError):
        RequestParams.from_record({"maxTokens": True})  # bool is not an int
    with pytest.raises(ValueError):
        RequestParams.from_record({"retry": {"enabled": 1}})
    parsed = RequestParams.from_record({
        "retry": {"enabled": False, "maxRetries": 0,
                  "provider": {"maxRetries": 0, "maxRetryDelayMs": 1000}}})
    assert parsed.retry["provider"]["maxRetryDelayMs"] == 1000


def test_absent_params_keep_the_pre_mpx_compile_behavior():
    """params=None and all-None both take the same compile path as before
    MPX (asserted on the reconfiguration class and on no param intent ever
    appearing - the honest observable contract, not a byte claim)."""
    context = _context("codex", "codex.config.toml")
    for params in (None, _request_params()):
        compiled = CodexAdapter().compile(context, {}, _choice(
            "codex", params=params, brand_fields={"before_provider": "openai"}))
        assert isinstance(compiled, Refusal) is False
        # provider unchanged -> the pre-MPX session-local path, param-free
        assert compiled.reconfiguration == "session-local"
        assert all(intent.field_path != ("model_reasoning_effort",)
                   for intent in compiled.intents)


# -- codex: reasoning effort (the one pinned family) -----------------------------


def test_codex_effort_projects_the_pinned_native_field():
    context = _context("codex", "codex.config.toml")
    compiled = CodexAdapter().compile(context, {}, _choice(
        "codex", params=_request_params(reasoning_effort="xhigh")))
    paths = [intent.field_path for intent in compiled.intents]
    assert ("model_reasoning_effort",) in paths
    effort = next(intent for intent in compiled.intents
                  if intent.field_path == ("model_reasoning_effort",))
    assert effort.typed_value == "xhigh"
    # a config.toml top-level write is read at launch: never session-local
    assert compiled.reconfiguration == "restart-resume"


def test_codex_effort_vocabulary_is_pinned_and_deepseek_subset_applies():
    context = _context("codex", "codex.config.toml")
    refused = CodexAdapter().compile(context, {}, _choice(
        "codex", params=_request_params(reasoning_effort="xhigh"),
        brand_fields={"provider_family": "deepseek"}))
    assert isinstance(refused, Refusal) and "pinned vocabulary" in refused.message
    ok = CodexAdapter().compile(context, {}, _choice(
        "codex", params=_request_params(reasoning_effort="max"),
        brand_fields={"provider_family": "deepseek"}))
    assert isinstance(ok, IntentSet)
    assert common.codex_effort_values("deepseek") == ("low", "high", "max")


@pytest.mark.parametrize("family", ["budget", "timeout", "retry"])
def test_codex_unpinned_families_refuse_with_the_pinned_reason(family):
    context = _context("codex", "codex.config.toml")
    params = {
        "budget": _request_params(max_tokens=1024),
        "timeout": _request_params(timeout_ms=120000),
        "retry": _request_params(retry={"enabled": True, "maxRetries": 2,
                                        "provider": {"maxRetries": 1,
                                                     "maxRetryDelayMs": 500}}),
    }[family]
    compiled = CodexAdapter().compile(
        context, {}, _choice("codex", brand_fields={"before_provider": "openai"},
                             params=params))
    assert isinstance(compiled, Refusal), family
    assert "no first-hand" in compiled.message, family


# -- pi: budget rides the golden object; retry needs the settings target ---------


PI_MODELS = [{"id": "deepseek-flash", "maxTokens": 8192},
             {"id": "deepseek-reasoner", "maxTokens": 4096}]


def test_pi_budget_rewrites_the_golden_provider_object_from_the_native_sample():
    context = _context("pi", "pi.models.json")
    before = {"providers": {"deepseek": {"baseUrl": "https://api.deepseek.com",
                                         "models": PI_MODELS}}}
    compiled = PiAdapter().compile(
        context, before,
        _choice("pi", provider="deepseek", model="deepseek-reasoner",
                protocol="openai-chat",
                params=_request_params(max_tokens=2048)))
    assert isinstance(compiled, IntentSet)
    golden = next(intent for intent in compiled.intents
                  if intent.field_path == ("providers", "deepseek"))
    entries = {entry["id"]: entry for entry in golden.typed_value["models"]}
    assert entries["deepseek-reasoner"]["maxTokens"] == 2048
    assert entries["deepseek-flash"]["maxTokens"] == 8192  # siblings survive
    assert compiled.reconfiguration == "restart-resume"


def test_pi_budget_without_a_native_sample_or_entry_refuses():
    context = _context("pi", "pi.models.json")
    no_sample = PiAdapter().compile(
        context, {}, _choice("pi", provider="deepseek", model="deepseek-flash",
                             protocol="openai-chat",
                             params=_request_params(max_tokens=1024)))
    assert isinstance(no_sample, Refusal) and "native provider sample" in no_sample.message
    foreign = PiAdapter().compile(
        context, {"providers": {"deepseek": {"models": PI_MODELS}}},
        _choice("pi", provider="deepseek", model="unknown-model",
                protocol="openai-chat", params=_request_params(max_tokens=1024)))
    assert isinstance(foreign, Refusal) and "not in the current native sample" in foreign.message


def test_pi_retry_compiles_the_pinned_settings_block_against_its_own_target():
    context = _context("pi", "pi.models.json")
    compiled = PiAdapter().compile(
        context, {},
        _choice("pi", provider="deepseek", model="deepseek-flash",
                protocol="openai-chat",
                params=_request_params(retry={
                    "enabled": True, "maxRetries": 3,
                    "provider": {"maxRetries": 2, "maxRetryDelayMs": 800}})))
    assert isinstance(compiled, IntentSet)
    retry = next(intent for intent in compiled.intents
                 if intent.field_path == ("retry",))
    assert retry.target_handle.identity == common.PI_SETTINGS_HANDLE_ID
    assert retry.typed_value == {"enabled": True, "maxRetries": 3,
                                 "provider": {"maxRetries": 2,
                                              "maxRetryDelayMs": 800}}
    assert compiled.reconfiguration == "restart-resume"


def test_pi_effort_and_timeout_refuse_because_nothing_is_pinned_in_scope():
    context = _context("pi", "pi.models.json")
    effort = PiAdapter().compile(
        context, {}, _choice("pi", provider="deepseek", model="m",
                             protocol="openai-chat",
                             params=_request_params(reasoning_effort="high")))
    assert isinstance(effort, Refusal) and "launch-descriptor" in effort.message
    timeout = PiAdapter().compile(
        context, {}, _choice("pi", provider="deepseek", model="m",
                             protocol="openai-chat",
                             params=_request_params(timeout_ms=5000)))
    assert isinstance(timeout, Refusal) and "deployment descriptor" in timeout.message


# -- claude-code: nothing is pinned, every family refuses -------------------------


def test_claude_refuses_every_family_with_the_inventory_reason():
    context = _context("claude-code", "claude.settings.json")
    for params in (_request_params(reasoning_effort="high"),
                   _request_params(max_tokens=1024),
                   _request_params(timeout_ms=1000),
                   _request_params(retry={"enabled": False, "maxRetries": 0,
                                          "provider": {"maxRetries": 0,
                                                       "maxRetryDelayMs": 1}})):
        compiled = ClaudeAdapter().compile(
            context, {}, _choice("claude-code", protocol="anthropic-messages",
                                 params=params))
        assert isinstance(compiled, Refusal)
        assert "no first-hand request-param key" in compiled.message


# -- the wire payload schema and the descriptor claims -----------------------------


def test_payload_schema_carries_the_closed_request_params_object():
    from ordessa_model_provider_adapters import bridge
    schema = bridge.choice_payload_schema()
    properties = dict(schema.properties)
    assert "requestParams" in properties
    params = properties["requestParams"]
    names = [name for name, _ in params.properties]
    assert names == ["reasoningEffort", "maxTokens", "timeoutMs", "retry"]
    assert schema.required == ("provider", "model", "protocol")  # backward compatible


def test_malformed_request_params_answer_typed_results_not_raw_valueerror():
    from ordessa_model_provider_adapters import bridge
    from ordessa_harness_api import ErrorCode, TargetHandle as HarnessTargetHandle

    class _Target:
        kind = "file"
        handle = HarnessTargetHandle("codex.config.toml", 0)
    class _Installation:
        harness_id = "codex"
        native_version = (1, 5, 0)
    class _Context:
        installation = _Installation()
        targets = (_Target(),)
    context = _Context()
    payload = {"provider": "openai", "model": "gpt-5.1",
               "protocol": "openai-responses",
               "requestParams": {"maxTokens": 0}}
    assessed = bridge.BridgeConfigurationAdapter("codex").assess(context, payload)
    assert assessed.status == "unknown" and "malformed requestParams" in assessed.reason
    compiled = bridge.BridgeConfigurationAdapter("codex").compile(context, {}, payload)
    assert compiled.code is ErrorCode.INVALID_FRAGMENT
    assert "malformed requestParams" in compiled.reason


def test_the_retry_schema_and_the_dto_demand_the_same_keys():
    from ordessa_model_provider_adapters import bridge
    request_params = dict(bridge.choice_payload_schema().properties)["requestParams"]
    retry = dict(request_params.properties)["retry"]
    assert set(retry.required) == {"enabled", "maxRetries", "provider"}
    provider = dict(retry.properties)["provider"]
    assert set(provider.required) == {"maxRetries", "maxRetryDelayMs"}


def test_an_endpoint_change_is_never_dropped_by_the_budget_rewrite():
    """Review fix: budget rides the golden object, but the choice's own
    endpoint/protocol still win over the sample's routing facts."""
    context = _context("pi", "pi.models.json")
    before = {"providers": {"deepseek": {"baseUrl": "https://api.deepseek.com",
                                         "api": "openai-completions",
                                         "models": PI_MODELS}}}
    compiled = PiAdapter().compile(
        context, before,
        _choice("pi", provider="deepseek", model="deepseek-flash",
                protocol="openai-chat",
                params=_request_params(max_tokens=1024),
                brand_fields={}))
    assert isinstance(compiled, IntentSet)
    golden = next(intent for intent in compiled.intents
                  if intent.field_path == ("providers", "deepseek"))
    assert golden.typed_value["models"][0]["maxTokens"] == 1024
    assert set(golden.typed_value["models"][0]) == set(PI_MODELS[0])  # siblings' fields kept


def test_the_pi_descriptor_claims_the_settings_target_and_the_codex_effort_field():
    from ordessa_model_provider_adapters import bridge
    pi_claims = [claim for claim in bridge.descriptor_for("pi").claims
                 if claim.target_kind == "file"]
    assert any(claim.target_id == common.PI_SETTINGS_HANDLE_ID
               and claim.field_path == ("retry",) for claim in pi_claims)
    codex_claims = [claim for claim in bridge.descriptor_for("codex").claims
                    if claim.target_kind == "file"]
    assert any(claim.field_path == ("model_reasoning_effort",)
               for claim in codex_claims)


def test_an_unissued_param_target_compiles_to_a_typed_refusal_not_a_lookalike():
    """The pi settings claim is inert until the host issues the target: the
    bridge refuses with CAPABILITY_UNSUPPORTED instead of writing anywhere."""
    from ordessa_model_provider_adapters import bridge
    from ordessa_model_provider_adapters.types import (
        AdapterContext as Local, TargetHandle as LocalHandle)

    from ordessa_harness_api import TargetHandle as HarnessTargetHandle
    class _Target:
        kind = "file"
        handle = HarnessTargetHandle("pi.models.json", 0)
    class _Installation:
        harness_id = "pi"
        native_version = (0, 5, 2)
    class _Context:
        installation = _Installation()
        targets = (_Target(),)

    compiled = PiAdapter().compile(
        Local(target_handle=LocalHandle(harness_id="pi", scope="instance",
                                        identity="pi.models.json"),
              harness_version="0.5.2"),
        {},
        _choice("pi", provider="deepseek", model="m", protocol="openai-chat",
                params=_request_params(retry={
                    "enabled": False, "maxRetries": 0,
                    "provider": {"maxRetries": 0, "maxRetryDelayMs": 1}})))
    assert isinstance(compiled, IntentSet)
    refused = bridge.BridgeConfigurationAdapter("pi").compile(
        _Context(), {}, {
            "provider": "deepseek", "model": "m", "protocol": "openai-chat",
            "brandFields": {"provider_in_instance": False},
            "requestParams": {"retry": {
                "enabled": False, "maxRetries": 0,
                "provider": {"maxRetries": 0, "maxRetryDelayMs": 1}}}})
    from ordessa_harness_api import ErrorCode
    assert refused.code is ErrorCode.CAPABILITY_UNSUPPORTED
    assert "has not issued" in refused.reason
