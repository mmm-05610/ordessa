"""Contract-owned boundary view of the native activation result.

A structural interface, not a second model: the concrete
``NativeActivationReceipt`` (records/units journal) satisfies it. The boundary
declares only the attributes the framework reads back from the native owner,
so ``contracts`` does not depend on the records distribution.
"""
from __future__ import annotations

from typing import Protocol

from ordessa_execution_agents.harness.definitions import ApplicationTarget


class NativeActivationReceiptView(Protocol):
    operation_id: str
    target: ApplicationTarget
    manifest_digest: str
    native_session_identity: str
    applied_revision: str
    evidence_ref: str
