"""异常层级与拒绝原因码的合同：单一基类、兄弟互斥、原因码非空且自名。"""
from __future__ import annotations

import pytest

import pacthold_runtime_compat.capability as capability
from pacthold_runtime_compat.capability import (
    AuthorizationExceeded,
    AuthorizationMissing,
    CapabilityContractError,
    CapabilityIdInvalid,
    CapabilityUnknown,
    DeclarationConflict,
    EvidenceInvalid,
    RequirementConflict,
)

SUBCLASSES = (
    CapabilityIdInvalid,
    CapabilityUnknown,
    RequirementConflict,
    DeclarationConflict,
    AuthorizationMissing,
    AuthorizationExceeded,
    EvidenceInvalid,
)

# 冻结原因码：中立内部记录，wire 不可见；名字即值。
REFUSAL_CODES = (
    "REFUSAL_UNKNOWN_CAPABILITY",
    "REFUSAL_DECLARATION_MISSING",
    "REFUSAL_DECLARATION_CONFLICT",
    "REFUSAL_PARAMETER_NOT_COVERED",
    "REFUSAL_AUTHORIZATION_MISSING",
    "REFUSAL_AUTHORIZATION_EXCEEDED",
    "REFUSAL_EVIDENCE_STALE",
    "REFUSAL_ENVIRONMENT_MISMATCH",
    "REFUSAL_CONDITION_UNSATISFIED",
    "REFUSAL_PROVIDER_NOT_AUTHORIZED",
    "REFUSAL_PIN_NOT_MATCHED",
)


def test_every_subclass_derives_from_the_single_base() -> None:
    assert issubclass(CapabilityContractError, Exception)
    for exc in SUBCLASSES:
        assert issubclass(exc, CapabilityContractError)


def test_subclasses_are_mutually_independent() -> None:
    for left in SUBCLASSES:
        for right in SUBCLASSES:
            if left is not right:
                assert not issubclass(left, right)


@pytest.mark.parametrize("exc_type", SUBCLASSES)
def test_base_catch_covers_every_subclass(exc_type: type[CapabilityContractError]) -> None:
    with pytest.raises(CapabilityContractError):
        raise exc_type("refused")


def test_capability_id_invalid_carries_rejected_value() -> None:
    error = CapabilityIdInvalid("Bad@0")
    assert error.value == "Bad@0"
    assert "Bad@0" in str(error)


@pytest.mark.parametrize("name", REFUSAL_CODES)
def test_refusal_codes_are_non_empty_self_named_strings(name: str) -> None:
    value = getattr(capability, name)
    assert isinstance(value, str)
    assert value
    assert value == name
