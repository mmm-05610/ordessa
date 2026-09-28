"""The workspace domain's machine connectors (T014-S2b).

These builders used to live in the host's composition root
(`ordessa_server.bootstrap.runtime`). FR-006 says the host must not know
which environments a deployment can reach, so the construction — and the
machine-local bindings that decide it — now live with the domain whose
`kind ∈ {local, wsl, ssh}` decision gives a connector meaning, and whose
`WorkspaceService` is the connector's primary consumer. The compatibility
core only *reads* the resulting placement, which is why the builders do
not live there.

The env-var names are upstream identifiers from the agent-box era and are
byte-identical to the host's former reads (AGENTS rule 5): a deployment
that pinned the AGENT_BOX_* worker bindings keeps working unchanged.
A binding left unset simply means that placement is not composed here —
which `resolve_placement` and the workspace service then refuse out loud.

The module-level function names (`_builtin_connector`,
`_builtin_ssh_connector`, `_entry_point_factory`) are the monkeypatch
surface the placement tests use; call sites resolve them as module
attributes so a patch here takes effect before activation.
"""
from __future__ import annotations

import os
from typing import Any


def _builtin_connector(server_instance_id: str) -> Any | None:
    manifest = os.environ.get("AGENT_BOX_WSL_WORKER_MANIFEST")
    worker = os.environ.get("AGENT_BOX_WSL_WORKER_LINUX_PATH")
    if os.name != "nt" or not manifest or not worker:
        return None
    # A host connector is resolved by name here, exactly as the sandbox
    # provider is: the installed plugin entry point first, the importable
    # package as the PYTHONPATH-runtime fallback. Bindings left unset compose
    # no connector, which `resolve_placement` then refuses out loud.
    bindings = {
        "manifest_path": manifest, "linux_worker_path": worker,
        "server_instance_id": server_instance_id,
    }
    factory = _entry_point_factory("runtime-wsl")
    if factory is not None:
        try:
            return factory(**bindings)
        except TypeError:
            pass
    try:
        from agent_box_runtime_wsl import WslConnector
    except ImportError:
        return None
    return WslConnector(**bindings)


def _entry_point_factory(name: str):
    """The callable a plugin entry point registers under ``name``, if any."""
    from importlib import metadata

    from pacthold.extensions.loader import ENTRY_POINT_GROUP

    discovered = metadata.entry_points()
    group = (
        discovered.select(group=ENTRY_POINT_GROUP)
        if hasattr(discovered, "select") else discovered.get(ENTRY_POINT_GROUP, ())
    )
    wanted = name.strip().lower().replace("-", "_")
    for entry_point in group:
        if entry_point.name.lower().replace("-", "_") == wanted:
            return entry_point.load()
    return None


def _builtin_ssh_connector(server_instance_id: str):
    """Compose the SSH connector from process bindings, the way WSL's is.

    Like the WSL connector's bindings, these name machine-local facts the
    deployment document must not carry: which manifest pins the Worker, where
    the Worker already lives on the remote host, and the locator of the identity
    that may reach it. A binding left unset simply means that placement is not
    composed here - which `resolve_placement` then says out loud.
    """
    manifest = os.environ.get("AGENT_BOX_SSH_WORKER_MANIFEST")
    worker = os.environ.get("AGENT_BOX_SSH_WORKER_REMOTE_PATH")
    identity = os.environ.get("AGENT_BOX_SSH_IDENTITY_FILE")
    if not manifest or not worker or not identity:
        return None
    from ordessa_server.connectors import SshConnector

    port = os.environ.get("AGENT_BOX_SSH_PORT")
    return SshConnector(
        manifest_path=manifest, remote_worker_path=worker,
        identity_file=identity, server_instance_id=server_instance_id,
        port=int(port) if port else 22,
    )
