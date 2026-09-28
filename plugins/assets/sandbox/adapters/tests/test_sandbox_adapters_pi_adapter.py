"""T05 — Pi native-sandbox adapter: extension-backed only, never bare Pi.

Evidence: Pi has no built-in native sandbox; the official path is an optional
``sandbox/`` extension that replaces Bash and depends on an external runtime
(harness-adapters.md Pi row; API ``PiSandboxConfig`` refuses without a named
extension). With no evidence of the loaded extension the result is
``SANDBOX_NATIVE_UNSUPPORTED`` and NOTHING is compiled — there is no fallback
that configures bare Pi as isolated (the 横向反例 "Pi 扩展缺席却 UI 显示安全").
"""
from _sandbox_adapters_helpers import (
    PI_TARGET,
    authorized_facts,
    permissive_ceiling,
    pin,
    pi_intent,
    platform_facts,
    target_handle,
)

import pytest

from ordessa_harness_api import InvokeAction
from ordessa_sandbox_api import SandboxErrorCode
from ordessa_sandbox_adapters import (
    CompileRefusal,
    CompiledIntent,
    KIND_INVOKE_ACTION,
    PiSandboxAdapter,
    PiSandboxExtensionEvidence,
    sandbox_code_of,
)

CEILING = (permissive_ceiling(brand="pi"),)


def _loaded_evidence():
    return PiSandboxExtensionEvidence.of(
        extension_id="sandbox-ext", loaded=True,
        observed_native_version=pin_version())


def pin_version() -> str:
    from _sandbox_adapters_helpers import pinned_versions
    return pinned_versions()["pi"]


def test_no_extension_evidence_refuses_and_compiles_nothing():
    adapter = PiSandboxAdapter()
    result = adapter.compile(pi_intent(), target_handle(PI_TARGET), CEILING,
                             authorized=authorized_facts())
    assert isinstance(result, CompileRefusal)
    assert result.code.value == "SANDBOX_NATIVE_UNSUPPORTED"
    # zero compiled intents — no bare-Pi fallback
    assert result.emitted_intents == ()
    assert result.intents == ()


def test_extension_present_but_not_loaded_refuses():
    adapter = PiSandboxAdapter()
    unloaded = PiSandboxExtensionEvidence.of(
        extension_id="sandbox-ext", loaded=False,
        observed_native_version=pin_version())
    result = adapter.compile(pi_intent(), target_handle(PI_TARGET), CEILING,
                             authorized=authorized_facts(pi_sandbox_extension=unloaded))
    assert isinstance(result, CompileRefusal)
    assert result.code.value == "SANDBOX_NATIVE_UNSUPPORTED"
    assert result.emitted_intents == ()


def test_extension_observed_at_a_different_pin_is_unknown_not_compiled():
    adapter = PiSandboxAdapter()
    stale = PiSandboxExtensionEvidence.of(
        extension_id="sandbox-ext", loaded=True, observed_native_version="9.9")
    result = adapter.compile(pi_intent(), target_handle(PI_TARGET), CEILING,
                             authorized=authorized_facts(pi_sandbox_extension=stale))
    assert isinstance(result, CompileRefusal)
    assert result.code.value == "SANDBOX_EFFECT_UNKNOWN"


def test_loaded_extension_compiles_an_invoke_action():
    adapter = PiSandboxAdapter()
    result = adapter.compile(pi_intent(), target_handle(PI_TARGET), CEILING,
                             authorized=authorized_facts(pi_sandbox_extension=_loaded_evidence()))
    assert isinstance(result, CompiledIntent)
    assert result.intents
    kinds = {f.kind for f in result.intents}
    # the PLATFORM kind literal, not a private spelling
    assert kinds == {KIND_INVOKE_ACTION}
    paths = {f.field_path for f in result.intents}
    assert paths <= set(adapter.native_field_claims())


def test_loaded_extension_compiles_a_real_platform_invoke_action():
    """Pi's action form is the §C2 `InvokeAction`: the compiled field binds to
    the platform class and declares the observation it expects."""
    adapter = PiSandboxAdapter()
    handle = target_handle(PI_TARGET)
    result = adapter.compile(pi_intent(), handle, CEILING,
                             authorized=authorized_facts(pi_sandbox_extension=_loaded_evidence()))
    intent = result.intents[0].to_harness_c3()
    assert isinstance(intent, InvokeAction)
    assert intent.kind == KIND_INVOKE_ACTION
    # the platform's sealed InvokeAction carries NO target field: an action is
    # attributed by its IntentSource and addressed by action id — the pre-
    # binding record keeps the server-issued handle, the C3 action does not
    # re-carry it (intents.py InvokeAction(source, action_id, schema_version,
    # typed_payload, expected_observation)); asserting its absence here pins
    # the shape so a second private InvokeAction spelling cannot creep back in
    assert not hasattr(intent, "target")
    assert intent.source.facet_id == "sandbox.native-configuration"
    assert intent.action_id == "sandboxExtension"
    assert intent.schema_version  # the contribution version, platform-required
    assert intent.typed_payload == "sandbox-ext"
    assert intent.expected_observation == (
        f"pi-sandbox-extension-loaded:sandbox-ext@{pin_version()}")
    # an action without a declared expected observation is refused by the
    # platform DTO, not by a private guard here
    from ordessa_harness_api import ContractError
    bare = result.intents[0].__class__(**{
        **{f: getattr(result.intents[0], f) for f in
           ("field_path_segments", "value", "kind", "intent", "target")},
        "expected_observation": None})
    with pytest.raises(ContractError):
        bare.to_harness_c3()


def test_assess_without_extension_is_unsupported():
    adapter = PiSandboxAdapter()
    r = adapter.assess(pin("pi", pin_version()), platform_facts(), authorized_facts())
    assert r.status == "unsupported"
    assert sandbox_code_of(r.reason) is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED
    good = adapter.assess(pin("pi", pin_version()), platform_facts(),
                          authorized_facts(pi_sandbox_extension=_loaded_evidence()))
    assert good.status == "supported"
    assert good.evidence_ref
