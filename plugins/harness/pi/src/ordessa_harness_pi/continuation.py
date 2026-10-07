from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
@dataclass(frozen=True)
class PiContinuationV1:
    contract_id = "agent-box-pi.continuation@1"
    session_id: str
    session_file: str | None = None
    provider: str = "deepseek"
    model: str = ""
    session_file_digest: str = ""
    def __post_init__(self):
        if not _ID.fullmatch(self.session_id): raise ValueError("invalid Pi session id")
        if self.provider != "deepseek": raise ValueError("Pi continuation provider must be deepseek")
        if self.session_file and not Path(self.session_file).is_absolute(): raise ValueError("Pi session file must be absolute")
        if self.session_file_digest and not self.session_file_digest.startswith("sha256:"): raise ValueError("invalid session digest")
