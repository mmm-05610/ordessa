from dataclasses import dataclass
from typing import ClassVar

import pytest

from pacthold.extensions import (
    PluginContext,
    PluginDescriptor,
    PluginRegistration,
    check_plugin_conformance,
    load_installed_plugins,
)
from pacthold.work_core import (
    ExtensionRegistry,
    ExecutionStartReceipt,
    ProviderDescriptor,
    Ref,
    RefType,
)
from pacthold.work_core.repository import CoreRepository
from pacthold.work_core.services import ExecutionService, WorkService


@dataclass(frozen=True)
class ExampleResourceV1:
    contract_id: ClassVar[str] = "example.resource@1"
    value: str


class ExampleResourceProvider:
    supported_contract_ids = frozenset({ExampleResourceV1.contract_id})

    def descriptor(self):
        return ProviderDescriptor("example-resource", "Example resource", "2.0")

    def resolve(self, contract_id, ref):
        assert contract_id == ExampleResourceV1.contract_id
        return ExampleResourceV1(ref.native_id)


class ExampleExecutionProvider:
    def __init__(self):
        self.requests = []

    def descriptor(self):
        return ProviderDescriptor("example-execution", "Example execution", "3.1")

    def capabilities(self):
        return {"start": "supported", "observe": "supported"}

    def input_limits(self):
        return {ExampleResourceV1.contract_id: (1, 1)}

    def start(self, request):
        self.requests.append(request)
        return ExecutionStartReceipt(
            request.execution_id, request.dispatch_id, request.inputs_digest
        )

    def observe(self, native_ref):
        return native_ref


class ExamplePlugin:
    def __init__(self, *, api_version=1):
        self.api_version = api_version

    def descriptor(self):
        return PluginDescriptor(
            "example", "Example plugin", "1.2.3", self.api_version
        )

    def build(self, context):
        assert context.plugin_data_dir.name == "example"
        return PluginRegistration(
            contracts=(ExampleResourceV1,),
            resource_providers=(ExampleResourceProvider(),),
            execution_providers=(ExampleExecutionProvider(),),
        )


class FakeEntryPoint:
    name = "example"
    value = "example_plugin:create_plugin"

    def __init__(self, factory, dist=None):
        self.factory = factory
        self.dist = dist

    def load(self):
        return self.factory


def test_old_descriptor_constructor_and_new_fields_are_compatible(tmp_path):
    old = PluginDescriptor("old", "Old", "1")
    assert old.description == "" and old.docs_url is None and old.config_namespace is None
    current = PluginDescriptor("new", "New", "1", description="docs", docs_url="https://example.test", config_namespace="new")
    assert current.config_namespace == "new"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"docs_url": "ftp://example.test"},
        {"config_namespace": "bad namespace"},
        {"description": "x" * 513},
    ],
)
def test_descriptor_rejects_invalid_metadata(kwargs):
    with pytest.raises(ValueError):
        PluginDescriptor("bad", "Bad", "1", **kwargs)


def test_loader_records_distribution_metadata_and_version_warning(tmp_agent_box_home):
    class Distribution:
        name = "example-distribution"
        version = "9.9.9"

    registry = ExtensionRegistry()
    report = load_installed_plugins(
        registry,
        entry_points=(FakeEntryPoint(lambda: ExamplePlugin(), Distribution()),),
    )
    record = report.records[0]
    assert record.status == "READY"
    assert (record.distribution_name, record.distribution_version) == (
        "example-distribution",
        "9.9.9",
    )


def test_loader_without_entry_point_distribution_keeps_metadata_optional(tmp_agent_box_home):
    registry = ExtensionRegistry()
    record = load_installed_plugins(
        registry,
        entry_points=(FakeEntryPoint(lambda: ExamplePlugin()),),
    ).records[0]
    assert record.distribution_name is None
    assert record.distribution_version is None


def test_structural_conformance_does_not_call_provider_runtime_methods(tmp_path):
    class BombExecution(ExampleExecutionProvider):
        def start(self, request):
            raise AssertionError("start must not be called")
        def observe(self, native_ref):
            raise AssertionError("observe must not be called")

    class BombResource(ExampleResourceProvider):
        def resolve(self, contract_id, ref):
            raise AssertionError("resolve must not be called")

    class Plugin:
        def descriptor(self):
            return PluginDescriptor("bomb", "Bomb", "1")
        def build(self, context):
            return PluginRegistration((ExampleResourceV1,), (BombResource(),), (BombExecution(),))

    report = check_plugin_conformance(
        Plugin(), PluginContext("1", tmp_path, tmp_path / "plugins" / "bomb")
    )
    assert report.ok, report.format_text()


def test_plugin_registers_contract_and_providers_without_core_source_branch(
    tmp_agent_box_home,
):
    registry = ExtensionRegistry()
    report = load_installed_plugins(
        registry,
        strict=True,
        entry_points=(FakeEntryPoint(lambda: ExamplePlugin()),),
    )

    assert [record.status for record in report.records] == ["READY"]
    assert registry.get_contract_type("example.resource@1") is ExampleResourceV1
    assert registry.get_resource_provider("example-resource").descriptor().version == "2.0"
    assert registry.get("example-execution").descriptor().version == "3.1"


def test_loader_rejects_duplicate_host_extension_ids():
    class Selector:
        id = "same-selector"

    class Plugin:
        def __init__(self, plugin_id):
            self.plugin_id = plugin_id
        def descriptor(self):
            return PluginDescriptor(self.plugin_id, self.plugin_id, "1")
        def build(self, context):
            return PluginRegistration(resource_selectors=(Selector(),))

    class EP(FakeEntryPoint):
        def __init__(self, plugin):
            self.name = plugin.plugin_id
            self.value = self.name
            self.factory = lambda: plugin
            self.dist = None

    report = load_installed_plugins(
        ExtensionRegistry(), entry_points=(EP(Plugin("one")), EP(Plugin("two")))
    )
    assert [record.status for record in report.records] == ["READY", "FAILED"]
    assert "duplicate selector id" in (report.records[1].error or "")


def test_dynamic_contract_participates_in_real_dispatch_and_type_check(
    tmp_agent_box_home,
):
    registry = ExtensionRegistry()
    execution_provider = ExampleExecutionProvider()
    registry.register_contract(ExampleResourceV1)
    registry.register_resource_provider(ExampleResourceProvider())
    registry.register_execution_provider(execution_provider)
    repository = CoreRepository()
    work = WorkService(repository).create_work("exercise third-party contract")
    service = ExecutionService(repository)
    execution = service.create_execution(
        work.id,
        "example-execution",
        responsibility_intent="resolve extension input",
    )

    receipt = service.dispatch_execution(
        execution.id,
        ((ExampleResourceV1.contract_id, Ref(RefType.ARTIFACT, "example-resource", "x")),),
        registry,
        "extension-dispatch",
    )

    assert execution_provider.requests[0].inputs[ExampleResourceV1.contract_id] == (
        ExampleResourceV1("x"),
    )
    assert receipt.state == "accepted"
    event = next(
        event
        for event in repository.list_events(execution.id)
        if event.type.value == "ExecutionDispatchRequested"
    )
    assert event.data["provider"] == "example-execution"
    assert event.data["provider_version"] == "3.1"


def test_plugin_bundle_registration_is_atomic(tmp_agent_box_home):
    class InvalidProvider(ExampleResourceProvider):
        supported_contract_ids = frozenset({"missing.contract@1"})

    class BrokenPlugin(ExamplePlugin):
        def build(self, context):
            return PluginRegistration(
                contracts=(ExampleResourceV1,),
                resource_providers=(InvalidProvider(),),
            )

    registry = ExtensionRegistry()
    report = load_installed_plugins(
        registry,
        entry_points=(FakeEntryPoint(lambda: BrokenPlugin()),),
    )

    assert report.records[0].status == "FAILED"
    assert "example.resource@1" not in registry.contract_types()


def test_incompatible_plugin_is_visible_but_not_registered(tmp_agent_box_home):
    registry = ExtensionRegistry()
    report = load_installed_plugins(
        registry,
        entry_points=(FakeEntryPoint(lambda: ExamplePlugin(api_version=999)),),
    )
    assert report.records[0].status == "INCOMPATIBLE"
    assert "example.resource@1" not in registry.contract_types()


def test_contract_registry_rejects_unversioned_or_mutable_values():
    @dataclass
    class MutableContract:
        contract_id: ClassVar[str] = "example.mutable@1"
        value: str

    @dataclass(frozen=True)
    class UnversionedContract:
        contract_id: ClassVar[str] = "example.unversioned"
        value: str

    registry = ExtensionRegistry()
    with pytest.raises(ValueError, match="frozen dataclass"):
        registry.register_contract(MutableContract)
    with pytest.raises(ValueError, match="versioned contract_id"):
        registry.register_contract(UnversionedContract)


def test_cross_plugin_contracts_are_available_without_mutating_live_registry(tmp_path):
    class ConsumerExecution(ExampleExecutionProvider):
        def descriptor(self):
            return ProviderDescriptor("consumer-execution", "Consumer", "1")

        def input_limits(self):
            return {ExampleResourceV1.contract_id: (0, 1)}

    class ConsumerPlugin:
        def descriptor(self):
            return PluginDescriptor("consumer", "Consumer", "1")

        def build(self, context):
            return PluginRegistration(execution_providers=(ConsumerExecution(),))

    context = PluginContext("1", tmp_path, tmp_path / "plugins")
    registry = ExtensionRegistry()
    registry.register_contract(ExampleResourceV1)
    before = dict(registry.contract_types())
    report = check_plugin_conformance(
        ConsumerPlugin(), context, available_contract_types=registry.contract_types()
    )
    assert report.ok, report.format_text()
    assert dict(registry.contract_types()) == before

    missing_report = check_plugin_conformance(ConsumerPlugin(), context)
    assert not missing_report.ok
    assert any(d.code == "execution.unknown_contract" for d in missing_report.errors)
