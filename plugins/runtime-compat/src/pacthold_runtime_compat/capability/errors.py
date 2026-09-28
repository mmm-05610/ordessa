"""能力合同的类型化异常与拒绝原因码。

异常层级只回答"哪一类合同被违反"；为什么被拒绝的细粒度记录走原因码常量
（``REFUSAL_*``）。原因码是中立的内部记录，不出现在 wire 上。
"""
from __future__ import annotations


class CapabilityContractError(Exception):
    """能力合同层所有类型化异常的基类。"""


class CapabilityIdInvalid(CapabilityContractError):
    """非法能力 id；``value`` 携带被拒绝的原值。"""

    def __init__(self, value: object, detail: str | None = None) -> None:
        self.value = value
        message = f"invalid capability id {value!r}"
        if detail is not None:
            message = f"{message}: {detail}"
        super().__init__(message)


class CapabilityUnknown(CapabilityContractError):
    """未知 id 的需求 → 拒绝，绝不默认满足。"""


class RequirementConflict(CapabilityContractError):
    """需求集合内部冲突。"""


class DeclarationConflict(CapabilityContractError):
    """同 providerId 重复候选 / 同 id 重复声明。"""


class AuthorizationMissing(CapabilityContractError):
    """demand 无适用 grant（fail-closed）。"""


class AuthorizationExceeded(CapabilityContractError):
    """demand 超出 grant 授权上界。"""


class EvidenceInvalid(CapabilityContractError):
    """被采用证据过期 / 环境不符 / 静态缺失。"""


# 拒绝原因码：中立内部记录，wire 不可见。
REFUSAL_UNKNOWN_CAPABILITY = "REFUSAL_UNKNOWN_CAPABILITY"
REFUSAL_DECLARATION_MISSING = "REFUSAL_DECLARATION_MISSING"
REFUSAL_DECLARATION_CONFLICT = "REFUSAL_DECLARATION_CONFLICT"
REFUSAL_PARAMETER_NOT_COVERED = "REFUSAL_PARAMETER_NOT_COVERED"
REFUSAL_AUTHORIZATION_MISSING = "REFUSAL_AUTHORIZATION_MISSING"
REFUSAL_AUTHORIZATION_EXCEEDED = "REFUSAL_AUTHORIZATION_EXCEEDED"
REFUSAL_EVIDENCE_STALE = "REFUSAL_EVIDENCE_STALE"
REFUSAL_EVIDENCE_ABSENT = "REFUSAL_EVIDENCE_ABSENT"
REFUSAL_ENVIRONMENT_MISMATCH = "REFUSAL_ENVIRONMENT_MISMATCH"
REFUSAL_CONDITION_UNSATISFIED = "REFUSAL_CONDITION_UNSATISFIED"
REFUSAL_PROVIDER_NOT_AUTHORIZED = "REFUSAL_PROVIDER_NOT_AUTHORIZED"
REFUSAL_PIN_NOT_MATCHED = "REFUSAL_PIN_NOT_MATCHED"

__all__ = [
    "REFUSAL_AUTHORIZATION_EXCEEDED",
    "REFUSAL_AUTHORIZATION_MISSING",
    "REFUSAL_CONDITION_UNSATISFIED",
    "REFUSAL_DECLARATION_CONFLICT",
    "REFUSAL_DECLARATION_MISSING",
    "REFUSAL_ENVIRONMENT_MISMATCH",
    "REFUSAL_EVIDENCE_ABSENT",
    "REFUSAL_EVIDENCE_STALE",
    "REFUSAL_PARAMETER_NOT_COVERED",
    "REFUSAL_PIN_NOT_MATCHED",
    "REFUSAL_PROVIDER_NOT_AUTHORIZED",
    "REFUSAL_UNKNOWN_CAPABILITY",
    "AuthorizationExceeded",
    "AuthorizationMissing",
    "CapabilityContractError",
    "CapabilityIdInvalid",
    "CapabilityUnknown",
    "DeclarationConflict",
    "EvidenceInvalid",
    "RequirementConflict",
]
