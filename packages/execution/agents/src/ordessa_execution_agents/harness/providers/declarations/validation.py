from .loader import HarnessRegistry


def validate_registry(registry: HarnessRegistry):
    """Return diagnostics for the caller's explicitly captured registry."""
    if not isinstance(registry, HarnessRegistry):
        raise TypeError("expected HarnessRegistry")
    return registry.diagnostics
