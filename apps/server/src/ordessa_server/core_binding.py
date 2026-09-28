"""``CoreBinding`` — the single Pacthold seam of one Server composition (T015).

Shape (fixed by ``specs/010-platform-core/reports/B.md`` §"T015 seam decision"):

* exactly ONE class, constructed ONCE PER COMPOSITION by
  ``bootstrap/runtime.build_runtime`` and handed to consumers through the
  existing host wall (``host_ports["core.binding"]`` for declaring plugins,
  the per-composition resolver position for host-side consumers — the same
  shape as ``harness_resolver`` / ``error_family_resolver``).  It is never a
  module-level singleton: S2a-R proved in this repo that per-composition
  state on a module global leaks across hosts in one process, and a Core
  binding installed that way would be strictly worse.
* imports come ONLY from ``pacthold.public`` (the facade's own docstring is
  the authority on what it exposes; ``packages/pacthold/tests/platform/
  test_public_contract.py`` locks it).  No dataclass here mirrors a C1 type.
* the C2→C1 step is a TRANSLATION BY IDENTITY: the plugin's opaque
  ``Contribution`` payload is handed to ``CoreContributionSet`` construction
  as-is (``_as_contribution_set``).  If a payload shape does not fit the C1
  constructor, that is a report-worthy mismatch, surfaced as the constructor
  error — never reshaped inside the host.
* failure semantics inherit the T012/T013 registration transaction: a
  raising ``stage`` aborts the round with zero leaked contributions and the
  owner stays unbound (``CoreRegistry.stage`` validates against local copies
  and reserves nothing until the whole batch checks out).
* ``close()`` runs BEFORE any store teardown in the composition's stop path
  and SURFACES the ``ShutdownReport`` instead of discarding it.

Store topology (S1c decision, landed in the same commit as required): the
composition's C1 Core gets its OWN file inside the data root
(``<data root>/state/core.sqlite``), never the legacy product database file.
``CoreStore`` is self-owned (``sqlite3.connect(path, timeout=10.0,
check_same_thread=False)``, no connection-injection seam), and the host's
in-process write lock does not serialise a second OS-level connection on the
same file — so a shared legacy file would rest on sqlite's bare 10 s timeout
for every multi-statement write sequence that the legacy chain performs
outside one explicit transaction.  The counterexample witness for that
decision is ``apps/server/tests/platform/
test_platform_core_instance_124.py::
test_shared_file_topology_counterexample_double_applies_a_write``; the two
live compositions gate ("关闭 A 后 B 仍可读写") is proven in the same module
with two real compositions in one process.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pacthold.public import (
    CoreContributionSet,
    CoreRegistration,
    CoreRegistrySnapshot,
    CoreRuntime,
    CoreStore,
    ExecutionPlan,
    ExecutionView,
    OwnerNotRegisteredError,
    ReconcileResult,
    RuntimeClosedError,
    ShutdownReport,
    StopDispatchResult,
    SubmitResult,
)


def _as_contribution_set(payload: Any) -> CoreContributionSet:
    """Translate the plugin's opaque C2 payload to C1 by identity.

    Accepted shapes, tried in order: an already-built ``CoreContributionSet``
    (passed through untouched), a mapping of the C1 constructor's own keyword
    names (expanded verbatim), or any object exposing the three C1 field
    names (handed to the constructor as-is).  Anything else raises from the
    C1 constructor itself — the mismatch stays visible at the seam.
    """
    if isinstance(payload, CoreContributionSet):
        return payload
    if isinstance(payload, Mapping):
        return CoreContributionSet(**payload)
    return CoreContributionSet(
        contracts=payload.contracts,
        resource_providers=payload.resource_providers,
        execution_providers=payload.execution_providers,
    )


class CoreBinding:
    """One composition's whole Pacthold core: one instance store, one runtime.

    Lifecycle: constructed cold by ``build_runtime`` (no file, no connection);
    the first verb opens the round lazily, so a composition that never uses
    Core never grows a core file.  ``close()`` retires the round and keeps
    the ``ShutdownReport``; ``open()`` on a closed binding starts the next
    round over the same server-owned file (a restart, not a resurrection —
    in-memory registration state is the new round's, durable facts stay in
    the store, exactly ``CoreRuntime``'s own restart contract).
    """

    def __init__(self, store_path: Path | str) -> None:
        if not isinstance(store_path, (Path, str)):
            raise TypeError(f"CoreBinding store_path must be Path or str, got {store_path!r}")
        self._store_path = str(store_path)
        self._store: CoreStore | None = None
        self._runtime: CoreRuntime | None = None
        self._ever_opened = False
        self._shutdown_report: ShutdownReport | None = None

    # -- identity / topology facts (plain data, never C1 mirrors) -----------

    @property
    def store_path(self) -> str:
        return self._store_path

    @property
    def ever_opened(self) -> bool:
        return self._ever_opened

    @property
    def shutdown_report(self) -> Any | None:
        """The last ``close()`` report, surfaced (never swallowed) for the
        composition's owner to read after the round retired."""
        return self._shutdown_report

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> CoreRuntime:
        """Start (or restart after a close) this composition's Core round."""
        if self._runtime is not None:
            return self._runtime
        self._store = CoreStore(self._store_path)
        self._runtime = CoreRuntime(self._store)
        self._ever_opened = True
        return self._runtime

    def close(self) -> ShutdownReport:
        """Retire the round: ``CoreRuntime.close()`` FIRST (it surfaces the
        report and closes its own store last); an unopened binding reports
        the empty shutdown fact without ever touching the filesystem."""
        if self._runtime is None:
            if self._shutdown_report is None:
                self._shutdown_report = ShutdownReport()
            return self._shutdown_report
        runtime = self._runtime
        self._runtime = None
        self._store = None
        self._shutdown_report = runtime.close()
        return self._shutdown_report

    def _round(self) -> CoreRuntime:
        if self._runtime is None:
            if not self._ever_opened:
                return self.open()
            raise RuntimeClosedError(
                "CoreBinding round is closed; the composition re-opens it on start()")
        return self._runtime

    # -- registration --------------------------------------------------------

    def bind_owner(self, owner: str, contributions: Any) -> CoreRegistration:
        """Stage the owner's batch through C1 and publish it atomically.

        A raising stage leaves the registry exactly as before (zero leaked
        contributions) and the owner stays unbound — C1's
        ``CoreRegistry.stage`` contract, not a re-implementation."""
        return self._round_bind(owner, _as_contribution_set(contributions))

    def _round_bind(self, owner: str, contribution_set: CoreContributionSet) -> CoreRegistration:
        registration = self._round().stage(owner, contribution_set)
        registration.commit()
        return registration

    def unbind_owner(self, owner: str) -> None:
        """Remove one owner's active batch; refused typed while the owner
        still holds unresolved leases (FR-007, C1 ``unregister``)."""
        self._round().unregister(owner)

    def snapshot(self) -> CoreRegistrySnapshot:
        return self._round().registry_snapshot()

    # -- the pacthold.contributions point handler (T012/T013 round shape) ---

    def stage(self, contribution: Any, owner: str) -> CoreRegistration:
        """Contribution-point handler: validate + reserve, publish nothing.

        ``contribution`` is the C2 ``Contribution`` the host injects the
        owner with; its opaque ``payload`` is translated by identity.  The
        returned handle is the prepared record the host commits or rolls
        back when the whole round stages."""
        return self._round().stage(owner, _as_contribution_set(contribution.payload))

    def commit(self, contribution: Any, prepared: CoreRegistration, owner: str) -> None:
        prepared.commit()

    def rollback(self, contribution: Any, prepared: CoreRegistration, owner: str) -> None:
        """The host's retirement/undo call — C1's own batch rules, no fudge.

        A STAGED batch rolls back (idempotent). A COMMITTED batch may already
        have been consumed by dispatch, and C1 forbids rolling it back: it
        retires through ``CoreRuntime.unregister`` — which refuses typed
        (``OwnerBusyError``) while the owner holds unresolved leases, the
        busy-refusal the unload gate demands. An already-closed round has
        nothing to retire into: the store keeps the durable facts and the
        ``ShutdownReport`` lists what is unresolved."""
        if prepared.state == "committed":
            if self._runtime is None:
                return
            try:
                self._runtime.unregister(owner)
            except OwnerNotRegisteredError:
                pass  # idempotent: already retired through a prior round
            return
        if prepared.state in ("rolled_back", "unregistered"):
            return
        prepared.rollback()

    # -- execution verbs (real C1 dispatch, not a substitute) ----------------

    def submit(self, plan: ExecutionPlan) -> SubmitResult:
        return self._round().submit(plan)

    def query(self, execution_id: str) -> ExecutionView:
        return self._round().query(execution_id)

    def request_stop(self, execution_id: str, operation_key: str) -> StopDispatchResult:
        return self._round().request_stop(execution_id, operation_key)

    def reconcile(self, execution_id: str, operation_key: str) -> ReconcileResult:
        return self._round().reconcile(execution_id, operation_key)
