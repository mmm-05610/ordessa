"""Application error contract (single owner)."""


class ApplicationError(RuntimeError):
    def __init__(self, code: str, *, retry: str = "never", failure_diagnostic=None,
                 failure_evidence_ref=None, failure_evidence_linked=False):
        if failure_diagnostic is not None:
            from .failure_diagnostic import FailureDiagnostic
            if type(failure_diagnostic) is not FailureDiagnostic:
                raise TypeError('Validated failure diagnostic required')
        if failure_evidence_ref is not None:
            from ...domain.common.models.refs import BlobRef
            if type(failure_evidence_ref) is not BlobRef:
                raise TypeError('Original failure evidence reference required')
        if (type(failure_evidence_linked) is not bool
                or failure_evidence_linked and failure_evidence_ref is None):
            raise TypeError('Failure evidence linkage requires its original reference')
        super().__init__(code)
        self.code = code
        self.retry = retry
        self.failure_diagnostic = failure_diagnostic
        self.failure_evidence_ref = failure_evidence_ref
        self.failure_evidence_linked = failure_evidence_linked


__all__ = ['ApplicationError']
