from dataclasses import dataclass
@dataclass(frozen=True)
class OpenCodeContinuationV1:
    contract_id = "agent-box.opencode-continuation@1"
    session_id: str

__all__ = ["OpenCodeExecutionProvider", "OpenCodeProfileAuthority", "OpenCodeProfileRef"]
__all__ = ["OpenCodeContinuationV1"]
