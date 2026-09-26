"""Canonical, immutable, query-oriented Extension Catalog.

The catalog is the single process-local authority for Host-facing extension
contributions (selectors, finalization contributors, host controls, harness
managers, continuation routes, credential materializers).  It is not a Work
Core entity, never enters a database, never imports Web, and never holds
transport handlers (Phase 4).  Every contribution carries its plugin
ownership/provenance; duplicates are fail closed at build time.

Hosts (Web today, ACP/CLI/third-party Hosts tomorrow) consume this catalog
instead of re-implementing aggregation over :class:`PluginLoadReport`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from .api import RegistryBindable, SelectorCompatibility
from .runtime_composition.protocol import TransportOperationHandler

# Canonical contribution kinds; each is an independent namespace, so the same
# id may legitimately exist in two kinds (e.g. a selector and a contributor
# both named "git-workspace").
RESOURCE_SELECTOR = "resource_selector"
FINALIZATION_CONTRIBUTOR = "finalization_contributor"
HOST_CONTROL = "host_control"
HARNESS_MANAGER = "harness_manager"
CONTINUATION_ROUTE = "continuation_route"
CREDENTIAL_MATERIALIZER = "credential_materializer"
TRANSPORT_OPERATION = "transport_operation"

CONTRIBUTION_KINDS = (
    RESOURCE_SELECTOR,
    FINALIZATION_CONTRIBUTOR,
    HOST_CONTROL,
    HARNESS_MANAGER,
    CONTINUATION_ROUTE,
    CREDENTIAL_MATERIALIZER,
    TRANSPORT_OPERATION,
)


@dataclass(frozen=True)
class ExtensionContribution:
    """One bounded, immutable ownership record for a catalog entry."""

    kind: str
    component_id: str
    plugin_id: str
    distribution_name: str | None = None
    distribution_version: str | None = None
    component: object = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class ExtensionCatalog:
    """Immutable, query-oriented view over all READY plugin contributions.

    Frozen: attribute assignment is rejected, the internal contribution index
    is a read-only mapping, and every query returns tuples or the live
    component objects — no mutable internal state is exposed.
    """

    _contributions: Mapping[tuple[str, str], ExtensionContribution]

    @classmethod
    def from_contributions(cls, contributions) -> "ExtensionCatalog":
        return cls(MappingProxyType({(record.kind, record.component_id): record for record in contributions}))

    def contributions(self) -> tuple[ExtensionContribution, ...]:
        return tuple(self._contributions.values())

    def owner_of(self, kind: str, component_id: str) -> ExtensionContribution | None:
        """Return the ownership record for one contribution, or None."""
        return self._contributions.get((kind, component_id))

    def _values(self, kind: str) -> tuple[object, ...]:
        return tuple(record.component for record in self._contributions.values() if record.kind == kind)

    def _get(self, kind: str, component_id: str) -> object:
        record = self._contributions.get((kind, component_id))
        if record is None:
            raise KeyError(f"unknown {kind}: {component_id}")
        return record.component

    # -- selectors ---------------------------------------------------------
    def selectors(self) -> tuple[object, ...]:
        return self._values(RESOURCE_SELECTOR)

    def get_selector(self, selector_id: str) -> object:
        return self._get(RESOURCE_SELECTOR, selector_id)

    def selectors_for_provider(self, provider_id: str, *, harness_type: str | None = None) -> tuple[object, ...]:
        """Return selectors compatible with a provider, without ID guessing."""
        result = []
        for selector in self.selectors():
            compatibility = getattr(selector, "compatibility", SelectorCompatibility())
            if compatibility.execution_provider_ids and provider_id not in compatibility.execution_provider_ids:
                continue
            if harness_type and compatibility.harness_types and harness_type not in compatibility.harness_types:
                continue
            result.append(selector)
        return tuple(result)

    # -- finalization contributors ----------------------------------------
    def finalization_contributors(self) -> tuple[object, ...]:
        return self._values(FINALIZATION_CONTRIBUTOR)

    def get_finalization_contributor(self, contributor_id: str) -> object:
        return self._get(FINALIZATION_CONTRIBUTOR, contributor_id)

    # -- host controls ------------------------------------------------------
    def host_controls(self) -> tuple[object, ...]:
        return self._values(HOST_CONTROL)

    def get_host_control(self, provider_id: str) -> object:
        return self._get(HOST_CONTROL, provider_id)

    # -- harness managers ---------------------------------------------------
    def harness_managers(self) -> tuple[object, ...]:
        return self._values(HARNESS_MANAGER)

    def get_harness_manager(self, harness_id: str) -> object:
        return self._get(HARNESS_MANAGER, harness_id)

    # -- continuation routes -------------------------------------------------
    def continuation_routes(self) -> tuple[object, ...]:
        return self._values(CONTINUATION_ROUTE)

    def routes(self) -> tuple[object, ...]:
        return self.continuation_routes()

    def get_continuation_route(self, route_id: str) -> object:
        return self._get(CONTINUATION_ROUTE, route_id)

    # -- credential materializers --------------------------------------------
    def credential_materializers(self) -> tuple[object, ...]:
        return self._values(CREDENTIAL_MATERIALIZER)

    def get_credential_materializer(self, provider_id: str) -> object:
        return self._get(CREDENTIAL_MATERIALIZER, provider_id)

    # -- transport operations --------------------------------------------------
    def transport_operations(self) -> tuple[object, ...]:
        return self._values(TRANSPORT_OPERATION)

    def get_transport_operation(self, operation_type: str) -> object:
        return self._get(TRANSPORT_OPERATION, operation_type)


class ExtensionCatalogBuilder:
    """Staged, fail-closed builder used by the plugin loader and by the
    canonical from-report helper.

    ``prepare`` validates one full registration (per-kind ids, cross-plugin
    duplicates, materializer contract knowledge) without mutating state, so a
    plugin that fails anywhere leaves no orphan contribution; ``commit`` is a
    pure data append that cannot fail.
    """

    def __init__(self) -> None:
        self._seen: dict[tuple[str, str], str] = {}
        self._records: list[ExtensionContribution] = []

    def prepare(
        self,
        registration: Any,
        *,
        plugin_id: str,
        distribution_name: str | None = None,
        distribution_version: str | None = None,
        known_contracts: frozenset[str] = frozenset(),
    ) -> tuple[ExtensionContribution, ...]:
        local: dict[tuple[str, str], str] = {}
        records: list[ExtensionContribution] = []
        specs = (
            (RESOURCE_SELECTOR, "selector", registration.resource_selectors, "id"),
            (FINALIZATION_CONTRIBUTOR, "contributor", registration.finalization_contributors, "id"),
            (HOST_CONTROL, "control", registration.host_controls, "provider_id"),
            (HARNESS_MANAGER, "harness", registration.harness_managers, "harness_id"),
            (CONTINUATION_ROUTE, "route", registration.continuation_routes, "descriptor"),
            (CREDENTIAL_MATERIALIZER, "materializer", registration.credential_materializers, "provider_id"),
            (TRANSPORT_OPERATION, "transport operation", registration.transport_operations, "descriptor"),
        )
        for kind, label, items, attr in specs:
            for item in items:
                if kind == CONTINUATION_ROUTE:
                    descriptor = item.descriptor()
                    component_id = getattr(descriptor, "id", None)
                elif kind == TRANSPORT_OPERATION:
                    # A transport contribution is the typed
                    # TransportOperationContribution(descriptor, handler) pair.
                    descriptor = item.descriptor
                    handler = item.handler
                    if not isinstance(handler, TransportOperationHandler):
                        raise ValueError(
                            "transport operation handler must implement the typed SPI: "
                            f"{getattr(descriptor, 'operation_type', None)}"
                        )
                    if handler.descriptor() != descriptor:
                        raise ValueError(
                            f"transport operation handler descriptor mismatch: {descriptor.operation_type}"
                        )
                    component_id = descriptor.operation_type
                else:
                    component_id = getattr(item, attr, None)
                if not isinstance(component_id, str) or not component_id:
                    raise ValueError(f"{label} must declare a non-empty {attr}")
                key = (kind, component_id)
                if key in local or key in self._seen:
                    raise ValueError(f"duplicate {label} id: {component_id}")
                if kind == CREDENTIAL_MATERIALIZER:
                    self._validate_materializer(item, component_id, plugin_id, known_contracts)
                local[key] = plugin_id
                records.append(ExtensionContribution(
                    kind, component_id, plugin_id, distribution_name, distribution_version, item,
                ))
        return tuple(records)

    @staticmethod
    def _validate_materializer(item: object, provider_id: str, plugin_id: str, known_contracts: frozenset[str]) -> None:
        supported = getattr(item, "supported_contract_ids", None)
        if not isinstance(supported, frozenset) or not supported or not all(isinstance(cid, str) and cid for cid in supported):
            raise ValueError(
                f"credential materializer {provider_id!r} (plugin {plugin_id!r}) "
                "must declare a non-empty frozenset of supported contract ids"
            )
        unknown = set(supported) - set(known_contracts)
        if unknown:
            raise ValueError(
                f"credential materializer {provider_id!r} (plugin {plugin_id!r}) "
                f"declares unregistered credential contracts: {', '.join(sorted(unknown))}"
            )

    def commit(self, records: tuple[ExtensionContribution, ...]) -> None:
        for record in records:
            self._seen[(record.kind, record.component_id)] = record.plugin_id
            self._records.append(record)

    def build(self) -> ExtensionCatalog:
        return ExtensionCatalog.from_contributions(tuple(self._records))


def build_catalog_from_report(report: Any, *, registry: Any = None) -> ExtensionCatalog:
    """Canonical catalog assembly for manually prepared environments.

    Used by the Web compatibility shim and by embedders that assemble a
    Registry/PluginLoadReport themselves.  It applies exactly the same
    fail-closed validation and ownership recording as the plugin loader; it is
    not a second aggregation implementation living inside a Host.
    """
    builder = ExtensionCatalogBuilder()
    base = frozenset(registry.contract_types()) if registry is not None else frozenset()
    for record in report.ready:
        registration = record.registration
        if registration is None:
            continue
        known = base | {
            getattr(contract, "contract_id", None)
            for contract in registration.contracts
            if isinstance(contract, type)
        } - {None}
        pending = builder.prepare(
            registration,
            plugin_id=record.descriptor.id if record.descriptor is not None else record.entry_point,
            distribution_name=record.distribution_name,
            distribution_version=record.distribution_version,
            known_contracts=frozenset(known),
        )
        builder.commit(pending)
    return builder.build()


def activate_registry_bindings(catalog: ExtensionCatalog, registry: Any) -> tuple[str, ...]:
    """Activate one environment: bind bindable contributions exactly once.

    Walks BOTH extension surfaces — Catalog contributions and Registry
    providers — because a provider can legitimately need the activated
    Catalog (for example the local RuntimeHost's transport operation
    resolver).  Only components implementing the explicit
    :class:`RegistryBindable` / :class:`CatalogBindable` protocols are bound,
    exactly once each, in deterministic order.  A binding failure propagates:
    the environment must never pretend a plugin is READY when its
    contributions could not bind.
    """
    bound: list[str] = []
    seen: set[tuple[str, str]] = set()

    def _activate(kind: str, component_id: str, component: object) -> None:
        key = (kind, component_id)
        if key in seen:
            return
        seen.add(key)
        if isinstance(component, RegistryBindable):
            component.bind_registry(registry)
            bound.append(f"{kind}:{component_id}")
        if isinstance(component, CatalogBindable):
            component.bind_catalog(catalog)
            bound.append(f"{kind}:{component_id}")

    for contribution in catalog.contributions():
        _activate(contribution.kind, contribution.component_id, contribution.component)
    for provider in registry.resource_providers():
        _activate("resource_provider", provider.descriptor().id, provider)
    for provider in registry.execution_providers():
        _activate("execution_provider", provider.descriptor().id, provider)
    return tuple(bound)


@runtime_checkable
class CatalogBindable(Protocol):
    """Explicit opt-in for contributions that need the activated Catalog.

    The canonical pattern is a provider that must look up sibling
    contributions (today: the local RuntimeHost's transport operation
    resolver).  Binding happens once per contribution during environment
    activation, after every plugin has committed; implementations must be
    side-effect free and idempotent for the same catalog.
    """

    def bind_catalog(self, catalog: "ExtensionCatalog") -> None: ...


class TransportOperationResolver:
    """Immutable operation_type → contribution lookup for one environment."""

    def __init__(self, contributions: Mapping[str, ExtensionContribution]) -> None:
        self._contributions: Mapping[str, ExtensionContribution] = MappingProxyType(dict(contributions))

    @classmethod
    def from_catalog(cls, catalog: "ExtensionCatalog") -> "TransportOperationResolver":
        return cls({
            record.component_id: record
            for record in catalog.contributions()
            if record.kind == TRANSPORT_OPERATION
        })

    def resolve(self, operation_type: str) -> ExtensionContribution:
        contribution = self._contributions.get(operation_type)
        if contribution is None:
            raise KeyError(f"unknown transport operation: {operation_type}")
        return contribution

    def operation_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._contributions))


def activate_catalog_bindings(catalog: ExtensionCatalog) -> tuple[str, ...]:
    """Bind CatalogBindable contributions exactly once, in catalog order.

    A binding failure propagates: the environment must never pretend a plugin
    is READY when its contributions could not bind.
    """
    bound: list[str] = []
    seen: set[tuple[str, str]] = set()
    for contribution in catalog.contributions():
        key = (contribution.kind, contribution.component_id)
        if key in seen:
            continue
        seen.add(key)
        component = contribution.component
        if isinstance(component, CatalogBindable):
            component.bind_catalog(catalog)
            bound.append(f"{contribution.kind}:{contribution.component_id}")
    return tuple(bound)
