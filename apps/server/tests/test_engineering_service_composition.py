"""One public Engineering gate in an original scoped library/runtime round."""
from ordessa_engineering.application.api import EngineeringService
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts, SUPPORTED_METHODS
from ordessa_server.composition.engineering import EngineeringServerPlugin, select_engineering
import pytest
from ordessa_server_plugin_api.wire_errors import WireError


def test_registered_catalog_and_requests_share_one_public_service_and_original_factory(tmp_path):
    path = tmp_path / 'library.sqlite'
    library = EngineeringLibrary.create(path, library_id='one-gate', schema_version=10)
    library.close()
    authority = InstanceAccessAuthority(lambda: 'synthetic-instance-token', grants=())
    calls = []
    def ports(factory, access, scope):
        calls.append((factory, access, scope))
        return EngineeringApplicationPorts()
    plugin = EngineeringServerPlugin(path=path, library_id='one-gate', scope=Scope('realm', 'project'),
        authority_resolver=lambda: authority, application_ports_factory=ports)
    registration = plugin.build(None)
    try:
        first = plugin._binding_for(authority)
        assert type(first.service) is EngineeringService
        plugin.capability_catalog().read_current()
        assert plugin._binding_for(authority) is first
        assert len(calls) == 1
        assert calls[0][0] is plugin._factory
        assert calls[0][1] is first.access
        assert first.factory.library is plugin.library
        with pytest.raises(WireError):
            plugin._binding_for(InstanceAccessAuthority(lambda: 'another-synthetic-token', grants=()))
    finally:
        registration.disposal()
    with pytest.raises(WireError):
        plugin._binding_for(authority)


def test_retired_independent_run_and_submission_routes_are_absent():
    assert 'engineering.implementation.start_run' not in SUPPORTED_METHODS
    assert 'engineering.submissions.record' not in SUPPORTED_METHODS
    assert 'engineering.submissions.record_report' in SUPPORTED_METHODS


def _selection_options(path, **overrides):
    options = {
        "library_path": path,
        "library_id": "one-gate",
        "scope": Scope("realm", "project"),
    }
    options.update(overrides)
    return options


def test_selection_does_not_build_runtime_or_open_an_existing_library(tmp_path, monkeypatch):
    path = tmp_path / "existing.sqlite"
    library = EngineeringLibrary.create(path, library_id="one-gate", schema_version=10)
    library.close()
    before = path.read_bytes()

    opened = []
    def unexpected_open(cls, *args, **kwargs):
        opened.append((args, kwargs))
        raise AssertionError("selection must not open the library")
    monkeypatch.setattr(EngineeringLibrary, "open", classmethod(unexpected_open))

    from ordessa_server.composition import runtime as runtime_module
    runtime_builds = []
    def unexpected_runtime_build(*args, **kwargs):
        runtime_builds.append((args, kwargs))
        raise AssertionError("selection must not build a Server runtime")
    monkeypatch.setattr(runtime_module, "build_runtime", unexpected_runtime_build)

    authority = object()
    plugin, configure_runtime = select_engineering(
        _selection_options(path), authority_resolver=lambda: authority)

    assert isinstance(plugin, EngineeringServerPlugin)
    assert plugin.library is None
    assert callable(configure_runtime)
    assert opened == []
    assert runtime_builds == []
    assert path.read_bytes() == before


def test_selection_explicitly_creates_only_a_missing_library(tmp_path):
    path = tmp_path / "new.sqlite"
    plugin, configure_runtime = select_engineering(
        _selection_options(path, create_library=True, schema_version=10),
        authority_resolver=lambda: None,
    )
    assert path.is_file()
    assert plugin.library is None
    assert callable(configure_runtime)

    with pytest.raises(ValueError, match="nonexistent path"):
        select_engineering(
            _selection_options(path, create_library=True, schema_version=10),
            authority_resolver=lambda: None,
        )


def test_selection_callback_grants_existing_runtime_authority_without_replacing_it(tmp_path):
    path = tmp_path / "existing.sqlite"
    library = EngineeringLibrary.create(path, library_id="one-gate", schema_version=10)
    library.close()
    authority = InstanceAccessAuthority(lambda: "synthetic-token", grants=())
    resolver_calls = []
    def resolve_authority():
        resolver_calls.append(True)
        return authority

    capabilities = ("engineering.capabilities",)
    plugin, configure_runtime = select_engineering(
        _selection_options(path, machine_capabilities=capabilities),
        authority_resolver=resolve_authority,
    )
    runtime = type("Runtime", (), {"wire": type("Wire", (), {"identity_authority": authority})()})()
    configure_runtime(runtime)

    assert runtime.wire.identity_authority is authority
    principal = authority.authenticate("Bearer synthetic-token")
    assert principal.kind == "machine"
    assert principal.assurance == "instance-bearer"
    assert principal.grants == (AccessGrant(Scope("realm", "project"), capabilities),)
    assert resolver_calls == [True]
    assert plugin._authority_resolver is resolve_authority


@pytest.mark.parametrize("options", [
    {"library_path": "library.sqlite", "library_id": "one-gate"},
    {"library_path": "library.sqlite", "library_id": "one-gate", "realm": "realm"},
    {"library_path": "library.sqlite", "library_id": "one-gate", "project": "project"},
])
def test_selection_rejects_missing_scope_or_half_configured_realm_project(tmp_path, options):
    path = tmp_path / options["library_path"]
    selected = {**options, "library_path": path, "create_library": True}
    with pytest.raises(ValueError, match="scope|realm and project"):
        select_engineering(selected, authority_resolver=lambda: None)
    assert not path.exists()


def test_selection_rejects_unimplemented_capability_and_unknown_configuration(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="implemented Engineering capabilities"):
        select_engineering(
            _selection_options(path, create_library=True,
                machine_capabilities=("engineering.capabilities", "engineering.new_unimplemented")),
            authority_resolver=lambda: None,
        )
    with pytest.raises(ValueError, match="Unknown Engineering configuration fields"):
        select_engineering(
            _selection_options(path, create_library=True, hidden_fallback=True),
            authority_resolver=lambda: None,
        )
    with pytest.raises(ValueError, match="supported Engineering schema"):
        select_engineering(
            _selection_options(path, create_library=True, schema_version=9),
            authority_resolver=lambda: None,
        )
    assert not path.exists()


def test_unit_reviewer_capability_is_explicit_and_has_no_default_machine_grant(tmp_path):
    from ordessa_server.composition.engineering import (
        _engineering_selection, DEFAULT_MACHINE_CAPABILITIES,
    )
    selected = _engineering_selection(_selection_options(tmp_path / 'library.sqlite',
        machine_capabilities=('engineering.reviewer.unit',)))
    assert selected[4] == ('engineering.reviewer.unit',)
    assert 'engineering.reviewer.unit' not in DEFAULT_MACHINE_CAPABILITIES


def test_selection_accepts_trusted_realm_project_configuration(tmp_path):
    path = tmp_path / "existing.sqlite"
    library = EngineeringLibrary.create(path, library_id="one-gate", schema_version=10)
    library.close()
    plugin, _ = select_engineering(
        {"library_path": path, "library_id": "one-gate", "realm": "cli-realm",
         "project": "cli-project", "machine_capabilities": ("engineering.capabilities",)},
        authority_resolver=lambda: None,
    )
    assert plugin.scope == Scope("cli-realm", "cli-project")


def test_selection_callback_refuses_a_different_runtime_authority(tmp_path):
    path = tmp_path / "existing.sqlite"
    library = EngineeringLibrary.create(path, library_id="one-gate", schema_version=10)
    library.close()
    selected_authority = InstanceAccessAuthority(lambda: "selected-token", grants=())
    other_authority = InstanceAccessAuthority(lambda: "other-token", grants=())
    _, configure_runtime = select_engineering(
        _selection_options(path), authority_resolver=lambda: selected_authority)
    runtime = type("Runtime", (), {"wire": type("Wire", (), {"identity_authority": other_authority})()})()

    with pytest.raises(ValueError, match="existing instance authority"):
        configure_runtime(runtime)
    assert other_authority.authenticate("Bearer other-token").grants == ()
