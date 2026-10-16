"""Current method-bound Unit report admission; authored claims remain asserted."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ...contracts.errors import ApplicationError
from ...orchestration.method_content import document_spec, validate_document_content
from ....domain.common.models.values import Digest


@dataclass(frozen=True)
class DeclaredUnitReportBinding:
    document_type: str
    execution_ref: object
    output_refs: tuple


@dataclass(frozen=True)
class VerifiedUnitReport:
    method_ref: object
    report_schema_ref: object
    output_refs: tuple
    report_content_digest: Digest
    execution_operation_ref: str
    prompt_input_digest: Digest
    query_digest: str
    captured_observation_ref: object


class MethodUnitReportSource:
    """Combine original MethodControl, BlobStore and trusted business binding.

    bindings.guard_report_binding resolves the original work/step/attempt and
    author Unit identity, method-declared report type and fixed outputs. It must
    hold current source/authority guards through the caller's COMMIT. No caller
    binding, default role, repository scan or test execution is accepted here.
    """
    def __init__(self, factory, method_control, blobs, bindings):
        if (getattr(method_control, 'factory', None) is not factory
                or getattr(blobs, 'authority_id', None) != factory.authority_id
                or bindings is None or getattr(bindings, 'factory', None) is not factory):
            raise ApplicationError('SUBMISSION_REPORT_AUTHORITY_MISMATCH')
        self.factory, self.methods, self.blobs, self.bindings = factory, method_control, blobs, bindings

    @contextmanager
    def guard_report(self, context, package, submission, captured):
        method = package.payload.method_ref
        with self.methods.guard_selected(context) as snapshot:
            selected = snapshot.ref
            if (selected.method_id, selected.release_version, selected.schema_version,
                    selected.snapshot_digest) != (method.method_id, method.release_version,
                    method.schema_version, method.snapshot_digest.hex):
                raise ApplicationError('SUBMISSION_REPORT_METHOD_MISMATCH')
            with self.bindings.guard_report_binding(context, snapshot, package, submission) as binding:
                if (type(binding) is not DeclaredUnitReportBinding
                        or binding.execution_ref != submission.execution_ref
                        or binding.output_refs != submission.output_refs):
                    raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
                content = submission.method_content
                spec = document_spec(snapshot, binding.document_type)
                exact = content.schema_ref
                resources = [r for r in snapshot.resources if r.resource_id == exact.resource_id]
                if (exact.method_ref != method or len(resources) != 1
                        or resources[0].logical_path != exact.logical_path
                        or resources[0].digest != exact.resource_digest.hex
                        or spec.schema_ref.resource_id != exact.resource_id
                        or spec.schema_ref.sha256 != exact.resource_digest.hex):
                    raise ApplicationError('SUBMISSION_REPORT_SCHEMA_MISMATCH')
                valid = validate_document_content(snapshot, binding.document_type, {'value': content.value})
                if not valid.ok:
                    raise ApplicationError(valid.error.code)
                receipt = decode_json(self.blobs.read_verified(captured.blob_ref))
                summary = receipt.get('summary')
                if (captured.state != 'completed' or receipt.get('state') != 'completed'
                        or type(summary) is not dict or summary.get('successfulRpcResponse') is not True
                        or type(summary.get('text')) is not str):
                    raise ApplicationError('SUBMISSION_REPORT_OUTPUT_UNAVAILABLE')
                try:
                    reported = decode_json(summary['text'].encode('utf-8'))
                    raw = canonical_bytes(reported)
                except (ValueError, TypeError, UnicodeError):
                    raise ApplicationError('SUBMISSION_REPORT_OUTPUT_INVALID') from None
                if raw != content.value_bytes:
                    raise ApplicationError('SUBMISSION_REPORT_OUTPUT_MISMATCH')
                yield VerifiedUnitReport(method, exact, binding.output_refs,
                    Digest('sha256', hashlib.sha256(raw).hexdigest()),
                    submission.execution_ref.operation_ref, submission.execution_ref.prompt_input_digest,
                    captured.query_digest, captured.blob_ref)
