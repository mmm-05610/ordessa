"""Provider-neutral errors for the production Work Core."""


class WorkCoreError(RuntimeError):
    """Base class for Work Core failures."""


class WorkNotOpen(WorkCoreError):
    pass


class InvalidProjection(WorkCoreError):
    pass


class InvalidProjectionTransition(WorkCoreError):
    """A projection would reopen or rewrite an already-terminal Execution."""


class InvalidRef(WorkCoreError):
    pass


class ProviderUnavailable(WorkCoreError):
    pass


class CapabilityUnsupported(WorkCoreError):
    pass


class DispatchFailed(WorkCoreError):
    pass


class DispatchAmbiguous(WorkCoreError):
    """A requested Dispatch's outcome cannot be proven after a crash."""


class DispatchRejected(WorkCoreError):
    pass


class ExecutionStartRejected(WorkCoreError):
    """A provider proved its accountable native start did not occur."""


class ExecutionStartIndeterminate(WorkCoreError):
    """A native start may have occurred; the Dispatch must remain ambiguous."""


class InvalidStartReceipt(WorkCoreError):
    """A provider returned a malformed or mismatched typed start receipt."""


class ContractViolation(WorkCoreError):
    pass


class InputFrozen(WorkCoreError):
    pass


class InvalidResourceObservation(WorkCoreError):
    pass


class FinalizationRequired(WorkCoreError):
    """The first terminal projection must use the atomic finalization API."""


class FinalizationConflict(WorkCoreError):
    """A finalization key or terminal Execution conflicts with this bundle."""
