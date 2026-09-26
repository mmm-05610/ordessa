"""Compatibility alias — the implementation moved to
`ordessa_server_compat.persistence` (core-cleanup stage 3).
Single-source re-export; no second implementation."""
from ordessa_server_compat.persistence import (  # noqa: F401
    ProductRepositoryView,
)
