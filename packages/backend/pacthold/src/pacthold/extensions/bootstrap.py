"""Canonical bootstrap for the extension environment (Registry + Catalog).

specs/010 T009: the kernel bootstrap assembles a neutral environment — an
empty-contract :class:`ExtensionRegistry` and the kernel catalog.  Shared
runtime contracts, seed contract types and business contribution kinds are
injected by the assembling product (see
``pacthold_runtime_compat.bootstrap``) through the ``registry`` /
``catalog_builder`` parameters; there is deliberately no second loading
path.
"""
from __future__ import annotations

from dataclasses import dataclass

from .catalog import (
    ExtensionCatalog,
    ExtensionCatalogBuilder,
    activate_catalog_bindings,
    activate_registry_bindings,
)
from .loader import PluginLoadReport, load_installed_plugins
from ..work_core.registry import ExtensionRegistry


@dataclass(frozen=True)
class ExtensionEnvironment:
    """One process-local extension environment.

    ``registry`` owns contracts and providers; ``catalog`` owns Host-facing
    contributions with ownership provenance; ``report`` is diagnostics and
    provenance only (READY/FAILED/INCOMPATIBLE, descriptors, distribution
    metadata, errors).
    """

    registry: ExtensionRegistry
    catalog: ExtensionCatalog
    report: PluginLoadReport


def build_extension_environment(
    *,
    strict: bool = False,
    entry_points=None,
    registry: ExtensionRegistry | None = None,
    catalog_builder: ExtensionCatalogBuilder | None = None,
) -> ExtensionEnvironment:
    """The single canonical loader path.

    Loads every installed plugin transactionally into a fresh (or supplied,
    pre-seeded) Registry and Catalog, then activates the environment by
    binding :class:`RegistryBindable` contributions exactly once each.
    """
    reg = registry if registry is not None else ExtensionRegistry()
    builder = catalog_builder if catalog_builder is not None else ExtensionCatalogBuilder()
    report = load_installed_plugins(reg, strict=strict, entry_points=entry_points, catalog=builder)
    catalog = builder.build()
    activate_registry_bindings(catalog, reg)
    activate_catalog_bindings(catalog)
    return ExtensionEnvironment(registry=reg, catalog=catalog, report=report)


def build_extension_environment_from_parts(
    registry: ExtensionRegistry,
    report: PluginLoadReport,
    *,
    catalog_builder: ExtensionCatalogBuilder | None = None,
) -> ExtensionEnvironment:
    """Canonical environment for manually assembled Registry/Report pairs.

    Used by tests and embedders that assemble plugins themselves.  The catalog
    is built by exactly the same fail-closed builder the loader uses, and
    bindings are activated here — never inside a Host.
    """
    from .catalog import build_catalog_from_report

    catalog = build_catalog_from_report(report, registry=registry, builder=catalog_builder)
    activate_registry_bindings(catalog, registry)
    activate_catalog_bindings(catalog)
    return ExtensionEnvironment(registry=registry, catalog=catalog, report=report)


def build_extension_registry(
    *,
    strict: bool = False,
    entry_points=None,
    registry: ExtensionRegistry | None = None,
    catalog_builder: ExtensionCatalogBuilder | None = None,
) -> tuple[ExtensionRegistry, PluginLoadReport]:
    """Compatibility wrapper: returns ``(registry, report)``.

    Delegates to the canonical environment builder; it implements no second
    loading path.  New code should use :func:`build_extension_environment`.
    """
    environment = build_extension_environment(
        strict=strict,
        entry_points=entry_points,
        registry=registry,
        catalog_builder=catalog_builder,
    )
    return environment.registry, environment.report


__all__ = [
    "ExtensionEnvironment",
    "build_extension_environment",
    "build_extension_environment_from_parts",
    "build_extension_registry",
]
