"""specs/010 T009 product assembly: injection works on the single kernel path.

The kernel mechanism files (loader/catalog/conformance/diagnostics/bootstrap/
api) must be business-blind, and the assembly must inject exactly its own
defaults through the public parameters — no second loading path (C5/R5).
These tests pin the positive wiring (a business plugin is catalogued through
the kernel loader) and the negatives that used to live inside the kernel's
inline kind table (transport SPI mismatch, duplicate ids, unknown credential
contracts).
"""
from __future__ import annotations

import pytest

from pacthold.extensions.api import PluginDescriptor
from pacthold.work_core.db import _reset_connection_for_tests, registered_migration_sources
from pacthold_runtime_compat import bootstrap as product_bootstrap
from pacthold_runtime_compat.api import PluginRegistration as ProductPluginRegistration
from pacthold_runtime_compat.catalog import (
    CREDENTIAL_MATERIALIZER,
    HARNESS_MANAGER,
    PRODUCT_CONTRIBUTION_KINDS,
    TRANSPORT_OPERATION,
    ProductExtensionCatalog,
)
from pacthold_runtime_compat.resource_contracts import CONTRACT_TYPES, CredentialRefV1
from pacthold_runtime_compat.runtime_composition.protocol import (
    TransportOperationContribution,
    TransportOperationDescriptor,
)

CREDENTIAL_CONTRACT_ID = CredentialRefV1.contract_id


class FakeEntryPoint:
    def __init__(self, name, factory):
        self.name = name
        self.value = f"{name}.stub"
        self._factory = factory
        self.dist = None

    def load(self):
        return self._factory


class HarnessManagerStub:
    def __init__(self, harness_id):
        self.harness_id = harness_id


class MaterializerStub:
    provider_id = "fake-materializer"
    supported_contract_ids = frozenset({CREDENTIAL_CONTRACT_ID})


class RouteDescriptorStub:
    def __init__(self, route_id):
        self.id = route_id


class RouteStub:
    def __init__(self, route_id):
        self._route_id = route_id

    def descriptor(self):
        return RouteDescriptorStub(self._route_id)


class TransportHandler:
    def __init__(self, descriptor):
        self._descriptor = descriptor

    def descriptor(self):
        return self._descriptor

    def validate(self, operation):
        return None

    def execute(self, transport, operation):
        return None


def _transport_contribution(operation_type="fake.op@1", mismatch=False):
    descriptor = TransportOperationDescriptor(operation_type=operation_type)
    handler_descriptor = (
        TransportOperationDescriptor(operation_type="other.op@1") if mismatch else descriptor
    )
    return TransportOperationContribution(descriptor, TransportHandler(handler_descriptor))


def _plugin(registration_factory, plugin_id="fake-product-plugin"):
    def factory():
        class Plugin:
            def descriptor(self):
                return PluginDescriptor(plugin_id, "Fake product plugin", "0.1")

            def build(self, context):
                return registration_factory()

        return Plugin()
    return factory


def _environment(entry_points, **kwargs):
    kwargs.setdefault("register_migrations", False)
    return product_bootstrap.build_product_environment(entry_points=tuple(entry_points), **kwargs)


def test_product_registry_seeds_contracts_and_shared_runtime_once():
    registry = product_bootstrap.build_product_registry()
    seeded = registry.contract_types()
    for contract_id in CONTRACT_TYPES:
        assert contract_id in seeded
    shared = registry.root_shared_contract_ids()
    assert {
        product_bootstrap.RUNTIME_HOST_CONTRACT_ID,
        product_bootstrap.SANDBOX_CONTRACT_ID,
        product_bootstrap.TERMINAL_SESSION_CONTRACT_ID,
    } == shared
    # a second build gives a fresh registry — no process-global seeding:
    other = product_bootstrap.build_product_registry()
    assert other.contract_types() is not registry.contract_types()


def test_kernel_defaults_are_not_business_seeded():
    """Bare kernel side of the same rule: an unseeded registry knows nothing
    about product contracts (the kernel never imports the assembly)."""
    from pacthold.work_core.registry import ExtensionRegistry

    assert ExtensionRegistry().contract_types() == {}


def test_build_product_environment_registers_legacy_chain_by_default():
    try:
        env = product_bootstrap.build_product_environment(entry_points=())
        namespaces = [source.namespace for source in registered_migration_sources()]
        assert "agent_box_legacy" in namespaces
        assert isinstance(env.catalog, ProductExtensionCatalog)
    finally:
        _reset_registered_sources_and_conn()


def _reset_registered_sources_and_conn():
    from pacthold.work_core.db import _reset_registered_migration_sources_for_tests

    _reset_connection_for_tests()
    _reset_registered_migration_sources_for_tests()


def test_business_kinds_are_catalogued_through_the_single_kernel_path():
    registration = lambda: ProductPluginRegistration(  # noqa: E731
        harness_managers=(HarnessManagerStub("fake-harness"),),
        continuation_routes=(RouteStub("fake-route"),),
        credential_materializers=(MaterializerStub(),),
        transport_operations=(_transport_contribution(),),
    )
    env = _environment([FakeEntryPoint("fake", _plugin(registration))])
    record = env.report.records[0]
    assert record.status == "READY", record.error
    catalog = env.catalog
    assert isinstance(catalog, ProductExtensionCatalog)
    assert catalog.get_harness_manager("fake-harness") is not None
    assert catalog.get_continuation_route("fake-route") is not None
    assert catalog.get_credential_materializer("fake-materializer") is not None
    assert catalog.get_transport_operation("fake.op@1") is not None
    kinds = {contribution.kind for contribution in catalog.contributions()}
    assert kinds == {HARNESS_MANAGER, CREDENTIAL_MATERIALIZER, TRANSPORT_OPERATION} | {
        "continuation_route"
    }
    assert set(PRODUCT_CONTRIBUTION_KINDS) >= kinds


@pytest.mark.parametrize(
    "registration_factory, expected_error",
    [
        (
            lambda: ProductPluginRegistration(
                transport_operations=(_transport_contribution(mismatch=True),)
            ),
            "descriptor mismatch",
        ),
        (
            lambda: ProductPluginRegistration(
                credential_materializers=(
                    type("Bad", (MaterializerStub,), {
                        "provider_id": "unknown-contract-materializer",
                        "supported_contract_ids": frozenset({"agent-box.unknown@1"}),
                    })(),
                )
            ),
            "unregistered credential contracts",
        ),
    ],
)
def test_business_kind_negatives_stay_fail_closed_on_the_product_path(
    registration_factory, expected_error
):
    env = _environment([FakeEntryPoint("bad", _plugin(registration_factory))])
    record = env.report.records[0]
    assert record.status == "FAILED"
    assert expected_error in record.error, record.error


def test_duplicate_business_component_ids_across_plugins_are_rejected():
    first = lambda: ProductPluginRegistration(  # noqa: E731
        harness_managers=(HarnessManagerStub("dup-harness"),)
    )
    second = lambda: ProductPluginRegistration(  # noqa: E731
        harness_managers=(HarnessManagerStub("dup-harness"),)
    )
    env = _environment(
        [
            FakeEntryPoint("a_plugin", _plugin(first, "plugin-a")),
            FakeEntryPoint("b_plugin", _plugin(second, "plugin-b")),
        ]
    )
    statuses = {record.entry_point: record.status for record in env.report.records}
    assert statuses["a_plugin"] == "READY"
    assert statuses["b_plugin"] == "FAILED"
    failed = next(record for record in env.report.records if record.status == "FAILED")
    assert "duplicate harness id: dup-harness" in failed.error
