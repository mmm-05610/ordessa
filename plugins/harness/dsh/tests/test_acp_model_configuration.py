"""dsh ACP model semantics: honest empty tables, typed refusals, no native calls.

No dsh binary, model call or production configuration owner is involved; the
adapter surface is intentionally absent and every test pins that absence.
"""
from dataclasses import replace

import pytest

from ordessa_execution_agents.harness.definitions.model_compilation import (
    AdapterContext, ChoiceRequest, RequestParams, Refusal, TargetHandle, Verdict,
)
from ordessa_harness_dsh.acp_model_configuration import (
    ADAPTER_ID, DSH_MODEL_KIND, DshAdapter, registration_manifest,
)
from ordessa_harness_dsh.acp_model_facts import (
    DIALECT, NATIVE_TARGET, RANGE_STRINGS, ProtocolUnsupported,
    identity_text, translate_protocol, version_in_range,
)


def context(session="ses-fixture", target=None, version="0.1.5-rc.1"):
    return AdapterContext(target or TargetHandle("dsh", "instance", "fixture"), version,
                          {"native_session_id": session})


def choice(**changes):
    brand = {"before_provider": "acme"}
    brand.update(changes)
    return ChoiceRequest("provider-config", "new-model", "https://fixture.test",
                         "openai-responses", "ref://fixture-secret", "acme", brand)


# -- facts: empty-table family rules -----------------------------------------


def test_family_tables_are_empty_by_construction():
    assert DIALECT == {}
    assert NATIVE_TARGET == {"dsh": None}
    assert RANGE_STRINGS == {"dsh": ""}


@pytest.mark.parametrize("protocol", ["openai-responses", "openai-chat", "anthropic-messages",
                                      "gemini-generate", "future/protocol"])
def test_translate_protocol_always_refuses_for_dsh(protocol):
    with pytest.raises(ProtocolUnsupported):
        translate_protocol("dsh", protocol)


def test_translate_protocol_refuses_other_families():
    with pytest.raises(ProtocolUnsupported):
        translate_protocol("codex", "openai-responses")


@pytest.mark.parametrize("version,expected", [
    # prerelease pins (0.1.5-rc.1 / 0.2.0-rc.2) are unparsable by the range
    # parser: honestly "unknown", never "supported" — the range is empty.
    ("0.1.5-rc.1", "unknown"), ("0.2.0-rc.2", "unknown"),
    ("1.2.3", "unsupported"), (None, "unknown"), ("garbage", "unknown")])
def test_version_range_is_empty_so_nothing_is_supported(version, expected):
    assert version_in_range("dsh", version) == expected


def test_version_fact_cannot_describe_another_family():
    with pytest.raises(ValueError):
        version_in_range("codex", "0.157.1")


# -- adapter: assess / compile / verify --------------------------------------


def test_assess_is_unsupported_with_the_absence_reason():
    result = DshAdapter().assess(context(), choice())
    assert result.verdict == "unsupported"
    assert "no pinned model-configuration evidence port" in result.reason
    assert result.harness_id == "dsh"
    assert result.native_version == "0.1.5-rc.1"


@pytest.mark.parametrize("version", ["0.1.5-rc.1", "0.2.0-rc.2", None])
def test_assess_never_upgrades_with_the_cli_pin(version):
    # The npm CLI pin is a channel pin: it must never upgrade a configuration
    # assessment to supported.
    assert DshAdapter().assess(context(version=version), choice()).verdict == "unsupported"


def test_compile_refuses_own_target_with_the_absence_reason():
    result = DshAdapter().compile(context(), {}, choice())
    assert isinstance(result, Refusal)
    assert result.code == "capability-unsupported"
    assert "honestly absent" in result.message
    assert result.details == {"kind": DSH_MODEL_KIND}


@pytest.mark.parametrize("target", [TargetHandle("pi", "instance", "fixture"),
                                     TargetHandle("dsh", "instance", None),
                                     TargetHandle("codex", "instance", "fixture")])
def test_foreign_or_missing_target_cannot_compile(target):
    result = DshAdapter().compile(context(target=target), {}, choice())
    assert isinstance(result, Refusal)
    assert result.code == "target-conflict"


def test_project_scope_target_refuses_with_the_absence_reason():
    # dsh pins NO scope claim in this tree: an out-of-instance scope cannot be
    # refused as a scope conflict (that would invent a scope fact); it hits
    # the honest absence refusal instead.
    result = DshAdapter().compile(context(target=TargetHandle("dsh", "project", "fixture")),
                                  {}, choice())
    assert isinstance(result, Refusal)
    assert result.code == "capability-unsupported"


@pytest.mark.parametrize("facts", [{}, {"before_provider": None}])
def test_absent_original_provider_still_refuses_with_the_absence_reason(facts):
    result = DshAdapter().compile(context(), {}, replace(choice(), brand_fields=facts))
    assert isinstance(result, Refusal)
    assert result.code == "capability-unsupported"


@pytest.mark.parametrize("params", [RequestParams(reasoning_effort="high"),
                                     RequestParams(max_tokens=1024)])
def test_request_params_never_produce_intents(params):
    result = DshAdapter().compile(context(), {}, replace(choice(), params=params))
    assert isinstance(result, Refusal)  # no CompileIntent is ever produced


def test_verify_is_always_unknown():
    compiler = DshAdapter()
    verdict = compiler.verify(context(), {"desired_model": "new-model",
                                          "readback": {"model": "new-model"},
                                          "native_session_id": "ses-fixture"})
    assert isinstance(verdict, Verdict)
    assert verdict.verdict == "unknown"
    assert "never an applied fact" in verdict.reason
    assert compiler.verify(context(), {"rpc_ack": True}).verdict == "unknown"
    assert compiler.verify(context(), {}).verdict == "unknown"


def test_verify_foreign_target_is_unknown():
    verdict = DshAdapter().verify(context(target=TargetHandle("pi", "instance", "fixture")),
                                  {"desired_model": "new-model"})
    assert verdict.verdict == "unknown"
    assert "target identity" in verdict.reason


# -- registration manifest -----------------------------------------------------


def test_manifest_shape_and_identity():
    manifest = registration_manifest()
    assert manifest == {
        "adapter_id": ADAPTER_ID,
        "facet_id": "assets.model-provider",
        "facet_schema_version": 1,
        "api_version": "v1",
        "harness_id": "dsh",
        "kind": DSH_MODEL_KIND,
        "supported_native_versions": "",
        "native_target": None,
        "entries": ("assess", "compile", "verify"),
        "payload_schema": "model-provider.choice.v1",
        "claims": {},
    }


def test_identity_text_helper_boundary():
    assert identity_text("acme.dev") is True
    for bad in (None, "", " ", True, 1, "bad\x00identity", " bad"):
        assert identity_text(bad) is False
