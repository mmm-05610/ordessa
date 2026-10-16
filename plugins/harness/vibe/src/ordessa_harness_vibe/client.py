"""Mistral Vibe consumer client (family ``vibe``, protocol ``acp/v1``).

Pinned facts (N011, official
https://docs.mistral.ai/vibe/code/use-vibe-in-other-ides read 2026-10-04):

- Channel: Vibe implements the Agent Client Protocol and is published in the
  ACP registry; the reviewed page does not pin a standalone server command —
  registry/IDE-driven setup is the documented path. The stdio launch shape is
  recorded as unpinned until an installed artifact is measured (G1).
- **Shared-home hazard (attack point)**: Vibe stores credentials in ``~/.vibe/``
  and reuses them across sessions AND across the CLI/VS Code extension;
  agents/skills/MCP/profiles load from ``~/.vibe/`` and per-project ``.vibe/``.
  Isolated launches therefore pin the Vibe home into the scratch tree and
  never read the user's ``~/.vibe`` (G12).
- No installer is run here (upstream setup flows may modify uv/global env —
  out of scope; registered as a caution). IDE context is not assumed provided.
"""

from __future__ import annotations

from typing import Any

from ordessa_execution_agents.harness.protocols.acp import AcpClient

FAMILY_ID = "vibe"
PROTOCOL = "acp/v1"


class VibeClient(AcpClient):
    """One owned Vibe ACP process."""

    FAMILY_ID = FAMILY_ID
    PROTOCOL = PROTOCOL

    def describe(self) -> dict[str, Any]:
        return {
            "familyId": FAMILY_ID,
            "channel": "acp (registry-published agent)",
            "protocol": PROTOCOL,
            "sharedHome": "~/.vibe shared across CLI/VS Code — isolated at launch (G12)",
            "customization": "agents/skills/MCP/profiles from ~/.vibe and project .vibe/",
            "launchShape": "unpinned until a local artifact is measured (no install authorized)",
        }
