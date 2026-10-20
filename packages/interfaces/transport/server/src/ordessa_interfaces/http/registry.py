"""Authenticated generic F1 HTTP transport; requires existing FastAPI runtime.

No domain branch, CoreBinding, old plugin host or default grants. ASGI libraries
are imported only when constructing the app; missing dependencies are a startup
block, never a route to another runtime.
"""
from ordessa_interfaces.system_access.access_control.authentication import AccessError
from ordessa_interfaces.http.serialization import WireError,encode_error
from .loopback import _loopback_authority
from contextlib import asynccontextmanager


def create_registry_app(runtime, *, on_bound=None, close_on_shutdown=False):
    from fastapi import FastAPI,Request
    from fastapi.responses import JSONResponse
    import json
    if on_bound is not None and not callable(on_bound):
        raise TypeError('listening callback must be callable')
    @asynccontextmanager
    async def lifespan(_app):
        try:
            if runtime._closed:
                raise RuntimeError('current registry runtime is closed')
            if on_bound is not None:
                on_bound()
            yield
        finally:
            if close_on_shutdown:
                runtime.close()
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)

    @app.middleware('http')
    async def loopback_policy(request:Request, call_next):
        host=request.headers.get('host','')
        origin=request.headers.get('origin')
        if not _loopback_authority(host) or (origin and not _loopback_authority(origin.split('//',1)[-1])):
            return JSONResponse({'error':'LOOPBACK_POLICY_REJECTED'},status_code=403)
        return await call_next(request)

    @app.get('/live')
    async def live():
        return {'status':'alive'}

    @app.post('/wire/v1/{method}')
    async def wire(method:str,request:Request):
        try:
            # Authenticate before reading request material; original authority.
            authorization=request.headers.get('authorization','')
            runtime.authority.authenticate(authorization)
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>1048576:raise WireError('INVALID_REQUEST','request too large')
            body=json.loads(raw)
            if type(body) is not dict or body.get('method')!=method:
                raise WireError('INVALID_REQUEST','method mismatch')
            return JSONResponse(await runtime.wire(body,authorization))
        except AccessError:
            return JSONResponse({'error':'AUTHENTICATION_REFUSED'},status_code=401)
        except (ValueError,TypeError):
            return JSONResponse(encode_error(None,WireError('INVALID_REQUEST','malformed request')),status_code=400)
        except WireError as exc:
            return JSONResponse(encode_error(None,exc),status_code=400)
    return app
