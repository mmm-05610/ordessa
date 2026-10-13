"""Typed error family (E1 §G002-1 counterexamples map onto these).

Refusals are typed so callers can distinguish "the guarantee you asked for is
absent" (retry with raw by *explicit* user choice only) from "identity
mismatch" (never retried) and "unknown result" (query-only, never resend).
No error string doubles as an approval or a terminal fact.
"""
from __future__ import annotations


class EnvironmentError(Exception):
    """Base of the typed contract error family."""

    code = "ENVIRONMENT_ERROR"


class IdentityMismatchError(EnvironmentError):
    """A ref/key/generation did not match the expected full identity.

    Counterexample it must catch: a native_id or stale ref used as a control
    handle; I2/g1 replayed against I1/g1 state.
    """

    code = "IDENTITY_MISMATCH"


class AdmissionRefusedError(EnvironmentError):
    """The lifecycle gate refused a new admission (draining/retired/closing)."""

    code = "ADMISSION_REFUSED"


class AuthorityConflictError(EnvironmentError):
    """A second writer for the same AuthorityKey — single-writer violation.

    Counterexamples: same entity registered under a second schema major; a
    fresh namespace alias for the same physical fact; the frontend opening a
    second writer for a backend-owned target.
    """

    code = "AUTHORITY_CONFLICT"


class GuaranteeUnavailableError(EnvironmentError):
    """A reliable request lacks fingerprint/Store/native evidence.

    Raised BEFORE dispatch; never silently downgrades to raw and never
    disables the ordinary raw path.
    """

    code = "GUARANTEE_UNAVAILABLE"


class ComparisonUnavailableError(EnvironmentError):
    """An old key/tombstone cannot be compared (key rotated away, decoder gone).

    The spent tombstone still blocks re-dispatch; only authorized lookup of
    the original fact remains.
    """

    code = "COMPARISON_UNAVAILABLE"


class UnknownResultError(EnvironmentError):
    """Delivery/effect state is unknown — query-only, never re-dispatch."""

    code = "UNKNOWN_RESULT"
