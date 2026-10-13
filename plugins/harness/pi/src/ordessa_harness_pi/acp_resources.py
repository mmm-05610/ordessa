"""Own ACP resource input for explicit host staging; no effects or discovery."""
from pathlib import Path

def acp_resources():
    root = Path(__file__).resolve().parent
    return tuple((name, root / name) for name in ('acp/vendor/pi-session-history.js', 'acp/vendor/backward-line-scan.js', 'acp/vendor/SOURCE.json', 'acp/vendor/LICENSE', 'acp/vendor/PATCHES.md', '_registration_declarations/pi-runtime-artifact.json'))
