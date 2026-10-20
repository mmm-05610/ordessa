"""Explicit installed sandbox factory selection owned by Environment composition.

The caller supplies the provider name. Selection loads only the first declared
match and checks its factory; it never invokes that factory or chooses defaults.
"""
from ordessa_environments.definitions.sandbox_port import (
    ENTRY_POINT_GROUP, SANDBOX_PORT_FACTORY, SandboxPortUnavailable,
)


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
