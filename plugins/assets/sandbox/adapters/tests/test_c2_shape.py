"""T05 — the §C2 `sandbox.native-configuration@1` adapter shape.

Each brand adapter exposes exactly `assess / compile / verify` (contracts.md
§C2: input = version / platform / config-target handle / authorized facts;
output = assess/compile/verify). Since the foundation checkpoint the
contribution rides the REAL `harness.configuration-adapters` point: the
registration carries `Contribution` records whose payload is the platform's
`ConfigurationAdapterDescriptor`, keyed by `(harnessId, nativeVersionRange)`
with owner/generation left for the host to assign (§C4) — the author never
declares an owner and the package keeps no private admission copy.

Since the `harness-api` checkpoint the verdict types are the platform's too:
`assess` answers an `ordessa_harness_api.Assessment` and `verify` a
`Verification`, and the host-callable shape is the published
`ConfigurationAdapter` contract (`surface.py`) — the package keeps no local
mirror of either.
"""
from __future__ import annotations

import inspect

from _sandbox_adapters_helpers import (
    CODEX_TARGET,
    authorized_facts,
    codex_intent,
    effect_observation,
    permissive_ceiling,
    pin,
    platform_facts,
    target_handle,
)
from ordessa_harness_api.contracts import (
    AdapterContext,
    Assessment,
    ConfigurationAdapter,
    ConfigurationAdapterDescriptor,
    Match,
    Verification,
    VerificationUnknown,
)
from server_plugin_api import ServerPluginContext, ServerPluginDescriptor

from ordessa_sandbox_adapters import (
    ADAPTER_PLUGIN_ID,
    ClaudeSandboxAdapter,
    CodexSandboxAdapter,
    PiSandboxAdapter,
    SANDBOX_CONFIGURATION_POINT_ID,
    SANDBOX_FACET_ID,
    SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID,
    SandboxAdaptersServerPlugin,
    SandboxConfigurationSurface,
    build_configuration_descriptor,
    default_sandbox_adapters,
)

BRAND_OF = {CodexSandboxAdapter: "codex", ClaudeSandboxAdapter: "claude-code",
            PiSandboxAdapter: "pi"}


def test_each_adapter_exposes_assess_compile_verify():
    for adapter in default_sandbox_adapters():
        for verb in ("assess", "compile", "verify"):
            assert callable(getattr(adapter, verb)), (adapter.adapter_id, verb)


def test_the_local_adapter_protocol_copy_is_gone():
    """`SandboxNativeConfigurationAdapter` mirrored the platform Protocol; after
    the harness-api checkpoint the published `ConfigurationAdapter` is the only
    adapter shape this package names."""
    import ordessa_sandbox_adapters
    assert not hasattr(ordessa_sandbox_adapters, "SandboxNativeConfigurationAdapter")
    for name in ("AssessReport", "AssessOutcome", "VerifyResult", "VerifyOutcome"):
        assert not hasattr(ordessa_sandbox_adapters, name), name


def test_compile_takes_the_server_issued_target_handle_not_a_string():
    """§C2's "配置目标句柄" is the platform handle: a bare string is refused as
    a typed refusal, and no generation is ever invented from it."""
    adapter = CodexSandboxAdapter()
    result = adapter.compile(codex_intent(), "codex-config-toml",
                             (permissive_ceiling(),))
    assert result.outcome == "refusal"
    assert result.code.value == "SANDBOX_INTENT_INVALID"
    assert result.emitted_intents == ()
    ok = adapter.compile(codex_intent(), target_handle(CODEX_TARGET),
                         (permissive_ceiling(),))
    assert ok.outcome == "intent-set"


def test_the_surface_conforms_to_the_published_configuration_adapter():
    """No private protocol any more: conformance is to the PLATFORM type."""
    surface = SandboxConfigurationSurface(
        CodexSandboxAdapter(), intent=codex_intent(),
        platform_facts=platform_facts(), authorized=authorized_facts(),
        ceilings=(permissive_ceiling(),))
    # the platform Protocol is in the real base list (Python-enforced shape)
    assert ConfigurationAdapter in type(surface).__mro__
    for member in sorted(ConfigurationAdapter.__protocol_attrs__):
        if member == "descriptor":
            # the payload the point's handler isinstance-checks is the platform's
            assert isinstance(surface.descriptor, ConfigurationAdapterDescriptor)
            continue
        implemented = getattr(type(surface), member)
        # every method is implemented here, not inherited as the `...` stub
        protocol_method = getattr(ConfigurationAdapter, member)
        assert implemented is not protocol_method, member
        assert callable(implemented), member
        # and each one is declared against the platform context type: the
        # platform protocol spells every verb `def assess(self, context, ...)`,
        # so the context arrives as a parameter (the adapter holds none) —
        # the surface matches the platform parameter-for-parameter and the
        # first parameter after `self` is `context`
        declared = list(inspect.signature(protocol_method).parameters)
        assert list(inspect.signature(implemented).parameters) == declared, member
        assert declared[0] == "self" and declared[1] == "context", member


def test_assess_and_verify_answer_with_platform_objects(pinned):
    adapter = CodexSandboxAdapter()
    assessment = adapter.assess(pin("codex", pinned["codex"]), platform_facts(),
                                authorized_facts())
    assert isinstance(assessment, Assessment)
    assert assessment.status in {"supported", "unsupported", "unknown"}
    assert isinstance(adapter.verify(effect_observation("verified")), Match)
    assert isinstance(adapter.verify(effect_observation("unknown")),
                      VerificationUnknown)


def test_adapter_is_keyed_by_harness_and_version_range():
    for adapter in default_sandbox_adapters():
        assert adapter.harness_id == BRAND_OF[type(adapter)]
        assert adapter.version_range is not None
        descriptor = build_configuration_descriptor(adapter)
        assert descriptor.harness_id == adapter.harness_id
        assert descriptor.facet_id == SANDBOX_FACET_ID
        # the measured range still gates assess: an out-of-range pin is
        # `unknown`, never an invented menu
        assert descriptor.native_versions.minimum == \
            descriptor.native_versions.maximum


def test_assess_returns_the_platform_assessment(pinned):
    adapter = CodexSandboxAdapter()
    report = adapter.assess(pin("codex", pinned["codex"]), platform_facts(),
                            authorized_facts())
    assert report.status in {"supported", "unsupported", "unknown"}


def test_compile_takes_intent_target_handle_and_ceiling():
    adapter = CodexSandboxAdapter()
    result = adapter.compile(codex_intent(), target_handle(CODEX_TARGET),
                             (permissive_ceiling(),))
    # a supported compile is a value (intent-set), never an exception
    assert result.outcome in {"intent-set", "refusal"}



def test_registration_carries_the_real_contributions_not_a_private_port():
    plugin = SandboxAdaptersServerPlugin()
    descriptor = plugin.descriptor()
    assert isinstance(descriptor, ServerPluginDescriptor)
    assert descriptor.id == ADAPTER_PLUGIN_ID
    # `requires` stays empty: Sandbox installs without Permissions (gate 2)
    assert descriptor.requires == ()
    registration = plugin.build(ServerPluginContext(
        plugin_id=descriptor.id, data_root=None, ports={}))
    # the old private port-named contribution is gone; the facet rides the
    # real point declared on the registration
    assert registration.provided_ports == {}
    batch = registration.contributions
    assert len(batch.contributions) == 3
    assert {item.point_id for item in batch.contributions} == \
        {SANDBOX_CONFIGURATION_POINT_ID}
    # owner/generation are host-assigned (§C4): nothing author-declared
    for item in batch.contributions:
        assert not hasattr(item.payload, "owner")
        assert not hasattr(item.payload, "generation")


def test_contract_id_still_names_the_facet_for_the_domain_dialect():
    assert SANDBOX_NATIVE_CONFIGURATION_CONTRACT_ID == \
        "sandbox.native-configuration@1"
