"""Explicit Agent/Profile reads plus the original external workspace fence.

The Agent provenance is captured identity data, never a workspace permission or
liveness lease. The independently supplied workspace guard owns action scopes.
No Unit lookup, creator, launch, send or default grant is reachable here.
"""
from contextlib import contextmanager
from collections.abc import Mapping
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorization
from ordessa_engineering.domain.packages.models import ImplementationPackage, PreparedPackagePayload
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.models.execution_refs import agent_instance_ref_bytes
from ordessa_agents.public import InteractionService, AgentInstanceRef
from ordessa_agents.profiles import ProfileRevisionRef, encode_revision_ref
from ordessa_agents.sdk.interactions import BindingProvenance


class OriginalAgentDispatchSelection:
    def __init__(self, source, expected_profile_revision, *, read_invocation_resolver,
                 workspace_scope_guard):
        if (type(source) is not InteractionService
                or type(expected_profile_revision) is not ProfileRevisionRef
                or not callable(read_invocation_resolver)):
            raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
        if not callable(workspace_scope_guard):
            raise ApplicationError('DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE')
        self.source = source
        self.expected_profile_revision = expected_profile_revision
        self.read_invocation_resolver = read_invocation_resolver
        self.workspace_scope_guard = workspace_scope_guard

    @property
    def work_scope_ready(self):
        return True  # Explicit original read port and external action fence bound.

    def describe_work_profile(self, context, package, authorization):
        if (context.scope != package.scope or authorization.scope != context.scope
                or authorization.package_ref != package.ref):
            raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID')
        profile = self.expected_profile_revision
        environment = EnvironmentRef(profile.environment_namespace, profile.profile_id,
            Digest('sha256', profile.digest.removeprefix('sha256:')))
        if any(environment not in scope.environment_refs for _, scope in authorization.scope_by_action):
            raise ApplicationError('ACTION_SCOPE_NOT_AUTHORIZED')
        return encode_revision_ref(profile)

    def _read(self, context, agent_ref):
        try:
            instance = AgentInstanceRef.decode(decode_json(agent_instance_ref_bytes(agent_ref)))
            invocation = self.read_invocation_resolver(context, instance.projection())
            if invocation is None:
                raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
            observed = self.source.read_binding(instance, invocation=invocation)
            if (type(observed) is not BindingProvenance or observed.instance_ref != instance
                    or observed.profile_ref != self.expected_profile_revision):
                raise ApplicationError('DISPATCH_SELECTION_PROFILE_MISMATCH')
            # Revalidate the closed original provenance, including its digest.
            BindingProvenance.decode(observed.projection())
            return observed
        except ApplicationError:
            raise
        except Exception:
            raise ApplicationError('DISPATCH_SELECTION_BINDING_UNAVAILABLE') from None

    @contextmanager
    def guard_work_selection(self, context, package, agent_ref, authorization, params):
        if (type(context) is not CommandContext or type(package) is not ImplementationPackage
                or type(package.payload) is not PreparedPackagePayload
                or type(authorization) is not WorkPackageAuthorization
                or authorization.package_ref != package.ref or authorization.scope != context.scope
                or package.scope != context.scope or not isinstance(agent_ref, Mapping)):
            raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID')
        self.describe_work_profile(context, package, authorization)
        observed = self._read(context, agent_ref)
        profile = observed.profile_ref
        yield EnvironmentRef(profile.environment_namespace, profile.profile_id,
            Digest('sha256', profile.digest.removeprefix('sha256:')))
        # This detects changed captured identity; it does not claim a live lease.
        if self._read(context, agent_ref) != observed:
            raise ApplicationError('DISPATCH_SELECTION_BINDING_CHANGED')

    @contextmanager
    def guard_work_scope(self, context, package, agent_ref, authorization, actions):
        self._read(context, agent_ref)
        scopes = dict(authorization.scope_by_action)
        if not set(actions) <= set(scopes):
            raise ApplicationError('ACTION_SCOPE_NOT_AUTHORIZED')
        with self.workspace_scope_guard(context, package.ref, agent_ref,
                tuple((action, scopes[action]) for action in actions)):
            yield


__all__ = ['OriginalAgentDispatchSelection']
