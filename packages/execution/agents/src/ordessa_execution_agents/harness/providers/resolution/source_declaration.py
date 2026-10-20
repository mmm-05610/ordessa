"""Materialize the digest of a Harness-owned source declaration."""
from pathlib import Path
from ordessa_infrastructure.filesystem.content_digest import content_digest
from ordessa_execution_agents.harness.definitions.command_projection import RuntimeSourceDeclaration

def declare_source(kind: str, source_path: object, guest_target: str, *, access: str = "ro",
                   provenance: str = "", authorized_scope: str = "execution") -> RuntimeSourceDeclaration:
    """Shared projector helper: declare one source with its content digest.

    Handles only generic paths, digests and declarations.  It knows nothing
    about any contract, provider, or guest path convention — the guest target
    is always the calling projector's decision.
    """
    return RuntimeSourceDeclaration(
        kind, str(Path(source_path)), guest_target, access,
        content_digest(source_path), provenance=provenance,
        authorized_scope=authorized_scope,
    )

