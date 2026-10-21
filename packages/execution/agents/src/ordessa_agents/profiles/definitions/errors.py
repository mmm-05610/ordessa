"""Profile-owned validation, admission, storage and result errors."""


class ProfileValidationError(ValueError):
    code = "PROFILE_INVALID"


class HistoricalProfileIdentityMismatch(ProfileValidationError):
    """A historical Profile reference belongs to a different identity scope."""

    code = "IDENTITY_MISMATCH"


class ProfileRevisionConflict(ProfileValidationError):
    code = "PROFILE_REVISION_CONFLICT"


class ProfileAccessRefused(RuntimeError):
    code = "ADMISSION_REFUSED"


class ProfileStoreUnavailable(RuntimeError):
    code = "GUARANTEE_UNAVAILABLE"


class ProfileChangeUnknown(RuntimeError):
    code = "UNKNOWN_RESULT"
