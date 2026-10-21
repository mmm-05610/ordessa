"""Pinned bindings for installed Harness providers (one rule, every consumer).

A provider binding names the exact definition the caller admits and the digest of
the implementation bytes it is about to run. Both the CLI's local composition and
the Server's default product derive that binding here, so "what an installed
provider is" cannot drift between the two entry points.

Loading the entry point is unavoidable: the digest is over the module file that
will actually run. A missing or unreadable file is a refusal, never a binding
without a digest.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import hashlib


class ProviderBindingError(RuntimeError):
    """An installed provider cannot be pinned to an exact definition and digest."""

    code = "HARNESS_PROVIDER_UNPINNABLE"


def pinned_binding(entry_point, *, environment_namespace: str) -> "dict[str, object]":
    """The closed binding a brand factory receives for one installed entry point.

    ``definition_ref`` is (namespace, provider id, distribution revision) and
    ``implementation_digest`` is the SHA-256 of the module file that will run.
    """
    from ordessa_agents.sdk import HarnessError

    if type(environment_namespace) is not str or not environment_namespace:
        raise ProviderBindingError("a Profile environment namespace is required")
    name = getattr(entry_point, "name", None)
    if type(name) is not str or not name:
        raise ProviderBindingError("installed provider entry point has no name")
    distribution_version = getattr(getattr(entry_point, "dist", None), "version", None) or "0"
    try:
        factory = entry_point.load()
    except Exception:
        raise ProviderBindingError("installed provider cannot be loaded: " + name) from None
    module_name = getattr(type(factory), "__module__", "")
    module = sys.modules.get(module_name)
    path = getattr(module, "__file__", None)
    if not path or not os.path.isfile(path):
        raise HarnessError("HARNESS_PROVIDER_UNAVAILABLE")
    digest = "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return {
        "definition_ref": {
            "environmentNamespace": environment_namespace,
            "definitionId": name,
            "revision": distribution_version,
        },
        "implementation_digest": digest,
    }


def installed_provider_names() -> "tuple[str, ...]":
    """Sorted names of the providers installed in this environment (admission is separate)."""
    from importlib.metadata import entry_points

    return tuple(sorted(point.name for point in entry_points(group="ordessa.harness_providers")))


__all__ = ["ProviderBindingError", "installed_provider_names", "pinned_binding"]
