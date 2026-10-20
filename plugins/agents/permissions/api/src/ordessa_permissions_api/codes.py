"""Stable refusal codes and the diagnostics that carry them (FR-09).

Two vocabularies stay apart on purpose:

* `RefusalCode` is the enforcement subset the wire contract names, and it is
  closed - a caller cannot invent a code at runtime;
* `SCHEMA_CODES` are construction-time refusals (a rule, ceiling or intent
  record that is not shaped right). They are never reported as a decision.

A diagnostic names its source, its target and a remedy suggestion, and nothing
else: there is no field an argument payload or a credential could be carried
through, and every accepted text field is bounded printable single-line text.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Final, Mapping, Sequence

__all__ = [
    "DEFAULT_REMEDIES",
    "MAX_DIAGNOSTIC_TEXT",
    "SCHEMA_CODES",
    "CodeKind",
    "POLICY_DENY",
    "PolicyDenyCode",
    "PolicyRefusal",
    "RefusalCode",
    "code_kind",
    "enforcement_codes",
    "is_enforcement_code",
    "probe",
]

#: Single-line bounded text; control characters (including tabs and newlines)
#: cannot smuggle a payload into a diagnostic.
_SAFE_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")
MAX_DIAGNOSTIC_TEXT = 512


class RefusalCode(str, Enum):
    """The stable enforcement codes; the value is the wire spelling."""

    POLICY_CEILING_VIOLATION = "POLICY_CEILING_VIOLATION"
    POLICY_ADAPTER_MISSING = "POLICY_ADAPTER_MISSING"
    POLICY_SCOPE_UNVERIFIED = "POLICY_SCOPE_UNVERIFIED"
    PERMISSION_UNKNOWN_TOOL = "PERMISSION_UNKNOWN_TOOL"
    APPROVAL_STALE = "APPROVAL_STALE"
    APPROVAL_NOT_ACTIONABLE = "APPROVAL_NOT_ACTIONABLE"
    APPROVAL_RESULT_UNKNOWN = "APPROVAL_RESULT_UNKNOWN"


class PolicyDenyCode(str, Enum):
    """The effective policy denies the operation; nothing was refused *about*
    the request itself, so no `RefusalCode` (which explains a failure) fits."""

    POLICY_DENY = "policy_deny"


#: The one value of `PolicyDenyCode`, exported for call sites that only need to
#: recognise "the policy itself denied this" without naming a failure.
POLICY_DENY: Final[PolicyDenyCode] = PolicyDenyCode.POLICY_DENY


class CodeKind(str, Enum):
    """`unsupported` and `unknown` are different answers and never merged."""

    VIOLATION = "violation"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


_KINDS: Final[Mapping[RefusalCode, CodeKind]] = {
    RefusalCode.POLICY_CEILING_VIOLATION: CodeKind.VIOLATION,
    RefusalCode.APPROVAL_STALE: CodeKind.VIOLATION,
    RefusalCode.APPROVAL_NOT_ACTIONABLE: CodeKind.VIOLATION,
    RefusalCode.POLICY_ADAPTER_MISSING: CodeKind.UNSUPPORTED,
    RefusalCode.PERMISSION_UNKNOWN_TOOL: CodeKind.UNSUPPORTED,
    RefusalCode.POLICY_SCOPE_UNVERIFIED: CodeKind.UNKNOWN,
    RefusalCode.APPROVAL_RESULT_UNKNOWN: CodeKind.UNKNOWN,
}

SCHEMA_CODES: Final[frozenset[str]] = frozenset({
    "PERMISSION_RULE_INVALID",
    "PERMISSION_ACTION_UNSUPPORTED",
    "PERMISSION_PATTERN_INVALID",
    "PERMISSION_CEILING_INVALID",
    "PERMISSION_INTENT_INVALID",
    "PERMISSION_SNAPSHOT_INVALID",
    "PERMISSION_REQUEST_INVALID",
    "PERMISSION_DECISION_INVALID",
    "PERMISSION_APPROVAL_INVALID",
    "PERMISSION_BRAND_UNSUPPORTED",
    "PERMISSION_MODE_UNSUPPORTED",
    "PERMISSION_AUTHORIZATION_INVALID",
    "PERMISSION_DIAGNOSTIC_INVALID",
})

DEFAULT_REMEDIES: Final[Mapping[str, str]] = {
    RefusalCode.POLICY_CEILING_VIOLATION.value:
        "ask the administrator for a ceiling that permits this exposure; a Profile"
        " or session choice cannot widen it",
    RefusalCode.POLICY_ADAPTER_MISSING.value:
        "install or restore the policy provider for this Harness; operations stay"
        " refused while no trusted ceiling exists",
    RefusalCode.POLICY_SCOPE_UNVERIFIED.value:
        "re-obtain this policy record from its trusted source; an unverified or"
        " lower-scope record cannot act as an upper bound",
    RefusalCode.PERMISSION_UNKNOWN_TOOL.value:
        "declare the tool in the permission vocabulary or report the Harness"
        " version; an unknown tool is never treated as 'no rule'",
    RefusalCode.APPROVAL_STALE.value:
        "request a fresh approval for this exact operation; an expired or foreign"
        " grant is not re-bound",
    RefusalCode.APPROVAL_NOT_ACTIONABLE.value:
        "the execution already ended; start a new turn instead of approving the"
        " closed one",
    RefusalCode.APPROVAL_RESULT_UNKNOWN.value:
        "query or reconcile the existing operation before retrying; an unconfirmed"
        " result is never read as approval",
    "PERMISSION_RULE_INVALID":
        "correct the rule: it may only use the declared fields, values and order",
    "PERMISSION_ACTION_UNSUPPORTED":
        "use one of the declared interpretation results (allow, ask, deny)",
    "PERMISSION_PATTERN_INVALID":
        "give a bounded target pattern with a literal prefix; a bare wildcard is not"
        " a target",
    "PERMISSION_CEILING_INVALID":
        "correct the ceiling record's declared fields; unknown fields are not ignored",
    "PERMISSION_INTENT_INVALID":
        "correct the intent record; ceiling-only fields cannot live in an intent",
    "PERMISSION_SNAPSHOT_INVALID":
        "issue a snapshot bound to every identity field; a partial snapshot is not a"
        " decision input",
    "PERMISSION_REQUEST_INVALID":
        "supply every trusted field of the authorization request; a missing fact"
        " fails closed",
    "PERMISSION_DECISION_INVALID":
        "construct the decision through the domain helpers so its binding fields"
        " are complete",
    "PERMISSION_APPROVAL_INVALID":
        "keep the approval record within its declared shape and state machine",
    "PERMISSION_BRAND_UNSUPPORTED":
        "this Harness brand has no declared permission vocabulary here",
    "PERMISSION_MODE_UNSUPPORTED":
        "choose a mode that this brand actually declares; mode names are not shared"
        " across brands",
    "PERMISSION_AUTHORIZATION_INVALID":
        "an exception needs a verifiable administrator authorization bound to this"
        " operation, revision and expiry",
    "PERMISSION_DIAGNOSTIC_INVALID":
        "report a declared code with a bounded single-line source and target",
}

_SUMMARIES: Final[Mapping[str, str]] = {
    RefusalCode.POLICY_CEILING_VIOLATION.value: "an administrator upper bound denies or"
                                                 " narrows this operation",
    RefusalCode.POLICY_ADAPTER_MISSING.value: "no policy provider is present to state a"
                                              " trusted upper bound",
    RefusalCode.POLICY_SCOPE_UNVERIFIED.value: "the policy authority behind this input"
                                              " cannot be verified",
    RefusalCode.PERMISSION_UNKNOWN_TOOL.value: "the tool is not in the permission"
                                              " vocabulary",
    RefusalCode.APPROVAL_STALE.value: "the approval or snapshot no longer refers to this"
                                      " operation",
    RefusalCode.APPROVAL_NOT_ACTIONABLE.value: "the approval can no longer be acted on",
    RefusalCode.APPROVAL_RESULT_UNKNOWN.value: "the native outcome could not be confirmed",
    PolicyDenyCode.POLICY_DENY.value: "the effective policy denies this operation",
}


def enforcement_codes() -> tuple[RefusalCode, ...]:
    """The closed set of enforcement codes."""
    return tuple(RefusalCode)


def code_kind(code: RefusalCode | PolicyDenyCode | str) -> CodeKind:
    value = _code_value(code)
    if value == PolicyDenyCode.POLICY_DENY.value:
        return CodeKind.VIOLATION
    try:
        return _KINDS[RefusalCode(value)]
    except ValueError:
        raise PolicyRefusal("PERMISSION_DIAGNOSTIC_INVALID", source="codes.code_kind") from None


def is_enforcement_code(code: RefusalCode | PolicyDenyCode | str) -> bool:
    return _code_value(code) in {item.value for item in RefusalCode}


def probe(value: Any) -> str:
    """Render an offending value *for* a diagnostic without becoming one.

    A refusal must not fail while describing itself: a blank, control-character
    or over-long value is still named, but only in a form the diagnostic accepts.
    """
    if isinstance(value, str):
        text = value if len(value) <= 200 else value[:197] + "..."
        text = re.sub(r"[\x00-\x1f\x7f]", "?", text)
        return text if text.strip() else repr(value)[:200]
    return type(value).__name__


def _code_value(code: Any) -> str:
    if isinstance(code, (RefusalCode, PolicyDenyCode)):
        return code.value
    if not isinstance(code, str):
        raise PolicyRefusal("PERMISSION_DIAGNOSTIC_INVALID", source="codes._code_value",
                            target=type(code).__name__)
    return code


def _safe_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_TEXT.fullmatch(value) is None or not value.strip():
        raise PolicyRefusal("PERMISSION_DIAGNOSTIC_INVALID",
                            source=f"codes._safe_text({field})",
                            target=type(value).__name__)
    return value


class PolicyRefusal(Exception):
    """A typed refusal: a stable code plus a bounded, argument-free diagnostic."""

    __slots__ = ("code", "source", "target", "remedy", "index")
    #: The only fields a diagnostic can carry; there is no place for tool arguments
    #: or credentials, by construction.
    PUBLIC_FIELDS: Final[Sequence[str]] = ("code", "source", "target", "remedy", "index")

    def __init__(self, code: RefusalCode | PolicyDenyCode | str, *, source: Any,
                 target: Any = None, remedy: Any = None, index: Any = None) -> None:
        value = _code_value(code)
        if value not in DEFAULT_REMEDIES:
            raise PolicyRefusal("PERMISSION_DIAGNOSTIC_INVALID",
                                source="codes.PolicyRefusal", target=value) from None
        source_text = _safe_text(source, field="source")
        target_text = None if target is None else _safe_text(target, field="target")
        remedy_text = _safe_text(remedy, field="remedy") if remedy is not None \
            else DEFAULT_REMEDIES[value]
        if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
            raise PolicyRefusal("PERMISSION_DIAGNOSTIC_INVALID",
                                source="codes.PolicyRefusal(index)",
                                target=type(index).__name__) from None
        super().__init__(self._render(value, source_text, target_text, remedy_text))
        self.code = value
        self.source = source_text
        self.target = target_text
        self.remedy = remedy_text
        self.index = index

    @staticmethod
    def _render(value: str, source: str, target: str | None, remedy: str) -> str:
        parts = [f"source={source}"]
        if target is not None:
            parts.append(f"target={target}")
        parts.append(f"remedy={remedy}")
        if value in _SUMMARIES:
            parts.append(f"meaning={_SUMMARIES[value]}")
        return f"{value}: " + "; ".join(parts)

    @property
    def code_value(self) -> str:
        return self.code

    @property
    def refusal_code(self) -> RefusalCode | None:
        return RefusalCode(self.code) if is_enforcement_code(self.code) else None

    @property
    def human_readable(self) -> str:
        return str(self)
