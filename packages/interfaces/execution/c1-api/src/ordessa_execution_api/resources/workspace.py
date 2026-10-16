"""The materialized workspace contract consumed by execution adapters."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar


@dataclass(frozen=True)
class WorkspaceV1:
    contract_id: ClassVar[str] = "agent-box.workspace@1"

    path: PurePath
    source_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, PurePath) or not self.path.is_absolute():
            raise ValueError("workspace path must be absolute")
        if not isinstance(self.source_digest, str) or not self.source_digest.strip():
            raise ValueError("workspace source_digest is required")
