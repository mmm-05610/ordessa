"""Default product point and database injection through the public seam."""
from __future__ import annotations

import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server.bootstrap.runtime import StorageProviderMissingError
from ordessa_server.plugin_host import ResolvedContribution
from ordessa_harness_api import RuntimeAdapterDescriptor, VersionRange
from server_plugin_api import (
    Contribution, ContributionBatch, ContributionDeclarationError,
    ContributionOwnerBusyError, ContributionPointSpec,
    ServerPluginDescriptor, ServerPluginRegistration,
)
from contribution_fakes import RecordingHandler

RUNTIME = "harness.runtime-adapters"
CONFIG = "harness.configuration-adapters"


class RuntimeContributor:
    def descriptor(self):
        return ServerPluginDescriptor("test.runtime-contributor", "Runtime contributor", "1")

    def build(self, context):
        descriptor = RuntimeAdapterDescriptor(
            "test.adapter", "v1", "test-brand", (), VersionRange((1, 0, 0)))
        class ControlledRuntimeAdapter:
            """Carrier-only fixture; unexpected runtime execution stays red."""
            def __init__(self):
                self.descriptor = descriptor

            def not_exercised(self, *_args, **_kwargs):
                raise AssertionError("this test proves carrier lifecycle only")

            describe_installation = describe_targets = describe_actions = not_exercised
            prepare_launch = start = connect = close = reconcile = not_exercised
            prepare_reconfiguration = resume = not_exercised

        return ServerPluginRegistration(contributions=ContributionBatch((
            Contribution(RUNTIME, "v1", ControlledRuntimeAdapter(), required=True),
        )))


class EmptyPlugin:
    def descriptor(self):
        return ServerPluginDescriptor("test.empty", "Empty", "1")

    def build(self, context):
        return ServerPluginRegistration()


def test_default_product_registers_both_harness_points_and_reuses_handlers_on_restart(tmp_path):
    runtime = build_runtime(tmp_path / "data")
    host = runtime.plugin_host
    first = (host.contribution_points.point(RUNTIME), host.contribution_points.point(CONFIG))
    assert [(p.point_id, p.api_version, p.exclusive) for p in first] == [
        (RUNTIME, "v1", False), (CONFIG, "v1", False)]
    assert first[0].handler._registry is first[1].handler._registry
    runtime.start()
    runtime.stop()
    runtime.start()
    try:
        second = (host.contribution_points.point(RUNTIME), host.contribution_points.point(CONFIG))
        assert [p.handler for p in second] == [p.handler for p in first]
    finally:
        runtime.stop()


def test_external_plugin_uses_carrier_and_busy_unload_authority(tmp_path):
    runtime = build_runtime(tmp_path / "data")
    host = runtime.plugin_host
    runtime.start()
    try:
        host.activate(RuntimeContributor())
        views = host.contributions(RUNTIME)
        assert len(views) == 1 and isinstance(views[0], ResolvedContribution)
        assert views[0].owner == "test.runtime-contributor"
        assert views[0].payload.descriptor.harness_id == "test-brand"
        with host.use_contribution(RUNTIME) as held:
            assert held.owner == "test.runtime-contributor"
            with pytest.raises(ContributionOwnerBusyError):
                host.deactivate("test.runtime-contributor")
        host.deactivate("test.runtime-contributor")
        assert host.contributions(RUNTIME) == ()
    finally:
        runtime.stop()


def test_explicit_bare_host_without_database_provider_refuses_before_writes(tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as bootstrap_runtime

    def missing_product():
        raise RuntimeError("SERVER_PRODUCT_MISSING: no product installed")

    monkeypatch.setattr(bootstrap_runtime, "_resolve_product_composition", missing_product)
    root = tmp_path / "bare"
    with pytest.raises(StorageProviderMissingError):
        build_runtime(root, server_plugins=())
    assert not root.exists()


def test_explicit_bare_host_uses_installed_product_database_only(tmp_path):
    runtime = build_runtime(tmp_path / "bare-with-product", server_plugins=())
    try:
        assert runtime.plugin_host.active_ids() == ()
        assert runtime.plugin_host.contribution_points.point(RUNTIME) is None
        runtime.start()
        response = runtime.wire.hello({
            "clientVersions": ["wire/1"], "clientPresentationSupports": [],
        })
        assert response["serverId"].startswith("server_")
        assert [entry["id"] for entry in response["capabilities"]] == ["server.hello"]
    finally:
        runtime.stop()


def test_explicit_plugins_with_database_factory_do_not_resolve_product(tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as bootstrap_runtime

    def unavailable_product():
        raise AssertionError("explicit host selection must not resolve a product")

    class Database:
        def __init__(self, root):
            self.path = root / "state" / "agentbox.sqlite"

        def initialize(self):
            pass

    monkeypatch.setattr(bootstrap_runtime, "_resolve_product_composition", unavailable_product)
    runtime = build_runtime(
        tmp_path / "host-only", server_plugins=[EmptyPlugin()], database_factory=Database)
    try:
        assert runtime.plugin_host.contribution_points.point(RUNTIME) is None
        assert runtime.legacy_core is None
        runtime.start()
        assert runtime.started
    finally:
        runtime.stop()


def test_raising_database_factory_releases_data_root_ownership(tmp_path):
    import ordessa_server.bootstrap.runtime as bootstrap_runtime

    owners = []
    real_owner = bootstrap_runtime.DataRootOwner

    class TrackedOwner(real_owner):
        def __init__(self, root):
            super().__init__(root)
            owners.append(self)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(bootstrap_runtime, "DataRootOwner", TrackedOwner)

    root = tmp_path / "factory-failure"
    def raising_factory(_root):
        raise RuntimeError("database factory failed")

    try:
        with pytest.raises(RuntimeError, match="database factory failed"):
            build_runtime(root, server_plugins=(), database_factory=raising_factory)
        assert len(owners) == 1
        assert not owners[0].acquired
        retry_owner = real_owner(root)
        retry_owner.acquire()
        retry_owner.release()
    finally:
        owners[0].release()
        monkeypatch.undo()


def test_selected_product_without_database_provider_refuses_before_writes(tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as bootstrap_runtime

    class IncompleteProduct:
        def default_plugins(self):
            return ()

        def server_contribution_points(self):
            return ()

    monkeypatch.setattr(bootstrap_runtime, "_resolve_product_composition", IncompleteProduct)
    root = tmp_path / "missing-provider"
    with pytest.raises(StorageProviderMissingError):
        build_runtime(root)
    assert not root.exists()


def test_duplicate_product_points_refuse_before_host_or_data_writes(tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as bootstrap_runtime
    from ordessa_server_product.composition import create_composition

    actual = create_composition()

    class DuplicateProduct:
        def default_plugins(self):
            return actual.default_plugins()

        def database_type(self):
            return actual.database_type()

        def server_contribution_points(self):
            first = actual.server_contribution_points()[0]
            return (first, ContributionPointSpec(first.point_id, "v2", first.handler, False))

    monkeypatch.setattr(bootstrap_runtime, "_resolve_product_composition", DuplicateProduct)
    root = tmp_path / "duplicate-points"
    with pytest.raises(ContributionDeclarationError, match="duplicate"):
        build_runtime(root)
    assert not root.exists()


@pytest.mark.parametrize("point_id", ("wire.error-families", "wire.discovery-facets"))
def test_product_cannot_redeclare_host_point_before_writes(tmp_path, monkeypatch, point_id):
    import ordessa_server.bootstrap.runtime as bootstrap_runtime
    from ordessa_server_product.composition import create_composition

    actual = create_composition()

    class ConflictingProduct:
        def default_plugins(self):
            return actual.default_plugins()

        def database_type(self):
            return actual.database_type()

        def server_contribution_points(self):
            return (ContributionPointSpec(point_id, "v2", RecordingHandler(), False),)

    monkeypatch.setattr(bootstrap_runtime, "_resolve_product_composition", ConflictingProduct)
    root = tmp_path / "conflict"
    with pytest.raises(ContributionDeclarationError, match="host-owned"):
        build_runtime(root)
    assert not root.exists()


def test_wire_construction_failure_closes_core_and_releases_owner(tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as bootstrap_runtime
    import ordessa_server.wire.handlers as wire_handlers

    owners = []
    bindings = []
    real_owner = bootstrap_runtime.DataRootOwner
    real_binding = bootstrap_runtime.CoreBinding

    class TrackedOwner(real_owner):
        def __init__(self, root):
            super().__init__(root)
            owners.append(self)

    class TrackedBinding(real_binding):
        def __init__(self, path):
            super().__init__(path)
            bindings.append(self)

        def close(self):
            self.was_closed = True
            return super().close()

    def failed_wire(*args, **kwargs):
        raise RuntimeError("wire construction failed")

    monkeypatch.setattr(bootstrap_runtime, "DataRootOwner", TrackedOwner)
    monkeypatch.setattr(bootstrap_runtime, "CoreBinding", TrackedBinding)
    monkeypatch.setattr(wire_handlers, "WireService", failed_wire)
    try:
        with pytest.raises(RuntimeError, match="wire construction failed"):
            build_runtime(tmp_path / "wire-failure")
        assert len(owners) == len(bindings) == 1
        assert not owners[0].acquired
        assert bindings[0].was_closed
    finally:
        for owner in owners:
            owner.release()


def test_late_composition_failure_disposes_active_plugin_before_releasing_owner(
        tmp_path, monkeypatch):
    import ordessa_server.bootstrap.runtime as bootstrap_runtime
    import ordessa_server.wire.handlers as wire_handlers

    events = []
    owners = []
    real_owner = bootstrap_runtime.DataRootOwner

    class TrackedOwner(real_owner):
        def __init__(self, root):
            super().__init__(root)
            owners.append(self)

        def release(self):
            events.append("release")
            return super().release()

    class Database:
        def __init__(self, root):
            self.path = root / "state" / "agentbox.sqlite"

    class DisposablePlugin(EmptyPlugin):
        def build(self, context):
            return ServerPluginRegistration(disposal=lambda: events.append("dispose"))

    def failed_bind(self, resolver):
        raise RuntimeError("late bind failed")

    monkeypatch.setattr(bootstrap_runtime, "DataRootOwner", TrackedOwner)
    monkeypatch.setattr(wire_handlers.WireService, "bind_workspace_resolution", failed_bind)
    try:
        with pytest.raises(RuntimeError, match="late bind failed"):
            build_runtime(
                tmp_path / "late-failure", server_plugins=(DisposablePlugin(),),
                database_factory=Database,
            )
        assert events == ["dispose", "release"]
        assert len(owners) == 1 and not owners[0].acquired
    finally:
        for owner in owners:
            owner.release()
