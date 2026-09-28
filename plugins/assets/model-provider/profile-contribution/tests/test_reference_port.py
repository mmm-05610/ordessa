# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_reference_port.py, verbatim)
"""G4 tie-in: the Profile-side ReferencePort keeps referenced configs
un-archivable, with the legacy deep-walk reference rule and active-only
semantics."""
from __future__ import annotations

import pytest
from ordessa_server.errors import ServerError

from ordessa_model_provider.catalog import ModelCatalogService
from ordessa_model_provider.ports import REFERENCE_STATE_UNKNOWN
from ordessa_model_provider.records import ProviderModelRecords
from ordessa_model_provider_profile import (
    ProfileFacetView, ProfileViewReferencePort,
)

from ordessa_model_provider.testing import FakeCredentials, FakeHarnesses


class StaticProfiles:
    def __init__(self, profiles):
        self._profiles = profiles

    def list_active(self):
        return list(self._profiles)


def _catalog(stack, profiles):
    return ModelCatalogService(
        ProviderModelRecords(stack["database"], stack["idempotency"]),
        stack["objects"], harnesses=FakeHarnesses(), credentials=FakeCredentials(),
        reference_port=ProfileViewReferencePort(StaticProfiles(profiles)),
    )


def _create(catalog):
    return catalog.create("k1", {
        "displayName": "N", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [],
        "models": [{"modelId": "m1", "displayName": "m1",
                    "availability": "available", "unavailableReason": None}],
    })


def test_referencing_profile_blocks_archive(stack):
    profiles = [ProfileFacetView("profile-P", {
        "model": {"providerId": "WILL-BE-FILLED", "modelId": "m1"},
    })]
    catalog = _catalog(stack, profiles)
    created = _create(catalog)
    profiles[0].values["model"]["providerId"] = created["id"]
    with pytest.raises(ServerError) as excinfo:
        catalog.archive(created["id"], created["version"], "a1")
    assert excinfo.value.code == "REFERENCE_CONFLICT"
    assert excinfo.value.references == ["profile-P"]


def test_archived_profiles_no_longer_count_as_references(stack):
    catalog = _catalog(stack, [])  # the referencing profile is archived -> not listed
    created = _create(catalog)
    archived = catalog.archive(created["id"], created["version"], "a1")
    assert archived["archivedAt"] is not None


def test_nested_references_are_found_like_the_legacy_deep_walk(stack):
    profiles = [ProfileFacetView("profile-P", {
        "nested": [{"sub": {"providerId": "FILL", "modelId": "m1"}}],
    })]
    catalog = _catalog(stack, profiles)
    created = _create(catalog)
    profiles[0].values["nested"][0]["sub"]["providerId"] = created["id"]
    with pytest.raises(ServerError) as excinfo:
        catalog.archive(created["id"], created["version"], "a1")
    assert excinfo.value.code == "REFERENCE_CONFLICT"


def test_absent_profiles_view_still_fails_closed_through_the_port(stack):
    """The core refuses when no port exists; the port itself never answers a
    fake 'no references' for a view it does not have."""
    catalog = ModelCatalogService(
        ProviderModelRecords(stack["database"], stack["idempotency"]),
        stack["objects"], harnesses=FakeHarnesses(), credentials=FakeCredentials(),
        reference_port=None,
    )
    created = _create(catalog)
    with pytest.raises(ServerError) as excinfo:
        catalog.archive(created["id"], created["version"], "a1")
    assert excinfo.value.code == REFERENCE_STATE_UNKNOWN
