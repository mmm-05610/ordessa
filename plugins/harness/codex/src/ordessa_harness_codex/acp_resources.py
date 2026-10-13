"""Own ACP resource input for explicit host staging; no effects or discovery."""
from pathlib import Path

def acp_resources():
    root = Path(__file__).resolve().parent
    return tuple((name, root / name) for name in ('acp/launch_codex.mjs', 'acp/vendor/codex-session-history.js', 'acp/vendor/SOURCE.json', 'acp/vendor/LICENSE', 'acp/vendor/PATCHES.md', 'acp/launch_codex.json'))
