"""Original-library Submission source admission for the fixed report method."""
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace

from ordessa_infrastructure.encoding import canonical_bytes
from ....application.contracts.errors import ApplicationError
from ....application.contracts.commands import CommandContext
from ....application.orchestration.dispatch_method_run import resolve_method_run_package
from ....application.orchestration.method_runs import MethodRunBindings
from ....application.orchestration.steps.implementation_dispatch import (
    resolve_dispatch_submission_binding,
)
from ....application.usecases.changes.acceptance_closure import resolve_submission_acceptance
from ....application.usecases.changes.execution_capture import capture_execution_observation
from ....application.usecases.changes.report_source import MethodUnitReportSource
from ....application.usecases.changes.submissions import SubmissionUseCases
from ....domain.changes.dispatch_codec import decode_dispatch
from ....domain.changes.submission import Submission
from ....domain.common.models.refs import BlobRef
from ....domain.packages.models import ImplementationPackage
from ....methods.definitions.models.compiled import OperationNode, thaw_value
from ....application.contracts.execution_dispatch import EXECUTION_DISPATCH
from .method_report_bindings import SQLiteMethodUnitReportBindings
from .unit_of_work import SQLiteUoWFactory


class SQLiteSubmissionSource:
    """Verify a persisted report Submission against its original owners.

    Native observations are cold-read through the selected original UnitRecords
    query producer. They are never dispatched again. Execution and Engineering
    use different authorities, so this source does not claim a cross-store
    atomic transaction; it binds the captured observation to the immutable
    Submission and retains Engineering method/artifact guards through COMMIT.
    """

    def __init__(
        self,
        factory,
        *,
        method_runs,
        report_source,
        execution_records,
        blobs,
        execution_query_factory,
    ):
        from .blob_store import SQLiteBlobStore
        if type(factory) is not SQLiteUoWFactory or factory.library.schema_version != 15:
            raise ApplicationError("SUBMISSION_SOURCE_AUTHORITY_MISMATCH")
        if type(method_runs) is not MethodRunBindings or method_runs.factory is not factory:
            raise ApplicationError("SUBMISSION_SOURCE_METHOD_RUN_AUTHORITY_MISMATCH")
        if (type(report_source) is not MethodUnitReportSource
                or report_source.factory is not factory
                or report_source.methods is not method_runs.methods
                or type(report_source.bindings) is not SQLiteMethodUnitReportBindings
                or report_source.bindings.factory is not factory
                or report_source.bindings.methods is not method_runs.methods):
            raise ApplicationError("SUBMISSION_SOURCE_REPORT_AUTHORITY_MISMATCH")
        if (type(blobs) is not SQLiteBlobStore or blobs.library is not factory.library
                or blobs.authority_id != factory.authority_id
                or report_source.blobs is not blobs
                or not callable(getattr(blobs, "read_verified", None))
                or not callable(getattr(blobs, "put_verified", None))):
            raise ApplicationError("SUBMISSION_SOURCE_BLOB_AUTHORITY_MISMATCH")
        journal = getattr(execution_records, "journal", None)
        if (getattr(execution_records, "acp_turn_available", None) is not True
                or getattr(journal, "acp_turn_opt_in", None) is not True
                or not callable(getattr(execution_records, "acp_turn_query_digest", None))
                or not callable(getattr(execution_records, "query_acp_turn", None))
                or not callable(execution_query_factory)):
            raise ApplicationError("SUBMISSION_SOURCE_EXECUTION_AUTHORITY_UNAVAILABLE")
        work_source = method_runs.source
        if (getattr(work_source, "factory", None) is not factory
                or getattr(work_source, "methods", None) is not method_runs.methods
                or getattr(work_source, "blobs", None) is not blobs
                or getattr(work_source, "execution_records", None) is not execution_records
                or getattr(work_source, "execution_query_factory", None) is not execution_query_factory):
            raise ApplicationError("SUBMISSION_SOURCE_EXECUTION_AUTHORITY_MISMATCH")
        self.factory = factory
        self.method_runs = method_runs
        self.methods = method_runs.methods
        self.report_source = report_source
        self.records = execution_records
        self.blobs = blobs
        self.execution_query_factory = execution_query_factory

    @staticmethod
    def _unit_ref(execution):
        from ordessa_infrastructure.encoding import decode_json
        return {
            "environmentNamespace": execution.environment_namespace,
            "unitId": execution.unit_id,
            "ownerProviderRef": decode_json(execution.owner_provider_ref_bytes),
            "sourceRevision": execution.source_revision,
        }

    def _require_canonical_methodrun_binding(self, uow, submission, package, binding):
        from ....application.orchestration.method_runs import MethodRunBindings
        from ....domain.packages.codec import decode_package_ref
        from ....methods.definitions.models.compiled import CompiledProgram

        row = uow.workflow.run_row(binding.run_id)
        method_ref = MethodRunBindings._inputs(SimpleNamespace(scope=uow.scope), row)
        snapshot = uow.methods.read_snapshot(method_ref)
        program = MethodRunBindings._bound_program(snapshot, method_ref, row)
        if type(program) is not CompiledProgram:
            raise ApplicationError("SUBMISSION_DISPATCH_BINDING_MISMATCH")
        nodes = tuple(node for node in program.workflow.steps if node.id == binding.step_id)
        if len(nodes) != 1 or type(nodes[0]) is not OperationNode or nodes[0].operation != EXECUTION_DISPATCH:
            raise ApplicationError("SUBMISSION_DISPATCH_BINDING_MISMATCH")
        config = {} if nodes[0].config is None else thaw_value(nodes[0].config)
        slot = config.get("package_slot") if type(config) is dict else None
        slots = row["inputs"].get("slots")
        if (type(slot) is not str or slot not in (program.workflow.context_slots or ())
                or type(slots) is not dict or slot not in slots):
            raise ApplicationError("SUBMISSION_DISPATCH_BINDING_MISMATCH")
        try:
            slot_ref = decode_package_ref(slots[slot])
        except Exception as exc:
            raise ApplicationError("SUBMISSION_DISPATCH_BINDING_MISMATCH") from exc
        selected = resolve_method_run_package(
            uow, binding.run_id, self.method_runs, step_id=binding.step_id,
        )
        if selected != package or slot_ref != package.ref or submission.package_ref != package.ref:
            raise ApplicationError("SUBMISSION_DISPATCH_BINDING_MISMATCH")

    @contextmanager
    def guard_submission(self, context, submission, package):
        if (type(context) is not CommandContext
                or type(submission) is not Submission or type(package) is not ImplementationPackage
                or submission.scope != context.scope or package.scope != context.scope
                or submission.package_ref != package.ref):
            raise ApplicationError("SUBMISSION_SOURCE_BINDING_MISMATCH")
        try:
            SubmissionUseCases._validate_report_fact_shape(submission)
            with self.factory.begin(context.scope, "read") as uow:
                closure = resolve_submission_acceptance(
                    uow, submission.ref, method_runs=self.method_runs,
                )
                persisted = uow.submissions.resolve(submission.ref)
                current_package = uow.implementation.resolve_package(package.ref)
                if (persisted != submission or current_package != package
                        or closure.submission != submission or closure.package != package):
                    raise ApplicationError("SUBMISSION_SOURCE_BINDING_MISMATCH")
                binding = resolve_dispatch_submission_binding(
                    uow, submission, method_runs=self.method_runs,
                )
                self._require_canonical_methodrun_binding(uow, submission, package, binding)
                row = uow.dispatch.by_operation(
                    submission.execution_ref.operation_ref, context.scope,
                )
                if (row["dispatch_phase"] != "completed"
                        or row["result_blob_json"] != canonical_bytes(
                            asdict(submission.execution_ref.captured_observation_ref)
                        ).decode("utf-8")):
                    raise ApplicationError("SUBMISSION_SOURCE_EXECUTION_NOT_COMPLETED")
            execution = submission.execution_ref
            captured = capture_execution_observation(
                self.records,
                self.blobs,
                authority_id=self.factory.authority_id,
                unit_ref=self._unit_ref(execution),
                operation_ref=execution.operation_ref,
                expected_prompt_digest="sha256:" + execution.prompt_input_digest.hex,
                query_invocation=self.execution_query_factory(binding),
            )
            if (captured.state != "completed"
                    or captured.unit_ref != self._unit_ref(execution)
                    or captured.operation_ref != execution.operation_ref
                    or captured.expected_prompt_digest != "sha256:" + execution.prompt_input_digest.hex
                    or captured.query_digest != binding.expected_query_digest
                    or captured.blob_ref != execution.captured_observation_ref
                    or captured.authority_id != self.factory.authority_id):
                raise ApplicationError("SUBMISSION_SOURCE_EXECUTION_BINDING_MISMATCH")
            with self.report_source.guard_report(context, package, submission, captured) as admission:
                SubmissionUseCases._validate_report_admission(
                    submission, package, captured, admission,
                )
                yield None
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("SUBMISSION_SOURCE_PROVENANCE_UNAVAILABLE") from exc


__all__ = ["SQLiteSubmissionSource"]
