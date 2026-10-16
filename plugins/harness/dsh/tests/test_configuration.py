"""New: dsh configuration surface is honestly ABSENT in this package version.

No Codex-style CAS write path exists for dsh: the freeze pins NO configuration
evidence port for this family, so the four configuration methods never enter
the descriptor, calling them raises a typed refusal, and the ACP model
adapter (kind ``dsh.model``) assesses unsupported / refuses compile / verifies
unknown. No dsh binary, model, production input owner or authority is used.
"""
from types import SimpleNamespace
import inspect

import pytest

from test_provider import fixture, UNIT, DEFINITION, DIGEST, CONFIGURATION_CALLS
from ordessa_harness_dsh import DshRuntimeProvider, DshCapabilityUnsupported
from ordessa_harness_dsh.acp_model_configuration import ADAPTER_ID, DSH_MODEL_KIND, DshAdapter
from ordessa_harness_dsh.acp_model_facts import DIALECT, NATIVE_TARGET, RANGE_STRINGS
from ordessa_execution_agents.harness.definitions.model_compilation import (
    AdapterContext, ChoiceRequest, Refusal, TargetHandle, Verdict, Assessment,
)

CONFIGURATION_METHODS = ("describe_configuration", "inspect_configuration",
                         "apply_configuration", "query_change")


def test_provider_has_no_configuration_evidence_port_parameter():
    parameters = inspect.signature(DshRuntimeProvider.__init__).parameters
    assert "configuration_evidence" not in parameters
    assert "implementation_digest" in parameters
    assert parameters["implementation_digest"].default is inspect.Parameter.empty


def test_full_wiring_still_omits_every_configuration_method():
    provider, projection, records, client, context = fixture()
    methods = provider.descriptor.supported_methods
    for name in CONFIGURATION_METHODS:
        assert name not in methods
    described = provider.describe_definition(DEFINITION)
    for name in CONFIGURATION_METHODS:
        assert name not in described["supportedMethods"]
    assert described["familyId"] == "dsh"
    assert described["channel"] == "dsh-acp/1"
    assert described["recovery"] == "unsupported"
    assert described["nativeVersion"] == "0.1.5-rc.1"
    assert described["nativeVersionVerified"] is False


def test_each_configuration_method_raises_typed_refusal_with_the_absence_reason():
    provider, projection, records, client, context = fixture()
    for name, args in CONFIGURATION_CALLS:
        with pytest.raises(DshCapabilityUnsupported, match="dsh capability unavailable"):
            getattr(provider, name)(*args)
    # A refused configuration call never reaches the native channel.
    assert client.calls == []


def test_configuration_family_is_absent_even_when_channel_and_lease_ports_exist():
    provider, projection, records, client, context = fixture(
        lease_port=SimpleNamespace(bind=lambda *args: None))
    methods = provider.descriptor.supported_methods
    for name, args in CONFIGURATION_CALLS:
        assert name not in methods
        with pytest.raises(DshCapabilityUnsupported):
            getattr(provider, name)(*args)


# -- ACP model adapter: honest absence ---------------------------------------


def context(target=None, version="0.1.5-rc.1"):
    return AdapterContext(target or TargetHandle("dsh", "instance", "fixture"), version,
                          {"native_session_id": "ses-fixture"})


def choice():
    return ChoiceRequest("provider-config", "new-model", "https://fixture.test",
                         "openai-responses", "ref://fixture-secret", "acme",
                         {"before_provider": "acme"})


def test_registration_manifest_is_empty_by_design():
    manifest = DshAdapter.registration_manifest()
    assert manifest["adapter_id"] == ADAPTER_ID == "assets.model-provider.dsh"
    assert manifest["harness_id"] == "dsh"
    assert manifest["kind"] == DSH_MODEL_KIND == "dsh.model"
    assert manifest["supported_native_versions"] == ""
    assert manifest["native_target"] is None
    assert manifest["claims"] == {}


def test_empty_family_tables_are_frozen():
    assert DIALECT == {}
    assert NATIVE_TARGET == {"dsh": None}
    assert RANGE_STRINGS == {"dsh": ""}


def test_assess_is_unsupported_with_the_absence_reason():
    for version in ("0.1.5-rc.1", "0.2.0-rc.2", None, "garbage"):
        result = DshAdapter().assess(context(version=version), choice())
        assert isinstance(result, Assessment)
        assert result.verdict == "unsupported"
        assert "no pinned model-configuration evidence port" in result.reason
        assert result.harness_id == "dsh"
        assert result.native_version == version


def test_compile_refuses_typed_for_own_and_foreign_targets():
    compiler = DshAdapter()
    own = compiler.compile(context(), {}, choice())
    assert isinstance(own, Refusal)
    assert own.code == "capability-unsupported"
    assert "honestly absent" in own.message
    assert own.details == {"kind": "dsh.model"}
    for target in (TargetHandle("pi", "instance", "fixture"),
                   TargetHandle("dsh", "instance", None),
                   TargetHandle("codex", "instance", "fixture")):
        refusal = compiler.compile(context(target=target), {}, choice())
        assert isinstance(refusal, Refusal)
        assert refusal.code == "target-conflict"
    # dsh pins NO scope claim in this tree: an out-of-instance scope cannot
    # invent a scope conflict; it hits the honest absence refusal instead.
    scoped = compiler.compile(context(target=TargetHandle("dsh", "project", "fixture")),
                              {}, choice())
    assert isinstance(scoped, Refusal) and scoped.code == "capability-unsupported"


def test_verify_is_always_unknown_and_never_confirms():
    compiler = DshAdapter()
    verdict = compiler.verify(context(), {"desired_model": "new-model",
                                          "readback": {"model": "new-model"},
                                          "native_session_id": "ses-fixture"})
    assert isinstance(verdict, Verdict)
    assert verdict.verdict == "unknown"
    assert "never an applied fact" in verdict.reason
    foreign = compiler.verify(context(target=TargetHandle("pi", "instance", "fixture")),
                              {"desired_model": "new-model"})
    assert foreign.verdict == "unknown"


def test_no_provider_section_renderer_exists_for_dsh():
    import ordessa_harness_dsh.acp_model_facts as facts
    renderers = [name for name in dir(facts) if name.startswith("render_")]
    assert renderers == []  # no pinned dsh provider-section renderer exists
