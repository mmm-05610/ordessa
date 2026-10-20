from types import SimpleNamespace
import pytest
from ordessa_model_provider.harness_declarations import ModelConfigurationCatalog


def test_declarations_are_limited_to_configured_brands_not_runtime_evidence():
    from ordessa_harness_pi.configuration import c2
    catalog = ModelConfigurationCatalog([c2.descriptor()], protocol_ports={'pi': c2.declared_protocols},
        model_control_ports={'pi': c2.declared_model_control})
    assert catalog.registered() == ("pi",)
    assert catalog.get("pi").wire_protocols == {}
    assert catalog.wire_protocols("pi")
    assert set(catalog.wire_protocols("pi").values()) == {"declared"}
    assert catalog.wire_protocols("codex") == {}
    assert catalog.wire_protocols("unknown") == {}
    with pytest.raises(ValueError): ModelConfigurationCatalog(None, protocol_ports={}, model_control_ports={})
