"""``ordessa_persistence_sqlite`` — SQLite adapters for the frozen ports.

Public surface:

* :class:`SqliteStorePort` — the E1 StorePort over one SQLite file with C2
  same-root writer exclusivity, request-key claims, response slots and key
  tombstones;
* :class:`ProtectedFingerprintHmac` — the C2 fingerprint port (test keys are
  fixtures; production material comes from a secret port);
* :mod:`ordessa_persistence_sqlite.legacy_read` — READ-ONLY view over the
  sealed compat history schema (T005-02). The business DDL itself stays
  sealed in the archived migrations; nothing here writes to those tables.
"""
from .relationships import SqliteRelationshipStore
from .store import KeyConflictError, SqliteStorePort, WriterLockHeldError
from .fingerprint import ProtectedFingerprintHmac

__all__ = [
    "KeyConflictError",
    "SqliteRelationshipStore",
    "ProtectedFingerprintHmac",
    "SqliteStorePort",
    "WriterLockHeldError",
]
