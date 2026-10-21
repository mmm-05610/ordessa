"""Explicit selected declaration capture; framing contains no brand facts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ordessa_agents.harness.providers.declarations import RegistrationDeclarations
from ordessa_agents.harness.providers.declarations import HarnessRegistry, load_registry

_REGISTRY_PREFIX = b'schema_version = 1\n\n'
_LAUNCH_PREFIX = b'{\n  "schema_version": 1,\n  "harnesses": [\n'
_LAUNCH_SUFFIX = b'\n  ]\n}\n'


@dataclass(frozen=True)
class CapturedHarnessCatalog:
    registry: HarnessRegistry
    registry_bytes: bytes
    launch_descriptor_bytes: bytes


def capture_harness_catalog(
    declarations: Iterable[RegistrationDeclarations], *,
    launch_declarations: Iterable[RegistrationDeclarations],
) -> CapturedHarnessCatalog:
    """Capture both explicit orders, validate once, then share this same registry.

    Historical TOML and launch documents have independent ordering. The caller
    supplies selected declarations for each; no brand defaults or reserialization.
    The existing parser checks matching canonical identities and versions.
    """
    registry_fragments = tuple(declarations)
    launch_fragments = tuple(launch_declarations)
    if any(not isinstance(value, RegistrationDeclarations)
           for value in (*registry_fragments, *launch_fragments)):
        raise TypeError("expected RegistrationDeclarations")
    registry_bytes = _REGISTRY_PREFIX + b"".join(value.registry_toml for value in registry_fragments)
    launch_bytes = (_LAUNCH_PREFIX + b",\n".join(value.launch_json for value in launch_fragments)
                    + _LAUNCH_SUFFIX)
    registry = load_registry(registry_bytes.decode("utf-8"), launch_bytes.decode("utf-8"))
    return CapturedHarnessCatalog(registry, registry_bytes, launch_bytes)
