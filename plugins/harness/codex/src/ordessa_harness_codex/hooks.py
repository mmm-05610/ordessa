"""Bounded Codex lifecycle hook used by the interactive provider."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


_FIELDS = (
    "session_id",
    "transcript_path",
    "cwd",
    "hook_event_name",
    "model",
    "source",
)
_MAX_FIELD_LENGTH = 512


def record_session_start(target: Path, payload: object) -> None:
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "SessionStart":
        raise ValueError("expected a Codex SessionStart hook payload")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Codex SessionStart payload has no session_id")
    bounded = {
        key: (
            value[:_MAX_FIELD_LENGTH]
            if isinstance(value := payload.get(key), str)
            else None
        )
        for key in _FIELDS
    }
    bounded["observed_at"] = datetime.now(timezone.utc).isoformat()
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(bounded, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m ordessa_harness_codex.hooks OUTPUT", file=sys.stderr)
        return 2
    try:
        record_session_start(Path(args[0]), json.load(sys.stdin))
    except Exception as exc:
        print(f"agent-box Codex hook failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
