"""Construct the one existing method-run binding from selected owner ports.

This module validates composition shape and original factory identity only. It
does not create a WorkConditionSource, load a registry, choose method policy,
or grant permission.
"""
from ..contracts.errors import ApplicationError
from ..orchestration.method_runs import MethodRunBindings


_METHOD_CONTROL_GUARDS = ("guard_method", "guard_selected")
_WORK_SOURCE_GUARDS = (
    "guard_start",
    "guard_condition",
    "guard_step_completion",
)


def build_method_run_bindings(
    factory,
    *,
    method_control,
    work_condition_source,
    registry_loader,
) -> MethodRunBindings:
    """Validate and return the existing binding without invoking its ports.

    Composition supplies concrete original owners. The required ``factory``
    attributes are identity checks, not a substitute for guards held during
    Work operations. Registry content remains loaded and checked by the
    existing MethodRun owner at operation time.
    """
    if factory is None or not callable(getattr(factory, "begin", None)):
        raise ApplicationError("PERSISTENCE_AUTHORITY_UNAVAILABLE")

    if (getattr(method_control, "factory", None) is not factory
            or any(not callable(getattr(method_control, name, None))
                   for name in _METHOD_CONTROL_GUARDS)):
        raise ApplicationError("METHOD_AUTHORITY_MISMATCH")

    if work_condition_source is None:
        raise ApplicationError("WORK_SOURCE_AUTHORITY_UNAVAILABLE")
    if getattr(work_condition_source, "factory", None) is not factory:
        raise ApplicationError("WORK_SOURCE_AUTHORITY_MISMATCH")
    if any(not callable(getattr(work_condition_source, name, None))
           for name in _WORK_SOURCE_GUARDS):
        raise ApplicationError("WORK_SOURCE_AUTHORITY_UNAVAILABLE")

    if not callable(registry_loader):
        raise ApplicationError("OPERATION_REGISTRY_UNAVAILABLE")

    return MethodRunBindings(factory, method_control, work_condition_source, registry_loader)
