"""Bounded public refusal categories, without native logs or secret values."""


class UnitApiRefused(RuntimeError):
    code = 'UNIT_API_REFUSED'


class UnitIdentityMismatch(UnitApiRefused):
    """The requested Unit identity or its durable revision differs."""
    code = 'IDENTITY_MISMATCH'


class UnitAdmissionRefused(UnitApiRefused):
    """The Unit's current admission gate refuses this operation."""
    code = 'ADMISSION_REFUSED'


class UnitGuaranteeUnavailable(UnitApiRefused):
    """The explicit Unit operation lacks required authority or evidence."""
    code = 'GUARANTEE_UNAVAILABLE'


class UnitComparisonUnavailable(UnitApiRefused):
    """Spent request input cannot be compared; its no-replay fence remains."""
    code = 'COMPARISON_UNAVAILABLE'


class UnitOperationUnknown(RuntimeError):
    """A Unit effect may have happened; query the original fact, never retry."""
    code = 'UNKNOWN_RESULT'


class UnitReconnectUnavailable(UnitApiRefused):
    code = 'UNIT_RECONNECT_UNAVAILABLE'
