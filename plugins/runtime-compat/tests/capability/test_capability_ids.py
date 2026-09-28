"""capability id 形式校验的行为合同：合法放行、非法类型化拒绝并携带原值。"""
from __future__ import annotations

import pytest

from pacthold_runtime_compat.capability import (
    CAPABILITY_ID_PATTERN,
    CapabilityContractError,
    CapabilityIdInvalid,
    require_capability_id,
)

VALID_IDS = [
    "filesystem.readonly@1",
    "filesystem.writable@3",
    "network.none@1",
    "network.inherit@2",
    "agent-box.cap-name@12",
    "a.bc-d@9",
    # 冻结语法的名称段是 [a-z0-9.-]+：连续点不归 id 层管（与 protocol.py 同形），放行。
    "filesystem..readonly@1",
]

# 大写、空版本、@0、前导零、双点、非法字符、数字开头、多 @、空白等漂移写法一律拒绝。
INVALID_IDS = [
    "",
    "@1",
    "a@1",
    "Filesystem.readonly@1",
    "FILESYSTEM@1",
    "filesystem.readonly@",
    "filesystem.readonly@0",
    "filesystem.readonly@01",
    "filesystem.readonly@1x",
    "filesystem.readonly@-1",
    "filesystem.readonly@1.1",
    "file_system@1",
    "1filesystem@1",
    "filesystem.readonly@1@2",
    "filesystem.readonly@1 ",
    " filesystem.readonly@1",
    "filesystem.readonly\n@1",
]


def test_pattern_is_the_frozen_shape() -> None:
    assert CAPABILITY_ID_PATTERN == r"^[a-z][a-z0-9.-]+@[1-9][0-9]*$"


@pytest.mark.parametrize("value", VALID_IDS)
def test_valid_ids_pass_through_unchanged(value: str) -> None:
    assert require_capability_id(value) == value


@pytest.mark.parametrize("value", INVALID_IDS)
def test_invalid_ids_raise_typed_error(value: str) -> None:
    with pytest.raises(CapabilityIdInvalid) as excinfo:
        require_capability_id(value)
    # 原值必须被携带，供上层给出可读的拒绝细节。
    assert excinfo.value.value == value


def test_invalid_id_is_a_contract_error() -> None:
    with pytest.raises(CapabilityContractError):
        require_capability_id("NOT-AN-ID@1")


@pytest.mark.parametrize("value", [None, 1, b"filesystem.readonly@1", ("a",)])
def test_non_string_input_is_typed_rejection_not_type_error(value: object) -> None:
    with pytest.raises(CapabilityIdInvalid) as excinfo:
        require_capability_id(value)  # type: ignore[arg-type]
    assert excinfo.value.value is value
