"""Own ACP resource input for explicit host staging; no effects or discovery."""
from pathlib import Path

def acp_resources():
    root = Path(__file__).resolve().parent
    return tuple((name, root / name) for name in ('acp/launch_omp.mjs', 'acp/vendor/omp-session-history.js', 'acp/vendor/omp-extension-action-state.js', 'acp/vendor/extension-actions.js', 'acp/profile_declarations.mjs', 'acp/vendor/opencode-host.js', 'acp/opencode_native.mjs', 'acp/vendor/SOURCE.json', 'acp/vendor/LICENSE', 'acp/vendor/PATCHES.md', 'acp/native_host.mjs', 'acp/launch_omp.json'))
