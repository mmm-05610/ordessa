"""JS capability ceiling projection from the same explicitly captured registry."""
from ordessa_infrastructure.encoding.canonical_json import canonical_text
from ..harness_catalog import CapturedHarnessCatalog

def captured_capability_document(catalog: CapturedHarnessCatalog) -> dict:
    if type(catalog) is not CapturedHarnessCatalog:
        raise TypeError("explicit CapturedHarnessCatalog required")
    return {"schemaVersion": 1, "harnessTypes": {value.harness_type: sorted(value.capabilities) for value in catalog.registry.all()}}

def captured_capability_text(catalog: CapturedHarnessCatalog) -> str:
    return canonical_text(captured_capability_document(catalog))
