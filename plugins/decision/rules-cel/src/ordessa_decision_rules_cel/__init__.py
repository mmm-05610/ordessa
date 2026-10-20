"""CEL rules plugin for `ordessa.decision.rules` (requires `cel-python`)."""
from .engine import CelEngine, build

__all__ = ["CelEngine", "build"]
