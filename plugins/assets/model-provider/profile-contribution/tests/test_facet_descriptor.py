"""Z3 T04 increments: the facet descriptor gates (red before the module
existed; the migrated suite above stays untouched)."""
from __future__ import annotations

import pytest

from ordessa_model_provider_profile import facet_registration as fr


def test_facet_has_exactly_one_atomic_choice_item():
    descriptor = fr.facet_descriptor()
    assert descriptor.facet_id == "assets.model-provider"
    assert len(descriptor.items) == 1
    item = descriptor.items[0]
    assert item.item_id == "choice"
    assert item.value_type == "atomic"  # provider/model never split (MP-01)


def test_manifest_shape_for_the_profile_registration_point():
    manifest = fr.facet_registration_manifest()
    assert manifest["facetId"] == "assets.model-provider"
    assert manifest["apiMajor"] == 1
    assert manifest["schemaVersion"] == 1
    assert [item["id"] for item in manifest["items"]] == ["choice"]


def test_well_formed_atomic_value_validates():
    fr.validate_choice_value(
        {"harnessId": "pi", "providerConfigId": "p-1", "modelId": "m1"},
        harness_id="pi",
    )


def test_split_or_extra_keys_refuse():
    with pytest.raises(fr.FacetValueError) as excinfo:
        fr.validate_choice_value(
            {"harnessId": "pi", "providerConfigId": "p-1", "modelId": "m1",
             "reasoningEffort": "high"},
            harness_id="pi")
    assert excinfo.value.code == "PROFILE_FACET_VALUE_INVALID"
    with pytest.raises(fr.FacetValueError):
        # provider without a model is the split the atomic item forbids
        fr.validate_choice_value({"harnessId": "pi", "providerConfigId": "p-1"},
                                 harness_id="pi")


def test_harness_mismatch_refuses():
    with pytest.raises(fr.FacetValueError) as excinfo:
        fr.validate_choice_value(
            {"harnessId": "codex", "providerConfigId": "p-1", "modelId": "m1"},
            harness_id="pi")
    assert excinfo.value.code == "PROFILE_HARNESS_MISMATCH"


def test_secret_shaped_value_is_not_a_facet_value():
    with pytest.raises(fr.FacetValueError):
        fr.validate_choice_value(
            {"harnessId": "pi", "providerConfigId": "p-1", "apiKey": "sk-x"},
            harness_id="pi")
