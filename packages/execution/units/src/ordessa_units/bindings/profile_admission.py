"""Expose the original Unit admission owner to the Profiles public port.

These views borrow the Unit owner's lock, policy, fingerprint and atomic store.
They add no connection, authority, grant, or persistent state; only the error
vocabulary changes at the owner boundary.
"""
from ordessa_agents.profiles.definitions.errors import (
    ProfileAccessRefused,
    ProfileChangeUnknown,
    ProfileStoreUnavailable,
    ProfileValidationError,
)
from ordessa_infrastructure.database.records import DomainStorePort
from ordessa_units.errors import (
    UnitAdmissionRefused,
    UnitComparisonUnavailable,
    UnitGuaranteeUnavailable,
    UnitIdentityMismatch,
    UnitOperationUnknown,
)


def _profile_error(error):
    if isinstance(error, UnitAdmissionRefused):
        return ProfileAccessRefused(str(error))
    if isinstance(error, UnitIdentityMismatch):
        return ProfileValidationError(str(error))
    if isinstance(error, (UnitGuaranteeUnavailable, UnitComparisonUnavailable)):
        return ProfileStoreUnavailable(str(error))
    if isinstance(error, UnitOperationUnknown):
        return ProfileChangeUnknown(str(error))
    raise error


class _ProfileDomainStoreView:
    """DomainStorePort view that delegates to the one original Unit store."""

    def __init__(self, unit_context):
        self._unit_context = unit_context

    def _store(self):
        store = self._unit_context.store_port
        if not isinstance(store, DomainStorePort):
            raise ProfileStoreUnavailable("original Unit atomic store capability is unavailable")
        return store

    def read_domain(self, *args, **kwargs):
        try:
            return self._store().read_domain(*args, **kwargs)
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error

    def list_domain(self, *args, **kwargs):
        try:
            return self._store().list_domain(*args, **kwargs)
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error

    def read_domain_result(self, *args, **kwargs):
        try:
            return self._store().read_domain_result(*args, **kwargs)
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error

    def commit_domain_change(self, *args, **kwargs):
        try:
            return self._store().commit_domain_change(*args, **kwargs)
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error


class _ProfilePolicyView:
    """Map only the Unit policy's declared refusal/error categories."""

    def __init__(self, unit_context):
        self._unit_context = unit_context

    def _policy(self):
        policy = self._unit_context.policy
        if policy is None:
            raise ProfileAccessRefused("original Unit policy is unavailable")
        return policy

    def admit_object_access(self, *args, **kwargs):
        try:
            return self._policy().admit_object_access(*args, **kwargs)
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error

    def admit_invoke(self, *args, **kwargs):
        try:
            return self._policy().admit_invoke(*args, **kwargs)
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error


class _ProfileFingerprintView:
    """Borrow the Unit's protected fingerprint capability without granting."""

    def __init__(self, unit_context):
        self._unit_context = unit_context

    def _fingerprint_port(self):
        fingerprint_port = self._unit_context.fingerprint_port
        if fingerprint_port is None:
            raise ProfileStoreUnavailable("original Unit fingerprint capability is unavailable")
        return fingerprint_port

    def describe(self):
        try:
            return self._fingerprint_port().describe()
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error

    def fingerprint(self, *args, **kwargs):
        try:
            return self._fingerprint_port().fingerprint(*args, **kwargs)
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error


class UnitProfileAdmission:
    """Adapt the same UnitAdmissionContext to Profiles' admission contract."""

    def __init__(self, unit_context):
        from ordessa_units.admission.context import UnitAdmissionContext

        if not isinstance(unit_context, UnitAdmissionContext):
            raise TypeError("original UnitAdmissionContext required")
        self.unit_context = unit_context
        self._store_view = _ProfileDomainStoreView(unit_context)
        self._policy_view = _ProfilePolicyView(unit_context)
        self._fingerprint_view = _ProfileFingerprintView(unit_context)

    @property
    def environment_namespace(self):
        return self.unit_context.environment_namespace

    @property
    def principal_scope(self):
        return self.unit_context.principal_scope

    @property
    def admission_lock(self):
        return self.unit_context.admission_lock

    @property
    def store_port(self):
        return self._store_view if isinstance(self.unit_context.store_port, DomainStorePort) else None

    @property
    def policy(self):
        return self._policy_view if self.unit_context.policy is not None else None

    @property
    def fingerprint_port(self):
        return self._fingerprint_view if self.unit_context.fingerprint_port is not None else None

    def check_open(self):
        try:
            self.unit_context.check_open()
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error

    def check_environment(self, namespace):
        try:
            self.unit_context.check_environment(namespace)
        except (UnitAdmissionRefused, UnitIdentityMismatch, UnitGuaranteeUnavailable,
                UnitComparisonUnavailable, UnitOperationUnknown) as error:
            raise _profile_error(error) from error


__all__ = ["UnitProfileAdmission"]
