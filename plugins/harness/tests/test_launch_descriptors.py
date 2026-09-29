import json

import pytest

from ordessa_harness.registry.loader import (
    _builtin_registry_resource, load_builtin_registry, load_launch_descriptors,
    load_registry,
)


def _texts():
    resource = _builtin_registry_resource()
    return resource.read_text(encoding="utf-8"), resource.with_name("launch-descriptors.json").read_text(encoding="utf-8")


def test_canonical_manifest_matches_toml_and_aliases_are_not_brands():
    registry = load_builtin_registry()
    assert len(registry) == 7
    assert set(registry.launch_descriptors) == {definition.harness_type for definition in registry.all()}
    assert "claude" not in registry.launch_descriptors
    assert "omp" not in registry.launch_descriptors
    assert registry.registry_identity_version_matches("codex", "2.0") is True
    assert registry.registry_identity_version_matches("codex", None) is None
    assert registry.registry_identity_version_matches("codex", "999.0") is False
    assert registry.registry_identity_version_matches("claude", "0.81.2") is None


def test_manifest_drift_and_alias_as_second_brand_are_rejected():
    toml_text, descriptor_text = _texts()
    raw = json.loads(descriptor_text)
    raw["harnesses"][0]["registry_version"] = "999.0"
    with pytest.raises(ValueError, match="version drift"):
        load_registry(toml_text, json.dumps(raw))
    raw = json.loads(descriptor_text)
    raw["harnesses"].pop()
    with pytest.raises(ValueError, match="canonical IDs drift"):
        load_registry(toml_text, json.dumps(raw))
    raw = json.loads(descriptor_text)
    raw["harnesses"].append({**raw["harnesses"][0], "id": "claude", "aliases": []})
    with pytest.raises(ValueError, match="duplicate canonical or alias"):
        load_launch_descriptors(json.dumps(raw))


def test_descriptor_rejects_cross_brand_route_and_boolean_schema_version():
    _, descriptor_text = _texts()
    raw = json.loads(descriptor_text)
    raw["harnesses"][0]["launch"]["profile_id"] = "pi"
    with pytest.raises(ValueError, match="launch profile identity mismatch"):
        load_launch_descriptors(json.dumps(raw))
    raw = json.loads(descriptor_text)
    raw["harnesses"][1]["aliases"][0]["launch"]["profile_id"] = "codex"
    with pytest.raises(ValueError, match="launch profile identity mismatch"):
        load_launch_descriptors(json.dumps(raw))
    raw = json.loads(descriptor_text)
    raw["schema_version"] = True
    with pytest.raises(ValueError, match="launch descriptor schema"):
        load_launch_descriptors(json.dumps(raw))
