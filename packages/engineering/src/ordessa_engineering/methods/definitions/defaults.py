"""Shared model/format default values; no stage or contract execution."""
from types import MappingProxyType

# Model semantics have one owner; external syntax contracts reuse these values.
DOCUMENT_VALIDATION_TARGET_DEFAULT_V1 = "method_content"
CRITERION_DEFAULTS_V1 = MappingProxyType({
    "required": True, "blocking": True, "applies_to": (), "required_inputs": (),
})

