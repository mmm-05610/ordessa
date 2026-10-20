"""The default product has no managed capture/workspace authority ports."""

from ordessa_server.composition.configuration.product_selection import create_host_product_composition as create_composition


def test_default_product_does_not_select_managed_codex_input_or_fake_ready_ports():
    product = create_composition()
    assert product._agent_owner_inputs is None
    assert all(plugin.descriptor().id != "codex" for plugin in product.default_plugins())
