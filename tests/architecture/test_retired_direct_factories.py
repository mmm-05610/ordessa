"""Retired Profile factories cannot create another writer or runtime path."""
import importlib.util

import pytest

from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog


@pytest.mark.parametrize("family", ["codex", "pi", "claude-code", "opencode", "hermes", "dsh", "kilo"])
def test_retired_generic_provider_cannot_bypass_selected_agent_owner(family):
    assert capture_selected_harness_catalog().registry.get(family).harness_type == family
    assert importlib.util.find_spec(
        "ordessa_server_product.harness_adapters.generic.execution_provider") is None


@pytest.mark.parametrize("module", [
    "entrypoints", "plugin", "generic.factory", "generic.profile_store",
    "generic.profile_provider", "generic.profile_manager", "generic.profile_selector",
    "generic.profile_envelope", "generic.execution_provider",
])
def test_old_profile_factory_and_writer_modules_are_absent(module):
    assert importlib.util.find_spec("ordessa_server_product.harness_adapters." + module) is None



@pytest.mark.parametrize("family,expected_route", [
    ("opencode", None),
    ("hermes", {"source": "agentbox", "profile_id": "hermes"}),
    ("dsh", {"source": "agentbox", "profile_id": "dsh"}),
    ("kilo", {"source": "agentbox", "profile_id": "kilo"}),
])
def test_four_selected_brands_keep_public_registration_and_deployment_claims(family, expected_route):
    """A selected declaration and a production template still have callable producers.

    These are capability and launch-route declarations, not an Agent Unit
    publication or a native dispatch grant. OpenCode's canonical route is
    explicitly absent; its `omp` alias is retained by the same catalog.
    """
    import importlib
    import json

    from ordessa_server_product.composition import create_composition

    captured = capture_selected_harness_catalog()
    product = create_composition()
    product.bind_harness_registry(captured.registry)
    definition = product.harness_registry.get(family)
    assert definition.harness_type == family
    descriptor = product.harness_registry.launch_descriptors[family]
    assert descriptor["id"] == family
    assert descriptor["registry_version"] == definition.identity.version
    assert descriptor["launch"] == expected_route
    brand = importlib.import_module("ordessa_harness_" + family + ".registration_declarations")
    fragment = brand.registration_declarations()
    assert json.loads(fragment.launch_json) == descriptor
    assert fragment.registry_toml in captured.registry_bytes
    claims = product.capabilities_for(family)
    assert {name for name, enabled in claims.items() if enabled} == set(definition.capabilities)
    production = importlib.import_module("ordessa_harness_" + family + ".production")
    args = ({"binary_token": "controlled", "binary_digest": "sha256:" + "1" * 64}
            if family == "opencode" else
            {"artifact_token": "controlled", "tree_digest": "sha256:" + "1" * 64})
    declaration = production.harness_deployment(
        capabilities_for=product.capabilities_for, **args)
    assert declaration["id"] == family
    assert declaration["capabilityClaims"] == claims
    assert declaration["adapter"]["command"]
    if family == "kilo":
        assert declaration["projectionFiles"] == []
        assert json.loads(declaration["adapter"]["environment"]["KILO_CONFIG_CONTENT"]) == production.config_document()
        assert declaration["adapter"]["args"] == ["acp"]
    else:
        assert declaration["projectionFiles"]
    assert declaration["stateProjection"]["target"]
    if family == "opencode":
        assert descriptor["aliases"] == [{"id": "omp", "launch": {
            "source": "upstream", "profile_id": "omp"}}]
