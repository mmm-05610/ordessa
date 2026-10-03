"""Wire-refusal projection: the error-family table must not lie."""
from __future__ import annotations

from server_plugin_api import ServerError

from ordessa_extensions.approval import ApprovalError
from ordessa_extensions.definitions import ExtensionDefinitionError
from ordessa_extensions.error_families import (
    EXTENSIONS_ERROR_FAMILIES, to_server_error,
)


def test_known_code_maps_to_its_declared_family():
    err = to_server_error(ApprovalError("HOOK_UNKNOWN", "no such hook"))
    assert err.code == "HOOK_UNKNOWN"
    assert err.status == 404
    assert err.retryable is False


def test_invalid_request_codes_answer_400():
    err = to_server_error(
        ExtensionDefinitionError("EVENT_UNEVIDENCED", "not evidenced"))
    assert err.code == "EVENT_UNEVIDENCED"
    assert err.status == 400


def test_unknown_code_answers_unavailable_not_a_fake_400():
    err = to_server_error(ApprovalError("TOTALLY_UNMAPPED", "mystery"))
    assert err.code == "TOTALLY_UNMAPPED"
    assert err.status == 503
    assert err.retryable is True


def test_codeless_refusal_does_not_borrow_a_client_error():
    err = to_server_error(RuntimeError("invariant break, no code"))
    assert err.code == "UNAVAILABLE"
    assert err.status == 503
    assert err.retryable is True


def test_every_table_value_is_a_real_family():
    from server_plugin_api import FAMILIES
    assert set(EXTENSIONS_ERROR_FAMILIES.values()) <= set(FAMILIES)
