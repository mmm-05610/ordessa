"""Goose consumer client (family ``goose``, protocol ``acp/v1``).

Pinned facts (N010, official https://goose-docs.ai/docs/gdk/acp/ read
2026-10-04):

- Channel: **goose as an ACP agent/server** (NOT goose consuming other
  agents as providers — a different product surface). stdio mode:
  ``goose acp`` launched as a subprocess by the client, which owns the
  process lifetime. HTTP/WebSocket mode: ``goose serve`` (default
  127.0.0.1:3284, ACP endpoint ``/acp``) with ``GOOSE_SERVER__SECRET_KEY``
  and ``X-Secret-Key`` (browser WS: ``?token=``). stdio is chosen here.
- ``--dangerously-unauthenticated`` exists upstream but MUST NOT be used
  (docs restrict it to isolated local development) — launches planned here
  never carry it (SAFETY).
- Session/permission semantics beyond standard ACP are documented on a
  separate reference page and are registered unknown here; standard ACP
  (``session/request_permission`` etc.) is served by the shared seam and is
  never auto-answered.
- Version/license unspecified on the page (upstream moved to the Agentic AI
  Foundation, aaif-goose/goose) — recorded as unpinned (G1).
"""

from __future__ import annotations

from typing import Any

from ._acp import AcpClient

FAMILY_ID = "goose"
PROTOCOL = "acp/v1"


class GooseClient(AcpClient):
    """One owned ``goose acp`` stdio process."""

    FAMILY_ID = FAMILY_ID
    PROTOCOL = PROTOCOL

    def describe(self) -> dict[str, Any]:
        return {
            "familyId": FAMILY_ID,
            "channel": "stdio-acp (goose as ACP server)",
            "protocol": PROTOCOL,
            "alternateTransport": "goose serve HTTP/WS at 127.0.0.1:3284 /acp (not chosen)",
            "auth": "GOOSE_SERVER__SECRET_KEY applies to serve mode; stdio mode is process-owned",
            "forbiddenFlag": "--dangerously-unauthenticated is never used (SAFETY)",
        }
