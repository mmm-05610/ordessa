"""Explicit Host ACP staging from installed public provider resource ports.

No checkout lookup, aggregate discovery, default catalog, or new execution owner.
The caller owns this private destination and supplies its captured selected catalog.
"""
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from ..harness_catalog import CapturedHarnessCatalog
from .selected_acp_resources import selected_acp_resources

@dataclass(frozen=True)
class AccessEntryBundle:
    root: Path
    entry: Path
    captured_catalog: CapturedHarnessCatalog
    schema_version: int
    required: tuple[str, ...]

def stage_access_entry(destination: Path, captured_catalog: CapturedHarnessCatalog) -> AccessEntryBundle:
    if type(captured_catalog) is not CapturedHarnessCatalog:
        raise TypeError("explicit CapturedHarnessCatalog required")
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    sources = []
    for name in ('composition/native_channels/launch_catalog.mjs', 'composition/native_channels/selected_launch_ports.mjs', 'composition/native_channels/launch_policy.mjs', 'composition/native_channels/access_entry.mjs', 'composition/native_channels/controlled-peers.mjs'):
        sources.append(("apps/server/src/ordessa_server/" + name, files("ordessa_server").joinpath(name)))
    for name in ('harness/transport/profile_vocabulary.mjs', 'harness/protocols/acp.mjs', 'harness/transport/vendor/harness_remote/bridge/src/acp-client.js', 'harness/transport/vendor/harness_remote/bridge/src/backward-line-scan.js', 'harness/transport/executable_lookup.mjs', 'harness/transport/launch_resolution.mjs', 'harness/transport/launch_descriptor.mjs', 'harness/transport/vendor/harness_remote/SOURCE.json', 'harness/transport/vendor/harness_remote/LICENSE', 'harness/transport/vendor/harness_remote/PATCHES.md', 'harness/providers/resolution/_deployment/native-artifact-policy.mjs'):
        sources.append(("packages/execution/agents/src/ordessa_execution_agents/" + name, files("ordessa_execution_agents").joinpath(name)))
    for logical_root, declared in selected_acp_resources():
        for name, source in declared:
            sources.append((logical_root + "/" + name, source))
    seen = set()
    for logical, source in sources:
        if logical in seen or Path(logical).is_absolute() or ".." in Path(logical).parts:
            raise ValueError("invalid explicit ACP resource mapping")
        seen.add(logical)
        target = destination / logical
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        target.chmod(0o600)
    # The stage is one ESM tree; this fixed marker has no package discovery/deps.
    (destination / "package.json").write_bytes(b'{"type":"module"}\n')
    entry = destination / "apps/server/src/ordessa_server/composition/native_channels/access_entry.mjs"
    return AccessEntryBundle(destination, entry, captured_catalog, 1, tuple(logical for logical, _ in sources))
