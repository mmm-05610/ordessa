"""Unique phase and validation report data; no execution."""
from dataclasses import dataclass
from typing import Literal
from ..errors.diagnostics import Diagnostic

ValidationPhase = Literal["structural", "compatibility"]

@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    phase: ValidationPhase
    diagnostics: tuple[Diagnostic, ...] = ()
    compiler_version: str | None = None
    registry_snapshot_ref: str | None = None
    snapshot_digest: str | None = None


