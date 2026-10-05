"""Harness application operation journal (no external executor)."""

from .operation_journal import FenceObservation, NativeActivationReceipt, OperationJournal, JournalError
_SERVICE_EXPORTS={'ConfigurationApplicationService','NativeReadback','RuntimeSnapshot'}
_EVIDENCE_EXPORTS={'ControlledNativeStandIn','EVIDENCE_SUPPORTED_BRANDS','EVIDENCE_UNSUPPORTED_BRANDS',
    'NativeEvidenceService','NativeEvidenceUnsupported','supply_brand_evidence'}


def __getattr__(name):
    # Preserve existing imports on explicit use while a UnitRecords-only
    # composition never imports another family's configuration/runtime code.
    if name in _SERVICE_EXPORTS:
        from . import configuration_service
        return getattr(configuration_service,name)
    if name in _EVIDENCE_EXPORTS:
        from . import native_evidence
        return getattr(native_evidence,name)
    raise AttributeError(name)

__all__ = [
    "ConfigurationApplicationService", "ControlledNativeStandIn",
    "EVIDENCE_SUPPORTED_BRANDS", "EVIDENCE_UNSUPPORTED_BRANDS",
    "FenceObservation", "JournalError",
    "NativeActivationReceipt", "NativeEvidenceService", "NativeEvidenceUnsupported",
    "NativeReadback", "OperationJournal", "RuntimeSnapshot", "supply_brand_evidence",
]
