"""Process registrations and explicit installed sandbox provider discovery."""
from __future__ import annotations

from typing import Any
from ordessa_execution_api.environment.sandbox_port import (
    ENTRY_POINT_GROUP, SANDBOX_PORT_FACTORY, SANDBOX_PORT_MODULE_VARIABLE,
    SandboxPort, SandboxPortUnavailable,
)

_REGISTERED_FACTORIES: dict[str, Any] = {}


def register_sandbox_port_factory(name: str, factory: Any) -> None:
    """Register one port factory by provider name for this process."""
    if not isinstance(name, str) or not name.strip():
        raise SandboxPortUnavailable("SANDBOX_PROVIDER_UNRESOLVED", "empty provider name")
    _REGISTERED_FACTORIES[name.strip().lower().replace("-", "_")] = factory


def _load_factory(name: str):
    from ordessa_infrastructure.discovery import enumerate_entry_points, load_entry_point

    # Keep this consumer's declaration order and selection policy here.
    group = enumerate_entry_points(ENTRY_POINT_GROUP)
    wanted = name.strip().lower().replace("-", "_")
    matches = []
    for entry_point in group:
        entry_name = entry_point.name.lower().replace("-", "_")
        module_root = entry_point.value.split(":")[0].split(".")[0].lower().replace("-", "_")
        if entry_name == wanted or module_root == wanted:
            matches.append(entry_point)
    if not matches:
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED",
            f"no installed plugin entry point matches sandbox provider {name!r}",
        )
    module = load_entry_point(matches[0])
    factory = getattr(module, SANDBOX_PORT_FACTORY, None)
    if not callable(factory):
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED",
            f"plugin {name!r} exposes no {SANDBOX_PORT_FACTORY}",
        )
    return factory


def _factory_from_configured_module(provider: str):
    """The explicit module escape hatch, used only when the variable is set.

    The module name comes from the environment (the embedding runtime states
    which importable package serves the room); this layer never guesses a
    module name from a provider id.
    """
    import importlib
    import os

    module_name = os.environ.get(SANDBOX_PORT_MODULE_VARIABLE, "").strip()
    if not module_name:
        return None
    module = importlib.import_module(module_name)
    factory = getattr(module, SANDBOX_PORT_FACTORY, None)
    if not callable(factory):
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED",
            f"{SANDBOX_PORT_MODULE_VARIABLE} module {module_name!r} exposes no "
            f"{SANDBOX_PORT_FACTORY}",
        )
    declared = getattr(factory, "provider_ids", None)
    if declared is not None and provider.lower().replace("-", "_") not in {
        item.lower().replace("-", "_") for item in declared
    }:
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED",
            f"module {module_name!r} does not serve provider {provider!r}",
        )
    return factory


def resolve_sandbox_port(name: str) -> SandboxPort:
    """Resolve a provider name to its port, in declaration order.

    1. the process-local registry (an embedding process registered it);
    2. the installed plugin entry points (pip-installed deployments);
    3. the explicit ``AGENT_BOX_SANDBOX_MODULE`` module (PYTHONPATH runtimes).

    Every path is explicit; an unresolved name is a typed refusal rather than a
    silent fallback to some other sandbox.
    """
    if not isinstance(name, str) or not name.strip():
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED", "sandbox provider name is empty",
        )
    normalized = name.strip().lower().replace("-", "_")
    factory = _REGISTERED_FACTORIES.get(normalized)
    if factory is None:
        try:
            factory = _load_factory(name)
        except SandboxPortUnavailable:
            factory = _factory_from_configured_module(name)
        except ModuleNotFoundError:
            factory = _factory_from_configured_module(name)
        if factory is None:
            raise SandboxPortUnavailable(
                "SANDBOX_PROVIDER_UNRESOLVED",
                f"no registration, installed entry point or "
                f"{SANDBOX_PORT_MODULE_VARIABLE} module serves sandbox provider {name!r}",
            )
    return factory()


__all__ = ["register_sandbox_port_factory", "resolve_sandbox_port"]
