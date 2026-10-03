"""T005-01 store-seam tests: the core consumes the structural store face only.

``CoreRuntime`` is composed over the runtime-checkable
``CoreStoreProtocol`` face — the real call surface of
``CoreRuntime``/``DispatchCoordinator`` (``transaction``/``execute``/
``query_all``/``close``) — not over the concrete ``CoreStore`` class.  The
direction of admission is structural: any object carrying the face plugs in,
and the kernel's own SQLite implementation is just one such object.  Pinned
here:

* positive — a minimal in-memory stub implementing exactly the protocol face
  (no SQLite, no ``CoreStore`` inheritance) drives the stage/commit
  registration path, the store-backed ledger reads and the close/shutdown
  path;
* negative — an object missing a face method is refused with ``TypeError``
  at composition (typed refusal before any state is built);
* ``CoreStore`` still satisfies the protocol by structure (isinstance), so
  every existing ``CoreStore(path)`` construction consumer keeps working.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import pytest

from pacthold.core.registration import CoreContributionSet
from pacthold.core.runtime import CoreRuntime
from pacthold.core.store import CoreStore
from pacthold.core.store_port import CoreStoreProtocol


@dataclass(frozen=True)
class _SeamContract:
    """A minimal frozen dataclass contract (same shape rule as C1 staging)."""

    contract_id: str = "seam.contract@1"


class MemoryStoreStub:
    """A minimal in-memory implementation of the ``CoreStoreProtocol`` face.

    Deliberately NOT a ``CoreStore`` subclass — admission must be structural,
    not inheritance-based.  ``query_all`` answers like a fresh database (no
    tables, no recorded facts), which is exactly what the registration /
    ledger / shutdown paths read on a store with no dispatch history; no
    statement is ever written on these paths.
    """

    def __init__(self) -> None:
        self.closed = False
        self.transactions_opened = 0

    @contextmanager
    def transaction(self):
        self.transactions_opened += 1
        yield self  # an in-memory stub has no connection object to hand out

    def execute(self, sql: str, params: tuple = ()):
        raise AssertionError("registration/ledger/close paths issue no statements")

    def query_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        return []  # a fresh store: no sqlite_master tables, no facts

    def close(self) -> None:
        self.closed = True


def _contributions() -> CoreContributionSet:
    return CoreContributionSet(
        contracts=(_SeamContract,), resource_providers=(), execution_providers=()
    )


# ---------------------------------------------------------------------------
# positive: a protocol-shaped stub drives the real registration path
# ---------------------------------------------------------------------------


def test_memory_stub_store_admitted_and_drives_registration_path():
    stub = MemoryStoreStub()
    # structural admission: no inheritance from CoreStore involved
    assert isinstance(stub, CoreStoreProtocol)
    assert not isinstance(stub, CoreStore)

    runtime = CoreRuntime(stub)  # injected through the CoreStoreProtocol seam
    registration = runtime.stage("owner", _contributions())
    assert registration.state == "staged"
    assert runtime.registry_snapshot().contract_ids == ()  # staged publishes nothing

    registration.commit()
    assert runtime.registry_snapshot().contract_ids == ("seam.contract@1",)
    assert runtime.owner_busy("owner") is True

    runtime.unregister("owner")  # ledger read goes through stub.query_all: no leases
    assert runtime.owner_busy("owner") is False
    assert runtime.owner_busy("stranger") is False  # store-backed ledger: empty

    report = runtime.close()
    assert report.unresolved_executions == ()
    assert report.unresolved_leases == ()
    assert report.cleanup_failures == ()
    assert stub.closed is True  # shutdown reached the store through the seam


def test_runtime_store_property_returns_the_injected_seam_object():
    stub = MemoryStoreStub()
    runtime = CoreRuntime(stub)
    assert runtime.store is stub


# ---------------------------------------------------------------------------
# negative: a store missing the face is refused at composition
# ---------------------------------------------------------------------------


def test_store_missing_close_is_refused_at_composition():
    class NoClose:
        def transaction(self): ...

        def execute(self, sql, params=()): ...

        def query_all(self, sql, params=()):
            return []

    with pytest.raises(TypeError, match="CoreStoreProtocol"):
        CoreRuntime(NoClose())  # type: ignore[arg-type]


def test_store_missing_query_surface_is_refused_at_composition():
    class NoReads:
        def transaction(self): ...

        def execute(self, sql, params=()): ...

        def close(self): ...

    with pytest.raises(TypeError, match="CoreStoreProtocol"):
        CoreRuntime(NoReads())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# the kernel's own SQLite implementation still plugs into the same seam
# ---------------------------------------------------------------------------


def test_core_store_satisfies_the_protocol(tmp_path):
    store = CoreStore(tmp_path / "core.db")
    try:
        assert isinstance(store, CoreStoreProtocol)
        # the concrete constructor surface legacy consumers rely on is intact
        assert store.path == str(tmp_path / "core.db")
    finally:
        store.close()
    assert store.is_closed
