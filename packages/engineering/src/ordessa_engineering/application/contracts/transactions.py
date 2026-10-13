"""Application unit-of-work and transaction ports.

The application opens the UoW through this port and runs its business inside the
scope (read / validate / domain rules / form write intent), then calls the
adapter's atomic write primitives; the UoW commits or rolls back. The scope hides
the raw connection and SQL from the application, and no arbitrary callback is
passed into `domain`.

There is exactly one transaction authority (the original library transaction);
this port does not create a second UoW implementation.
"""
from __future__ import annotations

from typing import Protocol

from ...domain.common.models.identity import Scope
from .repositories import ArtifactRepository, CommandJournal, ProposalRepository, ReviewRepository
from .confirmation import AuthorizationRepository
from .implementation import ImplementationRepository
from .submissions import SubmissionRepository
from .acceptance import AcceptanceRepository
from .implementation_dispatch import DispatchRepository

__all__ = ['TransactionScope', 'UnitOfWork', 'EngineeringUoW', 'UoWFactory']


class TransactionScope(Protocol):
    # reads (same original transaction/connection)
    def read(self, ref): ...
    def require_current(self, ref) -> None: ...
    def head_ref(self, kind: str, stable_id: str): ...
    def head_revision(self, kind: str, stable_id: str): ...
    def run_row(self, run_id): ...
    def idempotency_row(self, operation_id): ...
    def next_step_ordinal(self, run_id): ...
    def step_rows(self, run_id): ...
    def list_run_rows(self, *, after=None, limit=128): ...
    # atomic write primitives
    def write_material(self, *, kind: str, stable_id: str, revision: int, body, generated: bool): ...
    def create_generated(self, *, kind: str, stable_id: str, body): ...
    def insert_idempotency(self, operation_id: str, payload_digest: str, ref) -> None: ...
    def insert_run(self, *, run_id, method_ref, registry_ref, inputs, now) -> None: ...
    def insert_step_log(self, *, run_id: str, ordinal: int, step_id: str, operation: str,
                        attempt: int, status: str, receipt_ref) -> None: ...
    def replace_run_inputs(self, *, run_id, expected_inputs, inputs) -> None: ...
    def update_run(self, *, run_id: str, status: str, cursor: int | None, wait_reason, now) -> None: ...


class UnitOfWork(Protocol):
    def open(self):  # context manager yielding TransactionScope
        ...


class EngineeringUoW(Protocol):
    engineering: ArtifactRepository
    reviews: ReviewRepository
    proposals: ProposalRepository
    commands: CommandJournal
    authorization: AuthorizationRepository
    # Explicit schema10 only; earlier schemas refuse this repository.
    methods: object
    # Explicit schema11 only; earlier schemas refuse without migration.
    implementation: ImplementationRepository
    submissions: SubmissionRepository
    acceptance: AcceptanceRepository
    workflow: TransactionScope
    dispatch: DispatchRepository
    # Explicit schema15 only, on the same library/transaction authority.
    reviewer_assignments: object
    scope: Scope
    authority_id: str
    def __enter__(self) -> "EngineeringUoW": ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def isolate(self): ...
    def __exit__(self, *exc): ...


class UoWFactory(Protocol):
    authority_id: str
    def begin_effect_cut(self, scope: Scope):
        """Same original write authority; acquisition refuses current contention."""
        ...
    def begin(self, scope: Scope, mode: str = "write") -> EngineeringUoW: ...
