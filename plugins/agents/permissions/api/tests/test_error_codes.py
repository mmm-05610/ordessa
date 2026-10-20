"""T01 red/green: stable refusal codes and honest diagnostics (FR-09)."""
from __future__ import annotations

import pytest

from ordessa_permissions_api import (
    CodeKind,
    DEFAULT_REMEDIES,
    PolicyRefusal,
    RefusalCode,
    SCHEMA_CODES,
    code_kind,
    enforcement_codes,
)

REQUIRED = {
    "POLICY_CEILING_VIOLATION",
    "POLICY_ADAPTER_MISSING",
    "POLICY_SCOPE_UNVERIFIED",
    "PERMISSION_UNKNOWN_TOOL",
    "APPROVAL_STALE",
    "APPROVAL_NOT_ACTIONABLE",
    "APPROVAL_RESULT_UNKNOWN",
}


def test_every_contracts_c4_permission_code_exists_with_its_exact_spelling() -> None:
    assert {code.value for code in RefusalCode} == REQUIRED


def test_enforcement_codes_are_exactly_the_declared_stable_set() -> None:
    assert set(enforcement_codes()) == REQUIRED


@pytest.mark.parametrize("code", sorted(REQUIRED))
def test_each_code_carries_a_human_remedy_suggestion(code: str) -> None:
    refusal = PolicyRefusal(code=code, source="admin policy admin-default@3",
                            target="edit /etc/passwd")
    assert refusal.remedy == DEFAULT_REMEDIES[code]
    assert refusal.remedy.strip()
    assert refusal.human_readable.startswith(code)
    assert refusal.code_value == code


def test_an_undeclared_enforcement_code_cannot_be_invented_by_a_caller() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyRefusal(code="POLICY_WHEN_I_FEEL_LIKE", source="x")
    assert exc.value.code in {"PERMISSION_DIAGNOSTIC_INVALID", "PERMISSION_DECISION_INVALID"}


@pytest.mark.parametrize("bad_source", ["", None, 7, "line\nbreak", "tab\there", "x" * 600])
def test_diagnostic_fields_are_bounded_printable_text(bad_source: object) -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyRefusal(code="APPROVAL_STALE", source=bad_source)  # type: ignore[arg-type]
    assert exc.value.code == "PERMISSION_DIAGNOSTIC_INVALID"


def test_a_diagnostic_names_the_source_and_target_and_never_an_argument_payload() -> None:
    refusal = PolicyRefusal(code="PERMISSION_UNKNOWN_TOOL", source="ceiling admin-default@3",
                            target="rm_all")
    text = str(refusal)
    assert text.startswith(
        "PERMISSION_UNKNOWN_TOOL: source=ceiling admin-default@3; target=rm_all; "
        f"remedy={DEFAULT_REMEDIES['PERMISSION_UNKNOWN_TOOL']}")
    assert "meaning=" in text
    # there is no field an argument payload could be smuggled through
    assert set(PolicyRefusal.PUBLIC_FIELDS) == {"code", "source", "target", "remedy", "index"}


def test_a_diagnostic_without_a_target_still_reads_cleanly() -> None:
    refusal = PolicyRefusal(code="POLICY_ADAPTER_MISSING", source="authorizer")
    assert "target=" not in str(refusal)
    assert "POLICY_ADAPTER_MISSING" in str(refusal)


def test_an_index_is_optional_but_must_be_an_integer() -> None:
    assert PolicyRefusal("PERMISSION_RULE_INVALID", source="rules", index=3).index == 3
    with pytest.raises(PolicyRefusal) as exc:
        PolicyRefusal("PERMISSION_RULE_INVALID", source="rules", index="3")  # type: ignore[arg-type]
    assert exc.value.code == "PERMISSION_DIAGNOSTIC_INVALID"


def test_unsupported_and_unknown_are_different_kinds_and_are_never_merged() -> None:
    assert code_kind(RefusalCode.POLICY_ADAPTER_MISSING) is CodeKind.UNSUPPORTED
    assert code_kind(RefusalCode.APPROVAL_RESULT_UNKNOWN) is CodeKind.UNKNOWN
    assert code_kind(RefusalCode.POLICY_ADAPTER_MISSING) is not CodeKind.UNKNOWN
    assert code_kind("APPROVAL_STALE") is CodeKind.VIOLATION


def test_every_enforcement_code_has_exactly_one_kind() -> None:
    kinds = {code.value: code_kind(code) for code in RefusalCode}
    assert set(kinds.values()) == {CodeKind.VIOLATION, CodeKind.UNSUPPORTED, CodeKind.UNKNOWN}
    assert kinds["POLICY_CEILING_VIOLATION"] is CodeKind.VIOLATION
    assert kinds["PERMISSION_UNKNOWN_TOOL"] is CodeKind.UNSUPPORTED
    assert kinds["POLICY_SCOPE_UNVERIFIED"] is CodeKind.UNKNOWN
    assert kinds["APPROVAL_NOT_ACTIONABLE"] is CodeKind.VIOLATION


def test_schema_codes_are_kept_apart_from_enforcement_codes() -> None:
    assert SCHEMA_CODES.isdisjoint(enforcement_codes())
    assert "PERMISSION_RULE_INVALID" in SCHEMA_CODES
    assert "PERMISSION_PATTERN_INVALID" in SCHEMA_CODES
    assert "PERMISSION_ACTION_UNSUPPORTED" in SCHEMA_CODES
    assert "PERMISSION_CEILING_INVALID" in SCHEMA_CODES
    assert "PERMISSION_INTENT_INVALID" in SCHEMA_CODES
