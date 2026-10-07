"""Historical ACP pure model semantics, not native app-server application."""
from dataclasses import replace
import tomllib
import pytest
from pacthold.harness_contracts.model_compilation import (
    AdapterContext, BindSecret, ChoiceRequest, CompileIntent, MountContent, Refusal, RequestParams, TargetHandle)
from ordessa_harness_codex.acp_model_configuration import CodexAdapter
from ordessa_harness_codex.acp_model_facts import render_codex_provider_section


def context(session="original-thread", target=None):
    return AdapterContext(target or TargetHandle("codex", "instance", "fixture"), "1.1.14",
                          {"native_session_id": session})


def choice(**changes):
    brand = {"before_provider": "acme"}; brand.update(changes)
    return ChoiceRequest("provider-config", "new-model", "https://fixture.test", "openai-responses",
                         "ref://fixture-secret", "acme", brand)


def test_model_only_is_session_local_and_cross_provider_preserves_all_intents():
    compiler = CodexAdapter()
    result = compiler.compile(context(), {}, choice())
    assert result.reconfiguration == "session-local" and len(result.intents) == 1
    assert result.intents[0].field_path == ("model",) and result.intents[0].typed_value == "new-model"
    result = compiler.compile(context(), {}, choice(before_provider="other"))
    assert result.reconfiguration == "restart-resume"
    assert result.resume_expectation == {"native_session_id": "original-thread"}
    assert any(isinstance(item, MountContent) and item.content_ref == "codex-provider-section:acme" for item in result.intents)
    assert any(isinstance(item, CompileIntent) and item.field_path == ("model_provider",) and item.typed_value == "acme" for item in result.intents)
    assert any(isinstance(item, BindSecret) and item.slot == "CODEX_API_KEY" and item.secret_ref == "ref://fixture-secret" for item in result.intents)


def test_same_provider_endpoint_change_keeps_routing_in_restart_plan():
    result = CodexAdapter().compile(context(), {}, choice(endpoint_changed=True))
    assert result.reconfiguration == "restart-resume"
    assert any(isinstance(item, MountContent) for item in result.intents)
    assert any(isinstance(item, CompileIntent) and item.field_path == ("model",) for item in result.intents)


def test_same_provider_credential_change_keeps_reference_without_rewriting_endpoint():
    result = CodexAdapter().compile(context(), {}, choice(credential_changed=True))
    assert result.reconfiguration == "restart-resume"
    assert any(isinstance(item, BindSecret) and item.secret_ref == "ref://fixture-secret" for item in result.intents)
    assert not any(isinstance(item, MountContent) for item in result.intents)


@pytest.mark.parametrize("value", [None, "", " ", True, 1, "bad\x00identity", "bad\ud800identity"])
def test_unobserved_or_untyped_thread_never_confirms_model(value):
    observed = {"desired_model": "new-model", "readback": {"model": "new-model"}, "native_session_id": value}
    assert CodexAdapter().verify(context(value), observed).verdict == "unknown"


@pytest.mark.parametrize("expected,actual", [(None,None), (True,1), ("", "")])
def test_untyped_model_comparison_never_confirms(expected,actual):
    assert CodexAdapter().verify(context(), {"desired_model": expected, "readback": {"model": actual},
                                           "native_session_id": "original-thread"}).verdict == "unknown"


@pytest.mark.parametrize("target", [TargetHandle("pi", "instance", "fixture"), TargetHandle("codex", "project", "fixture"), TargetHandle("codex", "instance", None)])
def test_foreign_or_missing_target_cannot_compile_or_confirm(target):
    compiler = CodexAdapter(); wrong = context(target=target)
    assert isinstance(compiler.compile(wrong, {}, choice()), Refusal)
    assert compiler.verify(wrong, {"desired_model": "new-model", "readback": {"model": "new-model"},
                                  "native_session_id": "original-thread"}).verdict == "unknown"


@pytest.mark.parametrize("flag", [True, 1, {}, "true"])
def test_changed_credential_without_valid_reference_refuses(flag):
    result = CodexAdapter().compile(context(), {}, replace(choice(credential_changed=flag), credential_ref=None))
    assert isinstance(result, Refusal)


@pytest.mark.parametrize("reference", [True, {}, 1, "bad\x00ref"])
def test_malformed_reference_never_becomes_secret_binding(reference):
    result = CodexAdapter().compile(context(), {}, replace(choice(before_provider="other"), credential_ref=reference))
    assert isinstance(result, Refusal)


@pytest.mark.parametrize("provider", ["acme.dev", 'quoted"provider'])
def test_toml_provider_name_is_one_literal_key(provider):
    section = render_codex_provider_section(provider=provider, base_url="https://fixture.test", protocol="openai-responses")
    tables = tomllib.loads(section)["model_providers"]
    assert list(tables) == [provider] and tables[provider]["name"] == provider


def test_quoted_endpoint_roundtrips_without_injection():
    endpoint = 'https://fixture.test/path?q="quoted"'
    section = render_codex_provider_section(provider="acme", base_url=endpoint, protocol="openai-responses")
    tables = tomllib.loads(section)
    assert list(tables) == ["model_providers"]
    assert tables["model_providers"]["acme"]["base_url"] == endpoint


@pytest.mark.parametrize("provider,endpoint", [('a\n[evil]', "https://fixture.test"), ('acme', 'https://fixture.test"\n[evil]'), ('acme', None)])
def test_malformed_toml_values_refuse_before_render(provider,endpoint):
    with pytest.raises(ValueError): render_codex_provider_section(provider=provider,base_url=endpoint,protocol="openai-responses")


def test_effort_and_supported_version_axes_preserve_positive_planning():
    compiler = CodexAdapter()
    result = compiler.compile(context(), {}, replace(choice(), params=RequestParams(reasoning_effort="high")))
    assert result.reconfiguration == "restart-resume"
    assert any(isinstance(item, CompileIntent) and item.field_path == ("model_reasoning_effort",) and item.typed_value == "high" for item in result.intents)
    assert compiler.assess(context(), choice()).verdict == "supported"
    assert compiler.assess(replace(context(), harness_version="0.157.1"), choice()).verdict == "unsupported"
    assert compiler.assess(replace(context(), harness_version=None), choice()).verdict == "unknown"


def test_real_same_thread_readback_is_positive_but_ack_is_not():
    compiler = CodexAdapter(); observation = {"desired_model": "new-model", "desired_provider": "acme",
        "readback": {"model": "new-model", "provider": "acme"}, "native_session_id": "original-thread"}
    verdict = compiler.verify(context(), observation)
    assert verdict.verdict == "match" and verdict.evidence == {"applied_layer": "thread-readback"}
    assert compiler.verify(context(), {"desired_model": "new-model", "rpc_ack": True}).verdict == "unknown"
    observation["native_session_id"] = "replacement-thread"
    assert compiler.verify(context(), observation).verdict == "mismatch"


@pytest.mark.parametrize("facts", [{}, {"before_provider": None}])
def test_absent_original_provider_cannot_be_assumed_unchanged(facts):
    result = CodexAdapter().compile(context(), {}, replace(choice(), brand_fields=facts))
    assert isinstance(result, Refusal)
    assert "previous provider" in result.message


@pytest.mark.parametrize("provider,endpoint", [("api\x7fhost", "https://fixture.test"), ("acme", "https://fixture.test/\x7fpath")])
def test_del_control_refuses_renderer_and_routing_compilation(provider, endpoint):
    with pytest.raises(ValueError):
        render_codex_provider_section(provider=provider, base_url=endpoint, protocol="openai-responses")
    desired = replace(choice(endpoint_changed=True), provider_name=provider, endpoint=endpoint)
    assert isinstance(CodexAdapter().compile(context(), {}, desired), Refusal)
