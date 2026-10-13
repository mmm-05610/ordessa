"""Own ACP resource input for explicit host staging; no effects or discovery."""
from pathlib import Path

def acp_resources():
    root = Path(__file__).resolve().parent
    return tuple((name, root / name) for name in ('acp/launch_claude.mjs', 'acp/launch_claude_code.mjs', 'acp/launch_claude.json', 'acp/launch_claude_code.json'))
