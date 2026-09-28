from __future__ import annotations
import hashlib
import importlib.util
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from .schema import HarnessDefinition, definition_from_dict

@dataclass(frozen=True)
class RegistryDiagnostics:
    digest: str
    errors: tuple[str, ...] = ()

class HarnessRegistry:
    def __init__(self, definitions, digest, diagnostics=(), launch_descriptors=None):
        self._definitions = {d.harness_type: d for d in definitions}
        self.launch_descriptors = launch_descriptors
        self.digest = digest
        self.diagnostics = RegistryDiagnostics(digest, tuple(diagnostics))
    def get(self, harness_type): return self._definitions[harness_type]
    def all(self): return tuple(self._definitions[k] for k in sorted(self._definitions))
    def __len__(self): return len(self._definitions)
    def registry_identity_version_matches(self, harness_type: str, version: str | None) -> bool | None:
        """Compare a canonical registry identity version, never runtime support."""
        if self.launch_descriptors is None:
            raise RuntimeError("launch descriptors not loaded")
        descriptor = self.launch_descriptors.get(harness_type)
        if descriptor is None:
            for canonical in self.launch_descriptors.values():
                if any(alias["id"] == harness_type for alias in canonical["aliases"]):
                    # Alias launch routes may use a different upstream adapter
                    # pin; the canonical registry version does not verify it.
                    return None
        if descriptor is None:
            return False
        if version is None:
            return None
        return version == descriptor["registry_version"]

def load_launch_descriptors(text: str) -> dict[str, dict]:
    """Validate the shared canonical/alias launch manifest, without guessing versions."""
    raw = json.loads(text)
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "harnesses"} or type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("invalid launch descriptor schema")
    entries = raw["harnesses"]
    if not isinstance(entries, list) or not entries or len(entries) > 16:
        raise ValueError("invalid launch descriptor entries")
    canonical = {}; names = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"id", "registry_version", "launch", "aliases"}:
            raise ValueError("invalid launch descriptor fields")
        identity, version = entry["id"], entry["registry_version"]
        if not isinstance(identity, str) or not identity or not isinstance(version, str) or not version:
            raise ValueError("invalid launch descriptor identity/version")
        if identity in names:
            raise ValueError("duplicate canonical or alias launch identity")
        names.add(identity); canonical[identity] = entry
        _validate_launch_route(entry["launch"], owner_id=identity)
        if not isinstance(entry["aliases"], list):
            raise ValueError("invalid launch aliases")
        for alias in entry["aliases"]:
            if not isinstance(alias, dict) or set(alias) != {"id", "launch"} or not isinstance(alias["id"], str) or not alias["id"]:
                raise ValueError("invalid launch alias")
            if alias["id"] in names:
                raise ValueError("alias is a second brand or collides with another identity")
            names.add(alias["id"])
            _validate_launch_route(alias["launch"], owner_id=alias["id"], required=True)
    return canonical


def _validate_launch_route(route, *, owner_id: str, required=False):
    if route is None and not required:
        return
    if not isinstance(route, dict) or set(route) != {"source", "profile_id"}:
        raise ValueError("invalid launch route")
    if route["source"] not in {"upstream", "agentbox"} or not isinstance(route["profile_id"], str) or not route["profile_id"]:
        raise ValueError("invalid launch profile source/id")
    if route["profile_id"] != owner_id:
        raise ValueError("launch profile identity mismatch")


def load_registry(text: str, launch_descriptor_text: str | None = None) -> HarnessRegistry:
    raw = tomllib.loads(text)
    if raw.get("schema_version") != 1: raise ValueError("unsupported registry schema_version")
    entries = raw.get("harness", [])
    if not isinstance(entries, list) or len(entries) > 16: raise ValueError("invalid harness registry")
    defs = []; seen = set(); drivers = set()
    for entry in entries:
        definition = definition_from_dict(entry)
        if definition.harness_type in seen: raise ValueError("duplicate harness_type")
        if definition.driver in drivers: raise ValueError("duplicate driver")
        seen.add(definition.harness_type); drivers.add(definition.driver); defs.append(definition)
    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    descriptors = None
    if launch_descriptor_text is not None:
        descriptors = load_launch_descriptors(launch_descriptor_text)
        if set(descriptors) != seen:
            raise ValueError("launch descriptor canonical IDs drift from TOML registry")
        for definition in defs:
            if descriptors[definition.harness_type]["registry_version"] != definition.identity.version:
                raise ValueError("launch descriptor registry version drift")
    return HarnessRegistry(tuple(defs), digest, launch_descriptors=descriptors)

def _builtin_registry_resource() -> Path:
    """Read the one canonical declaration without re-entering plugin imports."""
    spec = importlib.util.find_spec("ordessa_harness")
    locations = list(getattr(spec, "submodule_search_locations", None) or ())
    if not locations:
        raise RuntimeError("HARNESS_REGISTRY_RESOURCE_NOT_FOUND")
    return Path(locations[0]) / "harnesses.toml"


def load_builtin_registry() -> HarnessRegistry:
    resource = _builtin_registry_resource()
    text = resource.read_text(encoding="utf-8")
    descriptor_text = resource.with_name("launch-descriptors.json").read_text(encoding="utf-8")
    return load_registry(text, descriptor_text)
