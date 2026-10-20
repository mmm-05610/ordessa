"""Test-only stdio MCP server: real host, trusted principal, one demo tool."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from host_fakes import FakeEntryPoint, FakeFactory, make_capability
from ordessa_interfaces.channels.mcp import McpBridge
from ordessa_interfaces.system_access.assembly import build_host
from ordessa_interfaces.transport.mcp_stdio import serve_stdio


def main() -> None:
    capability = make_capability('demo', operation_ids=('demo.run',),
                                 cli={'command': 'demo', 'operation': 'run'},
                                 mcp={'tool': 'demo_run'})
    host = build_host(('demo',), {'services': object(), 'invocation_resolver': object()},
                      entry_points=(FakeEntryPoint('demo', FakeFactory(capability)),))
    bridge = McpBridge(host, principal={'principalId': 'mcp-test'})
    asyncio.run(serve_stdio(bridge))


if __name__ == '__main__':
    main()
