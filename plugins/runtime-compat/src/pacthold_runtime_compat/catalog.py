"""Product contribution kinds and catalog views for the compatibility assembly.

specs/010 T009: the kernel catalog kept its kind-spec mechanism blind to
business types; this module supplies the four Agent-Box contribution kinds
(harness managers, continuation routes, credential materializers, transport
operations) with exactly the validation the kernel catalog used to run
inline, plus the business query helpers and the transport resolver.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from pacthold.extensions.catalog import (
    CONTRIBUTION_KINDS as CORE_CONTRIBUTION_KINDS,
    CORE_CONTRIBUTION_SPECS,
    ContributionKindSpec,
    ExtensionCatalog,
    ExtensionCatalogBuilder,
    ExtensionContribution,
    ValidationContext,
    activate_catalog_bindings,
    activate_registry_bindings,
    build_catalog_from_report,
)

from .runtime_composition.protocol import TransportOperationHandler

# Business contribution kind constants (historical spellings unchanged).
HARNESS_MANAGER = "harness_manager"
CONTINUATION_ROUTE = "continuation_route"
CREDENTIAL_MATERIALIZER = "credential_materializer"
TRANSPORT_OPERATION = "transport_operation"

BUSINESS_CONTRIBUTION_KINDS = (
    HARNESS_MANAGER,
    CONTINUATION_ROUTE,
    CREDENTIAL_MATERIALIZER,
    TRANSPORT_OPERATION,
)

#: The full kind tuple as the product Hosts saw it before specs/010 T009.
PRODUCT_CONTRIBUTION_KINDS = CORE_CONTRIBUTION_KINDS + BUSINESS_CONTRIBUTION_KINDS

#: Back-compatible name inside this assembly's SDK surface.
CONTRIBUTION_KINDS = PRODUCT_CONTRIBUTION_KINDS


def _route_id(item: object) -> "str | None":
    return getattr(item.descriptor(), "id", None)


def _transport_id(item: object) -> "str | None":
    return getattr(getattr(item, "descriptor", None), "operation_type", None)


def _validate_materializer(item: object, context: ValidationContext) -> None:
    provider_id = getattr(item, "provider_id", None)
    supported = getattr(item, "supported_contract_ids", None)
    if not isinstance(supported, frozenset) or not supported or not all(isinstance(cid, str) and cid for cid in supported):
        raise ValueError(
            f"credential materializer {provider_id!r} (plugin {context.plugin_id!r}) "
            "must declare a non-empty frozenset of supported contract ids"
        )
    unknown = set(supported) - set(context.known_contracts)
    if unknown:
        raise ValueError(
            f"credential materializer {provider_id!r} (plugin {context.plugin_id!r}) "
            f"declares unregistered credential contracts: {', '.join(sorted(unknown))}"
        )


def _validate_transport(item: object, context: ValidationContext) -> None:
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


BUSINESS_CONTRIBUTION_SPECS: tuple[ContributionKindSpec, ...] = (
    ContributionKindSpec(HARNESS_MANAGER, "harness", "harness_managers",
                         "harness_id",
                         lambda item: getattr(item, "harness_id", None)),
    ContributionKindSpec(CONTINUATION_ROUTE, "route", "continuation_routes",
                         "descriptor", _route_id),
    ContributionKindSpec(CREDENTIAL_MATERIALIZER, "materializer",
                         "credential_materializers", "provider_id",
                         lambda item: getattr(item, "provider_id", None),
                         validate=_validate_materializer),
    ContributionKindSpec(TRANSPORT_OPERATION, "transport operation",
                         "transport_operations", "descriptor",
                         _transport_id,
                         validate=_validate_transport),
)

PRODUCT_CONTRIBUTION_SPECS = CORE_CONTRIBUTION_SPECS + BUSINESS_CONTRIBUTION_SPECS


class ProductExtensionCatalog(ExtensionCatalog):
    """Catalog with the business query helpers the product Hosts use."""

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


class ProductExtensionCatalogBuilder(ExtensionCatalogBuilder):
    """Kernel builder configured with the business contribution specs."""

    def __init__(self) -> None:
        super().__init__(kind_specs=PRODUCT_CONTRIBUTION_SPECS)

    def build(self) -> ProductExtensionCatalog:
        return ProductExtensionCatalog.from_contributions(tuple(self._records))  # type: ignore[arg-return]


def build_product_catalog_from_report(report, *, registry=None, builder=None) -> ProductExtensionCatalog:
    """Product catalog assembly (same code path as the kernel loader)."""
    builder = builder if builder is not None else ProductExtensionCatalogBuilder()
    return build_catalog_from_report(report, registry=registry, builder=builder)


class TransportOperationResolver:
    """Immutable operation_type → contribution lookup for one environment."""

    def __init__(self, contributions: Mapping[str, ExtensionContribution]) -> None:
        self._contributions: Mapping[str, ExtensionContribution] = MappingProxyType(dict(contributions))

    @classmethod
    def from_catalog(cls, catalog: ExtensionCatalog) -> "TransportOperationResolver":
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


__all__ = [
    "BUSINESS_CONTRIBUTION_KINDS",
    "BUSINESS_CONTRIBUTION_SPECS",
    "CONTRIBUTION_KINDS",
    "CONTINUATION_ROUTE",
    "CREDENTIAL_MATERIALIZER",
    "ExtensionCatalog",
    "ExtensionContribution",
    "HARNESS_MANAGER",
    "PRODUCT_CONTRIBUTION_KINDS",
    "PRODUCT_CONTRIBUTION_SPECS",
    "ProductExtensionCatalog",
    "ProductExtensionCatalogBuilder",
    "TRANSPORT_OPERATION",
    "TransportOperationResolver",
    "activate_catalog_bindings",
    "activate_registry_bindings",
    "build_product_catalog_from_report",
]
