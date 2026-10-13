"""Error/diagnostic and validation report data; no external handling."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class MethodError:
    code: str
    message: str
    resource_id: str | None = None
    path: str | None = None
    pointer: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: Literal["error", "warning"]
    message: str
    resource_id: str | None = None
    path: str | None = None
    pointer: str | None = None
    related_refs: tuple[str, ...] = ()


