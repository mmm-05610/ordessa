"""In-process loopback transport for channel identity and dispatch tests.

The transport carries the caller-supplied principal into the context unchanged;
it mints no identity, permission or domain object.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from ordessa_interfaces_contracts import envelope_from_result

from ..system_access.operations import RequestContext


@dataclass(frozen=True)
class EnvelopeReply:
    envelope: dict
    exit_code: int


class LoopbackTransport:
    """Synchronous-looking facade over the async host for tests and local tools."""

    def __init__(self, host) -> None:
        self.host = host

    async def request(self, operation_id: str, request: Mapping,
                      *, principal: Mapping, request_id: str) -> dict:
        context = RequestContext(principal=principal, request_id=request_id)
        result = await self.host.call(operation_id, request, context)
        return envelope_from_result(request_id=request_id,
                                   command=f'loopback {operation_id}', result=result)

    def request_sync(self, operation_id: str, request: Mapping,
                     *, principal: Mapping, request_id: str) -> dict:
        return asyncio.run(self.request(operation_id, request, principal=principal,
                                        request_id=request_id))


__all__ = ['EnvelopeReply', 'LoopbackTransport']
