"""能力合同的冻结数据形状与 canonical 序列化。

本模块只声明形状与构造期可判的不变式（如证据时间窗），不做匹配、不做授权、
不解释声明——那些是 match / selection 层的职责。所有 dataclass 均 frozen；
``Condition.expected_facts`` 与 ``RequirementParameterSet.targets`` 按合同排序存储。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Literal

from .errors import EvidenceInvalid

#: 唯一授权来源。Profile 默认值属偏好/生效配置层，在需求生成之前解析，不进入本合同。
GrantProvenance = Literal["locked-policy"]

#: 提供者支持姿态：unavailable ≡ 不支持；conditional 须条件通过。
SupportState = Literal["supported", "conditional", "unavailable"]


@dataclass(frozen=True)
class EvidenceRef:
    """一条证据引用：它从哪里来、绑定哪个环境、何时观测、何时过期。

    ``environment_binding`` 为 ``None`` 表示环境无关；有值时须等于
    ``MatchContext.environment_binding``。``observed_at`` 为 ``None`` 表示静态事实；
    ``expires_at`` 为 ``None`` 表示不过期（有值且早于判定时间 → 证据过期）。
    """

    kind: str  # "file-symbol" | "digest" | "config-key" | "probe"
    locator: str
    environment_binding: str | None
    observed_at: int | None
    expires_at: int | None

    def __post_init__(self) -> None:
        if self.expires_at is not None and self.observed_at is not None \
                and self.expires_at < self.observed_at:
            raise EvidenceInvalid(
                f"expires_at {self.expires_at} precedes observed_at {self.observed_at}"
            )


@dataclass(frozen=True)
class Condition:
    """提供者声明侧的条件；由 matcher 以权威 facts 求值。

    ``expected_facts`` 是不可变 canonical 形状（键, 期望值）的序对，排序存储。
    """

    name: str
    expected_facts: tuple[tuple[str, str], ...]
    evidence: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_facts", tuple(sorted(self.expected_facts)))


@dataclass(frozen=True)
class RequirementParameterSet:
    """需求/声明/授权共用的参数形状。

    ``targets`` 是 canonical 绝对路径（禁 ``..``、``//``），排序存储。
    """

    targets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "targets", tuple(sorted(self.targets)))


@dataclass(frozen=True)
class SandboxRequirement:
    """功能需求（demand）：来自 launcher 实际挂载面。"""

    capability_id: str
    parameters: RequirementParameterSet
    source: EvidenceRef


@dataclass(frozen=True)
class SandboxGrant:
    """授权上界：仅 locked-policy，来自部署文档授权字段。"""

    capability_id: str
    parameters: RequirementParameterSet
    provenance: GrantProvenance
    source: EvidenceRef


@dataclass(frozen=True)
class SandboxDeclaration:
    """提供者声明：永不生成/改写 demand、永不放宽 grant。"""

    capability_id: str
    support_state: SupportState  # unavailable ≡ 不支持；conditional 须条件通过
    condition: Condition | None  # 仅 conditional 时非 None
    parameters: RequirementParameterSet | None  # 声明实际强制覆盖的 targets（逐执行构造）
    evidence: tuple[EvidenceRef, ...]
    provider: str


@dataclass(frozen=True)
class EnvironmentFact:
    """环境观测；``value=None`` 即未知，绝不当作 false。"""

    key: str
    value: str | None
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class SandboxDeclarationDocument:
    """一份提供者的声明文档。

    ``environment_binding`` 是文档级绑定：构造它的那次执行的权威环境身份；
    ``digest`` 是 ``sha256(canonical json)``，同发行版同执行绑定凭证。
    同 id 重复声明的判定属 match/selection 层（→ :class:`DeclarationConflict`），
    构造期不做字段间校验。
    """

    provider: str
    revision: int
    environment_binding: str
    declarations: tuple[SandboxDeclaration, ...]
    digest: str


@dataclass(frozen=True)
class MatchContext:
    """匹配的必填权威上下文。"""

    environment_binding: str  # 当前执行的权威环境身份（无默认值）
    now: int  # 判定时间 epoch 秒（无默认值）


def _jsonable(value: Any) -> Any:
    """把 dataclass（含嵌套于容器内的）递归转成 JSON 可序列化形状。"""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """canonical JSON 文本：键排序、无空白分隔、非 ASCII 原样保留；dataclass 先转 dict。"""
    return json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def requirement_set_digest(requirements: tuple[SandboxRequirement, ...]) -> str:
    """需求集合的 digest：canonical JSON 后取 sha256 hexdigest。"""
    payload = canonical_json(tuple(requirements))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "Condition",
    "EnvironmentFact",
    "EvidenceRef",
    "GrantProvenance",
    "MatchContext",
    "RequirementParameterSet",
    "SandboxDeclaration",
    "SandboxDeclarationDocument",
    "SandboxGrant",
    "SandboxRequirement",
    "SupportState",
    "canonical_json",
    "requirement_set_digest",
]
