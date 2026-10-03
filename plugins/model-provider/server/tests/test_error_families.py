"""PB-4 (REQ-Z3-7): the domain's 13 failure codes self-publish their wire
families through the open ``wire.error-families`` point.

Red first (the codes rode ``details.internalCode`` with a temporary
UNAVAILABLE family), green through the plugin's own registration batch — no
host-table edit. Negatives: a conflicting row from another owner refuses the
whole activation at stage time (and the first owner's rows survive), a
contradiction with the static wire table refuses, and an unknown code still
falls through to UNAVAILABLE (publication must not mask anything).
"""
from __future__ import annotations

import pytest
from server_plugin_api import (
    Contribution, ContributionBatch, ServerPluginDescriptor,
    ServerPluginRegistration, WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
)

from ordessa_model_provider.choices import (
    ADAPTER_MISSING, CONFIG_REVISION_CONFLICT, CREDENTIAL_UNRESOLVED,
    MODEL_NOT_FOUND, OPERATION_UNKNOWN, PROVIDER_ARCHIVED, PROVIDER_NOT_FOUND,
    PROTOCOL_UNSUPPORTED, RESUME_UNAVAILABLE, SELECTION_UNSUPPORTED,
    TARGET_STALE, VERIFICATION_MISMATCH, VERSION_UNVERIFIED,
)
from ordessa_model_provider.plugin import _ERROR_FAMILIES, ModelProviderPlugin
from ordessa_server.wire.errors import ErrorFamilyContributionRefused
from ordessa_server.plugin_host.host import ServerPluginHost

from ordessa_model_provider.testing import FakeCredentials, FakeHarnesses

#: api-requests.md REQ-Z3-7 list, verbatim (code → family).
EXPECTED_FAMILIES = {
    PROVIDER_NOT_FOUND: "NOT_FOUND",
    MODEL_NOT_FOUND: "NOT_FOUND",
    PROVIDER_ARCHIVED: "CONFLICT_REQUEST",
    CONFIG_REVISION_CONFLICT: "CONFLICT_VERSION",
    SELECTION_UNSUPPORTED: "CAPABILITY_UNSUPPORTED",
    OPERATION_UNKNOWN: "OUTCOME_UNKNOWN",
    ADAPTER_MISSING: "CAPABILITY_UNSUPPORTED",
    VERSION_UNVERIFIED: "CAPABILITY_UNSUPPORTED",
    TARGET_STALE: "CONFLICT_REQUEST",
    RESUME_UNAVAILABLE: "CAPABILITY_UNSUPPORTED",
    VERIFICATION_MISMATCH: "OUTCOME_UNKNOWN",
    CREDENTIAL_UNRESOLVED: "UNAUTHENTICATED",
    PROTOCOL_UNSUPPORTED: "CAPABILITY_UNSUPPORTED",
}


def _stack_host():
    """A host with the four ports the plugin build needs (records only)."""
    import tempfile
    from pathlib import Path

    from pacthold.storage import ObjectStore
    from pacthold_runtime_compat.storage import Database

    root = Path(tempfile.mkdtemp())
    database = Database(root / "db.sqlite")
    # The host declares `wire.error-families` itself at construction
    # (host.py) — the plugin's batch stages against that declaration.
    return ServerPluginHost(host_ports={
        "database": database, "objects": ObjectStore(root / "objects"),
        "idempotency": database, "credentials": FakeCredentials(),
    })


def test_plugin_publishes_exactly_the_frozen_thirteen_codes():
    assert _ERROR_FAMILIES == EXPECTED_FAMILIES
    assert len(_ERROR_FAMILIES) == 13


def test_activated_plugin_resolves_every_code_through_the_host_point():
    host = _stack_host()
    host.activate(ModelProviderPlugin(harnesses=FakeHarnesses()))
    family_for = host.wire_error_families.family_for
    for code, family in EXPECTED_FAMILIES.items():
        assert family_for(code) == family, code
        assert family != "UNAVAILABLE"  # no UNAVAILABLE masquerade


def test_retirement_rolls_the_rows_out_of_this_composition():
    host = _stack_host()
    host.activate(ModelProviderPlugin(harnesses=FakeHarnesses()))
    host.deactivate("ordessa.model-provider")
    assert host.wire_error_families.family_for(PROVIDER_NOT_FOUND) == "UNAVAILABLE"


def test_second_owner_contradicting_a_code_refuses_and_first_survives():
    host = _stack_host()
    host.activate(ModelProviderPlugin(harnesses=FakeHarnesses()))

    class Intruder:
        def descriptor(self):
            return ServerPluginDescriptor("intruder.plugin", "Intruder", "1")

        def build(self, context):
            return ServerPluginRegistration(contributions=ContributionBatch((
                Contribution(WIRE_ERROR_FAMILIES_POINT_ID, WIRE_ERROR_FAMILIES_API_VERSION,
                             {PROVIDER_NOT_FOUND: "INVALID_REQUEST"}),
            )))

    with pytest.raises(ErrorFamilyContributionRefused):
        host.activate(Intruder())
    # the round rolled back: the domain's rows still answer, unharmed
    assert host.wire_error_families.family_for(PROVIDER_NOT_FOUND) == "NOT_FOUND"
    assert host.wire_error_families.contributed_families()[PROVIDER_NOT_FOUND] == (
        "ordessa.model-provider",)


def test_static_table_contradiction_refuses():
    host = _stack_host()
    # IDEMPOTENCY_CONFLICT is a static wire row (CONFLICT_REQUEST); claiming a
    # different family for it refuses at stage.
    class StaticIntruder:
        def descriptor(self):
            return ServerPluginDescriptor("static.intruder", "Static", "1")

        def build(self, context):
            return ServerPluginRegistration(contributions=ContributionBatch((
                Contribution(WIRE_ERROR_FAMILIES_POINT_ID, WIRE_ERROR_FAMILIES_API_VERSION,
                             {"IDEMPOTENCY_CONFLICT": "NOT_FOUND"}),
            )))

    with pytest.raises(ErrorFamilyContributionRefused):
        host.activate(StaticIntruder())


def test_unknown_codes_still_fall_through_to_unavailable():
    host = _stack_host()
    host.activate(ModelProviderPlugin(harnesses=FakeHarnesses()))
    assert host.wire_error_families.family_for("NOBODY_RAISES_THIS") == "UNAVAILABLE"
