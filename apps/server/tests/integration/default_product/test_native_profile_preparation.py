"""C01 retires Profile-backed native preparation until core ports exist."""
import importlib.util

from ordessa_server.composition.runtime import build_runtime


def test_native_profile_preparation_has_no_product_factory_or_capability(tmp_path):
    assert importlib.util.find_spec("ordessa_server_product.profile_preparation") is None
    runtime = build_runtime(tmp_path / "data")
    try:
        runtime.start()
        capabilities = runtime.wire.dispatch("agents.capabilities", {}, caller=runtime.wire.identity_authority.authenticate("Bearer " + runtime.token))
        assert capabilities["supports"]["nodePreparation"] is False
    finally:
        runtime.stop()
