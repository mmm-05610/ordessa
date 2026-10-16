"""Own ACP resource input for explicit host staging; no effects or discovery."""
from pathlib import Path

def acp_resources():
    root = Path(__file__).resolve().parent
    return tuple((name, root / name) for name in ('acp/launch_dsh.mjs', 'acp/launch_dsh.json'))
