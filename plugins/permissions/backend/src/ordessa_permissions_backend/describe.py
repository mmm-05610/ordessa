"""`permissions.policy.describe` - the read-only policy summary for Settings.

The Permissions Settings region (ux.md §Settings: 规则来源 / 组织上限只读摘要 /
用户默认意图) needs to show what the PolicyRepository actually holds; until
this method the only readers were in-process. Like the sandbox sibling's
`sandbox.describe`, this is a read with an exact declared shape: no required
params, the optional params `principal`/`scope`, nothing else.

What "read-only" means concretely here:

* the handler only ever reads the two policy stores and the review-finding
  rows; a test snapshots every table row and byte-compares after the calls;
* it grants nothing. `ready` is a *description* of the admission port's
  readiness derived exactly like `PermissionsAcpAdmission.ready` (installed
  authority plus authoritative native-session/runtime-generation evidence),
  never a licence; nothing in this response feeds a ruling;
* ceiling entries come from stored records. A `CeilingSource.UNVERIFIED`
  record is reported WITH its source (and its `signed` flag) so a client
  cannot mistake it for an enforceable limit - the enforcement lanes
  (`PolicyCeiling.from_record` provenance check, `ceilings_current()`) keep
  refusing it unchanged; a store that is not wired answers
  `ready: false` with empty lists, never a fabricated default.

Redaction is the package's existing discipline: the response is a closed
projection - every declared field present, nothing else. Unknown or oversized
fields in a stored record are refused outright (the same "unknown fields make
the record unverifiable, they are not ignored" rule as the API), the refusal
message carries the stable code only, and the intent-rule projection never
copies the authorization object or any per-rule payload beyond the closed
vocabulary the records already declare. No tool arguments and no secret
values are reachable from this method; absolute paths appear only inside rule
patterns, exactly as stored.

The `availability` predicate answers the hello question truthfully -
`POLICY_STORE_UNWIRED` when no repository is wired and
`POLICY_STORE_UNREADABLE` when the store cannot be read - and, per order 097,
it never gates dispatch: the handler still answers the honest empty body.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ordessa_permissions_api import (
    CeilingSource,
    PermissionIntent,
    PolicyCeiling,
    PolicyRefusal,
    RefusalCode,
    Scope,
)
from server_plugin_api import WireError
from server_plugin_api.wire_shape import bounded

from .policies import PolicyRepository

__all__ = [
    "DESCRIBE_OPTIONAL_PARAMS",
    "DESCRIBE_REQUIRED_PARAMS",
    "POLICY_DESCRIBE_METHOD",
    "PolicyDescribe",
]

POLICY_DESCRIBE_METHOD = "permissions.policy.describe"
#: exact wire/1 shape: nothing is required; `principal` attributes nothing
#: (stored policy records carry none) and `scope` filters by the record's own
#: scope value. The host's dispatch wall refuses every other param; this
#: handler never re-implements that refusal.
DESCRIBE_REQUIRED_PARAMS: frozenset[str] = frozenset()
DESCRIBE_OPTIONAL_PARAMS: frozenset[str] = frozenset({"principal", "scope"})

#: The closed stored-record vocabularies, pinned against the API by
#: test_policy_describe_record_vocabulary_matches_the_api.
_CEILING_FIELDS = frozenset(
    {"policyId", "scope", "revision", "source", "signed", "deny", "requireApproval",
     "maximumExposure", "effectiveFrom"})
_INTENT_REQUIRED_FIELDS = frozenset(
    {"intentId", "revision", "harnessId", "scope", "rules"})
_INTENT_ALLOWED_FIELDS = _INTENT_REQUIRED_FIELDS | {"desiredMode"}
#: `authorization` is part of the stored rule vocabulary but is deliberately
#: NOT part of the response rule: the projection never copies it.
_INTENT_RULE_ALLOWED_FIELDS = frozenset(
    {"key", "pattern", "action", "priority", "scope", "authorization"})
_SCOPE_VALUES = frozenset(item.value for item in Scope)
_SOURCE_VALUES = frozenset(item.value for item in CeilingSource)
_UNVERIFIED_PROVENANCE = RefusalCode.POLICY_SCOPE_UNVERIFIED.value


def _no_authority() -> bool:
    return False


class PolicyDescribe:
    """The handler + availability pair for `permissions.policy.describe`.

    `policies=None` is the honest unwired state (reachable by direct
    construction; the plugin's own build fails closed without a database
    port); `ready` is injected as a zero-arg predicate so the composed
    handler reports the admission port's readiness, derived exactly like it,
    without reaching into the adapter object.
    """

    def __init__(self, policies: PolicyRepository | None = None, *,
                 ready: Callable[[], bool] | None = None) -> None:
        self._policies = policies
        self._ready = ready if ready is not None else _no_authority

    # -- availability: the hello question only, never a dispatch gate ----------

    def availability(self) -> tuple[bool, str | None]:
        if self._policies is None:
            return False, "POLICY_STORE_UNWIRED: no policy repository is wired"
        try:
            self._policies.ceilings_current_records()
            self._policies.intents_current_records()
            self._policies.review_findings()
        except Exception:
            return False, "POLICY_STORE_UNREADABLE: the policy store could not be read"
        return True, None

    # -- the wire handler ---------------------------------------------------------

    def describe(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(params, Mapping):
            raise WireError("INVALID_REQUEST", "params must be an object")
        scope_filter: str | None = None
        if "scope" in params:
            candidate = bounded(params["scope"], "scope")
            if candidate not in _SCOPE_VALUES:
                raise WireError("INVALID_REQUEST", "scope must name a policy scope")
            scope_filter = candidate
        if "principal" in params:
            # Validated as a bounded string and deliberately inert: policy
            # records carry no principal, so naming one can neither widen nor
            # narrow what this method reports.
            bounded(params["principal"], "principal")
        if self._policies is None:
            ceilings: list[dict[str, Any]] = []
            intents: list[dict[str, Any]] = []
            needs_review: list[dict[str, Any]] = []
        else:
            ceilings = [_ceiling_view(raw)
                        for raw in self._policies.ceilings_current_records()]
            intents = [_intent_view(raw)
                       for raw in self._policies.intents_current_records()]
            # re-projected, never passed through: a finding row leaves the
            # store with exactly these three keys.
            needs_review = [{"source": item["source"], "index": item["index"],
                             "reason": item["reason"]}
                            for item in self._policies.review_findings()]
        if scope_filter is not None:
            ceilings = [item for item in ceilings if item["scope"] == scope_filter]
            intents = [item for item in intents if item["scope"] == scope_filter]
        try:
            ready = bool(self._ready())
        except Exception:
            # readiness is derived, never assumed: a failing source is False.
            ready = False
        return {"ready": ready, "ceilings": ceilings, "intents": intents,
                "needsReview": needs_review}


def _refuse(what: str, code: str) -> ValueError:
    # The message names the layer and the stable code only - never a stored
    # value, so a refusal cannot echo back what it just refused to carry.
    return ValueError(f"{what} is refused: stored record is invalid ({code})")


def _ceiling_view(raw: Mapping[str, Any]) -> dict[str, Any]:
    if set(raw) != _CEILING_FIELDS:
        raise _refuse("the ceiling record", "PERMISSION_CEILING_INVALID")
    scope = raw["scope"] if raw["scope"] in _SCOPE_VALUES else None
    source = raw["source"] if raw["source"] in _SOURCE_VALUES else None
    signed = raw["signed"] if type(raw["signed"]) is bool else None
    if scope is None or source is None or signed is None:
        raise _refuse("the ceiling record", "PERMISSION_CEILING_INVALID")
    try:
        ceiling = PolicyCeiling.from_record(raw)
    except PolicyRefusal as refusal:
        if refusal.code != _UNVERIFIED_PROVENANCE:
            raise _refuse("the ceiling record", refusal.code) from None
        # An untrusted provenance is still a stored record: validate every
        # OTHER field through the API's own parse (a provenance-neutral
        # projection), then report it with its real source and signed flag,
        # so the client sees an unverified row as exactly that. Enforcement
        # lanes keep reading through `from_record(raw)` and keep refusing it.
        probe = dict(raw)
        probe.update({"scope": Scope.ADMIN.value, "source": "signed-admin",
                      "signed": True})
        try:
            ceiling = PolicyCeiling.from_record(probe)
        except PolicyRefusal as nested:
            raise _refuse("the ceiling record", nested.code) from None
    def entries(items) -> list[dict[str, Any]]:
        return [{"key": item.tool.key,
                 "pattern": None if item.target is None else item.target.pattern,
                 "action": item.action} for item in items]
    return {
        "policyId": ceiling.policy_id, "scope": scope, "revision": ceiling.revision,
        "source": source, "signed": signed,
        "maximumExposure": ceiling.maximum_exposure.value,
        "effectiveFrom": ceiling.effective_from.isoformat(),
        "hardDenies": entries(ceiling.hard_denies),
        "requireApproval": entries(ceiling.require_approval),
    }


def _brand_mode_view(mode: Any) -> dict[str, Any]:
    # A brand mode is the closed (brand, name) pair it was declared as: the
    # name is only ever reported bound to its own harness, never as a
    # cross-brand synonym (FR-03).
    return {"brand": mode.brand, "name": mode.name}


def _intent_view(raw: Mapping[str, Any]) -> dict[str, Any]:
    keys = set(raw)
    if not _INTENT_REQUIRED_FIELDS <= keys or keys - _INTENT_ALLOWED_FIELDS:
        raise _refuse("the intent record", "PERMISSION_INTENT_INVALID")
    try:
        intent = PermissionIntent.from_record(raw)
    except PolicyRefusal as refusal:
        raise _refuse("the intent record", refusal.code) from None
    rules = [{"key": rule.tool.key,
              "pattern": None if rule.target is None else rule.target.pattern,
              "action": rule.action.value, "priority": rule.priority,
              "scope": rule.scope.value} for rule in intent.rules]
    mode = intent.desired_mode
    return {
        "intentId": intent.intent_id, "revision": intent.revision,
        "harnessId": intent.harness_id, "scope": intent.scope.value,
        "rules": rules,
        "desiredMode": None if mode is None else _brand_mode_view(mode),
    }
