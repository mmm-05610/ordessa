import pytest

from ordessa_execution_agents.harness.definitions import (
    CredentialRefV1,
    NativeCredentialRef,
)


def test_credential_ref_v1_remains_a_locator_contract_distinct_from_native_ref():
    reference = CredentialRefV1("codex-login", "codex-login/default", "codex")
    native = NativeCredentialRef("codex-login", "codex-login/default")

    assert CredentialRefV1.contract_id == "agent-box.credential@1"
    assert reference.native_locator == native.native_id
    assert reference.harness_scope == "codex"
    assert type(reference) is not type(native)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"provider": "", "native_locator": "locator", "harness_scope": "codex"},
        {"provider": "codex", "native_locator": "bad\0locator", "harness_scope": "codex"},
        {"provider": "codex", "native_locator": "locator", "harness_scope": "codex", "schema_version": 2},
    ],
)
def test_credential_ref_v1_preserves_locator_validation(kwargs):
    values = {"provider": "codex", "native_locator": "locator", "harness_scope": "codex"}
    values.update(kwargs)
    with pytest.raises(ValueError):
        CredentialRefV1(**values)
