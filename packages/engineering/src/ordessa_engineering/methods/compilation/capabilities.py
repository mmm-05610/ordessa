"""Compile only explicitly required capability bindings."""
from ..definitions.models import LoadedMethod

def compile_capabilities(loaded: LoadedMethod) -> list[dict]:
    required_capabilities = sorted(
        ({key: item[key] for key in ("capability_id", "kind", "interface_version", "contract_digest")}
         for item in loaded.manifest["requires"]),
        key=lambda item: item["capability_id"],
    )
    return required_capabilities
