"""Construct original report and acceptance admission from demand-side ports."""
from ..contracts.errors import ApplicationError
from ..usecases.changes.report_source import MethodUnitReportSource
from ..usecases.changes.declared_report import DeclaredWorkReportSource
from ..usecases.changes.acceptance_closure import SubmissionAcceptanceIntentAdmission


def build_method_unit_report_source(factory,*,method_control,blobs,bindings):
    return MethodUnitReportSource(factory,method_control,blobs,bindings)


def build_declared_unit_report_source(factory, *, method_control, blobs, source=None,
                                      correction_ports=None, content_rework_approval=None):
    """Construct or retain one report source over this exact original graph.

    ``correction_ports`` is an optional, host-selected, already assembled port
    set for the report-format-rework branch. It is never defaulted and never
    inferred; without it the ordinary report path and its refusals are unchanged.
    """
    if content_rework_approval is not None and (
            correction_ports is None
            or getattr(content_rework_approval, 'factory', None) is not factory
            or getattr(content_rework_approval, 'blobs', None) is not blobs
            or getattr(content_rework_approval, 'access', None) is not correction_ports.access
            or not callable(getattr(content_rework_approval, 'guard', None))):
        raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_UNAVAILABLE')
    if source is None:
        source = DeclaredWorkReportSource(factory, method_control, blobs,
                                          correction_ports=correction_ports)
        source.content_rework_approval = content_rework_approval
        return source
    if (type(source) is not DeclaredWorkReportSource or source.factory is not factory
            or source.methods is not method_control or source.blobs is not blobs):
        raise ApplicationError('SUBMISSION_REPORT_AUTHORITY_MISMATCH')
    if correction_ports is not None and source.correction_ports is not correction_ports:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNAVAILABLE')
    if (content_rework_approval is not None
            and getattr(source, 'content_rework_approval', None) is not content_rework_approval):
        raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_UNAVAILABLE')
    return source


def build_submission_acceptance_admission(factory,*,method_control,bindings):
    return SubmissionAcceptanceIntentAdmission(factory,method_control,bindings)


__all__=['build_method_unit_report_source','build_declared_unit_report_source','build_submission_acceptance_admission']
