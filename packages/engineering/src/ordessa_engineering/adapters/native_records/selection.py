"""Dispatch selection adapter over the original live Unit owner."""
from contextlib import contextmanager
from collections.abc import Mapping

from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.packages.models import ImplementationPackage
from ordessa_engineering.domain.packages.models import PreparedPackagePayload
from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorization
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_execution_agents.profiles import ProfileRevisionRef, encode_revision_ref
from ordessa_units.public import DirectoryBindingRef, InvocationContext, UnitServices


_UNIT_REF_FIELDS = frozenset({
    "environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision",
})


class OriginalDispatchSelection:
    """Hold the selected Unit owner's live source fence around dispatch cuts.

    ``binding_resolver`` is trusted Product configuration. It must resolve the
    exact original Profile, Directory, query invocation and query digest for
    this issued request, package and full Unit reference. This adapter issues
    no Unit query or permission and does not hold a lease across native waits.
    """

    def __init__(self, services, expected_profile_revision, *, binding_resolver,
                 work_binding_resolver=None, workspace_scope_guard=None):
        if (type(services) is not UnitServices
                or type(expected_profile_revision) is not ProfileRevisionRef
                or not callable(binding_resolver)):
            raise ApplicationError("DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE")
        self.services = services
        self.expected_profile_revision = expected_profile_revision
        self.binding_resolver = binding_resolver
        if work_binding_resolver is not None and not callable(work_binding_resolver):
            raise ApplicationError("DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE")
        self.work_binding_resolver = work_binding_resolver
        if workspace_scope_guard is not None and not callable(workspace_scope_guard):
            raise ApplicationError("DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE")
        self.workspace_scope_guard = workspace_scope_guard

    @property
    def work_scope_ready(self):
        return self.work_binding_resolver is not None and self.workspace_scope_guard is not None

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

    @contextmanager
    def guard_work_scope(self, context, package, unit_ref, authorization, actions):
        if self.workspace_scope_guard is None:
            raise ApplicationError("DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE")
        with self.workspace_scope_guard(context, package.ref, unit_ref,
                tuple((action, dict(authorization.scope_by_action)[action]) for action in actions)):
            yield

    @contextmanager
    def guard_work_selection(self, context, package, unit_ref, authorization, params):
        """Keep the original Unit/Profile permission fence for a prepared package.

        The Profile comes from this port's product binding and original Unit
        owner. A prepared package contains no execution profile to invent here.
        """
        if (type(context) is not CommandContext or type(package) is not ImplementationPackage
                or type(package.payload) is not PreparedPackagePayload
                or type(authorization) is not WorkPackageAuthorization
                or authorization.package_ref != package.ref or authorization.scope != context.scope
                or package.scope != context.scope or not isinstance(unit_ref, Mapping)
                or set(unit_ref) != _UNIT_REF_FIELDS or self.work_binding_resolver is None):
            raise ApplicationError("DISPATCH_SELECTION_BINDING_INVALID")
        profile, directory, invocation, input_digest = self.work_binding_resolver(
            context, package, unit_ref, authorization, params)
        expected = self.expected_profile_revision
        if (profile != expected or type(profile) is not ProfileRevisionRef
                or type(directory) is not DirectoryBindingRef
                or directory.environment_namespace != expected.environment_namespace
                or unit_ref['environmentNamespace'] != expected.environment_namespace
                or type(invocation) is not InvocationContext
                or type(input_digest) is not str or not input_digest
                or invocation.facts.get('inputDigest') != input_digest):
            raise ApplicationError("DISPATCH_SELECTION_BINDING_UNAVAILABLE")
        environment = EnvironmentRef(expected.environment_namespace, expected.profile_id,
            Digest('sha256', expected.digest.removeprefix('sha256:')))
        with self.services.guard_unit_selection(unit_ref,
                expected_profile_revision=profile, query_invocation=invocation,
                query_input_digest=input_digest, require_live=True):
            yield environment

    @contextmanager
    def guard_selection(self, context, package, unit_ref):
        if (type(context) is not CommandContext
                or type(package) is not ImplementationPackage
                or package.scope != context.scope
                or type(package.payload.execution_profile_ref) is not EnvironmentRef
                or not isinstance(unit_ref, Mapping)
                or set(unit_ref) != _UNIT_REF_FIELDS
                or any(type(unit_ref[name]) is not str or not unit_ref[name]
                       for name in ("environmentNamespace", "unitId", "sourceRevision"))
                or not isinstance(unit_ref["ownerProviderRef"], Mapping)
                or not unit_ref["ownerProviderRef"]):
            raise ApplicationError("DISPATCH_SELECTION_BINDING_INVALID")

        environment = package.payload.execution_profile_ref
        expected = self.expected_profile_revision
        if (environment.environment_id != expected.environment_namespace
                or environment.profile_id != expected.profile_id
                or environment.profile_digest.hex != expected.digest.removeprefix("sha256:")
                or unit_ref["environmentNamespace"] != expected.environment_namespace):
            raise ApplicationError("DISPATCH_SELECTION_PROFILE_MISMATCH")

        profile, directory, invocation, input_digest = self.binding_resolver(
            context, package, unit_ref,
        )
        if (type(profile) is not ProfileRevisionRef
                or profile != expected
                or type(directory) is not DirectoryBindingRef
                or directory.environment_namespace != expected.environment_namespace
                or type(invocation) is not InvocationContext
                or type(input_digest) is not str
                or not input_digest
                or invocation.facts.get("inputDigest") != input_digest):
            raise ApplicationError("DISPATCH_SELECTION_BINDING_UNAVAILABLE")

        with self.services.guard_unit_selection(
            unit_ref,
            expected_profile_revision=profile,
            query_invocation=invocation,
            query_input_digest=input_digest,
            require_live=True,
        ) as original_lease:
            yield original_lease


__all__ = ["OriginalDispatchSelection"]
