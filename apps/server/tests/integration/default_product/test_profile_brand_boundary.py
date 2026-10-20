"""The retired product Profile chain has no callable brand-facing helpers."""
import importlib.util

import pytest


@pytest.mark.parametrize("module", [
    "profile_wire_plugin", "profile_configuration", "profile_preparation",
    "profile_sessions", "native_configuration",
])
def test_retired_profile_module_is_absent(module):
    assert importlib.util.find_spec(f"ordessa_server_product.{module}") is None
