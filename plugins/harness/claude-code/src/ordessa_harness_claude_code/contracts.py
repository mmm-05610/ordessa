from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class ClaudeContinuationV1:
    contract_id: ClassVar[str] = "agent-box.claude-continuation@1"
    session_id: str
    project_key: str = ""
    schema_version: str = "claude-code-2"

    def __post_init__(self):
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("Claude continuation session_id is required")
        if not isinstance(self.project_key, str) or len(self.project_key) > 512:
            raise ValueError("invalid Claude continuation project key")
