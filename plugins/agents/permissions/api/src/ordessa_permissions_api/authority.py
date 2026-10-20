"""The authority FACT record and its neutral query port (PE1, 016 dispatch).

One `AuthorityRecord` answers, for one stored authorization fact: *who*
requested and *who* approved (or which administrator issued the exception),
*what* tool/target/operation it covers, at which *scope* (session / user /
profile), with which *expiry*, and in which *state* (active, expired,
revoked, consumed). It is a READ MODEL over the stores that already exist -
the `server_approvals` ledger (settled allow decisions and their one-time
grants) and the current intent revisions (user/profile-scoped allow rules and
their `AdminAuthorization` exceptions). This module defines no second store
and no second decision engine: `Authorizer.evaluate` stays the only ruling,
and nothing that is merely listed here lets a side effect proceed.

Two spellings map onto the persisted vocabulary, and the mapping is stated
once, here, so no consumer has to guess:

* ``Scope.SESSION`` / ``PermissionIntent(scope="session")`` and a settled
  approval grant -> ``AuthorityScope.SESSION``;
* ``Scope.PROJECT`` / intent scope ``"project"`` (the profile/project store
  spelling, kept byte-compat per FR-10) -> ``AuthorityScope.PROFILE``;
* ``Scope.USER`` / intent scope ``"user"`` -> ``AuthorityScope.USER``.

Refusal, not coercion, exactly like every other module here: unknown record
keys, unknown enum spellings, naive timestamps and missing bindings are
refused with a typed `PolicyRefusal`; nothing is defaulted. An absent field
for a person (``requestedBy`` / ``approvedBy``) is honestly ``None`` - the
projection never guesses an identity the store never recorded, and a query
that filters by person never matches a record whose person is unknown.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping, Protocol

from .codes import PolicyRefusal, probe
from .rules import ToolIdentity

__all__ = [
    "AUTHORITY_QUERY_PORT",
    "AUTHORITY_QUERY_PORT_VERSION",
    "AuthorityRecord",
    "AuthorityScope",
    "AuthoritySourceKind",
    "AuthorityStateKind",
    "PermissionsAuthorityQueryPort",
    "authority_id_for",
]

#: The provided-port name the backend registers the query surface under
#: (`ordessa_permissions_backend.plugin.AUTHORITY_PORT`; a guard test binds
#: this literal to that source text so the two cannot drift, same lane as
#: `PERMISSIONS_AUTHORIZER_PORT`).
AUTHORITY_QUERY_PORT: Final[str] = "permissions.authority.query@1"
AUTHORITY_QUERY_PORT_VERSION: Final[int] = 1

_RECORD_FIELDS: Final[frozenset[str]] = frozenset({
    "authorityId", "source", "scope", "tool", "target", "operationDigest",
    "requestedBy", "approvedBy", "grantedAt", "expiresAt", "state", "revision",
    "factRef",
})
#: Fields that must always carry a value; everything else is a declared
#: nullable (a fact the store could not attribute stays a declared absence).
_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset({
    "authorityId", "source", "scope", "tool", "state", "factRef",
})


class AuthoritySourceKind(str, Enum):
    """Which existing store a fact record was read from. Never a third store."""

    APPROVAL_GRANT = "approval_grant"
    POLICY_RULE = "policy_rule"

    @classmethod
    def of(cls, value: Any, *,
           source: str = "authority.AuthoritySourceKind.of") -> "AuthoritySourceKind":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target=probe(value)) from None


class AuthorityScope(str, Enum):
    """The three scopes the dispatch names; see the module docstring for the
    persisted-spelling mapping (`project` -> `profile`)."""

    SESSION = "session"
    USER = "user"
    PROFILE = "profile"

    @classmethod
    def of(cls, value: Any, *,
           source: str = "authority.AuthorityScope.of") -> "AuthorityScope":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target=probe(value)) from None


class AuthorityStateKind(str, Enum):
    """The state an authorization fact is in, derived from the stored facts
    alone: `active` may be listed as effective; `expired`, `revoked` and
    `consumed` never are. None of them is a ruling - see the port docstring."""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CONSUMED = "consumed"

    @classmethod
    def of(cls, value: Any, *,
           source: str = "authority.AuthorityStateKind.of") -> "AuthorityStateKind":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target=probe(value)) from None


def _text(value: Any, *, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or any(
            c in value for c in "\x00\r\n"):
        raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                            target=None if isinstance(value, str)
                            else type(value).__name__)
    return value


def _required_text(value: Any, *, source: str) -> str:
    text = _text(value, source=source)
    if text is None:
        raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                            target="None")
    return text


def _aware(value: Any, *, source: str) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target="unparseable timestamp") from None
    if not isinstance(value, dt.datetime) or value.tzinfo is None \
            or value.utcoffset() is None:
        raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                            target=None if isinstance(value, str)
                            else type(value).__name__)
    return value


def _digest_or_none(value: Any, *, source: str) -> str | None:
    text = _text(value, source=source)
    if text is None:
        return None
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                            target="not a lowercase hex digest")
    return text


def authority_id_for(*, source: str, fact_ref: str) -> str:
    """The one record id a stored fact projects to; deterministic, not random:
    the same approval row or the same rule revision can never mint two
    authority ids, mirroring `approval_id_for` for the fact layer."""
    label = _required_text(source, source="authority.authority_id_for")
    ref = _required_text(fact_ref, source="authority.authority_id_for")
    folded = hashlib.sha256(f"{label}\n{ref}".encode("utf-8")).hexdigest()
    return f"authority_{folded[:32]}"


@dataclass(frozen=True)
class AuthorityRecord:
    """One authorization fact, read from an existing store, in frozen shape.

    Nullability is declared, not improvised:

    * ``target`` / ``operationDigest`` - rules are tool-and-pattern facts and
      grants for a tool without a target carry none;
    * ``requestedBy`` - only grant-derived records can name the principal of
      the attributed operation; rule records never invent one;
    * ``approvedBy`` - the decided-allow approver when the ledger recorded
      one, the `AdminAuthorization` issuer for an exception rule, else None;
    * ``grantedAt`` - the approval row's recorded time, or None for a rule
      (the intents table keeps revisions, not grant timestamps: registered);
    * ``expiresAt`` - the grant's recorded expiry, or the authorization's
      expiry for an exception rule; None for a standing rule means the store
      recorded no expiry, NEVER that the fact is unlimited for enforcement -
      the ruling path re-checks ceilings and intents on every call;
    * ``revision`` - the approval row's CAS version, or the intent revision
      the rule was read from.
    """

    authority_id: str
    source: AuthoritySourceKind
    scope: AuthorityScope
    tool: str
    state: AuthorityStateKind
    fact_ref: str
    target: str | None = None
    operation_digest: str | None = None
    requested_by: str | None = None
    approved_by: str | None = None
    granted_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None
    revision: int | None = None

    @classmethod
    def of(cls, *, authority_id: Any = None, source: Any, scope: Any, tool: Any,
           state: Any, fact_ref: Any, target: Any = None,
           operation_digest: Any = None, requested_by: Any = None,
           approved_by: Any = None, granted_at: Any = None,
           expires_at: Any = None, revision: Any = None) -> "AuthorityRecord":
        source_kind = source if isinstance(source, AuthoritySourceKind) \
            else AuthoritySourceKind.of(source)
        parsed_tool = ToolIdentity(_required_text(tool,
                                                  source="authority.tool")).key
        parsed_revision = None
        if revision is not None:
            if isinstance(revision, bool) or not isinstance(revision, int) \
                    or revision < 1:
                raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID",
                                    source="authority.revision",
                                    target=repr(revision))
            parsed_revision = revision
        return cls(
            authority_id=_required_text(
                authority_id if authority_id is not None
                else authority_id_for(source=source_kind.value, fact_ref=fact_ref),
                source="authority.authorityId"),
            source=source_kind,
            scope=AuthorityScope.of(scope),
            tool=parsed_tool,
            state=state if isinstance(state, AuthorityStateKind)
            else AuthorityStateKind.of(state),
            fact_ref=_required_text(fact_ref, source="authority.factRef"),
            target=_text(target, source="authority.target"),
            operation_digest=_digest_or_none(operation_digest,
                                             source="authority.operationDigest"),
            requested_by=_text(requested_by, source="authority.requestedBy"),
            approved_by=_text(approved_by, source="authority.approvedBy"),
            granted_at=_aware(granted_at, source="authority.grantedAt"),
            expires_at=_aware(expires_at, source="authority.expiresAt"),
            revision=parsed_revision,
        )

    @classmethod
    def from_record(cls, raw: Any) -> "AuthorityRecord":
        source = "authority.AuthorityRecord.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target=None if raw is None
                                else type(raw).__name__)
        extra = set(raw) - _RECORD_FIELDS
        if extra:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target="unknown authority record fields: "
                                       + ",".join(sorted(extra)))
        missing = _REQUIRED_FIELDS - set(raw)
        if missing:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target="missing authority record fields: "
                                       + ",".join(sorted(missing)))
        return cls.of(**{
            "authority_id": raw.get("authorityId"), "source": raw.get("source"),
            "scope": raw.get("scope"), "tool": raw.get("tool"),
            "state": raw.get("state"), "fact_ref": raw.get("factRef"),
            "target": raw.get("target"),
            "operation_digest": raw.get("operationDigest"),
            "requested_by": raw.get("requestedBy"),
            "approved_by": raw.get("approvedBy"),
            "granted_at": raw.get("grantedAt"), "expires_at": raw.get("expiresAt"),
            "revision": raw.get("revision"),
        })

    def as_record(self) -> dict[str, Any]:
        return {
            "authorityId": self.authority_id, "source": self.source.value,
            "scope": self.scope.value, "tool": self.tool, "target": self.target,
            "operationDigest": self.operation_digest,
            "requestedBy": self.requested_by, "approvedBy": self.approved_by,
            "grantedAt": None if self.granted_at is None
            else self.granted_at.isoformat(),
            "expiresAt": None if self.expires_at is None
            else self.expires_at.isoformat(),
            "state": self.state.value, "revision": self.revision,
            "factRef": self.fact_ref,
        }

    @property
    def effective(self) -> bool:
        """Only an active record is ever listed as effective - and even that
        is a fact report, never a permission to proceed."""
        return self.state is AuthorityStateKind.ACTIVE

    def alive_at(self, moment: dt.datetime) -> bool:
        if self.state is not AuthorityStateKind.ACTIVE:
            return False
        return self.expires_at is None or moment <= self.expires_at


class PermissionsAuthorityQueryPort(Protocol):
    """The `permissions.authority.query@1` read surface (PE1-2/PE1-3).

    Consumers: the core's C4 admission alignment (AR-1) and the approval /
    settings surfaces. The backend instance is fetched through the host's
    port registry under `AUTHORITY_QUERY_PORT`; this package supplies only
    the contract and the DTO, and stays stdlib-only.

    Rules every consumer must keep:

    * these are FACTS, not rulings - `Authorizer.evaluate` (the
      `permissions.authorizer@1` port) remains the only operation-level
      verdict; nothing here lets a side effect proceed on its own;
    * absence is honest: an empty result means no effective authorization
      fact is recorded - it is never a default allow, and `lookup` of a
      fact that does not exist returns `None`, not a refusal-shaped guess;
    * the three listing views answer the dispatch's three questions:
      by operation (tool/target/digest/session), by session, by user.

    Parameter spellings are keyword-only text or None; a backend raises
    `PolicyRefusal` on a malformed query input, never on an empty world.
    """

    def effective_for_operation(self, *, tool: Any = None, target: Any = None,
                                session_id: Any = None, principal: Any = None,
                                operation_digest: Any = None,
                                now: Any = None) -> tuple[AuthorityRecord, ...]:
        """Active records that speak about this operation: grants bound to
        the exact operation digest when one is given, session grants for the
        given session, and current allow rules matching tool (and target)."""
        ...

    def effective_for_session(self, session_id: str,
                              *, now: Any = None) -> tuple[AuthorityRecord, ...]:
        """Active records attributed to exactly this session. Another
        session's records never surface (two-session isolation)."""
        ...

    def effective_for_user(self, principal: str,
                           *, now: Any = None) -> tuple[AuthorityRecord, ...]:
        """Active records a person is named on: grants they requested or
        approved, and rule exceptions they issued. A record with no
        attributable person is never folded in."""
        ...

    def lookup(self, fact_ref: str,
               *, now: Any = None) -> AuthorityRecord | None:
        """One record by its fact reference (the approval id, or the
        `intent_id@revision#index` spelling), whatever its state, or None.
        This is where an expired or revoked fact is read AS expired or
        revoked - the listings above only ever contain active ones."""
        ...

    def revoke(self, approval_id: str, *, reason: str,
               now: Any = None) -> AuthorityRecord | None:
        """Revoke one settled-allow grant: the stored fact keeps its settled
        decision (history is never rewritten) and gains a revocation record;
        the spent grant then refuses and the listings drop it. `reason` is
        required - a revocation without a stated reason is refused, never
        recorded. Returns the record in its new state, or None when no
        settled-allow grant answers to that id. Deny/invalid/open rows are
        not revocable and are reported as None, never silently accepted."""
        ...
