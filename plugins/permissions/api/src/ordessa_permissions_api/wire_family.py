"""Existing platform wire families for every code this package can emit (T010).

contracts §C4 requires refusals to map onto the wire families the platform
already defines - "错误须映射至既有 wire family, 不修改核心错误分支" - and FR-09
requires the refusal codes themselves to stay stable. This module is the
Permissions domain's published `code -> family` answer: the payload the
backend plugin contributes to the host's open `wire.error-families` seam,
mirroring how the workspace domain publishes its own table. The package stays
pure domain (stdlib plus itself): the platform symbols named below are the
DERIVATION sources checked by `tests/test_wire_family.py`, not imports here.

How each row was derived (every family name is READ from the platform's closed
`FAMILIES` set in `server_plugin_api.wire_errors`; none is invented, and a
guard test asserts `set(values) ⊆ FAMILIES`):

* `APPROVAL_STALE -> APPROVAL_INVALID`: the platform's own
  `STATIC_ERROR_FAMILIES` row; `family_for("APPROVAL_STALE")` answers exactly
  this and the mapping repeats it verbatim (a contributed row may never
  override a static row - the host aggregate refuses such a payload at stage).
* `APPROVAL_NOT_ACTIONABLE -> APPROVAL_INVALID`: the family the static table
  gives every approval-state refusal (`APPROVAL_INVALID`, `APPROVAL_EXPIRED`
  both answer it); the name is in `FAMILIES`.
* `APPROVAL_RESULT_UNKNOWN -> OUTCOME_UNKNOWN`: `family_for` answers the
  documented `UNAVAILABLE` fall-through (no producer composed), and this
  contributed row refines it to the platform family that names the condition
  ("the native outcome could not be confirmed").
* `POLICY_CEILING_VIOLATION -> FORBIDDEN` and `policy_deny -> FORBIDDEN`:
  mirrors the static table's policy-rejection precedent
  (`LOOPBACK_POLICY_REJECTED -> FORBIDDEN`); an administrator upper bound or
  the effective policy denying is a permission refusal, not a bad request.
* `POLICY_ADAPTER_MISSING -> CAPABILITY_UNSUPPORTED` and
  `PERMISSION_UNKNOWN_TOOL -> CAPABILITY_UNSUPPORTED`: the platform family
  for "this cannot be honoured here", the spelling the static table already
  uses for missing capability.
* `POLICY_SCOPE_UNVERIFIED -> UNAVAILABLE`: kept at whatever `family_for`
  yields. An unverified policy authority is a transient service-trust absence
  with retry/remedy guidance, not a capability statement, and the lane
  invents no stronger answer than the platform gives without a producer.
* schema refusals (`PERMISSION_*_INVALID`, construction-time only) map to
  `INVALID_REQUEST`, the admission-vocabulary family the static table uses
  for malformed input rows (`REQUEST_INVALID`, `ATTACHMENT_INVALID`);
  `PERMISSION_ACTION_UNSUPPORTED`, `PERMISSION_BRAND_UNSUPPORTED` and
  `PERMISSION_MODE_UNSUPPORTED` map to `CAPABILITY_UNSUPPORTED`.

`unsupported` and `unknown` are NOT merged by this mapping, at either level:

* code level (contracts §C4, unchanged): `unsupported` is
  `POLICY_ADAPTER_MISSING` / `PERMISSION_UNKNOWN_TOOL`, `unknown` is
  `POLICY_SCOPE_UNVERIFIED` / `APPROVAL_RESULT_UNKNOWN` - four distinct
  `RefusalCode` members whose spellings this module only reads;
* family level: every `unsupported`-kind code answers `CAPABILITY_UNSUPPORTED`
  while every `unknown`-kind code answers `UNAVAILABLE` or
  `OUTCOME_UNKNOWN` - disjoint family sets, asserted against `code_kind`.

Because the platform defines no family that would collapse the two, no further
recording of a merge is required; the guard test fails if a future row breaks
the disjointness.
"""
from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping

from .codes import PolicyRefusal, probe

__all__ = [
    "PERMISSION_ERROR_FAMILIES",
    "permissions_wire_family",
    "wire_body_for",
]

#: The plugin's published mapping. Like the workspace domain's table, its
#: module-level identity is the transaction token the host's
#: `wire.error-families` handler stages and commits - never a fresh copy per
#: build. Every value is a member of the platform's closed `FAMILIES` set
#: (guard-tested); the keys are exactly the codes this package can emit.
PERMISSION_ERROR_FAMILIES: Mapping[str, str] = MappingProxyType({
    # enforcement codes (contracts §C4 set, spellings owned by `codes.py`)
    "POLICY_CEILING_VIOLATION": "FORBIDDEN",
    "POLICY_ADAPTER_MISSING": "CAPABILITY_UNSUPPORTED",
    "POLICY_SCOPE_UNVERIFIED": "UNAVAILABLE",
    "PERMISSION_UNKNOWN_TOOL": "CAPABILITY_UNSUPPORTED",
    "APPROVAL_STALE": "APPROVAL_INVALID",
    "APPROVAL_NOT_ACTIONABLE": "APPROVAL_INVALID",
    "APPROVAL_RESULT_UNKNOWN": "OUTCOME_UNKNOWN",
    # the effective-policy denial value (`PolicyDenyCode`)
    "policy_deny": "FORBIDDEN",
    # construction-time schema refusals (`SCHEMA_CODES`; never reported as a
    # decision, but still emittable as a typed diagnostic)
    "PERMISSION_RULE_INVALID": "INVALID_REQUEST",
    "PERMISSION_ACTION_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
    "PERMISSION_PATTERN_INVALID": "INVALID_REQUEST",
    "PERMISSION_CEILING_INVALID": "INVALID_REQUEST",
    "PERMISSION_INTENT_INVALID": "INVALID_REQUEST",
    "PERMISSION_SNAPSHOT_INVALID": "INVALID_REQUEST",
    "PERMISSION_REQUEST_INVALID": "INVALID_REQUEST",
    "PERMISSION_DECISION_INVALID": "INVALID_REQUEST",
    "PERMISSION_APPROVAL_INVALID": "INVALID_REQUEST",
    "PERMISSION_BRAND_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
    "PERMISSION_MODE_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
    "PERMISSION_AUTHORIZATION_INVALID": "INVALID_REQUEST",
    "PERMISSION_DIAGNOSTIC_INVALID": "INVALID_REQUEST",
})


def permissions_wire_family(code: Any, *, resolver: Callable[[str], str] | None = None) -> str:
    """The existing platform family for a code this package can emit.

    `resolver` is the one-argument callable a composition injects (the host's
    aggregate answer); when present it wins even where it answers
    `UNAVAILABLE`, because that is the honest statement of "this composition
    did not stage the producer". Without one the published table answers. A
    code outside this package's vocabulary is refused with
    `PERMISSION_DIAGNOSTIC_INVALID` rather than given a family - the same
    closed-vocabulary rule `codes.PolicyRefusal` enforces at construction.
    """
    value = code.value if isinstance(code, Enum) else code
    if not isinstance(value, str) or value not in PERMISSION_ERROR_FAMILIES:
        raise PolicyRefusal("PERMISSION_DIAGNOSTIC_INVALID",
                            source="wire_family.permissions_wire_family",
                            target=probe(value))
    if resolver is not None:
        return resolver(value)
    return PERMISSION_ERROR_FAMILIES[value]


def wire_body_for(refusal: PolicyRefusal,
                  *, resolver: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Project a typed refusal onto the platform wire body, family and all.

    The shape is the one the platform's own error object sends: the family in
    the `code` slot, the human-readable diagnostic as `message`, and
    `details.internalCode` keeping the precise internal spelling - the same
    convention `converge_family` uses for a projected value. `source`,
    `target` and `remedy` ride along because FR-09 requires the diagnostic to
    stay understandable; they are already bounded single-line text validated
    by `PolicyRefusal`, so there is no field a tool argument or a credential
    could be carried through, before or after the mapping.
    """
    if not isinstance(refusal, PolicyRefusal):
        raise PolicyRefusal("PERMISSION_DIAGNOSTIC_INVALID",
                            source="wire_family.wire_body_for",
                            target=probe(refusal))
    family = permissions_wire_family(refusal.code, resolver=resolver)
    details: dict[str, Any] = {"internalCode": refusal.code, "source": refusal.source}
    if refusal.target is not None:
        details["target"] = refusal.target
    details["remedy"] = refusal.remedy
    if refusal.index is not None:
        details["index"] = refusal.index
    return {"code": family, "message": str(refusal), "details": details}
