"""Fail-closed checks for trusted Work/review product assembly inputs."""
import pytest
from types import SimpleNamespace

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_server.composition.engineering_method_unit_assembly import (
    method_unit_application_ports_factory,
)
from ordessa_server.composition import product_runtime
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess


def _callbacks():
    return {
        "author_unit_resolver": lambda *_args: None,
        "invocation_resolver": lambda *_args, **_kwargs: None,
        "unit_query_factory": lambda *_args, **_kwargs: None,
    }


def test_assembly_refuses_non_original_unit_owner_before_returning_ports_factory():
    with pytest.raises(ApplicationError, match="UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE"):
        method_unit_application_ports_factory(
            unit_owner=object(), proposal_ref=object(), phases=(), **_callbacks())


@pytest.mark.parametrize("missing", [
    "author_unit_resolver", "invocation_resolver", "unit_query_factory",
])
def test_assembly_refuses_missing_trusted_query_or_identity_producer(missing):
    callbacks = _callbacks()
    callbacks[missing] = None
    with pytest.raises(ApplicationError, match="UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE"):
        method_unit_application_ports_factory(
            unit_owner=object(), proposal_ref=object(), phases=(), **callbacks)


def test_assembly_refuses_noncallable_base_ports_factory():
    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_AUTHORITY_MISMATCH"):
        method_unit_application_ports_factory(
            unit_owner=object(), proposal_ref=object(), phases=(),
            base_ports_factory=object(), **_callbacks())


def test_public_command_access_scope_conversion_matches_domain_scope():
    wire_scope = WireScope("realm", "project")
    owner_scope = EngineeringCommandAccess.owner_scope(wire_scope)
    assert type(owner_scope) is EngineeringScope
    assert owner_scope == EngineeringScope("realm", "project")


@pytest.mark.parametrize("unbound", [False, True])
def test_product_runtime_opt_in_forwards_actual_selected_runtime_owner(monkeypatch, unbound):
    owner, authority = object(), object()
    runtime = SimpleNamespace(started=False,
        wire=SimpleNamespace(identity_authority=authority),
        unit_execution_owner=owner)
    selected_pi = SimpleNamespace(_runtime=runtime)
    composition = SimpleNamespace(selected_pi_execution=selected_pi)
    factory, access = object(), SimpleNamespace(authority=authority)
    scope = WireScope("realm", "project")
    bindings = SimpleNamespace(factory=factory, bind_selection=lambda *_args, **_kwargs: None)
    ports = SimpleNamespace(review_admission=SimpleNamespace(bindings=bindings))
    observed = []

    def default_runtime(data_root, *, engineering_options):
        callback = engineering_options["application_ports_factory"]
        observed.append((data_root, engineering_options))
        assert callback(factory, access, scope) is ports
        return "same-product-runtime"

    composition.default_runtime = default_runtime
    monkeypatch.setattr(product_runtime, "create_host_product_composition",
        lambda **kwargs: composition)

    def build_ports_factory(**kwargs):
        assert kwargs["unit_owner"] is owner
        observed.append(kwargs)
        return lambda actual_factory, actual_access, actual_scope: (
            ports if (actual_factory, actual_access, actual_scope)
            == (factory, access, scope) else None)

    monkeypatch.setattr(product_runtime, "method_unit_application_ports_factory",
        build_ports_factory, raising=False)
    options = {
        "proposal_ref": None if unbound else object(),
        "phases": None if unbound else (object(),),
        "author_unit_resolver": lambda *_args: None,
        "invocation_resolver": lambda *_args, **_kwargs: None,
        "unit_query_factory": lambda *_args, **_kwargs: None,
    }
    result = product_runtime.build_product_runtime(
        "selected-root", pi_selection=object(), pi_ports=object(),
        method_unit_options=options, library_path="/trusted/library.sqlite",
        library_id="selected-library", scope=scope)

    assert result == "same-product-runtime"
    assert len(observed) == 2
    assert observed[0][0] == "selected-root"
    assert "application_ports_factory" in observed[0][1]
    assert observed[1]["proposal_ref"] is options["proposal_ref"]
    if unbound:
        assert observed[1]["phases"] is None
        assert runtime.engineering_review_bindings is bindings
    else:
        assert not hasattr(runtime, "engineering_review_bindings")


@pytest.mark.parametrize("proposal_ref,phases", [
    (None, (object(),)), (object(), None), (None, ()), (object(), ()),
])
def test_product_runtime_refuses_partial_or_empty_subject_selection_before_runtime(
        monkeypatch, proposal_ref, phases):
    calls = []
    monkeypatch.setattr(product_runtime, "create_host_product_composition",
        lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ApplicationError, match="METHOD_SUBJECT_BINDING_MISMATCH"):
        product_runtime.build_product_runtime(
            "root", pi_selection=object(), pi_ports=object(),
            method_unit_options={"proposal_ref": proposal_ref, "phases": phases,
                                 **_callbacks()},
            library_path="/trusted/library.sqlite", library_id="selected-library",
            scope=WireScope("realm", "project"))
    assert calls == []


@pytest.mark.parametrize("change", [
    {"unknown": True}, {"unit_owner": object()},
])
def test_product_runtime_rejects_unapproved_method_unit_options_before_selection(
        monkeypatch, change):
    calls = []
    monkeypatch.setattr(product_runtime, "create_host_product_composition",
        lambda **kwargs: calls.append(kwargs))
    options = {
        "proposal_ref": object(), "phases": (object(),),
        "author_unit_resolver": lambda *_args: None,
        "invocation_resolver": lambda *_args, **_kwargs: None,
        "unit_query_factory": lambda *_args, **_kwargs: None,
        **change,
    }
    with pytest.raises(ApplicationError,
            match="UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE"):
        product_runtime.build_product_runtime(
            "root", pi_selection=object(), pi_ports=object(),
            method_unit_options=options, library_path="/trusted/library.sqlite",
            library_id="selected-library", scope=WireScope("realm", "project"))
    assert calls == []


def test_product_runtime_rejects_second_ports_factory_and_missing_selection_preflight(
        monkeypatch):
    calls = []
    monkeypatch.setattr(product_runtime, "create_host_product_composition",
        lambda **kwargs: calls.append(kwargs))
    options = {
        "proposal_ref": object(), "phases": (object(),),
        "author_unit_resolver": lambda *_args: None,
        "invocation_resolver": lambda *_args, **_kwargs: None,
        "unit_query_factory": lambda *_args, **_kwargs: None,
    }
    common = dict(method_unit_options=options, library_path="/trusted/library.sqlite",
        library_id="selected-library", scope=WireScope("realm", "project"))
    with pytest.raises(ApplicationError, match="UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE"):
        product_runtime.build_product_runtime("root", **common)
    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_AUTHORITY_MISMATCH"):
        product_runtime.build_product_runtime("root", pi_selection=object(), pi_ports=object(),
            application_ports_factory=lambda *_args: None, **common)
    assert calls == []


def test_product_runtime_none_keeps_original_engineering_options_behavior(monkeypatch):
    captured = []
    composition = SimpleNamespace(
        default_runtime=lambda data_root, *, engineering_options:
            captured.append((data_root, engineering_options)) or "original-path")
    monkeypatch.setattr(product_runtime, "create_host_product_composition",
        lambda **kwargs: composition)
    result = product_runtime.build_product_runtime("root")
    assert result == "original-path"
    assert captured == [("root", None)]


def test_product_runtime_refuses_noncallable_dispatch_prompt_producer_before_selection(monkeypatch):
    calls=[]
    monkeypatch.setattr(product_runtime, "create_host_product_composition",
        lambda **kwargs: calls.append(kwargs))
    options={"proposal_ref": object(), "phases": (object(),), **_callbacks(),
        "dispatch_prompt_parameters": object()}
    with pytest.raises(ApplicationError, match="WORK_NATIVE_SOURCE_UNAVAILABLE"):
        product_runtime.build_product_runtime("root", pi_selection=object(), pi_ports=object(),
            method_unit_options=options, library_path="/trusted/library.sqlite",
            library_id="selected-library", scope=WireScope("realm", "project"))
    assert calls==[]


def test_product_runtime_requires_same_submission_query_owner_for_native_dispatch(monkeypatch):
    calls=[]
    monkeypatch.setattr(product_runtime, "create_host_product_composition",
        lambda **kwargs: calls.append(kwargs))
    options={"proposal_ref": object(), "phases": (object(),), **_callbacks(),
        "dispatch_prompt_parameters": lambda *_args: {}}
    with pytest.raises(ApplicationError, match="WORK_NATIVE_SOURCE_UNAVAILABLE"):
        product_runtime.build_product_runtime("root", pi_selection=object(), pi_ports=object(),
            method_unit_options=options, library_path="/trusted/library.sqlite",
            library_id="selected-library", scope=WireScope("realm", "project"))
    assert calls==[]


def test_product_runtime_forwards_explicit_work_scope_guard_to_selected_owner(monkeypatch):
    owner, authority = object(), object()
    runtime = SimpleNamespace(started=False, wire=SimpleNamespace(identity_authority=authority),
        unit_execution_owner=owner)
    bindings = SimpleNamespace(factory=None, bind_selection=lambda *_args, **_kwargs: None)
    ports = SimpleNamespace(review_admission=SimpleNamespace(bindings=bindings))
    factory, access, scope = object(), SimpleNamespace(authority=authority), WireScope('realm', 'project')
    bindings.factory = factory
    seen = {}

    def scope_guard(*_args):
        raise AssertionError('Selecting a guard must not authorize an effect')

    def default_runtime(_root, *, engineering_options):
        assert engineering_options['application_ports_factory'](factory, access, scope) is ports
        return runtime

    composition = SimpleNamespace(selected_pi_execution=SimpleNamespace(_runtime=runtime),
        default_runtime=default_runtime)
    monkeypatch.setattr(product_runtime, 'create_host_product_composition', lambda **_kwargs: composition)

    def selected_constructor(**kwargs):
        seen.update(kwargs)
        return lambda *_args: ports

    monkeypatch.setattr(product_runtime, 'method_unit_application_ports_factory', selected_constructor)
    result = product_runtime.build_product_runtime('controlled-root', pi_selection=object(), pi_ports=object(),
        method_unit_options={'proposal_ref': None, 'phases': None, **_callbacks(),
            'dispatch_prompt_parameters': lambda *_args: {}, 'report_phase_key': 'implement',
            'workspace_scope_guard': scope_guard}, library_path='/controlled/library.sqlite',
        library_id='controlled-library', scope=scope)
    assert result is runtime
    assert seen['unit_owner'] is owner
    assert seen['workspace_scope_guard'] is scope_guard


@pytest.mark.parametrize('scope_guard,with_dispatch', [(object(), True), (lambda *_args: None, False)])
def test_product_runtime_refuses_unusable_work_scope_guard_before_composition(monkeypatch, scope_guard, with_dispatch):
    calls = []
    monkeypatch.setattr(product_runtime, 'create_host_product_composition', lambda **kwargs: calls.append(kwargs))
    options = {'proposal_ref': None, 'phases': None, **_callbacks(), 'workspace_scope_guard': scope_guard}
    if with_dispatch:
        options.update(dispatch_prompt_parameters=lambda *_args: {}, report_phase_key='implement')
    with pytest.raises(ApplicationError, match='DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE'):
        product_runtime.build_product_runtime('controlled-root', pi_selection=object(), pi_ports=object(),
            method_unit_options=options, library_path='/controlled/library.sqlite',
            library_id='controlled-library', scope=WireScope('realm', 'project'))
    assert calls == []
