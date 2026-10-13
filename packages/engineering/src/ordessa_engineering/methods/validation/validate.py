"""Pure complete method validation; source reconstruction is an application precondition."""
from ..definitions.models import LoadedMethod, CompilationCapabilities
from ..definitions.contracts.validation import ValidationReport
from .compatibility import validate_compatibility

def validate_captured_method(loaded: LoadedMethod, capabilities: CompilationCapabilities) -> ValidationReport:
    return validate_compatibility(loaded, capabilities)
