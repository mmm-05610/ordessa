"""Minimal correct Ordessa→MCP server (remote mode).

This is the *outward* MCP server: it exposes Ordessa capabilities as MCP tools
using the **official** MCP SDK (``mcp``), and it consumes the Ordessa
``system-access`` wire API over HTTP. It is not the MCP *asset* plugin
(``plugins/agents/resources/mcp``), which manages external MCP services.

Dependency boundary: this distribution's closure is the official SDK only. It
must **not** import ``ordessa_interfaces`` (or anything that does), so the
``jsonschema``/``referencing`` pins that conflict in one process never meet.
The transport (``transport.py``) is stdlib-only and validates the method,
endpoint and token before any socket opens.
"""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from .transport import wire_call

server = MCPServer("ordessa")


def _call(method: str, params: "dict | None" = None) -> dict:
    return wire_call(os.environ["ORDESSA_MCP_ENDPOINT"],
                     os.environ.get("ORDESSA_MCP_TOKEN", ""), method, params)


@server.tool()
def ordessa_capabilities() -> dict:
    """Discover the Ordessa Server's wire capabilities (``server.hello``)."""
    return _call("server.hello", {
        "clientVersions": ["wire/1"], "clientPresentationSupports": []})


@server.tool()
def ordessa_wire_call(method: str, params: "dict | None" = None) -> dict:
    """Invoke any Ordessa wire/1 business method and return its real result."""
    return _call(method, params)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
