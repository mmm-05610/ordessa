"""Engineering activation waits for the same live identity as its binding."""
import asyncio
from dataclasses import asdict

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.api import EXECUTION_DISPATCH
from ordessa_execution_agents.profiles import ProfileRevisionRef
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.engineering import (
    DEFAULT_MACHINE_CAPABILITIES, EngineeringServerPlugin,
    _verify_bound_unit_permission,
)
from ordessa_server.composition.product_runtime import build_product_runtime
from ordessa_server.composition.engineering import select_engineering
from ordessa_system_access_bindings.engineering_wire import (
    EngineeringWireBinding,
)


SCOPE = Scope("deferred-realm", "deferred-project")


def test_default_product_activates_engineering_through_host_and_rebinds_after_restart(
        tmp_path, monkeypatch):
    generated = []
    real_methods = EngineeringWireBinding.methods

    def observe_methods(binding, *, owner="ordessa.engineering"):
        result = real_methods(binding, owner=owner)
        generated.append((binding, result))
        return result

    monkeypatch.setattr(EngineeringWireBinding, "methods", observe_methods)
    runtime = build_product_runtime(tmp_path / "server", library_path=tmp_path / "library.sqlite",
        library_id="deferred-library", scope=SCOPE, create_library=True,
        machine_capabilities=("engineering.capabilities",))
    try:
        plugin_id = "ordessa.engineering"
        assert plugin_id in runtime.plugin_host.active_ids()
        assert any(plugin.descriptor().id == plugin_id for plugin in runtime.plugin_selection)
        active = runtime.plugin_host.active(plugin_id)
        assert len(generated) == 1
        assert active.registration.methods is generated[0][1]
        assert tuple(item.method_id for item in generated[0][1]) == active.method_ids
        assert EXECUTION_DISPATCH not in active.method_ids
        assert EXECUTION_DISPATCH not in DEFAULT_MACHINE_CAPABILITIES

        runtime.start()
        caller = runtime.wire.identity_authority.authenticate("Bearer " + runtime.token)
        descriptor = runtime.plugin_host.methods.lookup("engineering.capabilities")
        result = asyncio.run(descriptor.handler(
            {"scope": asdict(SCOPE), "requestId": "deferred-capabilities"}, caller))
        assert result["contract_version"] == "engineering-wire/1"
        assert len(generated) == 1  # The installed handler reuses its activation's binding.

        runtime.stop()
        assert not runtime.plugin_host.is_active(plugin_id)
        assert runtime.plugin_host.methods.lookup("engineering.capabilities") is None
        runtime.start()
        assert runtime.plugin_host.is_active(plugin_id)
        assert len(generated) == 2
        restarted = runtime.plugin_host.active(plugin_id)
        assert restarted.registration.methods is generated[1][1]
        assert tuple(item.method_id for item in generated[1][1]) == restarted.method_ids
        assert generated[1][0] is not generated[0][0]
        assert EXECUTION_DISPATCH not in restarted.method_ids
    finally:
        runtime.stop()


def test_plugin_build_closes_library_when_selected_owner_factory_fails(tmp_path):
    path = tmp_path / "partial-build.sqlite"
    library = EngineeringLibrary.create(path.resolve(), library_id="partial-build", schema_version=10)
    library.close()
    authority = InstanceAccessAuthority(lambda: "deferred-token", principal_id="deferred-owner",
        legacy_principal=None, grants=())

    def failing_owner_factory(factory, access, scope):
        raise ApplicationError("REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")

    plugin = EngineeringServerPlugin(path=path, library_id="partial-build", scope=SCOPE,
        authority_resolver=lambda: authority, application_ports_factory=failing_owner_factory)
    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_AUTHORITY_UNAVAILABLE"):
        plugin.build(None)
    assert plugin.library is None
    assert plugin._factory is None
    assert plugin._binding is None
    reopened = EngineeringLibrary.open(path.resolve(), library_id="partial-build")
    reopened.close()


def test_configuration_refuses_started_or_repeated_runtime_binding(tmp_path):
    path = tmp_path / "configure.sqlite"
    library = EngineeringLibrary.create(path.resolve(), library_id="configure", schema_version=10)
    library.close()
    authority = InstanceAccessAuthority(lambda: "configure-token", principal_id="configure-owner",
        legacy_principal=None, grants=())
    plugin, configure = select_engineering({"library_path": path.resolve(),
        "library_id": "configure", "scope": SCOPE, "machine_capabilities":
        ("engineering.capabilities",)}, authority_resolver=lambda: authority)

    class Runtime:
        wire = type("Wire", (), {"identity_authority": authority})()
        token = "configure-token"
        started = True

    runtime = Runtime()
    with pytest.raises(ValueError, match="before the runtime starts"):
        configure(runtime)
    assert authority.authenticate("Bearer configure-token").grants == ()

    runtime.started = False
    configure(runtime)
    assert authority.authenticate("Bearer configure-token").grants[0].capabilities == (
        "engineering.capabilities",)
    with pytest.raises(ValueError, match="already applied"):
        configure(runtime)
    assert plugin.library is None


def test_failed_deferred_activation_keeps_grants_and_selection_unmodified(tmp_path, monkeypatch):
    import ordessa_server.composition.configuration.product_selection as host_product_selection

    runtimes = []
    original_build = host_product_selection.build_runtime

    def observe_build(*args, **kwargs):
        runtime = original_build(*args, **kwargs)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(host_product_selection, "build_runtime", observe_build)

    def failing_owner_factory(factory, access, scope):
        raise ApplicationError("REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")

    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_AUTHORITY_UNAVAILABLE"):
        build_product_runtime(tmp_path / "failed-server", library_path=tmp_path / "failed.sqlite",
            library_id="failed-deferred", scope=SCOPE, create_library=True,
            machine_capabilities=("engineering.capabilities",),
            application_ports_factory=failing_owner_factory)
    assert len(runtimes) == 1
    runtime = runtimes[0]
    assert "ordessa.engineering" not in runtime.plugin_host.active_ids()
    assert all(plugin.descriptor().id != "ordessa.engineering" for plugin in runtime.plugin_selection)
    assert runtime.wire.identity_authority.authenticate("Bearer " + runtime.token).grants == ()
    reopened = EngineeringLibrary.open((tmp_path / "failed.sqlite").resolve(),
        library_id="failed-deferred")
    reopened.close()


def test_explicit_native_dispatch_without_bound_owner_refuses_activation(
        tmp_path, monkeypatch):
    import ordessa_server.composition.configuration.product_selection as host_product_selection

    runtimes = []
    original_build = host_product_selection.build_runtime

    def observe_build(*args, **kwargs):
        runtime = original_build(*args, **kwargs)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(host_product_selection, "build_runtime", observe_build)
    with pytest.raises(ValueError, match="not bound by the selected original owners"):
        build_product_runtime(tmp_path / "unbound-server", library_path=tmp_path / "unbound.sqlite",
            library_id="unbound-native", scope=SCOPE, create_library=True,
            machine_capabilities=(EXECUTION_DISPATCH,))
    assert len(runtimes) == 1
    runtime = runtimes[0]
    assert "ordessa.engineering" not in runtime.plugin_host.active_ids()
    assert all(plugin.descriptor().id != "ordessa.engineering" for plugin in runtime.plugin_selection)
    assert runtime.wire.identity_authority.authenticate("Bearer " + runtime.token).grants == ()
    assert EXECUTION_DISPATCH not in DEFAULT_MACHINE_CAPABILITIES
    assert runtime.plugin_host.methods.lookup(EXECUTION_DISPATCH) is None
    reopened = EngineeringLibrary.open((tmp_path / "unbound.sqlite").resolve(),
        library_id="unbound-native")
    reopened.close()


def test_selected_execution_owner_binds_before_engineering_activation(tmp_path, monkeypatch):
    from ordessa_server.composition.configuration.product_selection import (
        create_host_product_composition,
    )

    order = []
    original_build = EngineeringServerPlugin.build

    def observe_engineering_build(plugin, context):
        order.append("engineering-activation")
        return original_build(plugin, context)

    monkeypatch.setattr(EngineeringServerPlugin, "build", observe_engineering_build)

    def observe_selected_execution_owner(runtime):
        assert not runtime.plugin_host.is_active("ordessa.engineering")
        order.append("selected-execution-owner")

    composition = create_host_product_composition(
        execution_configurer=observe_selected_execution_owner)
    # Isolate the ordering under test from the unrelated Pi provider metadata
    # gate. The real host/product builder, Engineering selector, runtime, and
    # plugin host remain in use; no Unit or Grant state is substituted.
    monkeypatch.setattr(composition, "default_plugins", lambda: ())
    runtime = composition.default_runtime(tmp_path / "owner-order-server",
        engineering_options={"library_path": (tmp_path / "owner-order.sqlite").resolve(),
            "library_id": "owner-order", "scope": SCOPE, "create_library": True,
            "machine_capabilities": ("engineering.capabilities",)})
    try:
        assert order == ["selected-execution-owner", "engineering-activation"]
        assert runtime.plugin_host.is_active("ordessa.engineering")
    finally:
        runtime.stop()


def _unit_permission(authority, grants, tmp_path, *, scope=None):
    from ordessa_units.assembly import UnitRunPermission
    unit_scope = scope or Scope("permission-realm", "unit-project")
    principal = authority.authenticate("Bearer unit-permission-token")
    assert principal.grants == grants
    return UnitRunPermission(access_authority=authority, principal=principal,
        scope=unit_scope, agent_id="permission-agent",
        profile_revision=ProfileRevisionRef("permission-realm", "profile", 1,
            "sha256:" + "a" * 64),
        environment_identity="environment-id", root_directory=str(tmp_path.resolve()),
        actions=frozenset({"start"}), expires_at=4_000_000_000.0)


def test_bound_unit_permission_covers_engineering_scope_without_changing_epoch(tmp_path):
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant

    unit_scope = Scope("permission-realm", "unit-project")
    engineering_scope = Scope("permission-realm", "engineering-project")
    grants = (AccessGrant(unit_scope, ("execution.units.start",)),
        AccessGrant(engineering_scope, ("engineering.capabilities",)))
    authority = InstanceAccessAuthority(lambda: "unit-permission-token",
        principal_id="unit-permission-owner", legacy_principal=None, grants=grants)
    permission = _unit_permission(authority, grants, tmp_path)
    epoch = authority.credential_epoch

    _verify_bound_unit_permission(permission, authority, engineering_scope,
        ("engineering.capabilities",))

    assert authority.credential_epoch == epoch
    assert authority.authenticate("Bearer unit-permission-token").grants == grants
    assert permission.principal.credential_epoch == epoch


def test_bound_unit_permission_covers_engineering_capabilities_in_same_scope(tmp_path):
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant

    scope = Scope("permission-realm", "engineering-project")
    grants = (AccessGrant(scope, ("execution.units.start", "engineering.capabilities")),)
    authority = InstanceAccessAuthority(lambda: "unit-permission-token",
        principal_id="unit-permission-owner", legacy_principal=None, grants=grants)
    permission = _unit_permission(authority, grants, tmp_path, scope=scope)
    epoch = authority.credential_epoch

    _verify_bound_unit_permission(permission, authority, scope, ("engineering.capabilities",))

    assert authority.credential_epoch == epoch
    assert authority.authenticate("Bearer unit-permission-token").grants == grants
    assert permission.principal.credential_epoch == epoch


def test_bound_unit_permission_rejects_missing_engineering_grant_without_invalidation(tmp_path):
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant

    unit_scope = Scope("permission-realm", "unit-project")
    engineering_scope = Scope("permission-realm", "engineering-project")
    grants = (AccessGrant(unit_scope, ("execution.units.start",)),
        AccessGrant(engineering_scope, ("engineering.reviews.read",)))
    authority = InstanceAccessAuthority(lambda: "unit-permission-token",
        principal_id="unit-permission-owner", legacy_principal=None, grants=grants)
    permission = _unit_permission(authority, grants, tmp_path)
    epoch = authority.credential_epoch

    with pytest.raises(ValueError, match="lacks the selected Engineering scope/capabilities"):
        _verify_bound_unit_permission(permission, authority, engineering_scope,
            ("engineering.capabilities",))

    assert authority.credential_epoch == epoch
    assert authority.authenticate("Bearer unit-permission-token").grants == grants
    assert permission.principal.credential_epoch == epoch


def test_bound_unit_permission_rejects_foreign_authority_without_invalidation(tmp_path):
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant

    unit_scope = Scope("permission-realm", "unit-project")
    engineering_scope = Scope("permission-realm", "engineering-project")
    grants = (AccessGrant(unit_scope, ("execution.units.start",)),
        AccessGrant(engineering_scope, ("engineering.capabilities",)))
    original = InstanceAccessAuthority(lambda: "unit-permission-token",
        principal_id="unit-permission-owner", legacy_principal=None, grants=grants)
    foreign = InstanceAccessAuthority(lambda: "foreign-token",
        principal_id="foreign-owner", legacy_principal=None, grants=grants)
    permission = _unit_permission(original, grants, tmp_path)
    epoch = original.credential_epoch

    with pytest.raises(ValueError, match="does not use the runtime's original access authority"):
        _verify_bound_unit_permission(permission, foreign, engineering_scope,
            ("engineering.capabilities",))

    assert original.credential_epoch == epoch
    assert original.authenticate("Bearer unit-permission-token").grants == grants


def test_bound_unit_permission_rejects_stale_principal_without_further_mutation(tmp_path):
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant

    unit_scope = Scope("permission-realm", "unit-project")
    engineering_scope = Scope("permission-realm", "engineering-project")
    grants = (AccessGrant(unit_scope, ("execution.units.start",)),
        AccessGrant(engineering_scope, ("engineering.capabilities",)))
    authority = InstanceAccessAuthority(lambda: "unit-permission-token",
        principal_id="unit-permission-owner", legacy_principal=None, grants=grants)
    permission = _unit_permission(authority, grants, tmp_path)
    authority.invalidate()
    epoch = authority.credential_epoch

    with pytest.raises(ValueError, match="principal is stale"):
        _verify_bound_unit_permission(permission, authority, engineering_scope,
            ("engineering.capabilities",))

    assert authority.credential_epoch == epoch
    assert authority.authenticate("Bearer unit-permission-token").grants == grants
    assert permission.principal.credential_epoch != epoch
