"""The assets.memory facet (MB-1): one atomic item, AR-5 mirrored keys,
typed refusals, documented default."""
from __future__ import annotations

import pytest

from ordessa_memory import common, facet


def test_facet_descriptor_is_one_atomic_item_with_the_mirror_keys():
    descriptor = facet.facet_descriptor()
    assert descriptor["facetId"] == "assets.memory"
    assert len(descriptor["items"]) == 1
    item = descriptor["items"][0]
    assert item["id"] == "memory"
    assert item["valueType"] == "atomic"
    assert item["valueKeys"] == ["enabled", "budgetTokens", "extractionModelRef", "boundBrands"]


def test_default_binding_mounts_the_four_non_native_brands_and_keeps_extraction_off():
    default = common.default_binding()
    assert default["enabled"] is True
    assert sorted(default["boundBrands"]) == ["dsh", "kilo", "pi", "qwen"]


def test_editor_manifest_carries_the_attribution_line():
    manifest = facet.editor_registration_manifest()
    assert manifest["attribution"] == common.ATTRIBUTION
    assert manifest["facetId"] == "assets.memory"


def test_validate_binding_normalizes_and_deduplicates_brands():
    value = facet.validate_binding({
        "enabled": True, "budgetTokens": 1000, "extractionModelRef": "ref://m",
        "boundBrands": ["pi", "pi", "dsh"]})
    assert value["boundBrands"] == ["pi", "dsh"]


@pytest.mark.parametrize("value", [
    "not-an-object",
    {"enabled": True, "budgetTokens": None, "extractionModelRef": None},  # missing key
    {"enabled": True, "budgetTokens": None, "extractionModelRef": None,
     "boundBrands": ["pi"], "surprise": 1},  # unknown key
    {"enabled": "yes", "budgetTokens": None, "extractionModelRef": None,
     "boundBrands": ["pi"]},  # wrong type
    {"enabled": True, "budgetTokens": -5, "extractionModelRef": None,
     "boundBrands": ["pi"]},
    {"enabled": True, "budgetTokens": None, "extractionModelRef": "  ",
     "boundBrands": ["pi"]},
    {"enabled": True, "budgetTokens": None, "extractionModelRef": None,
     "boundBrands": []},
    {"enabled": True, "budgetTokens": None, "extractionModelRef": None,
     "boundBrands": ["not-a-brand"]},
])
def test_invalid_bindings_are_typed_refusals(value):
    with pytest.raises(facet.FacetValueError) as excinfo:
        facet.validate_binding(value)
    assert excinfo.value.code in {"invalid-binding", "unknown-key", "incomplete-binding"}
