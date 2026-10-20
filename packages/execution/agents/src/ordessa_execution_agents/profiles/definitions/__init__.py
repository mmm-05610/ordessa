"""Profile declarations and owner-defined errors."""

from .errors import (
    HistoricalProfileIdentityMismatch, ProfileAccessRefused, ProfileChangeUnknown,
    ProfileRevisionConflict, ProfileStoreUnavailable, ProfileValidationError,
)
from .secret_refs import SecretRef

__all__ = [
    "HistoricalProfileIdentityMismatch", "ProfileAccessRefused", "ProfileChangeUnknown",
    "ProfileRevisionConflict",
    "ProfileStoreUnavailable", "ProfileValidationError", "SecretRef",
]
