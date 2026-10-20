"""Route exact authorization intent types to their original admission owners."""
from contextlib import contextmanager

from ..contracts.errors import ApplicationError
from ..usecases.changes.apply import ChangeIntentAdmission
from ..usecases.packages.authorization import ImplementationIntentAdmission
from ..usecases.changes.acceptance_closure import SubmissionAcceptanceIntentAdmission
from ...domain.approvals.consent import AuthorizationIntent, ChangeAuthorizationIntent
from ...domain.approvals.implementation import (
    ImplementationAuthorizationIntent, WorkPackageAuthorizationIntent,
)


class _IntentAdmissionRouter:
    """Dispatch only; each original owner keeps its own guards through COMMIT."""

    def __init__(self, factory, change, implementation, acceptance):
        owners = (change, implementation, acceptance)
        expected_types = (ChangeIntentAdmission, ImplementationIntentAdmission,
                          SubmissionAcceptanceIntentAdmission)
        if any(type(owner) is not expected for owner, expected in zip(owners, expected_types)):
            raise ApplicationError("INTENT_ADMISSION_OWNER_UNAVAILABLE")
        if (factory is None or any(owner.factory is not factory for owner in owners)
                or any(not callable(getattr(owner, "guard_intent", None)) for owner in owners)):
            raise ApplicationError("INTENT_ADMISSION_AUTHORITY_MISMATCH")
        selected_methods = change.methods
        if any(owner.methods is not selected_methods for owner in owners):
            raise ApplicationError("INTENT_ADMISSION_METHOD_AUTHORITY_MISMATCH")
        self.factory = factory
        self.methods = selected_methods
        self.change = change
        self.implementation = implementation
        self.acceptance = acceptance

    @contextmanager
    def guard_intent(self, context, intent):
        if type(intent) is ChangeAuthorizationIntent:
            owner = self.change
        elif type(intent) in (ImplementationAuthorizationIntent, WorkPackageAuthorizationIntent):
            owner = self.implementation
        elif type(intent) is AuthorizationIntent:
            owner = self.acceptance
        else:
            raise ApplicationError("INTENT_OWNER_UNAVAILABLE")
        with owner.guard_intent(context, intent) as admitted:
            yield admitted


def build_intent_admission_router(factory, *, change, implementation, acceptance):
    """Compose the three existing guards without granting or defaulting access."""
    return _IntentAdmissionRouter(factory, change, implementation, acceptance)


def build_change_intent_admission(factory, *, method_control, bindings):
    return ChangeIntentAdmission(factory, method_control, bindings)


def build_implementation_intent_admission(factory, *, method_control, bindings):
    return ImplementationIntentAdmission(factory, method_control, bindings)


__all__ = ["build_intent_admission_router", "build_change_intent_admission",
           "build_implementation_intent_admission"]
