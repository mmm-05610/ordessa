"""Original report-source refusal for an honestly recorded failed dispatch.

The frozen 2.6 candidate is not compiled or run here. This controlled case
qualifies the existing native report source guard against a normal failed
terminal row persisted through the repository helper.
"""
from __future__ import annotations

import pytest

from ordessa_engineering.adapters.persistence.sqlite.method_report_bindings import (
    SQLiteMethodUnitReportBindings,
)
from ordessa_engineering.application.contracts.errors import ApplicationError

from submission_wait_business_fixture import build_submission_wait_fixture


@pytest.mark.parametrize("phase", ("completed", "failed"))
def test_original_report_source_requires_completed_terminal_dispatch(tmp_path, phase):
    env = build_submission_wait_fixture(
        tmp_path, report_phase=True, native_dispatch_phase=phase
    )
    try:
        assert env["native"]["dispatch_phase"] == phase
        source = SQLiteMethodUnitReportBindings(
            env["factory"], env["controls"], phase_key="record_report"
        )
        if phase == "completed":
            with source.guard_report_binding(
                env["context"], env["snapshot"], env["package"], env["submission"]
            ) as binding:
                assert binding.execution_ref == env["submission"].execution_ref
                assert binding.output_refs == env["submission"].output_refs
            return
        with pytest.raises(ApplicationError) as error:
            with source.guard_report_binding(
                env["context"], env["snapshot"], env["package"], env["submission"]
            ):
                pytest.fail("a failed native dispatch cannot qualify a report capture")
        assert error.value.code == "SUBMISSION_REPORT_BINDING_MISMATCH"
    finally:
        env["library"].close()
