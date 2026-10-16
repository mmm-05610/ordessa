"""Explicit role-to-source skill bindings."""
from ..definitions.models import LoadedMethod
from .workflow import _resource_ref

def compile_skills(loaded: LoadedMethod) -> list[dict]:
    resources = loaded.resources
    skill_resources = [
        {"role": role, "resource_ref": _resource_ref(resources[spec["resource"]])}
        for role, spec in sorted(loaded.manifest.get("skills", {}).items())
    ]
    return skill_resources
