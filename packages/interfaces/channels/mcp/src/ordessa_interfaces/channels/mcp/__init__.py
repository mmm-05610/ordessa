"""MCP metadata and tool dispatch over the same registry and schemas.

Tools expose exactly the operation input/output schemas; MCP calls share the
channel's authentication semantics. The caller identity comes from the trusted
composition that builds the bridge, never from tool arguments or client JSON.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from ordessa_interfaces_contracts import (
    CapabilityError, ContractError, OperationResult, envelope_from_result,
)

from ...system_access.operations import RequestContext


class McpBridgeError(ContractError):
    """A tool call cannot be served over MCP."""


def tool_specs(registry) -> list[dict]:
    """Declarative MCP tool list; duplicate tool names refuse."""
    tools: list[dict] = []
    seen: set[str] = set()
    for operation_id, registered in registry.operations.items():
        descriptor = registered.descriptor
        mcp = descriptor.mcp
        if not mcp:
            continue
        name = mcp['tool']
        if name in seen:
            raise ContractError('INVALID_INPUT', f'MCP tool name repeats: {name}')
        seen.add(name)
        tools.append({'name': name, 'operationId': operation_id,
                      'inputSchema': descriptor.input_schema,
                      'outputSchema': descriptor.output_schema})
    return tools


def tool_index(registry) -> dict[str, str]:
    return {tool['name']: tool['operationId'] for tool in tool_specs(registry)}


async def call_tool(host, tools: Mapping[str, str], name: str,
                    arguments: Mapping, context) -> OperationResult:
    """Dispatch one MCP tool call through the generic host."""
    operation_id = tools.get(name)
    if operation_id is None:
        raise ContractError('CAPABILITY_UNSUPPORTED', f'MCP tool is not registered: {name}')
    return await host.call(operation_id, arguments, context)


class McpBridge:
    """One authenticated MCP view over a built host.

    ``principal`` is the trusted identity selected by the composition that owns
    this bridge (the same authenticated mapping a CLI/loopback channel uses). It
    is captured once and never derived from ``arguments``; a client JSON object
    cannot extend or replace it. Requests are still validated by the generic
    host against the operation's closed schema.
    """

    def __init__(self, host, *, principal: Mapping[str, object]) -> None:
        if not isinstance(principal, Mapping):
            raise McpBridgeError('AUTHORITY_UNAVAILABLE', 'a trusted principal is required')
        self.host = host
        self.principal = dict(principal)
        self._index = tool_index(host.registry)
        self._tools = [dict(tool) for tool in tool_specs(host.registry)]

    @property
    def tools(self) -> list[dict]:
        return [dict(tool) for tool in self._tools]

    def operation_id(self, name: str) -> str:
        operation_id = self._index.get(name)
        if operation_id is None:
            raise McpBridgeError('CAPABILITY_UNSUPPORTED', f'MCP tool is not registered: {name}')
        return operation_id

    async def call(self, name: str, arguments: Mapping | None, *,
                   request_id: str | None = None) -> dict:
        """Dispatch one tool call and return the ``agent-tools/1`` envelope."""
        operation_id = self.operation_id(name)
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            raise McpBridgeError('INVALID_INPUT', 'tool arguments must be a JSON object')
        request_id = request_id or uuid.uuid4().hex
        if type(request_id) is not str or not request_id:
            raise McpBridgeError('INVALID_INPUT', 'a request id is required')
        context = RequestContext(principal=self.principal, request_id=request_id)
        try:
            result = await self.host.call(operation_id, arguments, context)
        except ContractError as error:
            result = OperationResult(status='refused',
                                     error=CapabilityError(error.code, error.message))
        return envelope_from_result(request_id=request_id, command=f'mcp {name}', result=result)

    @staticmethod
    def tool_result_text(envelope: Mapping) -> str:
        """The bounded text content an MCP ``tools/call`` returns."""
        return json.dumps(dict(envelope), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def tool_result_is_error(envelope: Mapping) -> bool:
        return envelope.get('status') in ('refused', 'unknown')


__all__ = ['McpBridgeError', 'tool_specs', 'tool_index', 'call_tool', 'McpBridge']
