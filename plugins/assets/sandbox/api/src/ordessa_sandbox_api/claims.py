"""Native config field claims (contracts.md §C2 conflict gate)."""
from __future__ import annotations

from .errors import SandboxApiError, SandboxErrorCode


class FieldClaimRegistry:
    """Pre-allocated ownership of native config fields.

    If the sandbox facet and the permissions' native projection touch the
    same field, the second claim is refused at stage time — no priority
    ordering may resolve it away.
    """

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def claim(self, *, adapter_id: str, native_field: str) -> None:
        owner = self._owners.get(native_field)
        if owner is not None and owner != adapter_id:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_CONFIG_CONFLICT,
                f"native config field {native_field!r} is already claimed by "
                f"adapter {owner!r}; adapter {adapter_id!r} cannot also own it",
                suggestion="pre-allocate disjoint fields between the two "
                           "business owners")
        self._owners[native_field] = adapter_id

    def owner_of(self, native_field: str) -> str | None:
        return self._owners.get(native_field)

    def claimed_fields(self) -> tuple[str, ...]:
        return tuple(sorted(self._owners))
