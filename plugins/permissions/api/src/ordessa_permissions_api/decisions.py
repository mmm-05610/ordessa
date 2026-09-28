"""Decision and approval data-transfer objects (§C1).

These are the *shapes* the authorizer ports speak with; there is no service and
no storage here. What this module does enforce is binding: a grant names the
operation digest, target, policy revision, ceiling revision and native
generation it was issued for, is good for exactly that operation, and is used up
once. A mismatch is a refusal - never a re-bind to something newer.

The persisted spellings (`open`/`settled`/`invalid`, `allow`/`deny`, the
`once`/`bounded` approval scope) keep the existing data identifiers so the
migration in T08 does not have to rename live rows.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Final, Mapping

from .codes import PolicyDenyCode, PolicyRefusal, RefusalCode, probe
from .rules import RuleAction, ToolIdentity

__all__ = [
    "AlreadyRecorded",
    "ApprovalDecision",
    "ApprovalFact",
    "ApprovalRequest",
    "ApprovalScope",
    "ApprovalState",
    "ApprovalStateKind",
    "AuthorizationDecision",
    "BoundGrant",
    "AllowedOnce",
    "BoundedApprovalScope",
    "DecideResult",
    "DecisionReason",
    "Denied",
    "GRANT_TTL",
    "InvalidApproval",
    "NativeReceipt",
    "OnceApprovalScope",
    "PendingApproval",
    "QueriedApproval",
    "QueryOutcome",
    "QueryUnknown",
    "Recorded",
    "UnknownApproval",
    "approval_id_for",
    "scope_to_record",
]

_TEXT_OK = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
GRANT_TTL: Final[dt.timedelta] = dt.timedelta(minutes=5)
_DECISION_FIELDS: Final[frozenset[str]] = frozenset(
    {"nativeRequestId", "operationDigest", "tool", "target", "subject", "action", "reason",
     "code", "policyDigest", "expiresAt"})
_REQUEST_FIELDS: Final[frozenset[str]] = frozenset(
    {"approvalId", "sessionId", "executionId", "nativeRequestId", "operationDigest", "toolKey",
     "target", "ceilingRevision", "policyRevision", "nativeGeneration", "requestedAt",
     "expiresAt", "version"})
_STATE_FIELDS: Final[frozenset[str]] = frozenset(
    {"approvalId", "sessionId", "executionId", "version", "state", "decision", "scope",
     "requestId", "nativeRequestId"})
_GRANT_FIELDS: Final[frozenset[str]] = frozenset(
    {"approvalId", "operationDigest", "target", "ceilingRevision", "policyRevision",
     "nativeGeneration", "expiresAt", "consumed"})


def _field(value: Any, *, source: str, code: str) -> str:
    if not isinstance(value, str) or _TEXT_OK.fullmatch(value) is None or not value.strip():
        raise PolicyRefusal(code, source=source,
                            target=None if isinstance(value, str) else type(value).__name__)
    return value


def _digest_text(value: Any, *, source: str, code: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PolicyRefusal(code, source=source,
                            target=None if isinstance(value, str) else type(value).__name__)
    return value


def _aware(value: Any, *, source: str, code: str) -> dt.datetime:
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            raise PolicyRefusal(code, source=source, target="unparseable timestamp") from None
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PolicyRefusal(code, source=source,
                            target=None if value is None else type(value).__name__)
    return value


def approval_id_for(*, operation_digest: str, native_request_id: str) -> str:
    """The one approval id an operation correlates to; deterministic, not random."""
    digest = _digest_text(operation_digest, source="decisions.approval_id_for",
                          code="PERMISSION_DECISION_INVALID")
    label = _field(native_request_id, source="decisions.approval_id_for",
                   code="PERMISSION_DECISION_INVALID")
    folded = hashlib.sha256(f"{digest}\n{label}".encode("utf-8")).hexdigest()
    return f"approval_{folded[:32]}"


class DecisionReason:
    """A cause that is both stable (a declared code) and explainable (a line)."""

    __slots__ = ("code", "message")

    def __init__(self, code: RefusalCode | PolicyDenyCode | str | None, message: Any) -> None:
        self.code = _normalize_code(code)
        self.message = _field(message, source="decisions.DecisionReason",
                              code="PERMISSION_DECISION_INVALID")

    @classmethod
    def of(cls, *, code: Any = None, message: Any) -> "DecisionReason":
        return cls(code, message)

    @property
    def is_refusal(self) -> bool:
        return isinstance(self.code, RefusalCode)

    def as_record(self) -> dict[str, Any]:
        return {"code": None if self.code is None else self.code.value, "message": self.message}

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, DecisionReason) and self.code == other.code
                and self.message == other.message)

    def __hash__(self) -> int:
        return hash((self.code, self.message))

    def __str__(self) -> str:
        return f"{None if self.code is None else self.code.value}: {self.message}"


def _normalize_code(value: Any) -> RefusalCode | PolicyDenyCode | None:
    if value is None:
        return None
    if isinstance(value, (RefusalCode, PolicyDenyCode)):
        return value
    try:
        return RefusalCode(value)
    except ValueError:
        pass
    try:
        return PolicyDenyCode(value)
    except ValueError:
        raise PolicyRefusal("PERMISSION_DECISION_INVALID", source="decisions.reason.code",
                            target=probe(value)) from None


@dataclass(frozen=True)
class AuthorizationDecision:
    """One ruling about one already-bound operation."""

    native_request_id: str
    operation_digest: str
    tool: str
    subject: str
    action: RuleAction
    reason: DecisionReason
    policy_digest: str
    expires_at: dt.datetime
    target: str | None = None

    @classmethod
    def of(cls, *, native_request_id: Any, operation_digest: Any, tool: Any, subject: Any,
           action: Any, reason: Any, policy_digest: Any, expires_at: Any,
           target: Any = None) -> "AuthorizationDecision":
        source = "decisions.AuthorizationDecision.of"
        return cls(
            native_request_id=_field(native_request_id, source=f"{source}.nativeRequestId",
                                     code="PERMISSION_DECISION_INVALID"),
            operation_digest=_digest_text(operation_digest, source=f"{source}.operationDigest",
                                          code="PERMISSION_DECISION_INVALID"),
            tool=ToolIdentity(tool).key,
            subject=_field(subject, source=f"{source}.subject",
                           code="PERMISSION_DECISION_INVALID"),
            action=RuleAction.of(action), reason=_as_reason(reason),
            policy_digest=_field(policy_digest, source=f"{source}.policyDigest",
                                 code="PERMISSION_DECISION_INVALID"),
            expires_at=_aware(expires_at, source=f"{source}.expiresAt",
                              code="PERMISSION_DECISION_INVALID"),
            target=None if target is None else _field(target, source=f"{source}.target",
                                                      code="PERMISSION_DECISION_INVALID"),
        )

    def alive_at(self, moment: dt.datetime) -> bool:
        return isinstance(moment, dt.datetime) and moment <= self.expires_at

    def as_record(self) -> dict[str, Any]:
        return {
            "nativeRequestId": self.native_request_id,
            "operationDigest": self.operation_digest, "tool": self.tool,
            "target": self.target, "subject": self.subject, "action": self.action.value,
            "reason": self.reason.as_record(), "policyDigest": self.policy_digest,
            "expiresAt": self.expires_at.isoformat(),
        }


@dataclass(frozen=True)
class Denied:
    """`Denied(code, evidenceRef)` from §C1: the refusal and where to read it."""

    code: RefusalCode | PolicyDenyCode
    evidence_ref: str
    reason: DecisionReason | None = None

    @classmethod
    def of(cls, *, code: Any, evidence_ref: Any, reason: Any = None) -> "Denied":
        source = "decisions.Denied.of"
        normalized = _normalize_code(code)
        if normalized is None:
            raise PolicyRefusal("PERMISSION_DECISION_INVALID", source=f"{source}.code",
                                target="None")
        return cls(
            code=normalized,
            evidence_ref=_field(evidence_ref, source=f"{source}.evidenceRef",
                                code="PERMISSION_DECISION_INVALID"),
            reason=None if reason is None else _as_reason(reason),
        )

    @property
    def outcome(self) -> str:
        return "denied"

    @property
    def is_stable_code(self) -> bool:
        return True


def _as_reason(value: Any) -> DecisionReason:
    if isinstance(value, DecisionReason):
        return value
    # A bare string may carry the explanation, but never invent a stable code:
    # the caller's own `code` field is what names the cause.
    if isinstance(value, str) and value.strip() and _TEXT_OK.fullmatch(value):
        return DecisionReason(None, value)
    raise PolicyRefusal("PERMISSION_DECISION_INVALID", source="decisions._as_reason",
                        target=None if value is None else type(value).__name__)


@dataclass(frozen=True)
class BoundGrant:
    """A one-time allowance for exactly the operation it was issued for."""

    approval_id: str
    operation_digest: str
    target: str | None
    ceiling_revision: str
    policy_revision: str
    native_generation: str
    expires_at: dt.datetime
    consumed: bool = False

    @classmethod
    def of(cls, *, approval_id: Any, request: Any, expires_at: Any) -> "BoundGrant":
        from .request_facts import OperationRequest

        if not isinstance(request, OperationRequest):
            raise PolicyRefusal("PERMISSION_DECISION_INVALID", source="decisions.BoundGrant.of",
                                target=None if request is None else type(request).__name__)
        return cls.from_record({
            "approvalId": approval_id, "operationDigest": request.operation_digest,
            "target": request.target, "ceilingRevision": request.ceiling_revision,
            "policyRevision": request.policy_revision,
            "nativeGeneration": request.native_generation, "expiresAt": expires_at,
            "consumed": False,
        })

    @classmethod
    def from_record(cls, raw: Any) -> "BoundGrant":
        source = "decisions.BoundGrant.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_DECISION_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        extra = set(raw) - _GRANT_FIELDS
        if extra:
            raise PolicyRefusal("PERMISSION_DECISION_INVALID", source=source,
                               target="unknown grant fields: " + ",".join(sorted(extra)))
        if raw.get("operationDigest") is None or raw.get("approvalId") is None:
            raise PolicyRefusal("PERMISSION_DECISION_INVALID", source=source,
                                target="missing grant binding")
        consumed = raw.get("consumed", False)
        if not isinstance(consumed, bool):
            raise PolicyRefusal("PERMISSION_DECISION_INVALID", source=f"{source}.consumed",
                                target=type(consumed).__name__)
        target = raw.get("target")
        return cls(
            approval_id=_field(raw.get("approvalId"), source=f"{source}.approvalId",
                              code="PERMISSION_DECISION_INVALID"),
            operation_digest=_digest_text(raw.get("operationDigest"),
                                         source=f"{source}.operationDigest",
                                         code="PERMISSION_DECISION_INVALID"),
            target=None if target is None else _field(target, source=f"{source}.target",
                                                      code="PERMISSION_DECISION_INVALID"),
            ceiling_revision=_field(raw.get("ceilingRevision"),
                                    source=f"{source}.ceilingRevision",
                                    code="PERMISSION_DECISION_INVALID"),
            policy_revision=_field(raw.get("policyRevision"), source=f"{source}.policyRevision",
                                   code="PERMISSION_DECISION_INVALID"),
            native_generation=_field(raw.get("nativeGeneration"),
                                     source=f"{source}.nativeGeneration",
                                     code="PERMISSION_DECISION_INVALID"),
            expires_at=_aware(raw.get("expiresAt"), source=f"{source}.expiresAt",
                              code="PERMISSION_DECISION_INVALID"),
            consumed=consumed,
        )

    @property
    def single_use(self) -> bool:
        return True

    def matches(self, request: Any) -> bool:
        """Every bound field must agree; a near miss is a refusal, not a re-bind."""
        return (self.operation_digest == request.operation_digest
                and self.target == request.target
                and self.ceiling_revision == request.ceiling_revision
                and self.policy_revision == request.policy_revision
                and self.native_generation == request.native_generation)

    def valid_for(self, request: Any, now: dt.datetime) -> bool:
        if self.consumed:
            return False
        if isinstance(now, dt.datetime) and now > self.expires_at:
            return False
        return self.matches(request)

    def consume(self) -> "BoundGrant":
        return replace(self, consumed=True)


@dataclass(frozen=True)
class AllowedOnce:
    """`AllowedOnce(boundGrant)` from §C1: one operation, one use."""

    grant: BoundGrant

    def __post_init__(self) -> None:
        if not isinstance(self.grant, BoundGrant):
            raise PolicyRefusal("PERMISSION_DECISION_INVALID", source="decisions.AllowedOnce",
                                target=type(self.grant).__name__)

    @property
    def outcome(self) -> str:
        return "allowed_once"


@dataclass(frozen=True)
class PendingApproval:
    """`PendingApproval(approvalId)` from §C1: nothing has run yet."""

    approval_id: str

    def __post_init__(self) -> None:
        _field(self.approval_id, source="decisions.PendingApproval",
               code="PERMISSION_APPROVAL_INVALID")

    @property
    def outcome(self) -> str:
        return "pending_approval"


class ApprovalStateKind(str, Enum):
    """The persisted `server_approvals` states, unchanged (FR-10 compatibility)."""

    OPEN = "open"
    SETTLED = "settled"
    INVALID = "invalid"


class ApprovalDecision(str, Enum):
    """The two decisions the existing `approvals.decide` wire accepts."""

    ALLOW = "allow"
    DENY = "deny"


SCOPE_ONCE: Final[str] = "once"
SCOPE_BOUNDED: Final[str] = "bounded"
SCOPE_SESSION_END: Final[str] = "session_end"


@dataclass(frozen=True)
class ApprovalScope:
    """The grant scope an approval decision carries, in the existing wire shape."""

    kind: str

    @classmethod
    def from_record(cls, raw: Any) -> "ApprovalScope":
        source = "decisions.ApprovalScope.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        kind = raw.get("kind")
        if kind == SCOPE_ONCE:
            if set(raw) != {"kind"}:
                raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                   target="once scope has unexpected fields")
            return OnceApprovalScope()
        if kind == SCOPE_BOUNDED:
            if set(raw) != {"kind", "until", "environmentId"}:
                raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                   target="bounded scope has unexpected fields")
            if raw.get("until") != SCOPE_SESSION_END:
                raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                   target=probe(raw.get("until")))
            environment_id = raw.get("environmentId")
            if environment_id is not None:
                environment_id = _field(environment_id, source=f"{source}.environmentId",
                                        code="PERMISSION_APPROVAL_INVALID")
            return BoundedApprovalScope(until=SCOPE_SESSION_END, environment_id=environment_id)
        raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                           target=probe(kind))

    def as_record(self) -> dict[str, Any]:
        return {"kind": self.kind}


@dataclass(frozen=True)
class OnceApprovalScope(ApprovalScope):
    kind: str = SCOPE_ONCE


@dataclass(frozen=True)
class BoundedApprovalScope(ApprovalScope):
    kind: str = SCOPE_BOUNDED
    until: str = SCOPE_SESSION_END
    environment_id: str | None = None

    def as_record(self) -> dict[str, Any]:
        return {"kind": self.kind, "until": self.until, "environmentId": self.environment_id}


def scope_to_record(scope: ApprovalScope | None) -> dict[str, Any] | None:
    return None if scope is None else scope.as_record()


@dataclass(frozen=True)
class ApprovalRequest:
    """What the user is being asked to rule on, bound to one operation."""

    approval_id: str
    session_id: str
    execution_id: str
    native_request_id: str
    operation_digest: str
    tool: str
    ceiling_revision: str
    policy_revision: str
    native_generation: str
    requested_at: dt.datetime
    expires_at: dt.datetime
    version: int = 1
    target: str | None = None

    @classmethod
    def from_record(cls, raw: Any) -> "ApprovalRequest":
        source = "decisions.ApprovalRequest.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        extra = set(raw) - _REQUEST_FIELDS
        if extra:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                               target="unknown approval request fields: "
                                      + ",".join(sorted(extra)))
        for wire in _REQUEST_FIELDS - {"target", "version"}:
            if raw.get(wire) is None:
                raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                   target=f"missing {wire}")
        version = raw.get("version", 1)
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=f"{source}.version",
                                target=repr(version))
        requested_at = _aware(raw.get("requestedAt"), source=f"{source}.requestedAt",
                              code="PERMISSION_APPROVAL_INVALID")
        expires_at = _aware(raw.get("expiresAt"), source=f"{source}.expiresAt",
                            code="PERMISSION_APPROVAL_INVALID")
        if expires_at <= requested_at:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=f"{source}.expiresAt",
                                target="expiresAt must be after requestedAt")
        target = raw.get("target")
        return cls(
            approval_id=_field(raw.get("approvalId"), source=f"{source}.approvalId",
                               code="PERMISSION_APPROVAL_INVALID"),
            session_id=_field(raw.get("sessionId"), source=f"{source}.sessionId",
                              code="PERMISSION_APPROVAL_INVALID"),
            execution_id=_field(raw.get("executionId"), source=f"{source}.executionId",
                                code="PERMISSION_APPROVAL_INVALID"),
            native_request_id=_field(raw.get("nativeRequestId"),
                                     source=f"{source}.nativeRequestId",
                                     code="PERMISSION_APPROVAL_INVALID"),
            operation_digest=_digest_text(raw.get("operationDigest"),
                                         source=f"{source}.operationDigest",
                                         code="PERMISSION_APPROVAL_INVALID"),
            tool=ToolIdentity(raw.get("toolKey")).key,
            ceiling_revision=_field(raw.get("ceilingRevision"),
                                    source=f"{source}.ceilingRevision",
                                    code="PERMISSION_APPROVAL_INVALID"),
            policy_revision=_field(raw.get("policyRevision"), source=f"{source}.policyRevision",
                                   code="PERMISSION_APPROVAL_INVALID"),
            native_generation=_field(raw.get("nativeGeneration"),
                                     source=f"{source}.nativeGeneration",
                                     code="PERMISSION_APPROVAL_INVALID"),
            requested_at=requested_at, expires_at=expires_at, version=version,
            target=None if target is None else _field(target, source=f"{source}.target",
                                                      code="PERMISSION_APPROVAL_INVALID"),
        )

    def bound_to(self, *, operation_digest: str, target: str | None = None,
                 policy_revision: str, ceiling_revision: str, native_generation: str) -> bool:
        return (self.operation_digest == operation_digest
                and (target is None or self.target == target)
                and self.policy_revision == policy_revision
                and self.ceiling_revision == ceiling_revision
                and self.native_generation == native_generation)

    def alive_at(self, moment: dt.datetime) -> bool:
        return isinstance(moment, dt.datetime) and moment <= self.expires_at


@dataclass(frozen=True)
class ApprovalState:
    """The CAS state of one approval, in the persisted vocabulary."""

    approval_id: str
    session_id: str
    execution_id: str
    version: int
    state: ApprovalStateKind
    native_request_id: str
    decision: ApprovalDecision | None = None
    scope: ApprovalScope | None = None
    request_id: str | None = None

    @classmethod
    def from_record(cls, raw: Any) -> "ApprovalState":
        source = "decisions.ApprovalState.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        extra = set(raw) - _STATE_FIELDS
        if extra:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                               target="unknown approval state fields: " + ",".join(sorted(extra)))
        for wire in ("approvalId", "sessionId", "executionId", "version", "state",
                     "nativeRequestId"):
            if raw.get(wire) is None:
                raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                   target=f"missing {wire}")
        try:
            kind = ApprovalStateKind(raw["state"])
        except ValueError:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=f"{source}.state",
                                target=probe(raw.get("state"))) from None
        decision = raw.get("decision")
        if decision is None:
            if kind is ApprovalStateKind.SETTLED:
                raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=f"{source}.decision",
                                    target="a settled approval has no decision")
        else:
            try:
                decision = ApprovalDecision(decision)
            except ValueError:
                raise PolicyRefusal("PERMISSION_APPROVAL_INVALID",
                                    source=f"{source}.decision",
                                    target=probe(raw.get("decision"))) from None
        version = raw.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=f"{source}.version",
                                target=repr(version))
        raw_scope = raw.get("scope")
        request_id = raw.get("requestId")
        return cls(
            approval_id=_field(raw.get("approvalId"), source=f"{source}.approvalId",
                               code="PERMISSION_APPROVAL_INVALID"),
            session_id=_field(raw.get("sessionId"), source=f"{source}.sessionId",
                              code="PERMISSION_APPROVAL_INVALID"),
            execution_id=_field(raw.get("executionId"), source=f"{source}.executionId",
                                code="PERMISSION_APPROVAL_INVALID"),
            version=version, state=kind,
            native_request_id=_field(raw.get("nativeRequestId"),
                                     source=f"{source}.nativeRequestId",
                                     code="PERMISSION_APPROVAL_INVALID"),
            decision=decision,
            scope=None if raw_scope is None else ApprovalScope.from_record(raw_scope),
            request_id=None if request_id is None else _field(
                request_id, source=f"{source}.requestId", code="PERMISSION_APPROVAL_INVALID"),
        )

    @property
    def is_open(self) -> bool:
        return self.state is ApprovalStateKind.OPEN

    @property
    def actionable(self) -> bool:
        return self.is_open


@dataclass(frozen=True)
class NativeReceipt:
    """What the native owner said about the request it was given."""

    native_request_id: str
    approval_id: str
    confirmed: bool
    observed_at: dt.datetime | None = None

    @classmethod
    def of(cls, *, native_request_id: Any, approval_id: Any, confirmed: Any,
           observed_at: Any = None) -> "NativeReceipt":
        source = "decisions.NativeReceipt.of"
        if not isinstance(confirmed, bool):
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=f"{source}.confirmed",
                                target=type(confirmed).__name__)
        stamp = None if observed_at is None else _aware(
            observed_at, source=f"{source}.observedAt", code="PERMISSION_APPROVAL_INVALID")
        if confirmed and stamp is None:
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=f"{source}.observedAt",
                                target="a confirmed receipt needs when it was observed")
        return cls(
            native_request_id=_field(native_request_id, source=f"{source}.nativeRequestId",
                                     code="PERMISSION_APPROVAL_INVALID"),
            approval_id=_field(approval_id, source=f"{source}.approvalId",
                               code="PERMISSION_APPROVAL_INVALID"),
            confirmed=confirmed, observed_at=stamp,
        )

    @classmethod
    def unknown(cls, *, native_request_id: Any, approval_id: Any) -> "NativeReceipt":
        """No corroboration yet: `unknown`, which is not the same as `no`."""
        return cls.of(native_request_id=native_request_id, approval_id=approval_id,
                      confirmed=False, observed_at=None)


@dataclass(frozen=True)
class ApprovalFact:
    """The queryable union: what was asked, what was decided, what was seen."""

    request: ApprovalRequest
    state: ApprovalState
    receipt: NativeReceipt | None = None

    @classmethod
    def of(cls, *, request: Any, state: Any, receipt: Any = None) -> "ApprovalFact":
        source = "decisions.ApprovalFact.of"
        if not isinstance(request, ApprovalRequest) or not isinstance(state, ApprovalState):
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                target="a fact needs its request and its state")
        if receipt is not None and not isinstance(receipt, NativeReceipt):
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                target=type(receipt).__name__)
        if (request.approval_id != state.approval_id
                or request.session_id != state.session_id
                or request.execution_id != state.execution_id
                or request.native_request_id != state.native_request_id):
            # Two records that disagree about who they belong to are not a fact.
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                target="approval identity fields disagree")
        if receipt is not None and (receipt.approval_id != request.approval_id
                                    or receipt.native_request_id != request.native_request_id):
            raise PolicyRefusal("PERMISSION_APPROVAL_INVALID", source=source,
                                target="native receipt correlation disagrees")
        return cls(request=request, state=state, receipt=receipt)

    @property
    def approval_id(self) -> str:
        return self.request.approval_id

    @property
    def operation_digest(self) -> str:
        return self.request.operation_digest

    @property
    def settled(self) -> bool:
        return self.state.state is not ApprovalStateKind.OPEN

    @property
    def native_confirmed(self) -> bool:
        return self.receipt is not None and self.receipt.confirmed


# --- decide / query outcome unions -----------------------------------------

class DecideResult:
    """Base of the `decide(...)` union from §C1."""

    __slots__ = ()

    @property
    def kind(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    @property
    def grants_execution(self) -> bool:
        return False


@dataclass(frozen=True)
class Recorded(DecideResult):
    version: int
    decision: ApprovalDecision

    @property
    def kind(self) -> str:
        return "recorded"

    @property
    def grants_execution(self) -> bool:
        return self.decision is ApprovalDecision.ALLOW


@dataclass(frozen=True)
class AlreadyRecorded(DecideResult):
    version: int
    decision: ApprovalDecision
    request_id: str

    @property
    def kind(self) -> str:
        return "already_recorded"

    @property
    def grants_execution(self) -> bool:
        return self.decision is ApprovalDecision.ALLOW


@dataclass(frozen=True)
class InvalidApproval(DecideResult):
    reason: str

    @property
    def kind(self) -> str:
        return "invalid"


@dataclass(frozen=True)
class UnknownApproval(DecideResult):
    """We do not know. Not `invalid`, not `allow`, and not retryable blindly."""

    reason: str

    @property
    def kind(self) -> str:
        return "unknown"


@dataclass(frozen=True)
class QueriedApproval:
    """`query/reconcile` answered: the state, and the receipt if there is one."""

    state: ApprovalState
    receipt: NativeReceipt | None = None

    @property
    def kind(self) -> str:
        return "resolved"

    @property
    def native_confirmed(self) -> bool:
        return self.receipt is not None and self.receipt.confirmed


@dataclass(frozen=True)
class QueryUnknown:
    """`query/reconcile` could not answer; the operation stays unresolved."""

    reason: str

    @property
    def kind(self) -> str:
        return "unknown"

    @property
    def grants_execution(self) -> bool:
        return False


QueryOutcome = QueriedApproval | QueryUnknown
