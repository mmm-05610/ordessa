"""Closed tool-category vocabulary and coverage parsing (FR-05, FR-06)."""
from __future__ import annotations

from enum import Enum
from typing import Iterable

from .errors import SandboxApiError, SandboxErrorCode


class ToolCategory(str, Enum):
    """Categories a native sandbox can be asked to cover. Closed set."""

    BASH = "bash"
    READ = "read"
    EDIT = "edit"
    MCP = "mcp"
    NETWORK = "network"

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.value


#: Strings that would stand for "everything". A wildcard can never be a
#: coverage declaration: each category must be named so it can be probed.
_WILDCARDS = frozenset({"all", "*", "everything", "any"})


def parse_coverage(values: Iterable[str]) -> frozenset[ToolCategory]:
    """Parse explicit category names; refuse wildcards and unknown names."""
    parsed: list[ToolCategory] = []
    for value in values:
        if isinstance(value, ToolCategory):
            parsed.append(value)
            continue
        text = str(value).strip().lower()
        if text in _WILDCARDS:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN,
                f"coverage wildcard {value!r} is not declarable; name each "
                "category (bash/read/edit/mcp/network) so each can be probed",
                suggestion="list the required categories explicitly",
            )
        try:
            parsed.append(ToolCategory(text))
        except ValueError as error:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_INTENT_INVALID,
                f"{value!r} is not a tool category",
                suggestion="use one of: bash, read, edit, mcp, network",
            ) from error
    return frozenset(parsed)
