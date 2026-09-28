"""Opaque identifiers and timestamps, isomorphic to the legacy server shapes.

The formats are load-bearing for data compatibility (AGENTS.md rule 5): the
migrated rows keep their ``profile_<32hex>`` ids, so the generator must stay
byte-compatible with the legacy ``opaque_id``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def opaque_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"
