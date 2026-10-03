"""T06 production wiring: the Q5 permissions domain behind Q4's fail-closed gate.

This module adapts the consumed ``codex/011-permissions-api-ready`` checkpoint
(consumption SHA recorded in ``specs/011-q4-mcp/checkpoint-consumption.md``) to
the two Q4 seams that were left waiting for it (gap G3):

* :class:`Q5PermissionAuthority` implements the consumer port
  ``backend/permissions.PermissionAuthority`` (frozen file, never edited here)
  and answers its ``authorize_tool_call`` from the **real** Q5 ruling service —
  the ``permissions.backend`` ``Authorizer`` (injected, duck-typed here so this
  plugin keeps its import boundary to published packages only). The Q5 outcome
  union maps 1:1 into ``ToolCallDecision`` and is **never widened**:
  ``AllowedOnce`` -> allowed, ``PendingApproval`` -> ``pending-approval`` (not
  approval: unattended is not implicit consent, contracts §4), ``Denied`` ->
  refused with a category classification (denied / expired / unknown) over the
  Q5 stable code. Any raise, any unrecognised answer, any unattributable call
  fails closed into a refusal before any side effect;
* :func:`q5_policy_denied_definition_ids` derives the resolve-hook
  ``policy_denied`` set (``backend/resolve.py``: "definition ids no layer may
  re-enable") from the real Q5 ceiling intersection: administrator hard denies
  and exposure-cap denials. ``AdminAuthorization`` is deliberately never an
  input — an authorization unlocks an intent-internal exception only and can
  never widen a ceiling (Q5 ``rules.py`` module contract), so it can never
  remove an id from this set.

Explicit thin adaptations (semantic deltas are tabulated in
``specs/011-q4-mcp/reports/t06-wiring.md``; nothing here re-decides):

* **argsDigest spelling** — Q4 producers hash with ``backend/definition.py``
  ``definition_digest`` ("``sha256:``" + 64 lowercase hex); Q5
  ``ArgumentDigest`` accepts the bare 64-hex only. The prefix is stripped here
  and the shape is validated *before* the authority is consulted (an invalid
  digest never reaches Q5, mirroring gate-1's "no consult, no side effects");
* **revision pins** — Q5 ``OperationRequest`` pins (``ceilingRevision``,
  ``policyRevision``) are *derived* from the objects in force
  (``intersect_ceilings`` / ``PermissionIntent.revision_digest``), never typed
  in. The caller's ``policy_revision`` argument is the MCP-plane revision label
  and cannot name a Q5 intent revision, so it is echoed on the decision but
  never used as a pin; pinning is this adapter's ``ceiling_provider`` /
  ``intent_provider`` (composition wires the same objects the injected
  ``Authorizer`` reads — a divergence makes Q5 itself deny
  ``POLICY_CEILING_VIOLATION``, never an allow);
* **request attribution** — Q5 requires every trusted field
  (serverInstanceId, nativeSessionId, executionId, nativeGeneration,
  nativeRequestId, principal, sessionId); the Q4 seam carries only
  principal/session_ref/lease_id. The composition supplies a
  ``binding_provider`` from those; a missing or incomplete binding is an
  ``unknown`` refusal *before* Q5 (a missing trusted fact fails closed — this
  module never substitutes an implicit default, FR-02);
* **tool vocabulary** — Q5's rule vocabulary is closed (``rules.TOOL_KEYS``);
  arbitrary MCP tool names are not Q5 tool keys. The composition supplies a
  ``tool_key_provider``; an unmapped name is passed through *verbatim* so the
  Q5 domain itself refuses it ``PERMISSION_UNKNOWN_TOOL`` — this adapter never
  invents a mapping to widen the gate.

Dependencies: ``ordessa_permissions_api`` (published domain types, imported)
and the Q4 glue constants (same package). The ``Authorizer`` arrives injected;
this module imports no host internals and no storage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, Tuple

import ordessa_permissions_api as q5

from .errors import PERMISSION_REFUSED
from .permissions import (
    GATE_AUTHORITY,
    PERMISSION_ARGS_DIGEST_REQUIRED,
    ToolCallDecision,
)

# -- refusal categories (dispatch: denied / pending / expired / unknown) -------
CATEGORY_DENIED = "denied"
CATEGORY_PENDING = "pending"
CATEGORY_EXPIRED = "expired"
CATEGORY_UNKNOWN = "unknown"

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SHA256_PREFIX = "sha256:"


def normalize_args_digest(digest: Any) -> Optional[str]:
    """The Q5 bare-hex spelling of a Q4 ``args_digest``, or ``None``.

    Accepts ``backend/definition.definition_digest`` output (``sha256:<hex64>``)
    and the bare 64-hex; anything else is unusable as an ``ArgumentDigest``
    and must refuse before the authority is consulted (Q4
    ``PERMISSION_ARGS_DIGEST_REQUIRED`` semantics).
    """
    if not isinstance(digest, str):
        return None
    text = digest[len(_SHA256_PREFIX):] if digest.startswith(_SHA256_PREFIX) else digest
    return text if _HEX64.fullmatch(text) else None


@dataclass(frozen=True)
class Q5RequestBinding:
    """The trusted Q5 request facts one (sessionRef, leaseId) call carries.

    Q4's seam names principal/session_ref/lease_id only; Q5's
    ``OperationRequest`` requires every field (no implicit defaults, FR-02).
    The composition's ``binding_provider`` produces one of these per call —
    from the lease record, the runtime generation and the harness-native
    request correlation — and a ``None`` return is an ``unknown`` refusal.
    """

    server_instance_id: str
    session_id: str
    native_session_id: str
    execution_id: str
    native_generation: str
    native_request_id: str
    target: Optional[str] = None


class Q5AuthorizerPort(Protocol):
    """The injected ruling service: ``permissions.backend.Authorizer``.

    Declared structurally (same signature as the real ``Authorizer.evaluate``)
    so this plugin never imports backend internals at module level; the tests
    run against the real service, not a mock. ``evaluate`` answers the §C1
    union ``AllowedOnce | PendingApproval | Denied`` and owns every record
    side effect (pending-approval rows, one-time grant consumption).
    """

    def evaluate(self, *, principal: Any, session_ref: Any, execution_ref: Any,
                 native_generation: Any, tool_identity: Any, target_facts: Any,
                 argument_digest: Any, ceiling_revision: Any, policy_revision: Any,
                 native_request_id: Any) -> Any: ...


#: Q5 stable code -> refusal category. Codes not listed classify as
#: ``unknown`` (an answer this adapter cannot read is never a denial-shaped
#: "no more" and never anything softer).
_CATEGORY_BY_CODE: Mapping[Any, str] = {
    q5.PolicyDenyCode.POLICY_DENY: CATEGORY_DENIED,
    q5.RefusalCode.POLICY_CEILING_VIOLATION: CATEGORY_DENIED,
    q5.RefusalCode.APPROVAL_STALE: CATEGORY_EXPIRED,
    q5.RefusalCode.APPROVAL_NOT_ACTIONABLE: CATEGORY_EXPIRED,
    q5.RefusalCode.POLICY_ADAPTER_MISSING: CATEGORY_UNKNOWN,
    q5.RefusalCode.POLICY_SCOPE_UNVERIFIED: CATEGORY_UNKNOWN,
    q5.RefusalCode.PERMISSION_UNKNOWN_TOOL: CATEGORY_UNKNOWN,
    q5.RefusalCode.APPROVAL_RESULT_UNKNOWN: CATEGORY_UNKNOWN,
}


def _category_for_code(code: Any) -> str:
    if isinstance(code, (q5.RefusalCode, q5.PolicyDenyCode)):
        return _CATEGORY_BY_CODE.get(code, CATEGORY_UNKNOWN)
    if isinstance(code, str):
        for enum_type in (q5.RefusalCode, q5.PolicyDenyCode):
            try:
                return _CATEGORY_BY_CODE.get(enum_type(code), CATEGORY_UNKNOWN)
            except ValueError:
                continue
    return CATEGORY_UNKNOWN


def _denied_message(denied: q5.Denied) -> str:
    reason = denied.reason
    if reason is None:
        message = "the Q5 authority denied this operation"
    else:
        message = getattr(reason, "message", None)
        if message is None:  # a bare-string reason (decisions._as_reason)
            message = str(reason)
    return message


class Q5PermissionAuthority:
    """The Q4 ``PermissionAuthority`` port served by the real Q5 domain.

    Every input the Q4 seam does not carry arrives injected; each absent piece
    fails closed, never open:

    * ``authorizer`` — the ruling service (``Authorizer``); required. A raise
      inside is a refusal (``unknown``), never a crash into the call path and
      never an allow;
    * ``ceiling_provider`` / ``intent_provider`` — the same current objects
      the injected authorizer reads, used only to compute Q5's derived
      revision pins (see module docstring); absent ceiling provider or an
      empty current ceiling set -> refusal (``unknown``; the empty-set reading
      is exactly Q5's own ``POLICY_ADAPTER_MISSING``, never an open field);
      absent intent -> the real ``NO_INTENT_REVISION``
      pin (a value, not an absence — Q5 ``intents.py``);
    * ``binding_provider(session_ref=..., lease_id=..., tool_name=...,
      args_digest=...) -> Q5RequestBinding | None`` — trusted request facts;
      ``None`` or a blank field -> refusal (``unknown``);
    * ``tool_key_provider(tool_name) -> str`` — MCP tool name to Q5 tool key;
      default is the identity map, so unmapped names ride into Q5's own
      closed-vocabulary refusal ``PERMISSION_UNKNOWN_TOOL``.
    """

    def __init__(self, *, authorizer: Q5AuthorizerPort,
                 binding_provider: Callable[..., Optional[Q5RequestBinding]],
                 ceiling_provider: Optional[Callable[[], Sequence[Any]]] = None,
                 intent_provider: Optional[Callable[[], Optional[q5.PermissionIntent]]] = None,
                 tool_key_provider: Optional[Callable[[str], str]] = None) -> None:
        self._authorizer = authorizer
        self._binding_provider = binding_provider
        self._ceiling_provider = ceiling_provider
        self._intent_provider = intent_provider
        self._tool_key_provider = tool_key_provider

    # -- the Q4 consumer port ---------------------------------------------------

    def authorize_tool_call(self, *, principal: Optional[str], session_ref: Optional[str],
                            lease_id: Optional[str], tool_name: str, args_digest: str,
                            policy_revision: Optional[str]) -> ToolCallDecision:
        """Ask the Q5 authority; map its answer without widening it.

        Order is load-bearing: the digest shape is checked before Q5 is
        touched (a refusal must not even write a pending-approval row), and
        every path after the ruling is a pure projection of the real Q5
        outcome union onto ``ToolCallDecision``.
        """
        digest = normalize_args_digest(args_digest)
        if digest is None:
            return ToolCallDecision.refused(
                code=PERMISSION_ARGS_DIGEST_REQUIRED,
                reason=f"[{CATEGORY_UNKNOWN}] the args digest is not a usable "
                       f"{_SHA256_PREFIX}<hex64> value; refused before the Q5 "
                       "authority is consulted (no side effects on an unattributable call)",
                gate=GATE_AUTHORITY, policy_revision=policy_revision)
        try:
            outcome, pins = self._rule(
                principal=principal, session_ref=session_ref, lease_id=lease_id,
                tool_name=tool_name, digest=digest)
        except _Q5Unavailable as failure:
            return ToolCallDecision.refused(
                code=PERMISSION_REFUSED,
                reason=f"[{CATEGORY_UNKNOWN}] {failure.adapted_reason}",
                gate=GATE_AUTHORITY, policy_revision=policy_revision)
        return self._project(outcome, pins=pins, policy_revision=policy_revision)

    # -- internals ----------------------------------------------------------------

    def _rule(self, *, principal: Optional[str], session_ref: Optional[str],
              lease_id: Optional[str], tool_name: str,
              digest: str) -> Tuple[Any, Mapping[str, Optional[str]]]:
        binding = self._binding_provider(
            session_ref=session_ref, lease_id=lease_id, tool_name=tool_name,
            args_digest=digest)
        if binding is None:
            raise _Q5Unavailable(
                "the call is not attributable to a Q5 operation "
                f"(no request binding for session_ref={session_ref!r} "
                f"lease_id={lease_id!r}); a missing trusted fact fails closed")
        if self._ceiling_provider is None:
            raise _Q5Unavailable("no ceiling provider is composed; the Q5 domain "
                                 "refuses every ruling without one (adapter missing)")
        try:
            ceilings = tuple(self._ceiling_provider() or ())
        except q5.PolicyRefusal as refusal:
            raise _Q5Unavailable(
                f"the ceiling provider refused: {refusal.code}") from refusal
        except Exception as exc:
            raise _Q5Unavailable(
                f"the ceiling provider raised {type(exc).__name__}") from exc
        if not ceilings:
            # Q5's own reading of an empty set is POLICY_ADAPTER_MISSING
            # (intersect_ceilings); the adapter mirrors the refusal without
            # inventing a pin — nothing proceeds while no trusted ceiling exists.
            raise _Q5Unavailable("no current ceiling from the composed provider "
                                 "(Q5 POLICY_ADAPTER_MISSING: operations stay refused)")
        try:
            effective = q5.intersect_ceilings(list(ceilings))
            intent = (self._intent_provider()
                      if self._intent_provider is not None else None)
            if intent is not None and not isinstance(intent, q5.PermissionIntent):
                raise _Q5Unavailable("the intent provider answered a non-intent object")
            tool_key = (self._tool_key_provider(tool_name)
                        if self._tool_key_provider is not None else tool_name)
            argument_digest = q5.ArgumentDigest.of(digest)
            authorizer = self._authorizer
            policy_pin = (q5.NO_INTENT_REVISION if intent is None
                          else intent.revision_digest)
            outcome = authorizer.evaluate(
                principal=principal,
                session_ref={"serverInstanceId": binding.server_instance_id,
                             "sessionId": binding.session_id,
                             "nativeSessionId": binding.native_session_id},
                execution_ref=binding.execution_id,
                native_generation=binding.native_generation,
                tool_identity=tool_key,
                target_facts=None if binding.target is None else {"target": binding.target},
                argument_digest=argument_digest,
                ceiling_revision=effective.revision_digest,
                policy_revision=policy_pin,
                native_request_id=binding.native_request_id)
        except q5.PolicyRefusal as refusal:
            raise _Q5Unavailable(
                f"the Q5 domain refused the request construction: {refusal.code}") \
                from refusal
        except _Q5Unavailable:
            raise
        except Exception as exc:  # fail closed: a broken authority is a refusal
            raise _Q5Unavailable(
                f"the Q5 authority raised {type(exc).__name__}; "
                "refused before side effects") from exc
        return outcome, {"policy_revision": policy_pin,
                         "ceiling_revision": effective.revision_digest}

    def _project(self, outcome: Any, *, pins: Mapping[str, Optional[str]],
                 policy_revision: Optional[str]) -> ToolCallDecision:
        pin = pins.get("policy_revision")
        echoed = pin if pin is not None else policy_revision
        if isinstance(outcome, q5.AllowedOnce):
            grant = outcome.grant  # BoundGrant, single-use, operation-bound
            return ToolCallDecision.allowed(
                basis="authority", gate=GATE_AUTHORITY,
                policy_revision=echoed,
                expires_at=grant.expires_at.timestamp())
        if isinstance(outcome, q5.PendingApproval):
            # Q5 asked for a human ruling: the call still stops here. Pending
            # is never folded into an allow for unattended execution.
            return ToolCallDecision.pending(
                reason=f"[{CATEGORY_PENDING}] the Q5 authority opened approval "
                       f"{outcome.approval_id!r} for this exact operation; nothing "
                       "has run and unattended is not implicit consent",
                gate=GATE_AUTHORITY, policy_revision=echoed)
        if isinstance(outcome, q5.Denied):
            code = outcome.code
            code_value = code.value if isinstance(
                code, (q5.RefusalCode, q5.PolicyDenyCode)) else str(code)
            category = _category_for_code(code)
            return ToolCallDecision.refused(
                code=PERMISSION_REFUSED,
                reason=f"[{category}] Q5 {code_value}: {_denied_message(outcome)} "
                       f"(evidence {outcome.evidence_ref})",
                gate=GATE_AUTHORITY, policy_revision=echoed)
        # An answer outside the §C1 union is `unknown`, never a guess.
        return ToolCallDecision.refused(
            code=PERMISSION_REFUSED,
            reason=f"[{CATEGORY_UNKNOWN}] the Q5 authority answered an unrecognized "
                   f"outcome {type(outcome).__name__}; refusing before side effects",
            gate=GATE_AUTHORITY, policy_revision=echoed)


class _Q5Unavailable(Exception):
    """Internal carrier: the Q5 plane could not speak about this call.

    Always projected to a fail-closed ``unknown`` refusal; it never escapes
    :meth:`Q5PermissionAuthority.authorize_tool_call` as an exception, because
    the call site treats a raised authority exactly as a refusal but the
    typed decision is what the audit references.
    """

    def __init__(self, adapted_reason: str) -> None:
        super().__init__(adapted_reason)
        self.adapted_reason = adapted_reason


# -- the resolve.py `policy_denied` hook supplier --------------------------------


def q5_policy_denied_definition_ids(
        *, ceilings: Sequence[Any],
        bindings: Sequence[Mapping[str, Any]]) -> Tuple[str, ...]:
    """Definition ids no assignment layer may re-enable, from the real Q5 ceiling.

    ``bindings`` names what each definition's enablement would execute in the
    Q5 vocabulary: ``{"definition_id": str, "tool_key": str,
    "target": str | None}``. An id is denied when the *effective* ceiling
    (``intersect_ceilings`` — denials accumulate, exposure takes the strictest
    bound) hard-denies its (tool, target), or when the exposure an allow on
    that tool implies exceeds the ceiling's ``maximum_exposure`` (the same
    test ``synthesis`` applies to an intent allow).

    Fail-closed readings:
    * no ceilings at all, or an untrusted intersection, or a ceiling set Q5
      cannot intersect -> **every** bound id is denied (a missing/unverifiable
      provider is exactly the state in which no re-enable may be trusted);
    * a ``tool_key`` outside the closed Q5 vocabulary -> denied (an unknown
      tool is never "no rule").

    ``AdminAuthorization`` is deliberately **not** an input: it unlocks an
    intent-internal priority exception only and can never widen a ceiling
    (Q5 ``rules.py``: "it can never widen a ceiling"), so no authorization can
    remove an id from this set.
    """
    items = list(ceilings or ())
    bound = [b for b in bindings]
    all_ids = tuple(str(b.get("definition_id")) for b in bound
                    if isinstance(b, Mapping) and b.get("definition_id"))
    if not items:
        return all_ids
    try:
        effective = q5.intersect_ceilings(items)
    except q5.PolicyRefusal:
        return all_ids
    if not effective.is_trusted:
        return all_ids
    denied = []
    for binding in bound:
        definition_id = binding.get("definition_id") if isinstance(binding, Mapping) else None
        if not isinstance(definition_id, str) or not definition_id:
            continue
        tool_key = binding.get("tool_key")
        target = binding.get("target")
        if not isinstance(tool_key, str) or tool_key not in q5.TOOL_KEYS:
            denied.append(definition_id)  # unknown vocabulary: never re-enableable
            continue
        if effective.blocks(tool_key, target):
            denied.append(definition_id)
            continue
        if q5.TOOL_EXPOSURE[tool_key].rank > effective.maximum_exposure.rank:
            denied.append(definition_id)
    return tuple(denied)
