"""Gemini CLI consumer client (family ``gemini-cli``, protocol ``acp/v1``).

Pinned facts (N008, official https://geminicli.com/docs/cli/acp-mode/ and
https://agentclientprotocol.com/protocol, read 2026-10-04):

- Channel: ``gemini --acp`` — official ACP server over stdio JSON-RPC 2.0.
  Headless JSON mode is a limited fallback and is NOT claimed as a persistent
  bidirectional channel.
- Session/task identity: ACP ``session/new`` / ``session/prompt`` /
  ``session/cancel`` (notification) / optional ``session/load``. A prompt
  response is the receipt boundary for that prompt; completion facts arrive
  via ``session/update`` (G6).
- Reverse channels: ``session/request_permission`` (tool-call approvals),
  ``fs/read_text_file``/``fs/write_text_file`` (proxied filesystem — the agent
  only touches files the client allows), ``terminal/*`` (ACP-level; the
  gemini page itself does not document terminal callbacks — registered
  unknown on that page, canonical names from the ACP spec), elicitation.
  This client NEVER auto-approves or auto-answers (SAFETY).
- Extensions: ``_``-prefixed custom methods and ``_meta`` data are the ACP
  unknown-extension contract and are preserved verbatim (G4).
- Telemetry env vars (``GEMINI_TELEMETRY_*``) exist upstream; launches pin
  telemetry off (G12).
"""

from __future__ import annotations

from typing import Any

from ordessa_execution_agents.harness.protocols.acp import AcpClient

FAMILY_ID = "gemini-cli"
PROTOCOL = "acp/v1"


class GeminiCliClient(AcpClient):
    """One owned ``gemini --acp`` process."""

    FAMILY_ID = FAMILY_ID
    PROTOCOL = PROTOCOL

    def describe(self) -> dict[str, Any]:
        return {
            "familyId": FAMILY_ID,
            "channel": "stdio-acp",
            "protocol": PROTOCOL,
            "sessionModelSwitch": "unstable_setSessionModel (documented as unstable)",
            "approvalLevel": "setSessionMode",
            "filesystem": "proxied fs/read_text_file + fs/write_text_file",
        }
