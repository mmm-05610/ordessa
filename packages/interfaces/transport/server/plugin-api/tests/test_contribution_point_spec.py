"""Product-declared points use only the public Server plugin contract."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from server_plugin_api import (
    ContributionDeclarationError, ContributionPointSpec,
    ServerContributionHandler, unique_contribution_point_specs,
)


class Handler(ServerContributionHandler):
    def stage(self, contribution, owner):
        return None

    def commit(self, contribution, prepared, owner):
        pass

    def rollback(self, contribution, prepared, owner):
        pass


def test_product_can_declare_open_harness_points_without_host_types():
    handler = Handler()
    specs = unique_contribution_point_specs((
        ContributionPointSpec("harness.runtime-adapters", "v1", handler, exclusive=False),
        ContributionPointSpec("harness.configuration-adapters", "v1", handler, exclusive=False),
    ))
    assert tuple(item.point_id for item in specs) == (
        "harness.runtime-adapters", "harness.configuration-adapters")
    assert specs[0].handler is handler
    assert specs[0].exclusive is False
    with pytest.raises(FrozenInstanceError):
        specs[0].point_id = "changed"


@pytest.mark.parametrize("point_id", ["", "Bad.point", "x..y", "1x.y", None])
def test_bad_point_id_refused(point_id):
    with pytest.raises(ContributionDeclarationError):
        ContributionPointSpec(point_id, "v1", Handler())


@pytest.mark.parametrize("version", ["", "v0", "V1", "1", "v1.0", None])
def test_bad_api_version_refused(version):
    with pytest.raises(ContributionDeclarationError):
        ContributionPointSpec("harness.runtime-adapters", version, Handler())


@pytest.mark.parametrize("handler", [None, object(), "handler"])
def test_unbound_or_wrong_handler_refused(handler):
    with pytest.raises(ContributionDeclarationError):
        ContributionPointSpec("harness.runtime-adapters", "v1", handler)


@pytest.mark.parametrize("exclusive", [0, 1, None, "false"])
def test_exclusive_is_strict_boolean(exclusive):
    with pytest.raises(ContributionDeclarationError):
        ContributionPointSpec("harness.runtime-adapters", "v1", Handler(), exclusive)


def test_duplicate_point_id_refused_before_host_registration():
    a = ContributionPointSpec("harness.runtime-adapters", "v1", Handler(), False)
    b = ContributionPointSpec("harness.runtime-adapters", "v2", Handler(), False)
    with pytest.raises(ContributionDeclarationError, match="duplicate"):
        unique_contribution_point_specs((a, b))
    with pytest.raises(ContributionDeclarationError):
        unique_contribution_point_specs((a, a))
    with pytest.raises(ContributionDeclarationError):
        unique_contribution_point_specs((a, "not-a-spec"))
