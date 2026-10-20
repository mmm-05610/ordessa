"""The actual operator must keep the closed diagnostic from its wire error."""
from dataclasses import asdict
import importlib.util
from pathlib import Path

from ordessa_engineering.application.api import ApplicationError, FailureDiagnostic
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_system_access_bindings.engineering_wire import _failure


path = Path(__file__).resolve().parents[3] / 'tooling/checks/server_product/probe-work-package-generation.py'
spec = importlib.util.spec_from_file_location('failure_diagnostic_operator', path)
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)


def test_operator_receipt_keeps_wire_diagnostic_and_link_status_without_exception_text():
    diagnostic = FailureDiagnostic.capture(OSError('do-not-copy-secret-text'), 'native_send')
    ref = BlobRef(Digest('sha256', 'a' * 64), len(diagnostic.encoded),
        'application/vnd.ordessa.dispatch-failure+json', 'bounded-diagnostic-blob')
    for linked in (False, True):
        error = ApplicationError('WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED', retry='reconcile',
            failure_diagnostic=diagnostic, failure_evidence_ref=ref, failure_evidence_linked=linked)
        for actual in (error, _failure(error)):
            saved = operator.safe_error(actual)
            assert saved['failure_diagnostic'] == diagnostic.to_dict()
            assert saved['failure_evidence_ref'] == asdict(ref)
            assert saved['failure_evidence_linked'] is linked
            assert 'do-not-copy-secret-text' not in repr(saved)


def test_operator_receipt_omits_arbitrary_error_data_and_diagnostic_fields():
    error = RuntimeError('do-not-copy-secret-text')
    error.failure_diagnostic = {'message': 'do-not-copy-secret-text'}
    error.data = {'failureDiagnostic': {'message': 'do-not-copy-secret-text'},
        'failureEvidenceRef': {'private': 'do-not-copy-secret-text'}}
    saved = operator.safe_error(error)
    assert set(saved) == {'type'}
