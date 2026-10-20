"""Official MCP stdio transport over the generic capability host.

The transport speaks the MCP protocol through the official SDK (``mcp==2.2.0``)
and delegates every tool call to :class:`McpBridge`, so the operation schemas and
the trusted principal are exactly those of the host. The client's JSON-RPC
``id`` is the only per-call correlation; it never carries identity.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping

try:  # the SDK is an optional extra so the host itself stays dependency-free
    import mcp.types as mcp_types
    from mcp.server.lowlevel import Server as _Server
    from mcp.server.stdio import stdio_server as _stdio_server
except ImportError:  # pragma: no cover - exercised when the extra is absent
    mcp_types = None
    _Server = None
    _stdio_server = None


BLOCKED_MESSAGE = 'BLOCKED: mcp==2.2.0 is not installed; MCP stdio transport unavailable'


class McpTransportUnavailable(RuntimeError):
    """A real MCP transport cannot run in this environment."""

    def __init__(self, message: str = BLOCKED_MESSAGE) -> None:
        super().__init__(message)
        self.code = 'MCP_TRANSPORT_UNAVAILABLE'


def sdk_available() -> bool:
    return _Server is not None and mcp_types is not None and _stdio_server is not None


def build_server(bridge, *, principal_resolver=None):
    """Build the official lowlevel MCP server for one bridge.

    ``principal_resolver`` (HTTP path) returns the verified per-request principal
    from the MCP context; without it (stdio path) the bridge's trusted principal
    is used. A per-request bridge is created from the verified principal, so no
    mutable identity is shared between concurrent requests.
    """
    if not sdk_available():
        raise McpTransportUnavailable()
    async def list_tools(context, params):
        return mcp_types.ListToolsResult(tools=[
            mcp_types.Tool(name=tool['name'],
                           description=f"Ordessa operation {tool['operationId']}",
                           input_schema=dict(tool['inputSchema']),
                           output_schema=dict(tool['outputSchema']))
            for tool in bridge.tools])

    async def call_tool(context, params):
        request_id = str(context.request_id) if context.request_id is not None else uuid.uuid4().hex
        request_bridge = bridge
        if principal_resolver is not None:
            from ..channels.mcp import McpBridge
            request_bridge = McpBridge(bridge.host,
                                       principal=principal_resolver(context))
        envelope = await request_bridge.call(params.name, params.arguments or {},
                                             request_id=request_id)
        is_error = request_bridge.tool_result_is_error(envelope)
        structured = None
        if not is_error:
            # The official client revalidates a non-error result against the
            # tool's declared outputSchema, so the envelope data must be carried
            # as structuredContent (the text form alone is rejected).
            data = envelope.get('data')
            structured = dict(data) if isinstance(data, Mapping) else {}
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type='text',
                                           text=request_bridge.tool_result_text(envelope))],
            structured_content=structured, is_error=is_error)

    return _Server('ordessa', version='0.1.0', on_list_tools=list_tools,
                   on_call_tool=call_tool)


async def serve_stdio(bridge, *, stdin=None, stdout=None) -> None:
    """Serve one stdio MCP connection until the client closes stdin."""
    server = build_server(bridge)
    async with _stdio_server(stdin, stdout) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


__all__ = ['BLOCKED_MESSAGE', 'McpTransportUnavailable', 'sdk_available', 'build_server',
           'serve_stdio']
