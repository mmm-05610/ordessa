# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_archive_protection.py, verbatim)
"""G4: the archive-time reference protection, port-shaped.

Two frozen behaviors (spec FR-ARCH-2):
* a port-reported reference refuses the archive (legacy REFERENCE_CONFLICT);
* an *absent* port refuses too (REFERENCE_STATE_UNKNOWN) - "cannot prove there
  are no references" must never read as "there are none". The counterexample
  this suite catches is any change that archives on a missing port.
"""
from __future__ import annotations

import pytest
from ordessa_server.errors import ServerError

from ordessa_model_provider.catalog import ModelCatalogService
from ordessa_model_provider.records import ProviderModelRecords

from ordessa_model_provider.testing import FakeCredentials, FakeHarnesses


class StaticReferencePort:
    def __init__(self, references):
        self._references = references

    def references_of(self, provider_config_id):
        return list(self._references)


def _catalog(stack, reference_port):
    return ModelCatalogService(
        ProviderModelRecords(stack["database"], stack["idempotency"]),
        stack["objects"], harnesses=FakeHarnesses(), credentials=FakeCredentials(),
        reference_port=reference_port,
    )


def _create(catalog):
    return catalog.create("k1", {
        "displayName": "N", "harness": None, "provider": "acme", "credentialId": None,
        "configuration": [],
        "models": [{"modelId": "m1", "displayName": "m1",
                    "availability": "available", "unavailableReason": None}],
    })


def test_referenced_config_refuses_archive_with_the_reference_list(stack):
    catalog = _catalog(stack, StaticReferencePort(["profile-1", "profile-2"]))
    created = _create(catalog)
    with pytest.raises(ServerError) as excinfo:
        catalog.archive(created["id"], created["version"], "a1")
    assert excinfo.value.code == "REFERENCE_CONFLICT"
    assert excinfo.value.status == 409
    assert excinfo.value.references == ["profile-1", "profile-2"]
    assert catalog.records.get(created["id"])["archived_at"] is None


def test_unreferenced_config_archives_through_the_port(stack):
    catalog = _catalog(stack, StaticReferencePort([]))
    created = _create(catalog)
    archived = catalog.archive(created["id"], created["version"], "a1")
    assert archived["archivedAt"] is not None


def test_absent_port_fails_closed(stack):
    catalog = _catalog(stack, None)
    created = _create(catalog)
    with pytest.raises(ServerError) as excinfo:
        catalog.archive(created["id"], created["version"], "a1")
    assert excinfo.value.code == "REFERENCE_STATE_UNKNOWN"
    assert excinfo.value.status == 409
    assert catalog.records.get(created["id"])["archived_at"] is None


def test_port_absence_guard_silence_would_be_visible(stack):
    """Counterexample proof: reading a missing port as 'no references' (the
    pre-spec regression) fails the typed-code assertion above - this canary
    pins that the refusal is the *code*, not just an exception."""
    catalog = _catalog(stack, None)
    created = _create(catalog)
    try:
        catalog.archive(created["id"], created["version"], "a1")
    except ServerError as error:
        assert error.code != "REFERENCE_CONFLICT"
    else:
        pytest.fail("archived with the reference port absent - the silent break G4 exists for")
