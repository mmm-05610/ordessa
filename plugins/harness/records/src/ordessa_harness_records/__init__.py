"""Explicit deployment-owned records; import performs no storage or native IO.

All journal/UnitRecords classes have one implementation. Importing this package
neither provisions storage nor grants authority; callers supply the original
journal and trusted owner ports explicitly.
"""
from .operation_journal import OperationJournal, JournalError, FenceObservation, NativeActivationReceipt
from .unit_records import UnitRecords, UnitRecordsRefused

__all__ = ["OperationJournal", "JournalError", "FenceObservation", "NativeActivationReceipt",
           "UnitRecords", "UnitRecordsRefused"]
