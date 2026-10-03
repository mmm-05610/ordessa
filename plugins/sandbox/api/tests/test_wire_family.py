"""T010b guard: the six Sandbox refusal codes resolve to EXISTING wire/1 families.

Contracts §C4 ("错误须映射至既有 wire family，不修改核心错误分支"): every
stable sandbox code must have a mapping onto one of the twelve families the
platform already publishes (`server_plugin_api.wire_errors.FAMILIES`), derived
from the platform's own resolution table — never a new family name, and never
a change to the core error branches. The mapping itself lives sandbox-side in
`ordessa_sandbox_api.wire_family` (an additive public export); these tests
check it against the real platform symbols.

`unsupported` and `unknown` stay two distinct codes (§C4 forbids merging
them): a missing probe must never read like a documented limit. They may land
in one family only when the platform vocabulary says so; the native-sandbox
"not available" verdict and the "effect unknown" verdict do NOT — the guard
below pins them apart because the two are the §C4 pair proper.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from ordessa_sandbox_api import SandboxErrorCode
from ordessa_sandbox_api.errors import SandboxApiError
from server_plugin_api.wire_errors import (FAMILIES, STATIC_ERROR_FAMILIES,
                                           WireError, converge_family,
                                           family_for)

from ordessa_sandbox_api.wire_family import (SANDBOX_WIRE_FAMILIES,
                                             wire_family_for)

#: The literal six-code set. Asserted against the enum verbatim so any
#: rename/removal of a code string breaks here (and in the cross-language
#: frontend test), never silently.
SIX_STABLE_CODE_NAMES = {
    "SANDBOX_NATIVE_UNSUPPORTED",
    "SANDBOX_COVERAGE_UNPROVEN",
    "SANDBOX_PLATFORM_UNSUPPORTED",
    "SANDBOX_CONFIG_CONFLICT",
    "SANDBOX_EFFECT_UNKNOWN",
    "PROVIDER_BUSY",
}

#: Schema-level input validation stays Python-side only (errors.py's own
#: comment): it has no wire row and must not gain one here.
PYTHON_ONLY_CODES = {"SANDBOX_INTENT_INVALID"}

WIRE_FAMILY_MODULE = Path(__file__).resolve().parent.parent / "src" / \
    "ordessa_sandbox_api" / "wire_family.py"


# --- the enum itself is unchanged (additive task, no code-contract edits) ---

def test_sandbox_error_code_enum_literal_set_unchanged():
    assert ({c.name for c in SandboxErrorCode},
            {c.value for c in SandboxErrorCode}) == (
        SIX_STABLE_CODE_NAMES | PYTHON_ONLY_CODES,
        SIX_STABLE_CODE_NAMES | PYTHON_ONLY_CODES,
    )


def test_name_and_value_of_every_member_are_identical_spellings():
    for code in SandboxErrorCode:
        assert code.name == code.value, code


# --- mapping domain and shape ---

def test_mapped_domain_is_exactly_the_six_stable_codes():
    assert set(SANDBOX_WIRE_FAMILIES) == SIX_STABLE_CODE_NAMES


def test_every_code_maps_to_exactly_one_family():
    for code, family in SANDBOX_WIRE_FAMILIES.items():
        assert isinstance(family, str), code
        assert re.fullmatch(r"[A-Z][A-Z_]*", family), (code, family)


# --- the platform facts behind each row ---

def test_no_new_family_names_mapped_is_subset_of_platform_families():
    assert set(SANDBOX_WIRE_FAMILIES.values()) <= FAMILIES


@pytest.mark.parametrize("code,expected_family", sorted(
    SANDBOX_WIRE_FAMILIES.items()))
def test_row_agrees_with_platform_resolution(code, expected_family):
    """Each row is derived from the platform, not invented.

    Three platform-side checks per row:
    - the mapped value answers itself through `family_for` (family names are
      identity-resolved; an unknown word would fall through to UNAVAILABLE);
    - every mapped family is one the platform table already answers for a
      same-shaped vocabulary word (exact row, or the family name itself, or a
      documented same-meaning row — see the pairs below);
    - `converge_family`/`WireError` keep the family slot byte-identical, i.e.
      the mapping lands in an existing branch and never modifies one.
    """
    assert family_for(expected_family) == expected_family
    resolved = wire_family_for(code, resolver=family_for)
    assert resolved == expected_family
    family = converge_family(expected_family, details := {})
    assert family == expected_family and details == {}
    error = WireError(family=resolved, message="sandbox refusal")
    assert error.family == expected_family
    assert error.to_body()["code"] == expected_family


#: Platform-table precedents: which existing row each sandbox row is derived
#: from (exact spelling, family-name identity, or the same-meaning platform
#: word). This is the "read the platform's table" half of the derivation.
PLATFORM_PRECEDENT_ROWS = {
    "SANDBOX_NATIVE_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
    "SANDBOX_COVERAGE_UNPROVEN": "CAPABILITY_UNSUPPORTED",
    "SANDBOX_PLATFORM_UNSUPPORTED": "CAPABILITY_UNSUPPORTED",
    "SANDBOX_CONFIG_CONFLICT": "ENTERPRISE_STATE_CONFLICT",
    "SANDBOX_EFFECT_UNKNOWN": "OUTCOME_UNKNOWN",
    "PROVIDER_BUSY": "SERVICE_UNAVAILABLE",
}


def test_each_row_names_a_precedent_row_that_exists_on_the_platform_side():
    for code, precedent in PLATFORM_PRECEDENT_ROWS.items():
        family = SANDBOX_WIRE_FAMILIES[code]
        if precedent in STATIC_ERROR_FAMILIES:
            assert family_for(precedent) == family, (code, precedent)
        else:
            assert precedent in FAMILIES and family_for(precedent) == family


# --- §C4: unsupported and unknown stay distinct ---

def test_unsupported_and_unknown_are_distinct_codes_and_never_merged_aliases():
    assert SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED is not \
        SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
    assert "SANDBOX_NATIVE_UNSUPPORTED" != "SANDBOX_EFFECT_UNKNOWN"
    # distinct codes survive as distinct keys even when rows share a family
    assert len(SANDBOX_WIRE_FAMILIES) == 6


def test_native_unsupported_and_effect_unknown_land_in_different_families():
    assert SANDBOX_WIRE_FAMILIES["SANDBOX_NATIVE_UNSUPPORTED"] != \
        SANDBOX_WIRE_FAMILIES["SANDBOX_EFFECT_UNKNOWN"]


# --- diagnostics over the mapping path leak nothing ---

def test_mapped_families_are_a_closed_vocabulary_no_free_text():
    # the only diagnostic string the mapping path can emit is a family name;
    # a family can not carry a path or a secret by construction
    for family in SANDBOX_WIRE_FAMILIES.values():
        assert family in FAMILIES
        assert "/" not in family and "~" not in family
        assert family == family.upper()


def test_mapping_module_source_carries_no_paths_or_config_tokens():
    text = WIRE_FAMILY_MODULE.read_text(encoding="utf-8")
    for token in ("~/.codex", "~/.claude", "~/.pi", ".codex/config.toml",
                  "/home/", "C:\\", "password", "token="):
        assert token not in text, token


def test_unmapped_input_refusal_message_leaks_nothing():
    # SANDBOX_INTENT_INVALID is Python-side only; asking for its family is
    # caller input validation, and the refusal repeats only the code word.
    with pytest.raises(SandboxApiError) as excinfo:
        wire_family_for(SandboxErrorCode.SANDBOX_INTENT_INVALID)
    message = str(excinfo.value)
    assert "/" not in message and "~" not in message
    excinfo.value.code is SandboxErrorCode.SANDBOX_INTENT_INVALID
    assert excinfo.value.code.value == "SANDBOX_INTENT_INVALID"


def test_string_and_enum_inputs_answer_the_same_family():
    for code in SIX_STABLE_CODE_NAMES:
        assert wire_family_for(SandboxErrorCode[code]) == \
            wire_family_for(code) == SANDBOX_WIRE_FAMILIES[code]
