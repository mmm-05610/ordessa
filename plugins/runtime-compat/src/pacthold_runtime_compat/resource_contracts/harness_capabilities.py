"""版本化的 Harness 能力合同：Python 侧的唯一事实来源。

本模块只回答三个问题，且不含任何品牌分支（各家语义只能来自数据/声明，不能来自这里的
条件判断）：

- ``declared``：静态上限，来自部署/插件声明，经 :func:`validate_claims` 校验后绝不超过
  canonical id 集合；本模块的任何函数都不会用运行时观测“回写”它。
- ``observed``：本次执行观测到的原生事实，三态 ``True`` / ``False`` / ``None``（未观测）。
- ``supported``：静态上限 ∩ 运行时观测。不变式：``supported ⇒ declared``。

能力分两类：

- 实现级（``IMPLEMENTATION_LEVEL_CAPABILITIES``）：已注册且被真实调用的 sidecar/driver
  操作合同“就是”它的观测来源；没有更强证据时按静态声明取用（不会超过静态上限）。
- 语义级（``SEMANTIC_CAPABILITIES``）：必须有显式运行时证据才 ``supported``；未观测一律
  ``false``（保守）。声明了 ``native_continuation`` 但没有原生播发，不等于它能续接。

``observed`` 只反映本次执行。任何调用方都不得据此改写全局 Profile 的静态能力。
"""
from __future__ import annotations

from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


CAPABILITY_SCHEMA_VERSION = 1

#: canonical 能力 id；顺序即 canonical 视图的次序。别名（漂移写法）永远被拒绝。
CANONICAL_CAPABILITY_IDS: tuple[str, ...] = (
    "start", "observe", "finish", "attach", "steer", "stream", "permissions",
    "native_continuation",
)

#: 每个能力的作用域：execution（一次执行的生命周期）/ message（一条消息）/
#: session（跨执行的会话身份）。
CAPABILITY_SCOPES: dict[str, str] = {
    "start": "execution", "observe": "execution", "finish": "execution",
    "stream": "message", "attach": "message", "steer": "message",
    "permissions": "execution", "native_continuation": "session",
}

#: 实现级能力：观测来源是"已注册且被真实调用的 sidecar/driver 操作"（拿到原生会话
#: 身份、prompt 返回、首条真实增量）。**未观测仍然是不支持**——本分类只说明证据从哪来，
#: 不允许把声明当成观测。
IMPLEMENTATION_LEVEL_CAPABILITIES = frozenset({"start", "observe", "finish", "stream"})

#: 语义级能力：必须有显式运行时证据才 supported；未观测一律 false（保守）。
SEMANTIC_CAPABILITIES = frozenset({"attach", "steer", "permissions", "native_continuation"})

# 稳定原因码：为什么某能力是/不是 supported。
CAPABILITY_NOT_DECLARED = "CAPABILITY_NOT_DECLARED"
CAPABILITY_OBSERVED_UNSUPPORTED = "CAPABILITY_OBSERVED_UNSUPPORTED"
CAPABILITY_NOT_OBSERVED = "CAPABILITY_NOT_OBSERVED"
CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION = (
    "CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION"
)

# 声明校验的类型化错误码。
CAPABILITY_CLAIMS_INVALID = "CAPABILITY_CLAIMS_INVALID"
CAPABILITY_UNKNOWN_ID = "CAPABILITY_UNKNOWN_ID"
CAPABILITY_VALUE_NOT_BOOLEAN = "CAPABILITY_VALUE_NOT_BOOLEAN"

#: 已知的漂移别名 → canonical id。别名只用于报错提示，永远不被接受：它们让错误
#: 可读（部署写错时立刻知道该写哪个 id），而不是让漂移写法“碰巧能用”。
DRIFT_ALIASES: Mapping[str, str] = {
    "streaming": "stream",
    "approvals": "permissions",
    "approval": "permissions",
    "attachments": "attach",
    "attachment": "attach",
    "sessions": "native_continuation",
    "session": "native_continuation",
    "resume": "native_continuation",
    "continuation": "native_continuation",
    "prompt": "start",
    "abort": "finish",
    "cancel": "finish",
}


class CapabilityDeclarationError(ValueError):
    """声明校验失败的类型化错误：``code`` 是稳定错误码，``message`` 是细节。"""

    code = CAPABILITY_CLAIMS_INVALID

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")
        self.message = message


class CapabilityClaimsInvalid(CapabilityDeclarationError):
    """形状非法（不是对象、不是 Mapping 之类）。"""

    code = CAPABILITY_CLAIMS_INVALID


class CapabilityUnknownId(CapabilityDeclarationError):
    """非 canonical id（含漂移别名）。"""

    code = CAPABILITY_UNKNOWN_ID


class CapabilityValueNotBoolean(CapabilityDeclarationError):
    """值不是真正的 JSON boolean。"""

    code = CAPABILITY_VALUE_NOT_BOOLEAN


@dataclass(frozen=True)
class CapabilityDeclaration:
    """一项能力在 canonical 视图里的完整陈述。

    ``declared`` 是静态上限，``observed`` 是本次执行的三态观测（``None`` 表示未观测，
    JSON 里就是 ``null``），``supported`` 是两者的合并结果。``native_evidence`` 只在
    有原生观测时给出观测来源（中立命名，不含品牌）。
    """

    id: str
    scope: str
    declared: bool
    observed: bool | None
    supported: bool
    reason: str | None
    native_evidence: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope,
            "declared": self.declared,
            "observed": self.observed,
            "supported": self.supported,
            "reason": self.reason,
            "nativeEvidence": self.native_evidence,
        }


def _unknown_id(key: Any) -> CapabilityUnknownId:
    hint = DRIFT_ALIASES.get(key) if isinstance(key, str) else None
    detail = f"unknown capability id {key!r}"
    if hint is not None:
        detail += f" (drift alias of {hint!r})"
    return CapabilityUnknownId(detail)


def validate_claims(claims: Mapping[str, Any]) -> dict[str, bool]:
    """严格校验 capabilityClaims，返回 canonical 次序的静态声明快照。

    - 键必须 ∈ :data:`CANONICAL_CAPABILITY_IDS`，否则 :class:`CapabilityUnknownId`
      （漂移别名会在消息里指出它应该是哪个 canonical id）；
    - 值必须是真正的 bool（str/int/None/list/dict 一律
      :class:`CapabilityValueNotBoolean`）；
    - 其它形状（不是对象/映射）一律 :class:`CapabilityClaimsInvalid`。

    返回值是新建的字典：调用方后续修改输入不会影响它，调用方也改不到本模块的状态。
    """
    if not isinstance(claims, MappingABC):
        raise CapabilityClaimsInvalid(
            f"capability claims must be a mapping of canonical ids to booleans, "
            f"not {type(claims).__name__}"
        )
    validated: dict[str, bool] = {}
    for key, value in claims.items():
        if not isinstance(key, str) or key not in CANONICAL_CAPABILITY_IDS:
            raise _unknown_id(key)
        if type(value) is not bool:
            raise CapabilityValueNotBoolean(
                f"capability {key!r} must be a real boolean, not {type(value).__name__}"
            )
        validated[key] = value
    return {capability_id: validated[capability_id]
            for capability_id in CANONICAL_CAPABILITY_IDS if capability_id in validated}


def canonical_capabilities(claims: Mapping[str, bool]) -> dict[str, bool]:
    """静态声明 → canonical 上限（等价于 :func:`validate_claims` 之后的规范化结果）。

    只包含被声明的 id；未声明的 id 由 :func:`merge_capabilities` 补成 false。
    """
    return validate_claims(claims)


def _validated_observations(observed: Mapping[str, bool | None]) -> dict[str, bool | None]:
    """校验三态观测：键必须是 canonical id，值必须是 bool 或 None。"""
    if not isinstance(observed, MappingABC):
        raise CapabilityClaimsInvalid(
            f"observed capabilities must be a mapping of canonical ids to tri-state values, "
            f"not {type(observed).__name__}"
        )
    validated: dict[str, bool | None] = {}
    for key, value in observed.items():
        if not isinstance(key, str) or key not in CANONICAL_CAPABILITY_IDS:
            raise _unknown_id(key)
        if value is not None and type(value) is not bool:
            raise CapabilityClaimsInvalid(
                f"observed capability {key!r} must be true, false or null, "
                f"not {type(value).__name__}"
            )
        validated[key] = value
    return validated


def _validated_evidence(evidence: Mapping[str, str] | None) -> dict[str, str]:
    if evidence is None:
        return {}
    if not isinstance(evidence, MappingABC):
        raise CapabilityClaimsInvalid("capability evidence must be a mapping of ids to strings")
    validated: dict[str, str] = {}
    for key, value in evidence.items():
        if not isinstance(key, str) or key not in CANONICAL_CAPABILITY_IDS:
            raise _unknown_id(key)
        if not isinstance(value, str) or not value:
            raise CapabilityClaimsInvalid(f"capability evidence for {key!r} must be a non-empty string")
        validated[key] = value
    return validated


def merge_capabilities(
    declared: Mapping[str, bool], observed: Mapping[str, bool | None],
    *, evidence: Mapping[str, str] | None = None,
) -> tuple[CapabilityDeclaration, ...]:
    """按合并规则产出 canonical 视图（按 id 顺序，含 false 项）。

    唯一规则（逐条可测）：

        supported == (declared is true and observed is true)

    ====================  ====================  =========  ===================================================
    declared               observed              supported  reason
    ====================  ====================  =========  ===================================================
    true                  true                  true       None
    true                  false                 false      CAPABILITY_OBSERVED_UNSUPPORTED
    true                  None                  false      CAPABILITY_NOT_OBSERVED
    false                 true                  false      CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION
    false                 false / None          false      CAPABILITY_NOT_DECLARED
    ====================  ====================  =========  ===================================================

    **未观测不等于支持。** ``IMPLEMENTATION_LEVEL_CAPABILITIES`` /
    ``SEMANTIC_CAPABILITIES`` 只规定"观测从哪里来、需要多强的证据"，绝不代替观测本身：
    实现级能力的观测来自已注册且被真实调用的 sidecar/driver 操作（拿到原生会话身份、
    prompt 返回、首条真实增量），语义级能力还要求各自的原生证据（`attach` 的
    prompt 能力、`permissions` 的真实 round-trip、`native_continuation` 的
    `sessionCapabilities.resume`）。没有观测就是 `CAPABILITY_NOT_OBSERVED`。

    未出现在 ``declared`` 里的 id 视作 false：运行时观测只能被静态声明“确认”，不能把
    产品能力抬高到声明之外（fail closed）。
    """
    declared_map = validate_claims(declared)
    observed_map = _validated_observations(observed)
    evidence_map = _validated_evidence(evidence)
    declarations: list[CapabilityDeclaration] = []
    for capability_id in CANONICAL_CAPABILITY_IDS:
        is_declared = declared_map.get(capability_id, False)
        observation = observed_map.get(capability_id)
        if is_declared and observation is True:
            supported, reason = True, None
        elif is_declared and observation is False:
            supported, reason = False, CAPABILITY_OBSERVED_UNSUPPORTED
        elif is_declared:  # 声明了但本次没有观测：不得因为"属于实现级"就假装支持
            supported, reason = False, CAPABILITY_NOT_OBSERVED
        elif observation is True:
            supported, reason = False, CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION
        else:
            supported, reason = False, CAPABILITY_NOT_DECLARED
        declarations.append(CapabilityDeclaration(
            id=capability_id,
            scope=CAPABILITY_SCOPES[capability_id],
            declared=is_declared,
            observed=observation,
            supported=supported,
            reason=reason,
            # 只有真的观测到原生事实时才给出观测来源。
            native_evidence=evidence_map.get(capability_id) if observation is not None else None,
        ))
    return tuple(declarations)


def capability_view(
    harness_type: str, declarations: Sequence[CapabilityDeclaration],
) -> dict[str, Any]:
    """canonical 视图：``{"schemaVersion", "harnessType", "capabilities"}``。"""
    return {
        "schemaVersion": CAPABILITY_SCHEMA_VERSION,
        "harnessType": harness_type,
        "capabilities": [declaration.as_dict() for declaration in declarations],
    }


__all__ = [
    "CANONICAL_CAPABILITY_IDS",
    "CAPABILITY_CLAIMS_INVALID",
    "CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION",
    "CAPABILITY_NOT_DECLARED",
    "CAPABILITY_NOT_OBSERVED",
    "CAPABILITY_OBSERVED_UNSUPPORTED",
    "CAPABILITY_SCHEMA_VERSION",
    "CAPABILITY_SCOPES",
    "CAPABILITY_UNKNOWN_ID",
    "CAPABILITY_VALUE_NOT_BOOLEAN",
    "CapabilityClaimsInvalid",
    "CapabilityDeclaration",
    "CapabilityDeclarationError",
    "CapabilityUnknownId",
    "CapabilityValueNotBoolean",
    "DRIFT_ALIASES",
    "IMPLEMENTATION_LEVEL_CAPABILITIES",
    "SEMANTIC_CAPABILITIES",
    "canonical_capabilities",
    "capability_view",
    "merge_capabilities",
    "validate_claims",
]
