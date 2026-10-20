"""Real public C2 projection must remain bound to the Host capture."""
from ordessa_server_product.composition import ProductCompositionUnavailable
import pytest

from ordessa_model_provider.plugin import ModelProviderPlugin
from ordessa_server.composition import selected_harness_catalog as selected
from ordessa_server.composition.harness_catalog import capture_harness_catalog
from ordessa_server.composition.selected_model_configuration import (
    bind_selected_model_configuration_catalog,
    capture_selected_model_configuration_catalog,
)
from ordessa_server.composition.configuration.product_selection import create_host_product_composition
from ordessa_server_product.composition import create_composition


def test_projection_uses_actual_selected_c2_declarations_from_same_host_registry():
    captured = selected.capture_selected_harness_catalog()
    product = create_composition()
    product.bind_harness_registry(captured.registry)
    catalog = bind_selected_model_configuration_catalog(product)
    assert product.bound_harness_registry is captured.registry
    assert product.bound_model_configuration_catalog is catalog
    assert catalog.registered() == ("pi", "codex", "claude-code")
    for harness_id in catalog.registered():
        assert captured.registry.get(harness_id).harness_type == harness_id
        assert catalog.get(harness_id).id == harness_id
        assert catalog.wire_protocols(harness_id)


def test_repeated_binding_reuses_projection_without_rereading_public_ports(monkeypatch):
    product = create_host_product_composition()
    original = product.bound_model_configuration_catalog
    import ordessa_server.composition.selected_model_configuration as model_selection
    def forbidden_capture(**kwargs):
        raise AssertionError("bound projection must not capture again")
    monkeypatch.setattr(model_selection, "capture_selected_model_configuration_catalog", forbidden_capture)
    assert bind_selected_model_configuration_catalog(product) is original
    assert product.bound_model_configuration_catalog is original


def test_missing_selected_provider_refuses_before_binding_projection():
    codex = selected.codex()
    captured = capture_harness_catalog((codex,), launch_declarations=(codex,))
    product = create_composition()
    product.bind_harness_registry(captured.registry)
    with pytest.raises(KeyError):
        bind_selected_model_configuration_catalog(product)
    assert product.bound_model_configuration_catalog is None
    assert product.host_harness_effects is None


def test_missing_capture_and_wrong_catalog_type_refuse():
    with pytest.raises(ValueError, match="captured Harness registry"):
        capture_selected_model_configuration_catalog(registry=None)
    product = create_composition()
    with pytest.raises(TypeError, match="ModelConfigurationCatalog"):
        product.bind_model_configuration_catalog(object())
    assert product.bound_model_configuration_catalog is None


def test_catalog_identity_cannot_be_replaced_after_binding():
    product = create_host_product_composition()
    original = product.bound_model_configuration_catalog
    second = capture_selected_model_configuration_catalog(registry=product.bound_harness_registry)
    assert second is not original
    with pytest.raises(ProductCompositionUnavailable, match="already bound"):
        product.bind_model_configuration_catalog(second)
    assert product.bound_model_configuration_catalog is original


def test_default_plugin_consumes_bound_catalog_and_preserves_explicit_override():
    product = create_host_product_composition()
    original = product.bound_model_configuration_catalog
    plugin = next(p for p in product.default_plugins() if isinstance(p, ModelProviderPlugin))
    assert plugin._harnesses is original
    explicit = capture_selected_model_configuration_catalog(registry=product.bound_harness_registry)
    overridden = next(p for p in product.default_plugins(harnesses=explicit)
                      if isinstance(p, ModelProviderPlugin))
    assert overridden._harnesses is explicit
    assert product.bound_model_configuration_catalog is original


def test_unbound_default_plugin_refuses_before_host_effects():
    product = create_composition()
    with pytest.raises(ProductCompositionUnavailable, match="model configuration catalog"):
        product.default_plugins()
    assert product.host_harness_effects is None
