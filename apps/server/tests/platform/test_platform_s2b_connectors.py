"""T014-S2b: the host stopped building connectors; workspace owns them.

Before this slice the composition root in
`ordessa_server.bootstrap.runtime` read the six AGENT_BOX_* machine
bindings, constructed the WSL/SSH connectors
itself, and published them as the `connectors` / `workspace.*_connector`
host ports — the host naming a business placement it does not own
(FR-006). After the move:

1. `build_runtime` has no `connector` / `ssh_connector` parameter and its
   source reads no connector binding — the builders live in
   `ordessa_workspace.connectors` with the env-var NAMES byte-identical
   (upstream identifiers, AGENTS rule 5), and the workspace plugin
   provides the connector ports through `provided_ports`
   (`plugin_host.provided_port(...)` is the host-side read path);
2. a bare composition composes NO connector even while every binding is
   set — the bindings are read by a plugin the composition does not
   contain;
3. the two error-family rows whose producer the workspace now composes
   (`SSH_TARGET_INVALID` / `SSH_IDENTITY_INVALID`) answer their frozen
   family ONLY in a composition that contains the workspace plugin, and
   fall through to `UNAVAILABLE` without it; the 67-row composed golden
   is unchanged (pinned by `test_platform_wire_error_families`).

Each gate fails if the move is undone in its own way, not as one
aggregate check.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server.bootstrap import runtime as runtime_module
from ordessa_workspace.error_families import WORKSPACE_ERROR_FAMILIES
from ordessa_workspace.plugin import WorkspaceServerPlugin

TREE = Path(__file__).resolve().parents[4]
RUNTIME_SOURCE = TREE / "apps" / "server" / "src" / "ordessa_server" / "bootstrap" / "runtime.py"
WORKSPACE_CONNECTORS = (TREE / "plugins" / "workspace" / "src"
                        / "ordessa_workspace" / "connectors.py")

#: The six machine bindings, byte-identical to what the host read before
#: S2b (upstream identifiers — this literal IS the compatibility surface).
CONNECTOR_BINDINGS = (
    "AGENT_BOX_WSL_WORKER_MANIFEST",
    "AGENT_BOX_WSL_WORKER_LINUX_PATH",
    "AGENT_BOX_SSH_WORKER_MANIFEST",
    "AGENT_BOX_SSH_WORKER_REMOTE_PATH",
    "AGENT_BOX_SSH_IDENTITY_FILE",
    "AGENT_BOX_SSH_PORT",
)


def test_build_runtime_no_longer_accepts_a_connector(tmp_path):
    """The parameter half of the move: the signature names no connector."""
    params = inspect.signature(runtime_module.build_runtime).parameters
    assert "connector" not in params
    assert "ssh_connector" not in params


def test_the_host_source_reads_no_connector_binding_and_builds_no_connector():
    """The source half: the env reads and the construction left the host."""
    source = RUNTIME_SOURCE.read_text(encoding="utf-8")
    for binding in CONNECTOR_BINDINGS:
        assert binding not in source, f"{binding} is still read by the host"
    assert "SshConnector" not in source
    assert "_builtin_ssh_connector(" not in source
    assert "\"connectors\"" not in source and "'connectors'" not in source


def test_the_workspace_plugin_owns_the_builders_with_the_same_names():
    """The builders moved, they did not vanish: same module-level names,
    same six bindings, each spelled byte-identically exactly once."""
    source = WORKSPACE_CONNECTORS.read_text(encoding="utf-8")
    for binding in CONNECTOR_BINDINGS:
        assert source.count(binding) == 1, binding
    assert "_builtin_connector" in source
    assert "_builtin_ssh_connector" in source
    assert "_entry_point_factory" in source


def test_a_bare_composition_composes_no_connector_even_with_bindings_set(
        tmp_path, monkeypatch):
    """The counterexample that fails on the OLD host: every binding set to
    manifest-reachable values used to make `build_runtime` itself reach for
    the connector classes; a plugin-less host now composes nothing at all."""
    for name in CONNECTOR_BINDINGS:
        monkeypatch.setenv(name, str(tmp_path / "no-such-manifest.json"))
    runtime = build_runtime(tmp_path / "data", server_plugins=())
    try:
        assert runtime.plugin_host.active_ids() == ()
        assert runtime.plugin_host.provided_port("workspace.wsl_connector") is None
        assert runtime.plugin_host.provided_port("workspace.ssh_connector") is None
        assert runtime.plugin_host.provided_port("connectors") is None
        assert "connectors" not in runtime.plugin_host.host_ports
        assert "workspace.wsl_connector" not in runtime.plugin_host.host_ports
        assert "workspace.ssh_connector" not in runtime.plugin_host.host_ports
        # The host still hands out the one fact the builders need, without
        # building anything with it.
        assert runtime.plugin_host.host_ports["server.instance_id"] == runtime.owner.instance_id
    finally:
        runtime.stop()


def test_the_workspace_plugin_provides_the_connector_ports(tmp_path):
    """Explicit connectors arrive as the plugin's own provided ports —
    `plugin_host.provided_port(...)` is the read path for consumers."""
    wsl = object()
    ssh = object()
    runtime = build_runtime(
        tmp_path / "data",
        server_plugins=(WorkspaceServerPlugin(connector=wsl, ssh_connector=ssh),),
    )
    try:
        assert runtime.plugin_host.provided_port("workspace.wsl_connector") is wsl
        assert runtime.plugin_host.provided_port("workspace.ssh_connector") is ssh
        assert runtime.plugin_host.provided_port("connectors") == {"wsl": wsl, "ssh": ssh}
        # The service was built over the injected connectors, not env-composed
        # ones (on this Linux host the env-composed pair is (None, None)).
        service = runtime.plugin_host.provided_port("workspace.service")
        assert service.connector is wsl
        assert service.ssh_connector is ssh
    finally:
        runtime.stop()


def test_the_ssh_connector_rows_answer_only_where_the_connector_is_composed(tmp_path):
    """Family rows moved with the CONSTRUCTION: without the workspace plugin
    in the round both codes fall through typed; the module-level lookup is
    static-only for both worlds."""
    from server_plugin_api import family_for as static_family_for

    bare = build_runtime(tmp_path / "bare", server_plugins=())
    try:
        assert "SSH_TARGET_INVALID" in WORKSPACE_ERROR_FAMILIES
        assert "SSH_IDENTITY_INVALID" in WORKSPACE_ERROR_FAMILIES
        assert bare.plugin_host.wire_error_families.family_for("SSH_TARGET_INVALID") == "UNAVAILABLE"
        assert bare.plugin_host.wire_error_families.family_for("SSH_IDENTITY_INVALID") == "UNAVAILABLE"
        assert bare.plugin_host.wire_error_families.contributed_families() == {}
        assert static_family_for("SSH_TARGET_INVALID") == "UNAVAILABLE"
        assert static_family_for("SSH_IDENTITY_INVALID") == "UNAVAILABLE"
    finally:
        bare.stop()
    composed = build_runtime(tmp_path / "full")
    try:
        assert composed.plugin_host.active_ids() == (
            "ordessa.workspace", "ordessa.server-compat", "ordessa.harness.acp",
            "ordessa.sandbox", "ordessa.sandbox-adapters",
            "ordessa.permissions-adapters")
        families = composed.plugin_host.wire_error_families
        assert families.family_for("SSH_TARGET_INVALID") == "INVALID_REQUEST"
        assert families.family_for("SSH_IDENTITY_INVALID") == "INVALID_REQUEST"
        assert families.contributed_families()["SSH_TARGET_INVALID"] == ("ordessa.workspace",)
        assert families.contributed_families()["SSH_IDENTITY_INVALID"] == ("ordessa.workspace",)
    finally:
        composed.stop()
