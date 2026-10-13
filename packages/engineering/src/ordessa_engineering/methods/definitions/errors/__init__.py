"""Unique-owner error/diagnostic/result exports."""
from .diagnostics import MethodError, Diagnostic
from .failures import MethodFailure
from .results import MethodResult
__all__ = ["MethodError", "Diagnostic", "MethodFailure", "MethodResult"]
