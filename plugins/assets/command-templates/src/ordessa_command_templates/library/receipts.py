"""Bounded, expiring expansion receipts owned by this domain (contracts.md).

The preview/insert flow mints a receipt the caller must present to insert. It
carries digests and sizes only — never the rendered body or the argument values —
so keeping it in memory leaks no user content into a list or log (FR-09). It has
a TTL and a capacity cap and is pruned by this module, not by Chat: after an
insert the draft is a Chat resource.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from ..api.dto import ExpansionReceipt
from ..api.errors import ContributorGoneError, StalePreviewError

#: Frozen receipt lifetime and cardinality (data-model.md "TTL/容量上限").
RECEIPT_TTL_SECONDS = 15 * 60
MAX_ACTIVE_RECEIPTS = 512


class ReceiptLedger:
    """A thread-safe, capped, self-expiring store of preview receipts."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 ttl: float = RECEIPT_TTL_SECONDS, capacity: int = MAX_ACTIVE_RECEIPTS) -> None:
        self._clock = clock
        self._ttl = ttl
        self._capacity = capacity
        self._lock = threading.Lock()
        self._receipts: "dict[str, tuple[ExpansionReceipt, float]]" = {}

    @property
    def ttl(self) -> float:
        return self._ttl

    @property
    def capacity(self) -> int:
        return self._capacity

    def issue(self, receipt: ExpansionReceipt) -> ExpansionReceipt:
        with self._lock:
            self._prune_locked()
            if len(self._receipts) >= self._capacity:
                # Capacity is a hard bound: refuse rather than evict a live preview.
                raise ContributorGoneError(
                    "the preview ledger is at capacity; wait for an insert or retry")
            self._receipts[receipt.operation_id] = (receipt, self._clock() + self._ttl)
            return receipt

    def get(self, operation_id: str) -> ExpansionReceipt:
        with self._lock:
            self._prune_locked()
            entry = self._receipts.get(operation_id)
            if entry is None:
                raise StalePreviewError(
                    f"receipt {operation_id!r} is unknown or expired; refresh the preview")
            return entry[0]

    def consume(self, operation_id: str) -> ExpansionReceipt:
        """Validate a receipt for insert and drop it (a receipt is single-use)."""
        with self._lock:
            self._prune_locked()
            entry = self._receipts.pop(operation_id, None)
            if entry is None:
                raise StalePreviewError(
                    f"receipt {operation_id!r} is unknown, expired or already used")
            return entry[0]

    def revoke_for(self, *, principal: str, target_fingerprint: str) -> int:
        """Drop every receipt for a principal+target when a provider unmounts."""
        removed = 0
        with self._lock:
            for op_id, (receipt, _) in list(self._receipts.items()):
                if (receipt.principal == principal
                        and receipt.target_fingerprint == target_fingerprint):
                    del self._receipts[op_id]
                    removed += 1
        return removed

    def prune(self) -> int:
        with self._lock:
            return self._prune_locked()

    def _prune_locked(self) -> int:
        now = self._clock()
        expired = [op for op, (_, exp) in self._receipts.items() if exp <= now]
        for op in expired:
            del self._receipts[op]
        return len(expired)

    def __len__(self) -> int:
        with self._lock:
            return len(self._receipts)
