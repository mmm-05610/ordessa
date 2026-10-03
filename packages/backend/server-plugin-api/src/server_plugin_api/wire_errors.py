"""wire/1's closed family set, the static code→family table and `WireError`.

T014-S2c published this module because *plugins* raise `WireError` directly
(the compatibility core's refusal path, the workspace plugin's wire surface,
the ACP plugin's capability refusals) and importing it from
`ordessa_server.wire.errors` was a rule-3 breach. One implementation answers
for host and plugin alike, which is the only way the frozen strings
(`"models must be a list"`, `INVALID_REQUEST`, the 67-row family answers) stay
byte-identical after the move.

What is deliberately **not** here: the contributed half of the table. Contributed
rows are per-composition state owned by the declaring plugin host
(`ordessa_server.wire.errors.ErrorFamilyAggregate`), and a plugin never reads an
aggregate — it contributes a payload and resolves through the callable the host
injects. This module holds only the *static* answers:

- `FAMILIES`: wire/1's closed twelve families (a new one is a contract change);
- `STATIC_ERROR_FAMILIES` (historically `_BY_CODE`): the codes the host itself
  or no component at all produces — transport/admission vocabulary, the kernel
  words, and the documented no-producer fallback rows;
- `family_for`: static table → family name → the `UNAVAILABLE` fall-through;
- `converge_family`: project a value that reached the family slot onto a real
  family, keeping the original in `details.internalCode`;
- `WireError`: the error object the wire sends, whose `__post_init__` converges.

The fall-through is load-bearing: an unregistered code answers `UNAVAILABLE`
and keeps its precise spelling in `details.internalCode`, so a composition
without a code's producer gives the honest typed absence instead of a 500.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


FAMILIES = frozenset({
    "UNAVAILABLE",
    "UNAUTHENTICATED",
    "FORBIDDEN",
    "NOT_FOUND",
    "CONFLICT_VERSION",
    "CONFLICT_REQUEST",
    "CONFLICT_REFERENCE",
    "INVALID_REQUEST",
    "CAPABILITY_UNSUPPORTED",
    "OUTCOME_UNKNOWN",
    "WORKER_UNREACHABLE",
    "APPROVAL_INVALID",
})

# Internal code -> wire family, for the rows the STATIC table answers: the
# transport/admission vocabulary (`REQUEST_*`, `AUTHENTICATION_REQUIRED`,
# `LOOPBACK_POLICY_REJECTED`), the connector-worker rows the host-side
# connector implementation still answers with, and the kernel-vocabulary
# rows (`SECRET_FIELD_FORBIDDEN`, `CAPABILITY_UNSUPPORTED` — produced by the
# kernel as well as by plugins, so a kernel word does not move into a
# plugin). Business rows live with the plugin that raises them and arrive
# through the `wire.error-families` contribution — since T014-S2b that
# includes `SSH_TARGET_INVALID` / `SSH_IDENTITY_INVALID`: the connector the
# host used to build is composed by the workspace plugin now, so those rows
# moved with the construction.
# Codes are matched exactly (never by prefix), so a specific code can not be
# swallowed by a shorter one.
STATIC_ERROR_FAMILIES: Mapping[str, str] = {
    "IDEMPOTENCY_CONFLICT": "CONFLICT_REQUEST",
    "ENTERPRISE_STATE_CONFLICT": "CONFLICT_REQUEST",
    "RECORD_VERSION_CONFLICT": "CONFLICT_VERSION",
    "APPROVAL_INVALID": "APPROVAL_INVALID",
    "APPROVAL_STALE": "APPROVAL_INVALID",
    "APPROVAL_EXPIRED": "APPROVAL_INVALID",
    "WORKSPACE_NOT_FOUND": "NOT_FOUND",
    "CREDENTIAL_NOT_FOUND": "NOT_FOUND",
    "REQUEST_INVALID": "INVALID_REQUEST",
    "REQUEST_TOO_LARGE": "INVALID_REQUEST",
    "SECRET_FIELD_FORBIDDEN": "INVALID_REQUEST",
    "ATTACHMENT_INVALID": "INVALID_REQUEST",
    "AUTHENTICATION_REQUIRED": "UNAUTHENTICATED",
    "LOOPBACK_POLICY_REJECTED": "FORBIDDEN",
    "CAPABILITY_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
    "SSH_WORKER_UNAVAILABLE": "UNAVAILABLE",
    "SSH_WORKER_DIGEST_MISMATCH": "UNAVAILABLE",
    "SSH_UNREACHABLE": "WORKER_UNREACHABLE",
    "SERVICE_UNAVAILABLE": "UNAVAILABLE",
    "WORKER_UNREACHABLE": "WORKER_UNREACHABLE",
    "QUEUE_ITEM_TOO_LATE": "CONFLICT_REQUEST",
    "SESSION_BUSY": "CONFLICT_REQUEST",
    "EVENT_CURSOR_EXPIRED": "INVALID_REQUEST",
}


#: What a composition hands a plugin that must project an internal code onto a
#: wire family: a one-argument callable, never the aggregate object itself
#: (T014-S2c — the compat surface used to re-derive families from its own
#: contribution payload and could therefore not see another plugin's rows; an
#: injected resolver answers with the whole composition's table while the
#: plugin still reads no aggregate).
FamilyResolver = Callable[[str], str]


def family_for(code: str) -> str:
    """The STATIC answer: static rows, family names, then the fall-through.

    Deliberately knows nothing about contributions — contributed rows are
    composition state and are resolved through the composition's own
    `ErrorFamilyAggregate.family_for` (see the host's
    `declare_wire_error_families_point` and the transport's
    `error_family_resolver`). A caller that holds no composition resolves
    contributed codes exactly as a composition without their producer does:
    `UNAVAILABLE`.
    """
    if code in STATIC_ERROR_FAMILIES:
        return STATIC_ERROR_FAMILIES[code]
    if code in FAMILIES:
        return code
    return "UNAVAILABLE"


def converge_family(value: str, details: dict[str, Any]) -> str:
    """Project a value that reached the family slot onto a real wire family.

    The alternative is raising, and raising is what made this a user-visible 500:
    the HTTP route answers anything that escapes `dispatch` as a bare status, so
    an internal code written into the family position traded a typed contract
    for twenty-one bytes of plain text (QA-008, AUD-B-001's family).
    The original value survives as `details.internalCode`, which is the same
    place `from_server_error` puts it. Convergence is the STATIC table's job:
    a family slot that holds a contributed code converges to `UNAVAILABLE`
    unless the caller resolved it through its composition first (that is
    exactly what `from_server_error`'s `family_lookup` argument is for).
    """
    family = family_for(value)
    if family != value:
        details.setdefault("internalCode", value)
    return family


@dataclass
class WireError(Exception):
    family: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    current: Any = None

    def __post_init__(self) -> None:
        self.details = dict(self.details)
        self.family = converge_family(self.family, self.details)
        super().__init__(self.message)

    @classmethod
    def from_server_error(cls, exc: Any,
                          family_lookup: "Callable[[str], str] | None" = None,
                          ) -> "WireError":
        """Project an internal ServerError onto the wire family set.

        `family_lookup` is the composition's resolver (an
        `ErrorFamilyAggregate.family_for` bound, as a lambda, at the
        transport's construction — or the callable a plugin is *injected* with
        at construction time). Without one the conversion answers the static
        table only; a contributed code then converges to the documented
        `UNAVAILABLE` fall-through, exactly as it does in a composition
        without its producer.
        """
        code = str(getattr(exc, "code", "UNAVAILABLE"))
        resolve = family_lookup if family_lookup is not None else family_for
        details: dict[str, Any] = {"internalCode": code}
        retryable = getattr(exc, "retryable", None)
        if retryable is not None:
            details["retryable"] = bool(retryable)
        error = cls(resolve(code), str(getattr(exc, "message", "Server operation failed")), details)
        current = getattr(exc, "current", None)
        if current is not None:
            error.current = current
        return error

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.family, "message": self.message}
        if self.details:
            body["details"] = dict(self.details)
        if self.current is not None:
            body["current"] = self.current
        return body
