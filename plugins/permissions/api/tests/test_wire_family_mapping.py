"""T010: every code this package can emit maps to an EXISTING platform family.

contracts §C4: "错误须映射至既有 wire family, 不修改核心错误分支" - the mapping
projects onto the closed family vocabulary the platform published
(`server_plugin_api.wire_errors`: `FAMILIES`, `STATIC_ERROR_FAMILIES`,
`family_for`, `converge_family`, `WireError`); it never invents a family name
and never touches the core's error branches. Every derivation in
`wire_family.py` is checked here against the platform's own symbols:

* each mapped family is a member of `FAMILIES` (no invented names);
* where the static table already answers a code, the mapping repeats that
  answer exactly (no override of a core row);
* the static resolver's only other answer is the documented `UNAVAILABLE`
  fall-through, which the contributed business rows refine;
* no code maps to two families, and the mapping covers exactly the codes the
  package can emit;
* `unsupported` and `unknown` stay distinguishable after mapping, and the two
  codes themselves keep their distinct spellings (§C4 forbids merging them).
"""
from __future__ import annotations

import pytest
import server_plugin_api
from server_plugin_api import FAMILIES, STATIC_ERROR_FAMILIES, WireError, family_for

from ordessa_permissions_api import (
    PERMISSION_ERROR_FAMILIES,
    PolicyRefusal,
    RefusalCode,
    SCHEMA_CODES,
    CodeKind,
    code_kind,
    enforcement_codes,
    permissions_wire_family,
    wire_body_for,
)

#: Every code the package can emit: the closed enforcement set, the
#: construction-time schema refusals, and the effective-policy denial value.
EMITTABLE = {code.value for code in RefusalCode} | set(SCHEMA_CODES) | {"policy_deny"}

#: The emittable codes a `PolicyRefusal` diagnostic can actually carry:
#: `policy_deny` is a decision reason, not a failure diagnostic, and the
#: closed constructor in `codes.py` refuses it - the mapping still answers it.
DIAGNOSTIC_CODES = EMITTABLE - {"policy_deny"}

#: `WireError.to_body()`'s exact shape; the projection may not smuggle a field
#: through that the platform body would not carry.
BODY_FIELDS = {"code", "message", "details"}
DETAIL_FIELDS = {"internalCode", "source", "target", "remedy", "index"}


# -- coverage and single-valuedness ------------------------------------------

def test_the_mapping_covers_exactly_every_emittable_code_once() -> None:
    assert set(PERMISSION_ERROR_FAMILIES) == EMITTABLE
    # a Mapping answers each key once; the length check proves no duplicate
    # spelling slipped in under a different key form.
    assert len(PERMISSION_ERROR_FAMILIES) == len(EMITTABLE)


@pytest.mark.parametrize("code", sorted(EMITTABLE))
def test_no_mapped_family_is_an_invented_name(code: str) -> None:
    family = PERMISSION_ERROR_FAMILIES[code]
    assert family in FAMILIES, f"{code} -> {family} is not a wire/1 family"
    assert family in set(server_plugin_api.FAMILIES)


def test_no_code_maps_to_two_families_and_the_core_table_is_not_rewritten() -> None:
    # one family per code:
    assert all(isinstance(v, str) for v in PERMISSION_ERROR_FAMILIES.values())
    # the platform's own module is untouched by this package:
    assert family_for("APPROVAL_STALE") == "APPROVAL_INVALID"
    assert "PERMISSION_UNKNOWN_TOOL" not in STATIC_ERROR_FAMILIES


# -- derivation against the platform resolver ---------------------------------

@pytest.mark.parametrize("code", sorted(EMITTABLE))
def test_the_static_resolver_never_disagrees_into_a_false_family(code: str) -> None:
    """Each row is either the static table's own answer or the documented
    `UNAVAILABLE` fall-through that a contributed business row refines."""
    static_answer = family_for(code)
    mapped = PERMISSION_ERROR_FAMILIES[code]
    assert static_answer in {mapped, "UNAVAILABLE"}, (code, static_answer, mapped)
    if code in STATIC_ERROR_FAMILIES:
        assert mapped == STATIC_ERROR_FAMILIES[code]


def test_the_fall_through_rows_that_keep_the_platform_answer() -> None:
    # `family_for` yields UNAVAILABLE for these and the lane does not invent
    # a stronger answer than the platform gives without a producer.
    assert PERMISSION_ERROR_FAMILIES["POLICY_SCOPE_UNVERIFIED"] == "UNAVAILABLE"
    assert family_for("POLICY_SCOPE_UNVERIFIED") == "UNAVAILABLE"
    # the only static row among our codes is honoured verbatim:
    assert PERMISSION_ERROR_FAMILIES["APPROVAL_STALE"] == STATIC_ERROR_FAMILIES["APPROVAL_STALE"]


# -- the unsupported / unknown split survives the mapping ---------------------

def test_unsupported_and_unknown_never_collapse_to_the_same_family() -> None:
    unsupported = {PERMISSION_ERROR_FAMILIES[c.value] for c in enforcement_codes()
                   if code_kind(c) is CodeKind.UNSUPPORTED}
    unknown = {PERMISSION_ERROR_FAMILIES[c.value] for c in enforcement_codes()
               if code_kind(c) is CodeKind.UNKNOWN}
    assert unsupported and unknown
    assert unsupported.isdisjoint(unknown)


def test_mapping_keeps_the_two_codes_themselves_distinct() -> None:
    # §C4 forbids merging at the code level even where families are shared:
    # the seven enforcement spellings are unchanged and `unsupported` and
    # `unknown` remain separate members.
    assert {c.value for c in RefusalCode} == {
        "POLICY_CEILING_VIOLATION", "POLICY_ADAPTER_MISSING", "POLICY_SCOPE_UNVERIFIED",
        "PERMISSION_UNKNOWN_TOOL", "APPROVAL_STALE", "APPROVAL_NOT_ACTIONABLE",
        "APPROVAL_RESULT_UNKNOWN"}
    assert "APPROVAL_RESULT_UNKNOWN" != "POLICY_ADAPTER_MISSING"


# -- resolver injection (composition path) ------------------------------------

def test_an_injected_composition_resolver_answers_first() -> None:
    seen: list[str] = []

    def resolver(code: str) -> str:
        seen.append(code)
        return "NOT_FOUND"

    assert permissions_wire_family("APPROVAL_STALE", resolver=resolver) == "NOT_FOUND"
    assert seen == ["APPROVAL_STALE"]
    # without one the published table answers:
    assert permissions_wire_family("APPROVAL_STALE") == "APPROVAL_INVALID"


def test_enum_and_plain_string_codes_resolve_alike() -> None:
    assert permissions_wire_family(RefusalCode.APPROVAL_STALE) == \
        permissions_wire_family("APPROVAL_STALE")


def test_policy_deny_is_mapped_although_the_diagnostic_constructor_refuses_it() -> None:
    # `codes.PolicyRefusal` will not carry a decision-reason code as a failure
    # diagnostic; the family table still answers it for the wire projection.
    assert permissions_wire_family("policy_deny") == PERMISSION_ERROR_FAMILIES["policy_deny"]
    assert PERMISSION_ERROR_FAMILIES["policy_deny"] in FAMILIES
    with pytest.raises(PolicyRefusal):
        PolicyRefusal(code="policy_deny", source="authorizer")


def test_an_unemittable_code_is_refused_not_familied() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        permissions_wire_family("POLICY_WHEN_I_FEEL_LIKE")
    assert exc.value.code == "PERMISSION_DIAGNOSTIC_INVALID"
    with pytest.raises(PolicyRefusal):
        permissions_wire_family("")


# -- diagnostics through the mapping path (FR-09) ------------------------------

@pytest.mark.parametrize("code", sorted(DIAGNOSTIC_CODES))
def test_each_mapped_code_still_carries_source_target_and_remedy(code: str) -> None:
    refusal = PolicyRefusal(code=code, source="admin ceiling admin-default@3",
                            target="edit /etc/hosts")
    body = wire_body_for(refusal)
    assert set(body) <= BODY_FIELDS
    assert body["code"] == PERMISSION_ERROR_FAMILIES[code]
    details = body["details"]
    assert set(details) <= DETAIL_FIELDS
    # the precise internal spelling survives next to the family:
    assert details["internalCode"] == code
    assert details["source"] == "admin ceiling admin-default@3"
    assert details["target"] == "edit /etc/hosts"
    assert details["remedy"] and details["remedy"].strip()


@pytest.mark.parametrize("code", sorted(DIAGNOSTIC_CODES))
def test_the_projected_body_converges_under_the_platform_wire_error(code: str) -> None:
    """Feeding the projection through the real `WireError` is a no-op on the
    family slot - proof the mapping speaks the platform's own convergence,
    not a private dialect."""
    refusal = PolicyRefusal(code=code, source="authorizer", target="tool:rm")
    body = wire_body_for(refusal)
    error = WireError(body["code"], body["message"], dict(body["details"]))
    assert error.family == PERMISSION_ERROR_FAMILIES[code]
    assert error.to_body()["code"] == error.family
    assert error.to_body()["details"]["internalCode"] == code


def test_tool_arguments_and_secrets_cannot_be_smuggled_through_the_projection() -> None:
    # a diagnostic field with a control character never reaches the mapping
    # path at all - construction refuses first:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyRefusal(code="POLICY_CEILING_VIOLATION", source="token\tx")
    assert exc.value.code == "PERMISSION_DIAGNOSTIC_INVALID"
    # and the projection exposes only the closed diagnostic field set:
    refusal = PolicyRefusal(code="POLICY_CEILING_VIOLATION", source="ceiling",
                            target="exfil", index=2)
    details = wire_body_for(refusal)["details"]
    assert set(details) <= DETAIL_FIELDS
    assert details["index"] == 2
    assert set(PolicyRefusal.PUBLIC_FIELDS) == {"code", "source", "target", "remedy", "index"}


def test_a_refusal_without_a_target_projects_without_one() -> None:
    body = wire_body_for(PolicyRefusal(code="POLICY_ADAPTER_MISSING", source="authorizer"))
    assert "target" not in body["details"]
    assert body["details"]["remedy"]
