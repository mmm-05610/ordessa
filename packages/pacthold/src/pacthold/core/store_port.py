"""``CoreStoreProtocol`` — the structural store seam of the core (T005-01).

``CoreRuntime`` and ``DispatchCoordinator`` consume the instance store only
through this structural face — exactly the methods they actually call: one
all-or-nothing ``transaction()`` scope, single-statement ``execute()``,
plain-tuple ``query_all()`` reads, and an idempotent ``close()``.  The method
surface is the real call face of those two consumers; nothing beyond it is
declared here.

``CoreStore`` (``pacthold.core.store``) is the kernel's own SQLite
implementation of this face.  Order 005 (T005-01) extracts the SQLite
connection/transaction *mechanism* into the environment-level persistence
package (``ordessa-persistence-sqlite``, the environment ``StorePort``
implementation); other implementations reach this core through the same
seam.  This module declares the seam only: no implementation, no state, and
no import of any implementation — import direction stays
implementation → core, never core → implementation (no reverse export).
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CoreStoreProtocol(Protocol):
    """Structural store face consumed by ``CoreRuntime``/``DispatchCoordinator``.

    Runtime admission is presence-based (``runtime_checkable``): an object is
    accepted when it carries this face, regardless of its concrete type or
    inheritance; a store missing a face method is refused at composition.
    """

    def transaction(self) -> Any:
        """One all-or-nothing write scope (context manager) on this store."""
        ...

    def execute(self, sql: str, params: tuple = ()) -> Any:
        """Single statement inside the caller's transaction scope."""
        ...

    def query_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Read helper returning plain tuple rows (no row-factory leakage)."""
        ...

    def close(self) -> None:
        """Close this store only.  Idempotent; never touches other stores."""
        ...
