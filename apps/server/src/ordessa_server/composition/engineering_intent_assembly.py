"""Route original Engineering intent guards over one selected owner graph."""
from ordessa_engineering.application.api import ApplicationError
from ordessa_engineering.application.assembly import (
    build_change_intent_admission,
    build_implementation_intent_admission,
    build_intent_admission_router,
    build_submission_acceptance_admission,
)


def build_engineering_intent_admission_router(
    factory, *, method_control, bindings, acceptance_admission=None,
):
    """Compose exact owner guards without adding authorization or policy.

    A supplied ``acceptance_admission`` is preserved by identity; otherwise it
    is built with Engineering's public acceptance builder. The change and
    implementation admissions are also built through public assembly APIs
    with those same objects. The returned router dispatches original intent
    types to their owners.
    """
    if (factory is None or not callable(getattr(factory, "begin", None))
            or getattr(method_control, "factory", None) is not factory):
        raise ApplicationError("INTENT_ADMISSION_AUTHORITY_MISMATCH")

    if acceptance_admission is None:
        acceptance_admission = build_submission_acceptance_admission(
            factory, method_control=method_control, bindings=bindings)
    if (getattr(acceptance_admission, "factory", None) is not factory
            or getattr(acceptance_admission, "methods", None) is not method_control
            or getattr(acceptance_admission, "bindings", None) is not bindings
            or not callable(getattr(acceptance_admission, "guard_intent", None))):
        raise ApplicationError("INTENT_ADMISSION_AUTHORITY_MISMATCH")

    change = build_change_intent_admission(
        factory, method_control=method_control, bindings=bindings)
    implementation = build_implementation_intent_admission(
        factory, method_control=method_control, bindings=bindings)
    router = build_intent_admission_router(
        factory, change=change, implementation=implementation,
        acceptance=acceptance_admission)
    if (getattr(router, "factory", None) is not factory
            or getattr(router, "methods", None) is not method_control
            or not callable(getattr(router, "guard_intent", None))):
        raise ApplicationError("INTENT_ADMISSION_AUTHORITY_MISMATCH")
    return router


__all__ = ["build_engineering_intent_admission_router"]
