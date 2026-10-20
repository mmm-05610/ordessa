"""Stateless native-purpose adapter over the ORIGINAL current instance authority.

Trusted composition supplies exact existing invocation/principal/project mapping;
this adapter creates no principal, grant, journal or persistent domain owner.
"""
from contextlib import contextmanager
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,VerifiedPrincipal
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_execution_agents.sdk.native_contracts import NativeWriteBinding,NativeOperationRef
from ordessa_execution_agents.sdk.interactions import InteractionsRefused

NATIVE_CAPABILITIES={'apply':'agents.configuration.apply','query':'agents.configuration.query'}
NATIVE_READ='agents.operations.read'


class OriginalNativeAccess:
    def __init__(self,base,authority,*,caller_resolver,scope_for_agent,principal_scope_for_caller):
        if (type(authority) is not InstanceAccessAuthority or base is None
                or any(not callable(p) for p in (caller_resolver,scope_for_agent,principal_scope_for_caller))):
            raise InteractionsRefused('NATIVE_ACCESS_MAPPING_UNAVAILABLE')
        self.base,self.authority=base,authority
        self.caller_resolver,self.scope_for_agent=caller_resolver,scope_for_agent
        self.principal_scope_for_caller=principal_scope_for_caller

    def _caller(self,invocation):
        caller=self.caller_resolver(invocation)
        if type(caller) is not VerifiedPrincipal:raise InteractionsRefused('AUTHORITY_UNAVAILABLE')
        self.authority.verify(caller)
        if self.principal_scope_for_caller(caller)!=self.base.principal_scope(invocation):
            raise InteractionsRefused('NATIVE_PRINCIPAL_MAPPING_MISMATCH')
        return caller

    def principal_scope(self,invocation):
        self._caller(invocation)
        return self.base.principal_scope(invocation)

    def check_send(self,*args):return self.base.check_send(*args)
    def check_read_turn(self,*args):return self.base.check_read_turn(*args)
    def check_read_binding(self,*args):return self.base.check_read_binding(*args)

    @contextmanager
    def _guard(self,invocation,instance,capability):
        caller=self._caller(invocation);scope=self.scope_for_agent(instance)
        if type(scope) is not Scope:raise InteractionsRefused('NATIVE_PROJECT_MAPPING_UNAVAILABLE')
        with self.authority.guard(caller,scope,capability):yield caller

    def check_native_dispatch(self,invocation,binding):
        if type(binding) is not NativeWriteBinding:raise InteractionsRefused('NATIVE_BINDING_INVALID')
        NativeWriteBinding.decode(binding.projection())
        with self._guard(invocation,binding.request.instance_ref,NATIVE_CAPABILITIES[binding.request.purpose]):pass

    def check_read_native_operation(self,invocation,ref,digest):
        if type(ref) is not NativeOperationRef:raise InteractionsRefused('NATIVE_REFERENCE_REQUIRED')
        with self._guard(invocation,ref.instance_ref,NATIVE_READ):pass

    @contextmanager
    def guard_native_dispatch(self,invocation,binding):
        if type(binding) is not NativeWriteBinding:raise InteractionsRefused('NATIVE_BINDING_INVALID')
        NativeWriteBinding.decode(binding.projection())
        with self._guard(invocation,binding.request.instance_ref,NATIVE_CAPABILITIES[binding.request.purpose]):yield

    @contextmanager
    def guard_write(self,binding,invocation):
        if type(binding) is not NativeWriteBinding:raise InteractionsRefused('NATIVE_BINDING_INVALID')
        with self._guard(invocation,binding.request.instance_ref,NATIVE_CAPABILITIES[binding.request.purpose]):yield
