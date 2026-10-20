"""Original instance authority + exact existing Profile principal/scope mapping."""
from contextlib import contextmanager
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,VerifiedPrincipal,AccessError
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_execution_agents.profiles import ProfileAccessRefused


class OriginalProfileAccess:
    def __init__(self,authority,*,caller_resolver,scope_for_service,principal_scope_for_caller):
        if type(authority) is not InstanceAccessAuthority or any(not callable(c) for c in (caller_resolver,scope_for_service,principal_scope_for_caller)):
            raise TypeError('original issuer and exact trusted Profile mapping required')
        self.authority=authority;self.caller_resolver=caller_resolver
        self.scope_for_service=scope_for_service;self.principal_scope_for_caller=principal_scope_for_caller

    @contextmanager
    def guard(self,operation,invocation,service):
        try:
            caller=self.caller_resolver(invocation)
            if type(caller) is not VerifiedPrincipal:raise ProfileAccessRefused('original caller required')
            self.authority.verify(caller)
            if self.principal_scope_for_caller(caller)!=service.principal_scope:
                raise ProfileAccessRefused('Profile principal mapping mismatch')
            scope=self.scope_for_service(service)
            if type(scope) is not Scope:raise ProfileAccessRefused('Profile scope mapping unavailable')
            if not operation.startswith('profiles.'):raise ProfileAccessRefused('foreign operation')
            with self.authority.guard(caller,scope,operation):yield
        except AccessError:
            raise ProfileAccessRefused('current original authority refused') from None
