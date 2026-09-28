"""PB-6: the model-provider facet GLUED to the real profile-api v2 surface
(REQ-Z3-3; consumed r2 = e6f720d347 via the PB-6 merge commit).

Every gate drives the REAL ``ordessa_profile`` objects — the published
``FacetRegistry``, the protocol check ``FacetProviderV2``, the descriptor
validators — never a local re-statement of the profile side. The
EffectiveChoiceResolver and the archive-time reference view keep their
011-era semantics (override/switch/reference) and are shown wired to the
real resolution inputs.
"""
from __future__ import annotations

import pytest
from ordessa_profile.contracts import Applicability
from ordessa_profile.errors import ProfileError
from ordessa_profile.facets import FacetRegistry

from ordessa_model_provider_profile.facet import EffectiveChoiceResolver, SessionOverrides
from ordessa_model_provider_profile.profile_glue import (
    BRANDS, FACET_ID, ModelProviderFacetProvider,
    register_model_provider_facet,
)
from ordessa_model_provider_profile.reference_port import (
    ProfileFacetView, ProfileViewReferencePort,
)

CHOICE = {"harnessId": "pi", "providerConfigId": "p-1", "modelId": "m1"}


def _registry_with_provider():
    registry = FacetRegistry()
    provider = register_model_provider_facet(registry)
    return registry, provider


def test_provider_registers_into_the_real_registry_as_v2():
    registry, provider = _registry_with_provider()
    assert registry.get(FACET_ID) is provider
    assert registry.owner_of(FACET_ID) == "ordessa.model-provider-profile"
    descriptor = provider.descriptor()
    assert descriptor.facet_id == FACET_ID
    assert [item.item_id for item in descriptor.item_descriptors] == ["choice"]
    assert registry.check_current(registry.generation) is None


def test_second_owner_claiming_the_facet_is_refused():
    registry, _provider = _registry_with_provider()
    with pytest.raises(ProfileError) as excinfo:
        registry.register(ModelProviderFacetProvider(),
                          owner_plugin_id="second.owner", v2=True)
    assert excinfo.value.code == "FACET_ID_CONFLICT"


def test_unload_then_reregister_is_the_honest_lifecycle():
    registry, provider = _registry_with_provider()
    registry.unregister(provider)
    assert registry.get(FACET_ID) is None
    reloaded = register_model_provider_facet(registry)
    assert registry.get(FACET_ID) is reloaded


def test_applicability_follows_the_brand_pins():
    provider = ModelProviderFacetProvider()
    for brand in BRANDS:
        assert provider.applicability({"harnessId": brand}) is Applicability.SUPPORTED
    assert provider.applicability({}) is Applicability.UNKNOWN
    assert provider.applicability({"harnessId": "not-a-brand"}) is Applicability.UNSUPPORTED


def test_validate_enforces_the_atomic_harness_bound_choice():
    provider = ModelProviderFacetProvider()
    assert provider.validate({"choice": CHOICE}, {"harnessId": "pi"}) == ()
    # a harness mismatch is a located violation, never a silent accept
    violations = provider.validate({"choice": CHOICE}, {"harnessId": "codex"})
    assert len(violations) == 1 and violations[0].item_id == "choice"
    # a split choice (missing keys) refuses — provider+model never separate
    assert provider.validate({"choice": {"harnessId": "pi", "modelId": "m1"}},
                             {"harnessId": "pi"})


def test_compile_emits_the_choice_intent_for_the_target_harness():
    provider = ModelProviderFacetProvider()
    result = provider.compile({"choice": CHOICE},
                              {"harnessId": "pi", "source": "profile@rev-7"})
    assert result.ok and len(result.intents) == 1
    intent = result.intents[0]
    assert intent.facet_id == FACET_ID and intent.op == "set"
    assert intent.value == CHOICE
    assert intent.source == "profile@rev-7"
    # a mismatched target harness never compiles
    assert not provider.compile({"choice": CHOICE},
                                {"harnessId": "claude-code"}).ok


def test_effective_choice_resolution_wired_to_profile_revision_inputs():
    """The resolver's merge semantics over a REAL resolved-profile revision
    mapping (the shape the profile side's resolution produces)."""
    resolver = EffectiveChoiceResolver(SessionOverrides())
    profile_revision = {"assets.model-provider/choice": CHOICE,
                        "profileRevision": "rev-7"}
    session = {"serverInstanceId": "s1", "harnessId": "pi", "acpSessionId": "a1"}
    assert resolver.effective(session, profile_revision)["assets.model-provider/choice"] == CHOICE
    # an override wins for THIS session only
    resolver.overrides.set(session, "assets.model-provider/choice",
                           {**CHOICE, "modelId": "m2"})
    effective = resolver.effective(session, profile_revision)
    assert effective["assets.model-provider/choice"]["modelId"] == "m2"
    other = {"serverInstanceId": "s1", "harnessId": "pi", "acpSessionId": "a2"}
    assert resolver.effective(other, profile_revision)["assets.model-provider/choice"] == CHOICE
    # an explicit profile switch clears the session's overrides together
    assert resolver.switch_profile(session) is True
    assert resolver.effective(session, profile_revision)["assets.model-provider/choice"] == CHOICE


def test_reference_port_wired_to_active_profile_views():
    """The archive-time check over the profile side's active-profile view:
    a profile whose stored values carry {providerId, modelId} references the
    config; absence is a provable no-reference."""
    profiles = [
        ProfileFacetView("prof-1", {"assets.model-provider/choice": {
            "harnessId": "pi", "providerId": "p-1", "modelId": "m1"}}),
        ProfileFacetView("prof-2", {"other.facet/item": {"modelId": "m9"}}),
    ]

    class View:
        def list_active(self):
            return profiles

    port = ProfileViewReferencePort(View())
    assert port.references_of("p-1") == ["prof-1"]
    assert port.references_of("p-absent") == []
