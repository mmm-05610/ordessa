"""The product declares domain points through public contracts only."""
from __future__ import annotations

from ordessa_server_product.composition import ServerProductComposition, create_composition
from server_plugin_api import ContributionPointSpec, unique_contribution_point_specs


def test_exact_harness_point_declarations_share_one_registry_per_composition():
    product = create_composition()
    points = product.server_contribution_points()
    assert isinstance(product, ServerProductComposition)
    assert points == unique_contribution_point_specs(points)
    assert all(isinstance(point, ContributionPointSpec) for point in points)
    assert [(point.point_id, point.api_version, point.exclusive) for point in points] == [
        ("harness.runtime-adapters", "v1", False),
        ("harness.configuration-adapters", "v1", False),
    ]
    assert points[0].handler._registry is points[1].handler._registry
    assert product.server_contribution_points()[0].handler is points[0].handler


def test_separate_product_compositions_have_separate_registry_instances():
    first = create_composition().server_contribution_points()
    second = create_composition().server_contribution_points()
    assert first[0].handler is not second[0].handler
    assert first[0].handler._registry is not second[0].handler._registry


def test_product_exposes_legacy_database_provider_without_opening_data():
    from pacthold_runtime_compat.storage import Database

    product = create_composition()
    assert product.database_type() is Database
    assert product.database_type() is Database
