"""C2 contribution declaration tests: shape rules, ownership, required/optional."""
from __future__ import annotations

import dataclasses

import pytest

from server_plugin_api import (
    CONTRIBUTION_POINT_ID,
    PACTHOLD_CONTRIBUTIONS_API_VERSION,
    PACTHOLD_CONTRIBUTIONS_POINT_ID,
    AbsentContribution,
    Contribution,
    ContributionBatch,
    ContributionDeclarationError,
    DuplicateContributionError,
    RequiredContributionMissingError,
    ServerPluginRegistration,
)


def test_fixed_core_point_is_declared_here():
    assert PACTHOLD_CONTRIBUTIONS_POINT_ID == "pacthold.contributions"
    assert PACTHOLD_CONTRIBUTIONS_API_VERSION == "v1"
    assert CONTRIBUTION_POINT_ID.fullmatch(PACTHOLD_CONTRIBUTIONS_POINT_ID)


def test_declares_the_core_point_with_an_opaque_payload():
    marker = object()
    contribution = Contribution(
        point_id=PACTHOLD_CONTRIBUTIONS_POINT_ID,
        api_version=PACTHOLD_CONTRIBUTIONS_API_VERSION,
        payload=marker,
        required=True,
    )
    assert contribution.payload is marker


@pytest.mark.parametrize("payload", [None, 0, "", False, {"any": object()}])
def test_payload_stays_opaque_and_unchecked(payload):
    contribution = Contribution(point_id="pacthold.contributions", api_version="v1",
                                payload=payload)
    assert contribution.payload is payload


@pytest.mark.parametrize("point_id", ["", "Contributions", "pacthold.Contributions",
                                      "pacthold..contributions", "pacthold.contributions.",
                                      "1pacthold.contributions", "pacthold contrib", None, 7])
def test_malformed_point_id_refuses_declaration(point_id):
    with pytest.raises(ContributionDeclarationError):
        Contribution(point_id=point_id, api_version="v1")


@pytest.mark.parametrize("api_version", ["", "1", "V1", "v0", "vv1", "v1.0", "latest", None, 1])
def test_bad_api_version_refuses_declaration(api_version):
    with pytest.raises(ContributionDeclarationError):
        Contribution(point_id="pacthold.contributions", api_version=api_version)


@pytest.mark.parametrize("required", ["yes", 1, 0, None])
def test_required_flag_must_be_boolean(required):
    with pytest.raises(ContributionDeclarationError):
        Contribution(point_id="pacthold.contributions", api_version="v1",
                     required=required)


def test_contribution_carries_no_author_declared_owner():
    assert "owner" not in {f.name for f in dataclasses.fields(Contribution)}
    with pytest.raises(TypeError):
        Contribution(point_id="pacthold.contributions", api_version="v1",
                     payload=object(), owner="self-declared")


def test_batch_requires_tuple_of_contributions():
    with pytest.raises(ContributionDeclarationError):
        ContributionBatch(contributions=[Contribution(point_id="a.b", api_version="v1")])
    with pytest.raises(ContributionDeclarationError):
        ContributionBatch(contributions=("not a contribution",))
    with pytest.raises(ContributionDeclarationError):
        ContributionBatch(open_points=["a.b"])


def test_duplicate_point_in_one_batch_refuses_exclusive_point():
    first = Contribution(point_id="pacthold.contributions", api_version="v1", payload=object())
    second = Contribution(point_id="pacthold.contributions", api_version="v1", payload=object())
    with pytest.raises(DuplicateContributionError) as excinfo:
        ContributionBatch(contributions=(first, second))
    assert excinfo.value.point_id == "pacthold.contributions"


def test_duplicate_point_passes_only_when_declared_open():
    first = Contribution(point_id="metrics.sinks", api_version="v1", payload="a")
    second = Contribution(point_id="metrics.sinks", api_version="v1", payload="b")
    batch = ContributionBatch(contributions=(first, second),
                              open_points=frozenset({"metrics.sinks"}))
    assert len(batch.contributions) == 2


def test_required_contribution_without_payload_refuses_the_batch():
    batch = ContributionBatch(contributions=(
        Contribution(point_id="pacthold.contributions", api_version="v1",
                     payload=None, required=True),))
    with pytest.raises(RequiredContributionMissingError) as excinfo:
        batch.check_required()
    assert excinfo.value.missing == ("pacthold.contributions",)


def test_host_named_required_point_absent_from_batch_refuses():
    batch = ContributionBatch(contributions=(
        Contribution(point_id="services.workspace", api_version="v1", payload=object()),))
    with pytest.raises(RequiredContributionMissingError) as excinfo:
        batch.check_required(("pacthold.contributions",))
    assert "pacthold.contributions" in excinfo.value.missing
    batch.check_required(("services.workspace",))


def test_optional_missing_is_observable_absence_not_an_error():
    batch = ContributionBatch(contributions=())
    resolved = batch.resolve("pacthold.contributions")
    assert isinstance(resolved, AbsentContribution)
    assert resolved.point_id == "pacthold.contributions"
    assert resolved.reason
    batch.check_required()


def test_null_payload_resolves_to_observable_absence():
    batch = ContributionBatch(contributions=(
        Contribution(point_id="services.workspace", api_version="v1", payload=None),))
    resolved = batch.resolve("services.workspace")
    assert isinstance(resolved, AbsentContribution)


def test_registration_gains_contributions_backwards_compatible():
    legacy_positional = ServerPluginRegistration(
        (), (), (), {}, (), None)
    assert legacy_positional.contributions == ContributionBatch()
    assert legacy_positional.contributions.contributions == ()

    batch = ContributionBatch(contributions=(
        Contribution(point_id="pacthold.contributions", api_version="v1",
                     payload=object(), required=True),))
    registration = ServerPluginRegistration(contributions=batch)
    assert registration.contributions is batch


@pytest.mark.parametrize("bad", [[], None, "batch", (Contribution(point_id="a.b", api_version="v1"),)])
def test_registration_rejects_non_batch_contributions(bad):
    with pytest.raises(ValueError):
        ServerPluginRegistration(contributions=bad)
