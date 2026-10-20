"""C01 retires the old Profile-to-native configuration adapter."""
import importlib.util

from ordessa_server.composition.configuration.product_selection import create_host_product_composition as create_composition


def test_native_profile_config_adapter_is_not_a_product_factory():
    assert importlib.util.find_spec("ordessa_server_product.profile_configuration") is None
    product = create_composition()
    assert callable(product.core_method_factory)
