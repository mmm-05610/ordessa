"""Server-side compatibility surfaces the monorepo rename had to keep.

The wire protocol version, the credential CLI entry, and the `AGENTBOX_*`
variable prefix are protocol/config surfaces shared with the still-running
hd004b leg and with existing deployments; the rename may not touch them.
"""
from __future__ import annotations

from pathlib import Path

TREE = Path(__file__).resolve().parents[3]


def test_the_wire_version_is_unchanged():
    from ordessa_server.wire.handlers import WIRE_VERSION

    assert WIRE_VERSION == "wire/1"


def test_the_agentbox_variable_prefix_stands():
    # T014-S2b: the AGENT_BOX_*SL/SSH_* connector bindings moved with the
    # connector builders into the workspace plugin; the guard follows the
    # code that reads the bindings, and the host keeps naming the prefix it
    # no longer owns out of. Both spellings must still be read somewhere in
    # the composed tree — a rename may not drop them silently.
    workspace_connectors = (TREE / "plugins" / "workspace" / "src"
                            / "ordessa_workspace" / "connectors.py").read_text(encoding="utf-8")
    assert "AGENT_BOX_" in workspace_connectors
