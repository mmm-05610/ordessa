"""Read-only historical continuation value; no resolver or execution authority."""
from dataclasses import dataclass

@dataclass(frozen=True)
class OpenCodeContinuationV1:
    contract_id = "agent-box.opencode-continuation@1"
    session_id: str
