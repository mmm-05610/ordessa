"""Field claims: two adapters on one native config field refuse at stage."""
from __future__ import annotations

import pytest

from ordessa_sandbox_api import FieldClaimRegistry, SandboxApiError, SandboxErrorCode


def test_single_owner_claim_accepted():
    registry = FieldClaimRegistry()
    registry.claim(adapter_id="sandbox-adapter", native_field="sandbox_mode")
    assert registry.owner_of("sandbox_mode") == "sandbox-adapter"


def test_same_owner_reclaim_is_idempotent():
    registry = FieldClaimRegistry()
    registry.claim(adapter_id="sandbox-adapter", native_field="sandbox_mode")
    registry.claim(adapter_id="sandbox-adapter", native_field="sandbox_mode")


def test_two_adapters_claiming_same_native_field_conflict():
    registry = FieldClaimRegistry()
    registry.claim(adapter_id="sandbox-adapter", native_field="sandbox_mode")
    with pytest.raises(SandboxApiError) as excinfo:
        registry.claim(adapter_id="permissions-adapter", native_field="sandbox_mode")
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT
    # the first owner keeps the field; the conflict never rewrites ownership
    assert registry.owner_of("sandbox_mode") == "sandbox-adapter"


def test_distinct_fields_do_not_conflict():
    registry = FieldClaimRegistry()
    registry.claim(adapter_id="sandbox-adapter", native_field="sandbox_mode")
    registry.claim(adapter_id="permissions-adapter", native_field="approval_policy")
    assert registry.owner_of("approval_policy") == "permissions-adapter"
