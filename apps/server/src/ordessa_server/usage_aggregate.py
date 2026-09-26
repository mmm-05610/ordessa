"""Compatibility alias — the implementation moved to
`ordessa_server_compat.usage_aggregate` (core-cleanup stage 3).
Single-source re-export; no second implementation."""
from ordessa_server_compat.usage_aggregate import (  # noqa: F401
    UsageAggregator,
)
