from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar

@dataclass(frozen=True)
class HermesContinuationV1:
    """Explicitly a portable handoff; Hermes native state is not resumable P0."""
    contract_id: ClassVar[str] = "agent-box.hermes-continuation@1"
    transcript_ref: str
    context_digest: str
    def __post_init__(self):
        if not self.transcript_ref or not self.context_digest:
            raise ValueError("Hermes transcript handoff requires a ref and digest")
