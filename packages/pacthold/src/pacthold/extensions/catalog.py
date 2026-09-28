"""Canonical, immutable, query-oriented Extension Catalog.

The catalog is the single process-local authority for Host-facing extension
contributions.  specs/010 T009: the kernel catalog knows only the neutral
contribution kinds (resource selectors, finalization contributors, host
controls).  Business kinds — harness managers, continuation routes,
credential materializers, transport operations — are contributed by the
compatibility assembly through ``ContributionKindSpec`` injection
(``pacthold_runtime_compat.catalog``); this module never imports them.

The catalog is not a Work Core entity, never enters a database, and never
holds transport handlers.  Every contribution carries its plugin
ownership/provenance; duplicates are fail closed at build time.

Hosts (Web today, ACP/CLI/third-party Hosts tomorrow) consume this catalog
instead of re-implementing aggregation over :class:`PluginLoadReport`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, runtime_checkable

from .api import RegistryBindable, SelectorCompatibility

# Canonical neutral contribution kinds; each is an independent namespace, so
# the same id may legitimately exist in two kinds (e.g. a selector and a
# contributor both named "git-workspace").  Business kinds live in the
# compatibility assembly, which registers them via ContributionKindSpec.
RESOURCE_SELECTOR = "resource_selector"
FINALIZATION_CONTRIBUTOR = "finalization_contributor"
HOST_CONTROL = "host_control"

CORE_CONTRIBUTION_KINDS = (
    RESOURCE_SELECTOR,
    FINALIZATION_CONTRIBUTOR,
    HOST_CONTROL,
)

#: Back-compatible name for the kernel-neutral kind tuple.
CONTRIBUTION_KINDS = CORE_CONTRIBUTION_KINDS


@dataclass(frozen=True)
class ValidationContext:
    """Facts a kind-spec validator may need; never mutates builder state."""

    plugin_id: str
    known_contracts: frozenset[str]


@dataclass(frozen=True)
class ContributionKindSpec:
    """How one contribution kind is read from a plugin registration.

    ``id_of`` extracts the component id from a component (raising
    ``ValueError`` for malformed contributions); ``validate`` runs optional
    kind-specific fail-closed checks.  The kernel defines only the neutral
    specs — an assembling product supplies its own business specs, keeping
    component-id extraction and validation semantics without teaching the
    kernel any business type.
    """

    kind: str
    label: str
    slot: str
    id_attr: str
    id_of: Callable[[object], "str | None"]
    validate: Callable[[object, ValidationContext], None] | None = None


def _direct_id(attr: str) -> Callable[[object], "str | None"]:
    def extract(item: object) -> "str | None":
        return getattr(item, attr, None)
    return extract


CORE_CONTRIBUTION_SPECS: tuple[ContributionKindSpec, ...] = (
    ContributionKindSpec(RESOURCE_SELECTOR, "selector", "resource_selectors",
                         "id", _direct_id("id")),
    ContributionKindSpec(FINALIZATION_CONTRIBUTOR, "contributor",
                         "finalization_contributors", "id", _direct_id("id")),
    ContributionKindSpec(HOST_CONTROL, "control", "host_controls",
                         "provider_id", _direct_id("provider_id")),
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


class ExtensionCatalogBuilder:
    """Staged, fail-closed builder used by the plugin loader and by the
    canonical from-report helper.

    ``prepare`` validates one full registration (per-kind ids, cross-plugin
    duplicates) without mutating state, so a plugin that fails anywhere
    leaves no orphan contribution; ``commit`` is a pure data append that
    cannot fail.  Kind specs default to the kernel-neutral set; an assembling
    product passes its own set (or extends the defaults) to describe its
    business contribution kinds.
    """

    def __init__(self, *, kind_specs: tuple[ContributionKindSpec, ...] = CORE_CONTRIBUTION_SPECS) -> None:
        self._specs = tuple(kind_specs)
        self._seen: dict[tuple[str, str], str] = {}
        self._records: list[ExtensionContribution] = []

    def prepare(
        self,
        registration,
        *,
        plugin_id: str,
        distribution_name: str | None = None,
        distribution_version: str | None = None,
        known_contracts: frozenset[str] = frozenset(),
    ) -> tuple[ExtensionContribution, ...]:
        local: dict[tuple[str, str], str] = {}
        records: list[ExtensionContribution] = []
        context = ValidationContext(plugin_id=plugin_id, known_contracts=known_contracts)
        for spec in self._specs:
            for item in getattr(registration, spec.slot, ()):
                component_id = spec.id_of(item)
                if not isinstance(component_id, str) or not component_id:
                    raise ValueError(f"{spec.label} must declare a non-empty {spec.id_attr}")
                key = (spec.kind, component_id)
                if key in local or key in self._seen:
                    raise ValueError(f"duplicate {spec.label} id: {component_id}")
                if spec.validate is not None:
                    spec.validate(item, context)
                local[key] = plugin_id
                records.append(ExtensionContribution(
                    spec.kind, component_id, plugin_id, distribution_name, distribution_version, item,
                ))
        return tuple(records)

    def commit(self, records: tuple[ExtensionContribution, ...]) -> None:
        for record in records:
            self._seen[(record.kind, record.component_id)] = record.plugin_id
            self._records.append(record)

    def build(self) -> ExtensionCatalog:
        return ExtensionCatalog.from_contributions(tuple(self._records))


def build_catalog_from_report(report, *, registry=None, builder: "ExtensionCatalogBuilder | None" = None) -> ExtensionCatalog:
    """Canonical catalog assembly for manually prepared environments.

    Used by the compatibility assembly and by embedders that assemble a
    Registry/PluginLoadReport themselves.  It applies exactly the same
    fail-closed validation and ownership recording as the plugin loader; it is
    not a second aggregation implementation living inside a Host.
    """
    builder = builder if builder is not None else ExtensionCatalogBuilder()
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


def activate_registry_bindings(catalog: ExtensionCatalog, registry) -> tuple[str, ...]:
    """Activate one environment: bind bindable contributions exactly once.

    Walks BOTH extension surfaces — Catalog contributions and Registry
    providers — because a provider can legitimately need the activated
    Catalog (for example a runtime host's transport operation resolver
    contributed by the assembly).  Only components implementing the explicit
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
    contributions (for example the assembly's runtime host transport
    resolver).  Binding happens once per contribution during environment
    activation, after every plugin has committed; implementations must be
    side-effect free and idempotent for the same catalog.
    """

    def bind_catalog(self, catalog: "ExtensionCatalog") -> None: ...


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
