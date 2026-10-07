from .loader import HarnessRegistry, load_registry, load_builtin_registry
def validate_registry(value=None):
    registry = load_builtin_registry() if value is None else (load_registry(value) if isinstance(value, str) else value)
    if not isinstance(registry, HarnessRegistry): raise TypeError("expected HarnessRegistry")
    return registry.diagnostics
