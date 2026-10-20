"""CLI commands on an explicitly retained current RegistryRuntime.

The caller owns runtime/resource lifetime and supplies an already authenticated
original caller. No daemon, credential lookup, policy, acquisition or cleanup is
created here. Generic parsing/dispatch remains the same interface channel.
"""
import asyncio

from ordessa_interfaces.channels.cli import async_run
from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.access_control.authentication import AccessError
from ordessa_interfaces_contracts import ContractError

from ..composition.registry_runtime import RegistryRuntime


class _RuntimeView:
    def __init__(self, runtime, caller):
        if type(runtime) is not RegistryRuntime:
            raise TypeError('original current RegistryRuntime required')
        self.runtime, self.caller = runtime, caller
        self.registry = runtime.host.registry
        self.envelope = runtime.host.envelope

    def authenticate(self, command):
        try:
            if self.runtime._closed:
                raise AccessError('RUNTIME_CLOSED')
            self.runtime.authority.verify(self.caller)
        except AccessError:
            raise ContractError('AUTHORITY_UNAVAILABLE',
                                'Original foreground authority unavailable') from None
        return {'id': self.caller.principal_id}

    async def call(self, operation_id, request, context):
        self.authenticate(operation_id)
        if type(context.request_id) is not str or len(context.request_id)>512:
            raise ContractError('INVALID_INPUT', 'Bounded request identity required')
        # Use the SAME trusted context mapping as RegistryRuntime.wire, rather
        # than treating the CLI's public principal mapping as an invocation.
        try:
            mapped=self.runtime.context_factory(self.caller,context.request_id,
                                                asyncio.get_running_loop().time()+30)
            self.authenticate(operation_id)
        except AccessError:
            raise ContractError('AUTHORITY_UNAVAILABLE', 'Original foreground authority unavailable') from None
        if type(mapped) is not RequestContext or mapped.request_id!=context.request_id:
            raise ContractError('AUTHORITY_UNAVAILABLE', 'Original context mapping unavailable')
        return await self.runtime.host.call(operation_id,request,mapped)


async def run(argv, *, runtime, caller, stdin=None, stdout=None, stderr=None):
    """Await one command on the caller's existing loop and retained host."""
    view=_RuntimeView(runtime,caller)
    return await async_run(argv,host=view,authenticate=view.authenticate,
                           stdin=stdin,stdout=stdout,stderr=stderr)
