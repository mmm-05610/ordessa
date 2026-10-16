"""Document/schema resource compilation; no external retrieval."""
from copy import deepcopy
from typing import Any
from ..definitions.models import LoadedMethod
from ..definitions.defaults import DOCUMENT_VALIDATION_TARGET_DEFAULT_V1
from .workflow import _resource_ref

def compile_documents(loaded: LoadedMethod) -> list[dict[str, Any]]:
    resources = loaded.resources
    documents: list[dict[str, Any]] = []
    specs = loaded.manifest.get("documents", [])
    for spec in specs:
        schema_ref = spec["schema"]["resource"]
        schema = resources[schema_ref]
        documents.append({
            "document_type": spec["document_type"],
            "schema_resource": _resource_ref(schema),
            "value_schema": deepcopy(schema.value),
            "template_resource": (_resource_ref(resources[spec["template"]["resource"]]) if "template" in spec else None),
            "validation_target": spec.get("validation_target", DOCUMENT_VALIDATION_TARGET_DEFAULT_V1),
        })

    return documents

def compile_schema_resources(loaded: LoadedMethod) -> list[dict[str, Any]]:
    return [{"schema_resource": _resource_ref(resource), "value_schema": deepcopy(resource.value)}
            for _, resource in sorted(loaded.resources.items())
            if resource.declaration["kind"] == "document_schema"]
