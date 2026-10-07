"""Codex-owned native thread identity for a continuation input."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class CodexContinuationV1:
    contract_id: ClassVar[str] = "agent-box.codex-continuation@1"

    thread_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.thread_id, str) or not self.thread_id.strip():
            raise ValueError("Codex continuation thread_id is required")
