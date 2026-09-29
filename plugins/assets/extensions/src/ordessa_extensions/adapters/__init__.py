"""The `ordessa_extensions.adapters` package: C2-registered hooks
projection adapters (EXT-5)."""
from __future__ import annotations

from .contribution import (
    CONFIGURATION_POINT, POINT_API_VERSION, HooksConfigurationAdapter,
    hooks_adapters,
)

__all__ = ["CONFIGURATION_POINT", "POINT_API_VERSION",
           "HooksConfigurationAdapter", "hooks_adapters"]
