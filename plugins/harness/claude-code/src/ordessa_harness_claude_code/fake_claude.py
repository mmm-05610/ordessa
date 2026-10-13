"""Offline fake executable used by the plugin's native rehearsal only."""
import json, os
from pathlib import Path

def main():
    workspace=Path.cwd(); execution=os.environ.get("AGENT_BOX_EXECUTION_ID", "offline")
    (workspace / "claude-fake-mutation.txt").write_text(execution + "\n", encoding="utf-8")
    (workspace / "claude-session.json").write_text(json.dumps({"session_id": execution, "project_key": str(workspace)}), encoding="utf-8")
    print("offline-fake-claude", flush=True)
    return 0

if __name__ == "__main__": raise SystemExit(main())
