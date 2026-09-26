"""A bounded piece of text that an ExecutionProvider may render as prompt."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


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
