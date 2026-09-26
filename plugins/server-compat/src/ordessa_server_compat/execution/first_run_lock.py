"""Backward-compatible entry for the per-library first-run lock (Order 80).

MB-E2b equal-move: the definitions live exactly once in
``pacthold.execution.first_run_lock`` (moved verbatim); this module
re-exports the same objects so historical import paths keep the identical
object identity. No second definition lives here -
``tests/server/test_e_modular_execution_lifecycle.py`` pins that by AST.
"""
from __future__ import annotations

from pacthold.execution.first_run_lock import (
    FIRST_RUN_WAIT_SECONDS, FirstRunGate, FirstRunLockTimeout, first_run_gate,
)

__all__ = [
    "FIRST_RUN_WAIT_SECONDS",
    "FirstRunGate",
    "FirstRunLockTimeout",
    "first_run_gate",
]
