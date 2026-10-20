"""Bind original method-declared report and acceptance sources to one graph."""
from dataclasses import replace

from ordessa_engineering.adapters.review_sources import (
    SQLiteMethodUnitReportBindings,
    SQLiteReviewBindings,
)
from ordessa_engineering.adapters.submission_sources import SQLiteSubmissionSource
from ordessa_engineering.application.api import ApplicationError
from ordessa_engineering.application.assembly import (
    build_method_unit_report_source,
    build_declared_unit_report_source,
    build_submission_acceptance_admission,
)
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts


def attach_method_unit_submission_ports(
    base_ports,
    *,
    factory,
    method_control,
    blobs,
    review_bindings,
    method_runs,
    phase_key,
    execution_records,
    execution_query_factory,
):
    """Attach report/acceptance ports over the caller's existing owner graph.

    The phase key is trusted method-selection data supplied by product
    composition. This helper neither chooses a phase nor resolves a Submission.
    """
    if getattr(getattr(factory, 'library', None), 'schema_version', None) == 17:
        # The current declared report has no compiled phase or MethodRun
        # dependency. Retain shared historical readers for their other owners;
        # this path neither inspects nor replaces those readers.
        if (type(base_ports) is not EngineeringApplicationPorts
                or getattr(method_control, 'factory', None) is not factory
                or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)
                or execution_records is None
                or getattr(execution_records, 'acp_turn_available', None) is not True
                or getattr(getattr(execution_records, 'journal', None), 'acp_turn_opt_in', None) is not True
                or not callable(getattr(execution_records, 'acp_turn_query_digest', None))
                or not callable(getattr(execution_records, 'query_acp_turn', None))
                or not callable(execution_query_factory)
                or base_ports.submission_source is not None
                or base_ports.blobs is not None and base_ports.blobs is not blobs
                or base_ports.execution_records is not None and base_ports.execution_records is not execution_records
                or base_ports.execution_query_factory is not None and base_ports.execution_query_factory is not execution_query_factory):
            raise ApplicationError('SUBMISSION_REPORT_AUTHORITY_MISMATCH')
        report_source = build_declared_unit_report_source(
            factory, method_control=method_control, blobs=blobs,
            source=base_ports.submission_report_source)
        return replace(base_ports, blobs=blobs, submission_report_source=report_source,
            execution_records=execution_records, execution_query_factory=execution_query_factory)
    if (type(base_ports) is not EngineeringApplicationPorts
            or type(review_bindings) is not SQLiteReviewBindings
            or getattr(review_bindings, "factory", None) is not factory
            or getattr(review_bindings, "methods", None) is not method_control
            or getattr(method_control, "factory", None) is not factory
            or getattr(method_runs, 'factory', None) is not factory
            or getattr(method_runs, 'methods', None) is not method_control
            or getattr(blobs, "authority_id", None) != getattr(factory, "authority_id", None)
            or type(phase_key) is not str or not phase_key
            or execution_records is None
            or getattr(execution_records, "acp_turn_available", None) is not True
            or getattr(getattr(execution_records, "journal", None), "acp_turn_opt_in", None) is not True
            or not callable(getattr(execution_records, "acp_turn_query_digest", None))
            or not callable(getattr(execution_records, "query_acp_turn", None))
            or not callable(execution_query_factory)):
        raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")
    work_source = getattr(method_runs, 'source', None)
    if (getattr(work_source, "factory", None) is not factory
            or getattr(work_source, "methods", None) is not method_control
            or getattr(work_source, "blobs", None) is not blobs
            or getattr(work_source, "execution_records", None) is not execution_records
            or getattr(work_source, "execution_query_factory", None) is not execution_query_factory):
        raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")
    admission = base_ports.review_admission
    if ((admission is not None and (
                getattr(admission, "factory", None) is not factory
                or getattr(admission, "methods", None) is not method_control
                or getattr(admission, "bindings", None) is not review_bindings))
            or (base_ports.blobs is not None and base_ports.blobs is not blobs)
            or (base_ports.execution_records is not None
                and base_ports.execution_records is not execution_records)
            or (base_ports.execution_query_factory is not None
                and base_ports.execution_query_factory is not execution_query_factory)
            or (base_ports.current_wait_bindings is not None
                and base_ports.current_wait_bindings is not method_runs)):
        raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")
    old_report = base_ports.submission_report_source
    if old_report is not None:
        old_bindings = getattr(old_report, "bindings", None)
        if (getattr(old_report, "factory", None) is not factory
                or getattr(old_report, "methods", None) is not method_control
                or getattr(old_report, "blobs", None) is not blobs
                or type(old_bindings) is not SQLiteMethodUnitReportBindings
                or getattr(old_bindings, "factory", None) is not factory
                or getattr(old_bindings, "methods", None) is not method_control
                or getattr(old_bindings, "phase_key", None) != phase_key):
            raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")
    old_acceptance = base_ports.acceptance_admission
    if old_acceptance is not None and (
            getattr(old_acceptance, "factory", None) is not factory
            or getattr(old_acceptance, "methods", None) is not method_control
            or getattr(old_acceptance, "bindings", None) is not review_bindings
            or not callable(getattr(old_acceptance, 'guard_intent', None))):
        raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")
    old_submission_source = base_ports.submission_source
    if old_submission_source is not None and (
            type(old_submission_source) is not SQLiteSubmissionSource
            or old_submission_source.factory is not factory
            or old_submission_source.method_runs is not method_runs
            or old_submission_source.report_source is not old_report
            or old_submission_source.records is not execution_records
            or old_submission_source.blobs is not blobs
            or old_submission_source.execution_query_factory is not execution_query_factory):
        raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")

    if old_report is None:
        report_bindings = SQLiteMethodUnitReportBindings(
            factory, method_control, phase_key=phase_key)
        report_source = build_method_unit_report_source(
            factory, method_control=method_control, blobs=blobs,
            bindings=report_bindings)
    else:
        report_source = old_report
        report_bindings = old_report.bindings
    acceptance_admission = (old_acceptance if old_acceptance is not None else
        build_submission_acceptance_admission(
            factory, method_control=method_control, bindings=review_bindings))
    if (report_source.factory is not factory
            or report_source.methods is not method_control
            or report_source.blobs is not blobs
            or report_source.bindings is not report_bindings
            or acceptance_admission.factory is not factory
            or acceptance_admission.methods is not method_control
            or acceptance_admission.bindings is not review_bindings):
        raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")
    submission_source = (old_submission_source if old_submission_source is not None else
        SQLiteSubmissionSource(
            factory, method_runs=method_runs, report_source=report_source,
            execution_records=execution_records, blobs=blobs,
            execution_query_factory=execution_query_factory))
    if (submission_source.factory is not factory
            or submission_source.method_runs is not method_runs
            or submission_source.report_source is not report_source
            or submission_source.records is not execution_records
            or submission_source.blobs is not blobs
            or submission_source.execution_query_factory is not execution_query_factory):
        raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")
    return replace(base_ports,
        blobs=blobs,
        current_wait_bindings=method_runs,
        submission_report_source=report_source,
        acceptance_admission=acceptance_admission,
        submission_source=submission_source,
        execution_records=execution_records,
        execution_query_factory=execution_query_factory)


__all__ = ["attach_method_unit_submission_ports"]
