"""Provider-safe digest invariants (JEV non-network assertions, core side)."""
import pytest

from decision_runtime.definitions.values import DecisionError, ContractError, canonical_bytes, digest


def settings_projection(**overrides):
    value = {"binding_ref": "jev-official/1", "secret_ref": "jev-api-key",
             "base_url": "https://api.typesafe.ai", "model": "jev-1.13.0",
             "accepted_response_models": (), "timeout_seconds": 10.0,
             "protocol_validation_version": "jev-protocol/1"}
    value.update(overrides)
    return {"kind": "jev_provider_settings", **value}


def test_digest_covers_safe_configuration_including_the_secret_reference():
    base = digest("descriptor", settings_projection())
    assert base == digest("descriptor", settings_projection())  # stable, canonical
    assert base != digest("descriptor", settings_projection(secret_ref="other-ref"))
    assert base != digest("descriptor", settings_projection(model="other-model"))
    # The secret VALUE is not a settings field: there is nothing to leak or hash.
    assert "api_key" not in settings_projection()


def test_digest_is_domain_separated_and_refuses_unknown_domains():
    assert digest("descriptor", {"a": 1}) != digest("question", {"a": 1})
    with pytest.raises(ContractError):
        digest("not-a-domain", {"a": 1})


def test_canonical_projection_never_accepts_callables_or_secret_objects():
    with pytest.raises(DecisionError):
        canonical_bytes({"secret": object()})
    with pytest.raises(DecisionError):
        canonical_bytes({"callback": lambda: None})
