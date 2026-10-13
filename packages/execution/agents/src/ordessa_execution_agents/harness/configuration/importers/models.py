"""Read-only external configuration import value objects."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass(frozen=True)
class ImportCandidate:
    source_type: str
    source_id: str
    name: str
    metadata: dict[str, Any]
    path: str

@dataclass(frozen=True)
class ImportPreview:
    source_type: str
    source_id: str
    source_profile_name: str
    source_digest: str
    fields_to_import: tuple[str, ...]
    fields_ignored: tuple[str, ...]
    fields_rejected: tuple[str, ...]
    capability_refs: tuple[dict[str, Any], ...]
    credential_locator: dict[str, Any] | None
    profile: dict[str, Any]
    warnings: tuple[str, ...]
    def public(self) -> dict[str, Any]:
        return asdict(self)
