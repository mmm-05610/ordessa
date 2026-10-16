"""Read-only native Pi session listing for continuation selection."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from .profile import PiPluginConfig

@dataclass(frozen=True)
class PiSessionInfo:
    session_id: str
    session_file: Path
    cwd: str | None = None
    model: str | None = None
    provider: str | None = None
    message_count: int = 0

def read_session_info(path: Path) -> PiSessionInfo | None:
    try:
        entries=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[:200000] if line.strip()]
    except (OSError, ValueError): return None
    header=next((x for x in entries if x.get("type")=="session" and isinstance(x.get("id"),str)),None)
    if not header: return None
    messages=[x.get("message",{}) for x in entries if x.get("type")=="message" and isinstance(x.get("message"),dict)]
    assistant=next((x for x in messages if x.get("role")=="assistant"),{})
    return PiSessionInfo(header["id"],path,header.get("cwd"),assistant.get("model"),assistant.get("provider"),len(messages))

class PiSessionScanner:
    def __init__(self, config: PiPluginConfig): self.config=config
    def locate(self, session_id: str):
        root=self.config.resolved_session_root
        matches=[p for p in root.rglob(f"*_{session_id}.jsonl") if p.is_file()] if root.is_dir() else []
        return max(matches,key=lambda p:p.stat().st_mtime) if matches else None
    def list(self):
        root=self.config.resolved_session_root
        return tuple(info for p in sorted(root.rglob("*.jsonl")) if (info:=read_session_info(p))) if root.is_dir() else ()
