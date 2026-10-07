from .loader import load_builtin_registry
REGISTRY = load_builtin_registry()
DEFINITIONS = REGISTRY.all()
