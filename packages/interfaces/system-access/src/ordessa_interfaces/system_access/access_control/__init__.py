"""AccessControl mechanisms: bearer identity + exact-scope access checks."""
from .authentication import AccessError, AccessGrant, InstanceAccessAuthority, VerifiedPrincipal

__all__ = ["AccessError", "AccessGrant", "InstanceAccessAuthority", "VerifiedPrincipal"]
