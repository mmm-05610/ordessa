"""Artifact acceptance ports over the original scoped transaction authority."""
from typing import Protocol


class AcceptanceRepository(Protocol):
    def create(self, receipt): ...
    def resolve(self, adoption_id): ...


class AcceptanceAdmissionPort(Protocol):
    def guard_intent(self, context, intent):
        """Exact Submission/current selected method/full acceptance closure.

        A captured Plan or client-selected requirements never supplies this
        admission. Keep original method/control fences through COMMIT.
        """
        ...
