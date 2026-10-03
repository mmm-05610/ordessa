"""The public surface stays whole: every exported name resolves, and the
contribution protocol joins it without renaming anything that predates it."""
from __future__ import annotations

import importlib

import server_plugin_api

PRE_EXISTING_EXPORTS = [
    "SERVER_PLUGIN_API_VERSION",
    "PLUGIN_METHOD_ID",
    "HttpRouteDescriptor",
    "ServerMethodDescriptor",
    "ServerPlugin",
    "ServerPluginContext",
    "ServerPluginDescriptor",
    "ServerPluginRegistration",
    "StreamRouteDescriptor",
    "ServerPluginError",
    "DuplicateMethodError",
    "DuplicatePluginError",
    "DuplicateStreamRouteError",
    "DuplicateHttpRouteError",
    "HttpRouteShapeChangedError",
    "HttpRouteUnmountedError",
    "DependencyError",
    "CyclicDependencyError",
    "DependentActiveError",
    "PortConflictError",
    "InvalidDeclarationError",
    "PluginCleanupError",
    "CleanupError",
]

CONTRIBUTION_EXPORTS = [
    "CONTRIBUTION_POINT_ID",
    "PACTHOLD_CONTRIBUTIONS_API_VERSION",
    "PACTHOLD_CONTRIBUTIONS_POINT_ID",
    "WIRE_DISCOVERY_FACETS_POINT_ID",
    "WIRE_DISCOVERY_FACETS_API_VERSION",
    "AbsentContribution",
    "Contribution",
    "ContributionBatch",
    "ContributionPointSpec",
    "ServerContributionHandler",
    "StagedBatch",
    "stage_contributions",
    "unique_contribution_point_specs",
    "ContributionDeclarationError",
    "DuplicateContributionError",
    "RequiredContributionMissingError",
    "ContributionStateError",
    "ContributionRollbackRefusedError",
    "ContributionCleanupError",
    "ContributionBatchCleanupError",
]


def test_every_exported_name_resolves():
    for name in server_plugin_api.__all__:
        assert hasattr(server_plugin_api, name), f"__all__ advertises missing {name}"


def test_pre_existing_exports_survive_the_contribution_addition():
    for name in PRE_EXISTING_EXPORTS:
        assert name in server_plugin_api.__all__, f"{name} dropped from __all__"
        assert getattr(server_plugin_api, name) is not None


def test_contribution_exports_are_public():
    for name in CONTRIBUTION_EXPORTS:
        assert name in server_plugin_api.__all__, f"{name} missing from __all__"
        assert getattr(server_plugin_api, name) is not None


def test_all_lists_everything_and_submodules_stay_importable():
    assert len(server_plugin_api.__all__) == len(set(server_plugin_api.__all__))
    for module_name in ("contract", "errors", "contributions", "internal_errors",
                        "record_encoding", "wire_errors", "wire_shape"):
        module = importlib.import_module(f"server_plugin_api.{module_name}")
        for name in (set(PRE_EXISTING_EXPORTS) | set(CONTRIBUTION_EXPORTS)):
            exported = getattr(server_plugin_api, name)
            if name in vars(module) or hasattr(module, name):
                assert getattr(module, name) is exported


#: T014-S2c: the vocabulary the host and the plugins share, published here so
#: no plugin imports a host internal for it (AGENTS rule 3).
PUBLISHED_WIRE_EXPORTS = [
    "ServerError",
    "unavailable",
    "MAX_CANONICAL_BYTES",
    "canonical",
    "digest",
    "reject_sensitive_keys",
    "FAMILIES",
    "STATIC_ERROR_FAMILIES",
    "FamilyResolver",
    "WireError",
    "converge_family",
    "family_for",
    "bounded",
    "request_id",
    "require",
    "version",
]


def test_the_published_wire_surface_is_exported():
    for name in PUBLISHED_WIRE_EXPORTS:
        assert name in server_plugin_api.__all__, f"{name} missing from __all__"
        assert getattr(server_plugin_api, name) is not None


def test_the_published_surface_adds_nothing_to_the_closed_family_set():
    """`FAMILIES` is the twelve of wire/1; publishing it must not grow it."""
    assert len(server_plugin_api.FAMILIES) == 12
    assert server_plugin_api.WireError("NOT_FOUND", "x").family == "NOT_FOUND"
