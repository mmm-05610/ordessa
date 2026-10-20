"""C01: missing native/profile authorities remain honestly unavailable."""
from __future__ import annotations

import importlib.util

from ordessa_server.composition.runtime import build_runtime
from ordessa_server_product.turn_application import ProductTurnApplication


def test_profile_overlay_sink_and_native_configuration_factory_are_retired():
    assert importlib.util.find_spec("ordessa_server_product.native_configuration") is None
    assert not hasattr(__import__("ordessa_server_product.turn_application",
                                 fromlist=["ProfileTurnIntentSink"]),
                       "ProfileTurnIntentSink")


def test_default_public_capabilities_and_unbound_turn_application_fail_closed(tmp_path):
    runtime = build_runtime(tmp_path / "data")
    try:
        runtime.start()
        assert runtime.plugin_host.provided_port("native.configuration") is None
        assert not any(plugin_id in runtime.plugin_host.active_ids()
                       for plugin_id in ("ordessa.profile", "ordessa.agent"))

        capabilities = runtime.wire.dispatch("agents.capabilities", {}, caller=runtime.wire.identity_authority.authenticate("Bearer " + runtime.token))
        assert capabilities["contractVersion"] == "agent-assembly/3"
        assert capabilities["supports"]["profileCatalog"] is False
        assert capabilities["supports"]["nodePreparation"] is False
        assert capabilities["supports"]["nodeLifecycle"] is False
        assert capabilities["supports"]["configurationManagement"] is False

        adapter = ProductTurnApplication(
            authority_of=lambda: None,
            catalog_of=lambda: (_ for _ in ()).throw(AssertionError("catalog must not be read")),
        )
        result = adapter.submit(
            {"serverInstanceId": "srv", "harnessId": "pi", "acpSessionId": "session"},
            operation_key="c01-no-native-authority",
            expected_sequence=None,
            intent={"choice": {"providerConfigId": "provider", "modelId": "model"}},
        )
        assert result.outcome == "refused"
        assert result.reason == "ADAPTER_MISSING"
    finally:
        runtime.stop()
