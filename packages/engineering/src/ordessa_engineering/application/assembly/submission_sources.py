"""Construct original report and acceptance admission from demand-side ports."""
from ..usecases.changes.report_source import MethodUnitReportSource
from ..usecases.changes.acceptance_closure import SubmissionAcceptanceIntentAdmission


def build_method_unit_report_source(factory,*,method_control,blobs,bindings):
    return MethodUnitReportSource(factory,method_control,blobs,bindings)


def build_submission_acceptance_admission(factory,*,method_control,bindings):
    return SubmissionAcceptanceIntentAdmission(factory,method_control,bindings)


__all__=['build_method_unit_report_source','build_submission_acceptance_admission']
