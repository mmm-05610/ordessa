"""The published wire-shape surface: one implementation, frozen refusal bytes.

T014-S2c moved the shared param-shape primitives, the family set with its
static table, `WireError`, `ServerError` and the record encoding out of
`ordessa_server` into this package, because plugins import them and AGENTS
rule 3 forbids a plugin reaching into host internals. What matters for the
protocol is that the *bytes* did not move: every refusal string below is what
the host produced before the move, pinned here so a "tidy-up" on one side
cannot silently change the wire on the other.

No product import in this file: these are contract-level tests, and the
host/plugin identity checks live in
`apps/server/tests/platform/test_platform_published_wire_surface.py`.
"""
from __future__ import annotations

import pytest

from server_plugin_api import (
    FAMILIES,
    STATIC_ERROR_FAMILIES,
    ServerError,
    WireError,
    bounded,
    canonical,
    converge_family,
    digest,
    family_for,
    reject_sensitive_keys,
    request_id,
    require,
    unavailable,
    version,
)


# -- the param-shape primitives ---------------------------------------------

def test_require_names_every_missing_param_in_one_frozen_sentence():
    with pytest.raises(WireError) as caught:
        require({"a": 1}, "a", "b", "c")
    error = caught.value
    assert (error.family, error.message) == (
        "INVALID_REQUEST", "params is missing b, c")


def test_bounded_and_request_id_and_version_keep_their_words():
    assert bounded("x" * 10, "field") == "x" * 10
    with pytest.raises(WireError) as caught:
        bounded("", "field")
    assert (caught.value.family, caught.value.message) == (
        "INVALID_REQUEST", "field must be a bounded string")
    with pytest.raises(WireError) as caught:
        bounded("y" * 12, "field", limit=4)
    assert caught.value.message == "field must be a bounded string"
    assert request_id("abcdefgh") == "abcdefgh"
    with pytest.raises(WireError) as caught:
        request_id("short")
    assert (caught.value.family, caught.value.message) == (
        "INVALID_REQUEST", "requestId must contain at least 8 characters")
    assert version(0) == 0
    with pytest.raises(WireError) as caught:
        version(True)
    assert (caught.value.family, caught.value.message) == (
        "INVALID_REQUEST", "expectedVersion must be a non-negative safe integer")
    with pytest.raises(WireError) as caught:
        version(2**53, "revision")
    assert caught.value.message == "revision must be a non-negative safe integer"


def test_the_family_set_is_closed_and_the_static_table_is_its_fallback_source():
    assert len(FAMILIES) == 12
    assert "CONFLICT_REFERENCE" in FAMILIES
    for family in sorted(FAMILIES):
        assert family_for(family) == family, family
    assert family_for("SOMETHING_UNREGISTERED") == "UNAVAILABLE"
    for code, family in STATIC_ERROR_FAMILIES.items():
        assert family_for(code) == family
        assert family in FAMILIES, f"{code} -> {family} invents a family"


def test_convergence_keeps_the_original_code_in_details():
    details: dict[str, object] = {}
    assert converge_family("SSH_UNREACHABLE", details) == "WORKER_UNREACHABLE"
    assert details == {"internalCode": "SSH_UNREACHABLE"}
    assert converge_family("NOT_FOUND", {}) == "NOT_FOUND"


# -- the error objects -------------------------------------------------------

def test_wire_error_from_server_error_needs_no_composition_for_a_static_code():
    error = WireError.from_server_error(ServerError("REQUEST_TOO_LARGE", "too big", status=422))
    assert (error.family, error.message, error.details) == (
        "INVALID_REQUEST", "too big",
        {"internalCode": "REQUEST_TOO_LARGE", "retryable": False})


def test_an_injected_resolver_answers_what_the_static_table_cannot():
    error = WireError.from_server_error(
        unavailable("SESSION_NOT_FOUND", "gone"), lambda code: "NOT_FOUND")
    assert (error.family, error.details["internalCode"]) == (
        "NOT_FOUND", "SESSION_NOT_FOUND")
    assert error.to_body() == {
        "code": "NOT_FOUND", "message": "gone",
        "details": {"internalCode": "SESSION_NOT_FOUND", "retryable": True}}


def test_record_encoding_is_the_stored_bytes_not_a_reimplementation():
    """`digest`'s prefix and the JSON settings are what existing rows were
    written with; a reformatter here would corrupt retained evidence."""
    assert digest({"b": 1, "a": [1, 2]}) == (
        "sha256:"
        "94a786c3662bc7beeb598efa7d8cb58d7bea25d6c275ea9785a0230ff1f8c2ba")
    assert canonical({"a": "é"}) == b'{"a":"\xc3\xa9"}'
    with pytest.raises(ServerError) as caught:
        reject_sensitive_keys({"configuration": {"api_key": "x"}})
    assert (caught.value.code, caught.value.message, caught.value.status) == (
        "SECRET_FIELD_FORBIDDEN", "Configuration contains a forbidden secret field", 422)
