"""Safe method validation/compilation entry points (pure method kernel orchestration).

These verify a caller-constructible projection against immutable captured bytes and
then delegate to the pure method kernels. They hold no publication or store authority.
"""
from __future__ import annotations

from copy import deepcopy

from .compilation.compiler import _compile_captured_method
from .definitions.contracts.validation import ValidationReport
from .definitions.errors import Diagnostic, MethodError, MethodFailure, MethodResult
from .definitions.models import CompiledMethod, CompilationCapabilities, LoadedMethod
from .loading.captured import verify_loaded_method
from .validation.compatibility import validate_compatibility


def validate_method(loaded: LoadedMethod, capabilities: CompilationCapabilities) -> ValidationReport:
    """Validate structure/references and injected capability compatibility.

    A fixture catalog may support design-time validation, but its warning is
    retained and never upgraded to a production-activation claim.
    """
    try:
        verified = verify_loaded_method(loaded)
        return validate_compatibility(verified, deepcopy(capabilities))
    except MethodFailure as exc:
        error = exc.error
        return ValidationReport(False, "compatibility", (Diagnostic(
            error.code, "error", error.message, error.resource_id,
            error.path, error.pointer,
        ),), registry_snapshot_ref=capabilities.registry_snapshot_ref)
    except (AttributeError, TypeError, ValueError, KeyError):
        return ValidationReport(False, "compatibility", (Diagnostic(
            "METHOD_VALIDATION_FAILED", "error", "method validation failed safely",
        ),), registry_snapshot_ref=capabilities.registry_snapshot_ref)


def compile_method(loaded: LoadedMethod, capabilities: CompilationCapabilities,
                   compiler_version: str) -> MethodResult[CompiledMethod]:
    """Rebuild caller-constructible caches from immutable bytes before compilation."""
    if not isinstance(compiler_version, str) or not compiler_version.strip():
        return MethodResult.failure(MethodError("COMPILER_VERSION_INVALID", "compiler version must be a non-empty string"))
    try:
        rebuilt = verify_loaded_method(loaded)
        captured_capabilities = deepcopy(capabilities)
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (AttributeError, TypeError, ValueError, KeyError, RecursionError):
        return MethodResult.failure(MethodError("LOADED_PROJECTION_INVALID", "loaded method projection could not be verified against captured bytes"))
    return _compile_captured_method(rebuilt, captured_capabilities, compiler_version)


__all__ = ["validate_method", "compile_method"]
