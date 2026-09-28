"""能力契约 id 的形式校验。

id 形状与 ``runtime_composition/protocol.py`` 的既有约定同形：
``^[a-z][a-z0-9.-]+@[1-9][0-9]*$``（小写名称 + 非零主版本，升版本即不兼容边界）。
非法 id 一律类型化拒绝，绝不静默放行。
"""
from __future__ import annotations

import re

from .errors import CapabilityIdInvalid

CAPABILITY_ID_PATTERN: str = r"^[a-z][a-z0-9.-]+@[1-9][0-9]*$"

_CAPABILITY_ID = re.compile(CAPABILITY_ID_PATTERN)


def require_capability_id(value: str) -> str:
    """校验能力 id，合法时原样返回；非法抛 :class:`CapabilityIdInvalid`（携带原值）。"""
    if not isinstance(value, str):
        raise CapabilityIdInvalid(value, "capability id must be a string")
    if _CAPABILITY_ID.fullmatch(value) is None:
        raise CapabilityIdInvalid(value, f"must match {CAPABILITY_ID_PATTERN}")
    return value


__all__ = ["CAPABILITY_ID_PATTERN", "require_capability_id"]
