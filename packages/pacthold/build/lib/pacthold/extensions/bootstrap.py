"""Canonical bootstrap for the extension environment (Registry + Catalog)."""
from __future__ import annotations

from dataclasses import dataclass

from .catalog import (
    ExtensionCatalog,
    ExtensionCatalogBuilder,
    activate_catalog_bindings,
    activate_registry_bindings,
)
from .loader import PluginLoadReport, load_installed_plugins
from .runtime_composition.protocol import (
    RuntimeHostV1,
    SandboxV1,
    TerminalSessionV1,
)
from ..work_core.registry import ExtensionRegistry

# Root-owned canonical shared runtime contracts.  They describe the execution
# runtime itself, so their Python types and their single registration point
# belong to the Root Runtime SDK -- never to a concrete provider plugin.
# Provider plugins resolve and provide these contracts but never re-declare
# a different type under the same id.
SHARED_RUNTIME_CONTRACTS: tuple[type, ...] = (
    RuntimeHostV1,
    SandboxV1,
    TerminalSessionV1,
)


def register_shared_runtime_contracts(registry: ExtensionRegistry) -> None:
    """Register the Root-owned shared runtime contracts exactly once."""
    for contract in SHARED_RUNTIME_CONTRACTS:
        registry.register_root_shared_contract(contract)


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
) -> ExtensionEnvironment:
    """The single canonical loader path.

    Loads every installed plugin transactionally into a fresh Registry and
    Catalog, then activates the environment by binding
    :class:`RegistryBindable` contributions exactly once each.
    """
    registry = ExtensionRegistry()
    register_shared_runtime_contracts(registry)
    builder = ExtensionCatalogBuilder()
    report = load_installed_plugins(registry, strict=strict, entry_points=entry_points, catalog=builder)
    catalog = builder.build()
    activate_registry_bindings(catalog, registry)
    activate_catalog_bindings(catalog)
    return ExtensionEnvironment(registry=registry, catalog=catalog, report=report)


def build_extension_environment_from_parts(
    registry: ExtensionRegistry,
    report: PluginLoadReport,
) -> ExtensionEnvironment:
    """Canonical environment for manually assembled Registry/Report pairs.

    Used by tests and embedders that assemble plugins themselves.  The catalog
    is built by exactly the same fail-closed builder the loader uses, and
    bindings are activated here — never inside a Host.
    """
    from .catalog import build_catalog_from_report

    catalog = build_catalog_from_report(report, registry=registry)
    activate_registry_bindings(catalog, registry)
    activate_catalog_bindings(catalog)
    return ExtensionEnvironment(registry=registry, catalog=catalog, report=report)


def build_extension_registry(
    *, strict: bool = False, entry_points=None
) -> tuple[ExtensionRegistry, PluginLoadReport]:
    """Compatibility wrapper: returns ``(registry, report)``.

    Delegates to the canonical environment builder; it implements no second
    loading path.  New code should use :func:`build_extension_environment`.
    """
    environment = build_extension_environment(strict=strict, entry_points=entry_points)
    return environment.registry, environment.report


__all__ = [
    "SHARED_RUNTIME_CONTRACTS",
    "ExtensionEnvironment",
    "build_extension_environment",
    "build_extension_environment_from_parts",
    "build_extension_registry",
    "register_shared_runtime_contracts",
]
