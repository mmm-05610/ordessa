"""Current generic registry transport runtime; no CoreBinding or Unit runtime.

Authentication belongs to the injected ORIGINAL instance authority. Context
construction is trusted composition mapping to original owner invocations. No
scope/permission is inferred from params, nor are bearer grants upgraded.
"""
import asyncio
from ordessa_interfaces.system_access import CapabilityHost,RequestContext
from ordessa_interfaces.system_access.queries import list_capabilities,list_operations,describe
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
from ordessa_interfaces_contracts import OperationResult,CapabilityError,ContractError,canonical_json
from ordessa_interfaces.http.serialization import decode_request,encode_result,encode_error,WireError


class RegistryRuntime:
    def __init__(self,host,authority,*,context_factory,close=None,server_id=None,deadline_seconds=30.0):
        if type(host) is not CapabilityHost or type(authority) is not InstanceAccessAuthority or not callable(context_factory):
            raise TypeError('current registry, original authority and trusted context mapping required')
        if server_id is not None and (type(server_id) is not str or not server_id or len(server_id)>512):
            raise ValueError("original Server identity required")
        if type(deadline_seconds) not in (int,float) or not 1<=deadline_seconds<=1800:
            raise ValueError("request deadline must be 1..300 seconds")
        self.server_id=server_id
        self.deadline_seconds=float(deadline_seconds)
        self.host=host;self.authority=authority;self.context_factory=context_factory
        self._close=close;self._closed=False

    def close(self):
        if self._closed:return
        self._closed=True
        if self._close is not None:self._close()

    async def wire(self,body,authorization):
        # Authentication always precedes even discovery; no token fallback.
        caller=self.authority.authenticate(authorization)
        identity,method,params=decode_request(body)
        if type(identity) is not str or not identity or len(identity)>512:
            raise WireError('INVALID_REQUEST','bounded string request identity required')
        if self._closed:raise WireError('CAPABILITY_UNSUPPORTED','registry runtime closed')
        if len(canonical_json(body))>1048576:raise WireError('INVALID_REQUEST','request too large')
        if method=='server.hello':
            if (self.server_id is None or set(params)-{'clientVersions','clientPresentationSupports'}
                    or type(params.get('clientVersions')) is not list or 'wire/1' not in params['clientVersions']
                    or type(params.get('clientPresentationSupports',[])) is not list):
                raise WireError('CAPABILITY_UNSUPPORTED','original transport identity/version unavailable')
            # Original transport handshake only, no domain execution methods.
            return encode_result(identity,{'serverId':self.server_id,'protocolVersion':'wire/1',
                'capabilities':[{'id':name,'supported':True} for name in ('capabilities.list','operations.describe','operations.call')],
                'auth':{'required':True,'schemes':['session_token']}})
        if method=='capabilities.list' and not params:
            value={**list_capabilities(self.host.registry),**list_operations(self.host.registry)}
            result=OperationResult('completed',data=value)
        elif method=='operations.describe' and set(params)=={'operationId'}:
            try:
                if type(params['operationId']) is not str:raise ContractError('INVALID_INPUT','operation identity required')
                result=OperationResult('completed',data=describe(self.host.registry,params['operationId']))
            except ContractError as exc:
                result=OperationResult('refused',error=CapabilityError(exc.code,'Registry operation unavailable'))
        elif method=='operations.call' and set(params)=={'operationId','input'}:
            context=self.context_factory(caller,identity,asyncio.get_running_loop().time()+self.deadline_seconds)
            if type(context) is not RequestContext or context.request_id!=identity:
                raise WireError('INVALID_REQUEST','trusted context mapping unavailable')
            self.authority.verify(caller)
            result=await self.host.call(params['operationId'],params['input'],context)
        else:
            result=OperationResult('refused',error=CapabilityError('CAPABILITY_UNSUPPORTED','Generic registry method unavailable'))
        return encode_result(identity,self.host.envelope(command=params.get('operationId',method),request_id=identity,result=result))
