"""Workflow first-use ordering and exact source reference binding."""
from copy import deepcopy
from typing import Any
from ..definitions.models import LoadedMethod, SourceResourceView

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
        if set(value) == {"resource", "criterion_id"}:
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
    workflow = loaded.resources[loaded.manifest["entry"]["resource"]].value

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


