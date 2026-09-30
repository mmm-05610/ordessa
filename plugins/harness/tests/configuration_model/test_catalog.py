from types import SimpleNamespace
import pytest
from ordessa_harness.configuration.model.catalog import ModelConfigurationCatalog


def test_declarations_are_limited_to_configured_brands_not_runtime_evidence():
    class Directory:
        def __contains__(self, name): return name in {"pi"}
        def registered(self): return ("pi",)
        def get(self, name): return SimpleNamespace(id=name, wire_protocols={})
    catalog = ModelConfigurationCatalog(Directory())
    assert catalog.registered() == ("pi",)
    assert catalog.get("pi").wire_protocols == {}
    assert catalog.wire_protocols("pi")
    assert set(catalog.wire_protocols("pi").values()) == {"declared"}
    assert catalog.wire_protocols("codex") == {}
    assert catalog.wire_protocols("unknown") == {}
    with pytest.raises(ValueError): ModelConfigurationCatalog(None)
