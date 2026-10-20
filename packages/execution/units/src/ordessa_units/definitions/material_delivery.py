"""Resolved workspace and prompt delivery values for an admitted execution.

The historical contract identifiers and local invariants are preserved. These
values do not resolve content, validate provider authority or grant execution.
"""
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


@dataclass(frozen=True)
class PromptFragmentV1:
    contract_id: ClassVar[str] = "agent-box.prompt-fragment@1"

    title: str
    content: str
    digest: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("title", self.title),
            ("content", self.content),
            ("digest", self.digest),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"prompt fragment {field_name} is required")


__all__ = ["WorkspaceV1", "PromptFragmentV1"]
