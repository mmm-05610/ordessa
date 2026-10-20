"""C01 retires Profile-owned session registration and overlay access."""
import importlib.util


def test_profile_native_session_registry_is_not_available_from_the_product():
    assert importlib.util.find_spec("ordessa_server_product.profile_sessions") is None
    assert importlib.util.find_spec("ordessa_server_product.native_configuration") is None
