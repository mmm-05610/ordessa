"""Drive the Ordessa MCP server over a real stdio MCP session (isolated env).

Run with the isolated MCP python (the env that has the official SDK). It opens
a genuine MCP stdio session against ``server.py``: lists tools, calls the
connectivity tool (``server.hello``) and the real Engineering business method
(``engineering.capabilities``), printing one JSON object per line.
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    # The configured isolated interpreter must hold the actual installed SDK,
    # channel and shared client closure. Do not qualify wheels through source aliases.
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "ordessa_mcp_server.server"],
        env={"PATH": os.environ.get("PATH", ""),
             "ORDESSA_MCP_ENDPOINT": os.environ["ORDESSA_MCP_ENDPOINT"],
             "ORDESSA_MCP_TOKEN": os.environ["ORDESSA_MCP_TOKEN"]})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            print(json.dumps({"tools": sorted(tool.name for tool in listed.tools)}), flush=True)
            connectivity = await session.call_tool("ordessa_capabilities", {})
            print(json.dumps({"connectivity": connectivity.model_dump()}, default=str), flush=True)
            business = await session.call_tool(
                "ordessa_wire_call", {
                    "method": "engineering.capabilities",
                    "params": {
                        "scope": {"realm_id": "mcp-realm", "project_id": "mcp-project"},
                        "requestId": "mcp-engineering-capabilities",
                    },
                })
            print(json.dumps({"business": business.model_dump()}, default=str), flush=True)


asyncio.run(main())
