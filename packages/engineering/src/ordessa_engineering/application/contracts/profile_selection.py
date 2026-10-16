"""Demand-side ports for method-bounded execution-profile selection.

This contract deliberately carries the original native objects. Engineering
defines neither an execution Profile DTO nor an authorization substitute.
"""
from collections.abc import Mapping
from typing import Any, Protocol


class ProfileSelectionSource(Protocol):
    """Resolve only the complete method-authorized native profile set."""

    def candidates(self, *, max_candidates: int) -> Mapping[str, tuple[object, str]]:
        """Return every permitted immutable native ref and its finite description.

        Implementations refuse when the allowed set is unavailable or exceeds
        ``max_candidates``; they must not silently truncate or consult latest.
        """
        ...

    def validate(self, profile_ref: object) -> object:
        """Recheck the exact native revision and return that same ref object."""
        ...


class ProfileChoicePort(Protocol):
    """Obtain one original Decision answer through its injected gateway."""

    async def choose(
        self,
        task: object,
        *,
        request_id: str,
        question_id: str,
        question_text: str,
        options: Mapping[str, str],
    ) -> object:
        """Return the native DecisionAnswer; implementations do not retry."""
        ...


class ProfileUnitPort(Protocol):
    """Create through the original Unit owner after selection is revalidated."""

    def create(self, profile_ref: object, authorization: Any) -> object:
        """Delegate selected-profile authorization and creation to Unit owner."""
        ...


__all__ = ["ProfileSelectionSource", "ProfileChoicePort", "ProfileUnitPort"]
