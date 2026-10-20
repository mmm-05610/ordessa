"""Prepared direct tests for the selected Product's injected Host callables.

These tests use the real ServerProductComposition, the real Host runtime and
core-method functions, and the installed Product entry point. They do not
start a server, invoke a model, or call the environment factory.
"""
from ordessa_server_product.composition import ProductCompositionUnavailable
import pytest

from ordessa_system_access_bindings import agents as agent_core_wire
from ordessa_server.composition import runtime as host_runtime
from ordessa_server.composition.configuration.product_selection import (
    create_host_product_composition,
)
from ordessa_server_product.composition import ServerProductComposition


def test_deployment_selector_binds_the_actual_host_application_functions():
    product = create_host_product_composition()
    assert type(product) is ServerProductComposition
    assert product._host_runtime_builder is host_runtime.build_runtime
    assert product._host_core_method_factory is agent_core_wire.agent_core_methods


def test_installed_product_host_resolver_binds_the_same_actual_host_functions():
    product = host_runtime._resolve_product_composition()
    assert type(product) is ServerProductComposition
    assert product._host_runtime_builder is host_runtime.build_runtime
    assert product._host_core_method_factory is agent_core_wire.agent_core_methods


def test_noncallable_application_port_pair_refuses_without_partial_binding():
    product = ServerProductComposition()
    with pytest.raises(TypeError, match="explicit host runtime builder and core method factory"):
        product.bind_host_application_ports(
            runtime_builder=host_runtime.build_runtime,
            core_method_factory=None,
        )
    assert product._host_runtime_builder is None
    assert product._host_core_method_factory is None


def test_unbound_core_port_refuses_before_environment_resolution():
    product = ServerProductComposition()
    calls = []

    def environment_resolver():
        calls.append("resolved")
        raise AssertionError("the unbound Product must refuse before resolving Environment")

    with pytest.raises(ProductCompositionUnavailable, match="explicit host core method factory"):
        product.core_method_factory(environment_resolver)
    assert calls == []


def test_unbound_runtime_port_refuses_before_product_side_effects(tmp_path, monkeypatch):
    product = ServerProductComposition()
    calls = []
    monkeypatch.setattr(product, "_assemble_legacy_chain", lambda: calls.append("legacy"))
    with pytest.raises(ProductCompositionUnavailable, match="explicit host runtime builder"):
        product.default_runtime(tmp_path / "must-not-be-created")
    assert calls == []
    assert not (tmp_path / "must-not-be-created").exists()


def test_same_application_port_pair_is_idempotent_and_foreign_pair_is_atomic():
    product = ServerProductComposition()
    runtime_builder = host_runtime.build_runtime
    core_factory = agent_core_wire.agent_core_methods
    product.bind_host_application_ports(
        runtime_builder=runtime_builder,
        core_method_factory=core_factory,
    )
    bound = (product._host_runtime_builder, product._host_core_method_factory)

    product.bind_host_application_ports(
        runtime_builder=runtime_builder,
        core_method_factory=core_factory,
    )
    assert (product._host_runtime_builder, product._host_core_method_factory) == bound
    assert product._host_runtime_builder is runtime_builder
    assert product._host_core_method_factory is core_factory

    with pytest.raises(ProductCompositionUnavailable, match="different composition"):
        product.bind_host_application_ports(
            runtime_builder=lambda *_args, **_kwargs: None,
            core_method_factory=core_factory,
        )
    assert (product._host_runtime_builder, product._host_core_method_factory) == bound
    assert product._host_runtime_builder is runtime_builder
    assert product._host_core_method_factory is core_factory
