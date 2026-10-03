"""Discover trusted Python distributions and register their components."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Iterable

from .. import __version__
from ..work_core.runtime import agent_box_home
from ..work_core.registry import ExtensionRegistry
from .api import (
    PLUGIN_API_VERSION,
    PluginContext,
    PluginDescriptor,
    PluginRegistration,
)
from .catalog import ExtensionCatalogBuilder


ENTRY_POINT_GROUP = "agent_box.plugins"


class PluginCompatibilityError(RuntimeError):
    """Typed plugin compatibility failure used for stable load status."""


@dataclass(frozen=True)
class PluginLoadRecord:
    entry_point: str
    status: str
    descriptor: PluginDescriptor | None = None
    registration: PluginRegistration | None = None
    error: str | None = None
    distribution_name: str | None = None
    distribution_version: str | None = None


@dataclass(frozen=True)
class PluginLoadReport:
    records: tuple[PluginLoadRecord, ...]

    @property
    def ready(self) -> tuple[PluginLoadRecord, ...]:
        return tuple(record for record in self.records if record.status == "READY")

    @property
    def failed(self) -> tuple[PluginLoadRecord, ...]:
        return tuple(record for record in self.records if record.status != "READY")


def _entry_points() -> tuple[metadata.EntryPoint, ...]:
    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        selected = discovered.select(group=ENTRY_POINT_GROUP)
    else:  # Python 3.9/importlib_metadata compatibility
        selected = discovered.get(ENTRY_POINT_GROUP, ())
    return tuple(sorted(selected, key=lambda entry: (entry.name, entry.value)))


def _context(descriptor: PluginDescriptor) -> PluginContext:
    root = agent_box_home()
    return PluginContext(
        agent_box_version=__version__,
        agent_box_home=root,
        plugin_data_dir=root / "plugins" / descriptor.id,
    )


def _distribution_info(entry_point) -> tuple[str | None, str | None]:
    """Return optional entry-point distribution metadata without making it required."""
    dist = getattr(entry_point, "dist", None)
    if dist is None:
        return None, None
    try:
        return getattr(dist, "name", None), getattr(dist, "version", None)
    except Exception:
        return None, None


def load_installed_plugins(
    registry: ExtensionRegistry,
    *,
    strict: bool = False,
    entry_points: Iterable[metadata.EntryPoint] | None = None,
    catalog: ExtensionCatalogBuilder | None = None,
) -> PluginLoadReport:
    """Load installed plugins into ``registry`` and the staged ``catalog``.

    Plugin packages are trusted executable Python code. A failing plugin is
    isolated and reported by default; ``strict=True`` makes startup fail fast.
    Each plugin must register all its Contracts before its providers.

    Loading is transactional per plugin: the full registration is validated
    first (catalog contributions via ``prepare``, then contracts/providers via
    the registry's staged swap) and only a fully successful plugin commits to
    both.  A failure therefore never leaves orphan contributions in the
    Registry or the Catalog.
    """
    builder = catalog if catalog is not None else ExtensionCatalogBuilder()
    records: list[PluginLoadRecord] = []
    seen_plugin_ids: set[str] = set()
    selected = tuple(entry_points) if entry_points is not None else _entry_points()

    for entry_point in sorted(selected, key=lambda entry: (entry.name, entry.value)):
        distribution_name, distribution_version = _distribution_info(entry_point)
        descriptor: PluginDescriptor | None = None
        registration: PluginRegistration | None = None
        try:
            factory = entry_point.load()
            plugin = factory()
            descriptor = plugin.descriptor()
            if not isinstance(descriptor, PluginDescriptor):
                raise TypeError("descriptor() must return PluginDescriptor")
            if descriptor.api_version != PLUGIN_API_VERSION:
                raise PluginCompatibilityError(
                    f"plugin API {descriptor.api_version} is incompatible with "
                    f"host API {PLUGIN_API_VERSION}"
                )
            if descriptor.id in seen_plugin_ids:
                raise RuntimeError(f"duplicate plugin id: {descriptor.id}")
            registration = plugin.build(_context(descriptor))
            if not isinstance(registration, PluginRegistration):
                raise TypeError("build() must return PluginRegistration")

            known_contracts = frozenset(registry.contract_types()) | {
                getattr(contract, "contract_id", None)
                for contract in registration.contracts
                if isinstance(contract, type)
            } - {None}
            # Validate every contribution before anything is committed.
            pending = builder.prepare(
                registration,
                plugin_id=descriptor.id,
                distribution_name=distribution_name,
                distribution_version=distribution_version,
                known_contracts=known_contracts,
            )
            registry.register_components(
                contracts=registration.contracts,
                resource_providers=registration.resource_providers,
                execution_providers=registration.execution_providers,
            )
            # Pure data append; cannot fail after the registry committed.
            builder.commit(pending)
            seen_plugin_ids.add(descriptor.id)
            records.append(
                PluginLoadRecord(
                    entry_point.name,
                    "READY",
                    descriptor,
                    registration,
                    None,
                    distribution_name,
                    distribution_version,
                )
            )
        except Exception as exc:
            status = "INCOMPATIBLE" if isinstance(exc, PluginCompatibilityError) else "FAILED"
            record = PluginLoadRecord(
                entry_point.name,
                status,
                descriptor,
                registration,
                f"{type(exc).__name__}: {exc}",
                distribution_name,
                distribution_version,
            )
            records.append(record)
            if strict:
                raise RuntimeError(
                    f"failed to load Agent-Box plugin {entry_point.name}: {record.error}"
                ) from exc

    return PluginLoadReport(tuple(records))
