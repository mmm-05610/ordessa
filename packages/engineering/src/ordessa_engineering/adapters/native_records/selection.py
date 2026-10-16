"""Dispatch selection adapter over the original live Unit owner."""
from contextlib import contextmanager
from collections.abc import Mapping

from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.packages.models import ImplementationPackage
from ordessa_execution_agents.profiles import ProfileRevisionRef
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

    def __init__(self, services, expected_profile_revision, *, binding_resolver):
        if (type(services) is not UnitServices
                or type(expected_profile_revision) is not ProfileRevisionRef
                or not callable(binding_resolver)):
            raise ApplicationError("DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE")
        self.services = services
        self.expected_profile_revision = expected_profile_revision
        self.binding_resolver = binding_resolver

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
