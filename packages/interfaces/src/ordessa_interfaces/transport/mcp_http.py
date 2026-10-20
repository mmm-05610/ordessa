"""Loopback-only MCP Streamable HTTP transport with external authentication.

Loopback is a network scope, not an identity: the ASGI app never grants the
composition's principal to an arbitrary local client. An externally supplied
authenticator verifies the request credential and returns the trusted principal
mapping; every request is dispatched with exactly that principal. Missing,
invalid or expired credentials are refused with ``401`` *before* the MCP session
or any capability handler runs. Scope authorization stays in the existing host
and its capability handlers; this module copies no ACL.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect

from .mcp_stdio import (BLOCKED_MESSAGE, McpTransportUnavailable, build_server,
                        sdk_available)

LOOPBACK_HOSTS = frozenset({'127.0.0.1', 'localhost', '::1'})
HTTP_PATH = '/mcp'
UNAUTHORIZED_BODY = b'{"error":"UNAUTHORIZED","message":"trusted principal required"}'


def bearer_token(headers: dict[str, str]) -> str | None:
    value = headers.get('authorization')
    if type(value) is not str:
        return None
    scheme, _, token = value.partition(' ')
    if scheme.lower() != 'bearer' or not token.strip():
        return None
    return token.strip()


async def _principal(authenticate, token: str):
    result = authenticate(token)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _reject(send) -> None:
    await send({'type': 'http.response.start', 'status': 401,
                'headers': [(b'content-type', b'application/json'),
                            (b'content-length', str(len(UNAUTHORIZED_BODY)).encode())]})
    await send({'type': 'http.response.body', 'body': UNAUTHORIZED_BODY})


class AuthenticatedHttpApp:
    """ASGI wrapper: authenticate every HTTP request before it reaches the app.

    The principal is written to the request scope state (``request.state``), so
    the MCP callbacks read it per request. Nothing is stored on a shared bridge,
    so concurrent requests with different credentials cannot mix identities.
    """

    def __init__(self, app, authenticate) -> None:
        if not callable(authenticate):
            raise McpTransportUnavailable(
                'MCP HTTP requires an external trusted authenticator')
        self.app = app
        self.authenticate = authenticate

    async def __call__(self, scope, receive, send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        headers = {key.decode('latin-1').lower(): value.decode('latin-1')
                   for key, value in scope.get('headers', ())}
        token = bearer_token(headers)
        principal = None if token is None else await _principal(self.authenticate, token)
        if not isinstance(principal, dict) or not principal:
            await _reject(send)
            return
        state = dict(scope.get('state') or {})
        state['principal'] = dict(principal)
        scoped = dict(scope, state=state)
        await self.app(scoped, receive, send)


def principal_from_context(context):
    """Read the verified principal attached by :class:`AuthenticatedHttpApp`."""
    request = getattr(context, 'request', None)
    state = getattr(request, 'state', None)
    principal = getattr(state, 'principal', None)
    if not isinstance(principal, dict) or not principal:
        raise McpTransportUnavailable(
            'MCP HTTP dispatch without a verified principal is refused')
    return principal


def _manager(bridge):
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    return StreamableHTTPSessionManager(
        app=build_server(bridge, principal_resolver=principal_from_context),
        json_response=True, stateless=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=['127.0.0.1', '127.0.0.1:*', 'localhost', 'localhost:*',
                           '[::1]', '[::1]:*'],
            allowed_origins=[]))


def build_http_app(bridge, *, authenticate):
    """Return the authenticated ASGI app exposing MCP at ``/mcp``."""
    if not callable(authenticate):
        raise McpTransportUnavailable(
            'MCP HTTP requires an external trusted authenticator')
    if not sdk_available():
        raise McpTransportUnavailable()
    from starlette.applications import Starlette
    from starlette.routing import Mount
    manager = _manager(bridge)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    async def endpoint(scope, receive, send):
        # Exact-path dispatch: a Mount named /mcp would answer POST /mcp with a
        # 307 redirect to /mcp/, which JSON-RPC clients do not follow.
        path = scope.get('path', '')
        if path.rstrip('/') != HTTP_PATH:
            body = b'{"error":"NOT_FOUND"}'
            await send({'type': 'http.response.start', 'status': 404,
                        'headers': [(b'content-type', b'application/json'),
                                    (b'content-length', str(len(body)).encode())]})
            await send({'type': 'http.response.body', 'body': body})
            return
        await manager.asgi_app(scope, receive, send)

    inner = Starlette(routes=[Mount('/', app=endpoint)], lifespan=lifespan)
    return AuthenticatedHttpApp(inner, authenticate)


async def run_http(bridge, *, authenticate, host: str = '127.0.0.1', port: int = 0):
    """Serve the authenticated loopback MCP endpoint; returns (server, port, task)."""
    if host not in LOOPBACK_HOSTS:
        raise McpTransportUnavailable('MCP HTTP transport is loopback-only')
    app = build_http_app(bridge, authenticate=authenticate)
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level='warning', lifespan='on')
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    if not server.started:
        task.cancel()
        raise McpTransportUnavailable('MCP HTTP server did not start')
    bound = server.servers[0].sockets[0].getsockname()[1]
    return server, bound, task


__all__ = ['BLOCKED_MESSAGE', 'McpTransportUnavailable', 'LOOPBACK_HOSTS', 'HTTP_PATH',
           'UNAUTHORIZED_BODY', 'bearer_token', 'AuthenticatedHttpApp',
           'principal_from_context', 'build_http_app', 'run_http']
