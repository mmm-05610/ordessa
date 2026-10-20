"""Schema-17 Server report assembly identity checks using controlled records only.

The fixture creates an isolated schema-17 SQLite Work/package. The records and
query factory below are labeled synthetic guards: this test checks composition
identity and legacy-port retention, and never invokes native Unit records.
"""
from pathlib import Path
from dataclasses import replace
import sys
from types import SimpleNamespace

import pytest

_TEST_APPLICATIONS = Path.cwd() / "packages/engineering/tests/application"
if str(_TEST_APPLICATIONS) not in sys.path:
    sys.path.insert(0, str(_TEST_APPLICATIONS))

from test_work_package_approval_flow_v2 import build_work_package_approval
from ordessa_engineering.application.api import ApplicationError
from ordessa_server.composition.engineering_submission_assembly import (
    attach_method_unit_submission_ports,
)
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts


class _UntouchedLegacyReader:
    """Sentinel that fails if a schema-17 route inspects the legacy reader."""

    def __getattribute__(self, name):
        if name in {"__class__", "__repr__", "__str__"}:
            return object.__getattribute__(self, name)
        raise AssertionError(f"legacy reader was inspected: {name}")


class _ControlledRecords:
    """Synthetic shape only; methods fail if the assembler calls a query."""

    def __init__(self):
        self.acp_turn_available = True
        self.journal = SimpleNamespace(acp_turn_opt_in=True)

    def acp_turn_query_digest(self, *_args, **_kwargs):
        raise AssertionError("assembly must not query ACP records")

    def query_acp_turn(self, *_args, **_kwargs):
        raise AssertionError("assembly must not query ACP records")


def test_schema17_server_report_assembly_preserves_legacy_ports_and_reuses_exact_sources(
    tmp_path,
):
    with build_work_package_approval(tmp_path) as fixture:
        factory = fixture["factory"]
        method_control = fixture["env"].controls
        blobs = fixture["env"].blobs
        records = _ControlledRecords()
        query_factory = lambda *_args, **_kwargs: pytest.fail(
            "assembly must retain the callable without invoking it"
        )

        method_runs = _UntouchedLegacyReader()
        review_bindings = _UntouchedLegacyReader()
        base = EngineeringApplicationPorts(
            blobs=blobs,
            current_wait_bindings=method_runs,
        )
        kwargs = dict(
            factory=factory,
            method_control=method_control,
            blobs=blobs,
            review_bindings=review_bindings,
            method_runs=method_runs,
            phase_key="schema17-does-not-use-this-phase",
            execution_records=records,
            execution_query_factory=query_factory,
        )

        attached = attach_method_unit_submission_ports(base, **kwargs)
        assert attached.current_wait_bindings is method_runs
        assert attached.blobs is blobs
        assert attached.execution_records is records
        assert attached.execution_query_factory is query_factory
        assert attached.submission_report_source.factory is factory
        assert attached.submission_report_source.methods is method_control
        assert attached.submission_report_source.blobs is blobs
        assert not hasattr(attached.submission_report_source, "bindings")
        assert attached.acceptance_admission is None
        assert attached.submission_source is None

        # Repeated wiring returns the already-bound source and keeps all shared
        # sentinels by identity; no legacy reader, acceptance, or query is touched.
        rebound = attach_method_unit_submission_ports(attached, **kwargs)
        assert rebound.submission_report_source is attached.submission_report_source
        assert rebound.current_wait_bindings is method_runs
        assert rebound.execution_records is records
        assert rebound.execution_query_factory is query_factory
        assert rebound.acceptance_admission is None
        assert rebound.submission_source is None

        # A foreign source already present on the shared ports is a conflict.
        foreign_records = _ControlledRecords()
        foreign_base = EngineeringApplicationPorts(
            blobs=blobs,
            current_wait_bindings=method_runs,
            execution_records=foreign_records,
        )
        with pytest.raises(ApplicationError, match="SUBMISSION_REPORT_AUTHORITY_MISMATCH"):
            attach_method_unit_submission_ports(foreign_base, **kwargs)

        with pytest.raises(ApplicationError, match="SUBMISSION_REPORT_AUTHORITY_MISMATCH"):
            attach_method_unit_submission_ports(
                replace(attached, submission_report_source=object()), **kwargs)

        # Blob stores must share the SQLite UoW authority.
        foreign_blobs = SimpleNamespace(authority_id="foreign-authority")
        with pytest.raises(ApplicationError, match="SUBMISSION_REPORT_AUTHORITY_MISMATCH"):
            attach_method_unit_submission_ports(
                base,
                **{**kwargs, "blobs": foreign_blobs},
            )
