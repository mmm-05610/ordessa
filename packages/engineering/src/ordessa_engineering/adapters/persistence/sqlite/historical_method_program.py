"""Read-only reconstruction of published program/1; never a new compile path."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ....methods.definitions.errors import MethodError, MethodFailure
from ....methods.definitions.models import LoadedMethod, SourceResourceView
from ....methods.definitions.models.identity import method_digest


def _resource_ref(resource: SourceResourceView) -> dict[str, str]:
    return {
        "resource_id": resource.declaration["id"],
        "sha256": resource.captured.digest,
        "kind": resource.declaration["kind"],
    }


def _bind_refs(value: Any, resources: dict[str, SourceResourceView]) -> Any:
    if isinstance(value, list):
        return [_bind_refs(child, resources) for child in value]
    if isinstance(value, dict):
        if set(value) == {"resource"}:
            resource_id = value["resource"]
            return _resource_ref(resources[resource_id])
        if "resource" in value:
            resource_id = value["resource"]
            rest = {key: child for key, child in value.items() if key != "resource"}
            return {"resource_ref": _resource_ref(resources[resource_id]), **{
                key: _bind_refs(child, resources) for key, child in rest.items()
            }}
        return {key: _bind_refs(child, resources) for key, child in value.items()}
    return deepcopy(value)


def _first_use_order(loaded: LoadedMethod, kind: str) -> list[str]:
    """Order resources by workflow first use, then by stable resource ID."""
    ids = {key for key, item in loaded.resources.items() if item.declaration.get("kind") == kind}
    found: list[str] = []
    workflow = next((item.value for item in loaded.resources.values()
                     if item.declaration.get("kind") == "workflow" and isinstance(item.value, dict)), {})

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            resource_id = value.get("resource", value.get("resource_id"))
            if isinstance(resource_id, str) and resource_id in ids and resource_id not in found:
                found.append(resource_id)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(workflow)
    found.extend(sorted(ids - set(found)))
    return found


def _decision_order(loaded: LoadedMethod) -> list[str]:
    ids = [key for key, item in loaded.resources.items() if item.declaration.get("kind") == "question_set"]
    # Question-set ordering is semantic and stable: the input contract defines
    # the consumer-facing grouping; ID breaks ties. It does not depend on a host
    # registry's unrelated catalog ordering.
    return sorted(ids, key=lambda key: (
        str((loaded.resources[key].value or {}).get("input_contract", "")), key
    ))


def reconstruct_historical_program_v1(loaded: LoadedMethod, compiler_version: str) -> dict[str, Any]:
    resources = loaded.resources
    workflow_resources = [item for item in resources.values() if item.declaration.get("kind") == "workflow"]
    if len(workflow_resources) != 1 or not isinstance(workflow_resources[0].value, dict):
        raise MethodFailure(MethodError("WORKFLOW_RESOURCE_INVALID", "exactly one parsed workflow resource is required"))

    documents: list[dict[str, Any]] = []
    specs = loaded.manifest.get("documents", [])
    for spec in specs:
        schema_ref = spec["schema"]["resource"]
        schema = resources[schema_ref]
        documents.append({
            "document_type": spec["document_type"],
            "schema_resource": _resource_ref(schema),
            "value_schema": deepcopy(schema.value),
        })

    standards = [
        _bind_refs(resources[resource_id].value, resources)
        for resource_id in _first_use_order(loaded, "standard")
    ]
    decision_templates = [
        _bind_refs(resources[resource_id].value, resources)
        for resource_id in _decision_order(loaded)
    ]
    skill_ids: list[str] = []
    skills = loaded.manifest.get("skills", {})
    if isinstance(skills, dict):
        for skill in skills.values():
            resource_id = skill.get("resource") if isinstance(skill, dict) else None
            if isinstance(resource_id, str) and resource_id in resources and resource_id not in skill_ids:
                skill_ids.append(resource_id)
    skill_ids.extend(sorted({key for key, item in resources.items() if item.declaration.get("kind") == "skill"} - set(skill_ids)))
    skill_resources = [_resource_ref(resources[resource_id]) for resource_id in skill_ids]
    required_capabilities = sorted(
        ({key: item[key] for key in ("capability_id", "kind", "interface_version", "contract_digest")}
         for item in loaded.manifest["requires"]),
        key=lambda item: item["capability_id"],
    )
    # A validated catalog may contain unrelated host capabilities. Only method
    # requirements become part of this immutable program.
    return {
        "schema_version": 1,
        "compiler_version": compiler_version,
        "workflow": _bind_refs(workflow_resources[0].value, resources),
        "documents": documents,
        "standards": standards,
        "decision_templates": decision_templates,
        "skill_resources": skill_resources,
        "capability_bindings": required_capabilities,
    }

