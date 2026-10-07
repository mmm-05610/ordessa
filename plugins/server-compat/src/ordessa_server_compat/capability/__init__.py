"""能力合同公共包：id 校验、类型化异常、冻结数据形状、匹配/选择/需求三层的公共入口。

本包导出四组符号：``ids`` 的 id 校验；``errors`` 的类型化异常与原因码；
``documents`` 的冻结数据形状与 canonical 序列化；以及消费入口
``match_requirements`` / ``select_declaration`` / ``sidecar_requirements`` /
``sidecar_grants``（冻结合同 contracts-capability-v1.md 要求以
``capability.<name>`` 形式消费，D 接线与装配边界只走这一层）。

依赖方向：本包不 import server / work_core / runtime_composition / 任何插件；
``match``/``selection``/``requirements`` 层只依赖 ``ids``/``errors``/``documents``。
"""
from __future__ import annotations

from .documents import (
    Condition,
    EnvironmentFact,
    EvidenceRef,
    GrantProvenance,
    MatchContext,
    RequirementParameterSet,
    SandboxDeclaration,
    SandboxDeclarationDocument,
    SandboxGrant,
    SandboxRequirement,
    SupportState,
    canonical_json,
    requirement_set_digest,
)
from .errors import (
    REFUSAL_AUTHORIZATION_EXCEEDED,
    REFUSAL_AUTHORIZATION_MISSING,
    REFUSAL_CONDITION_UNSATISFIED,
    REFUSAL_DECLARATION_CONFLICT,
    REFUSAL_DECLARATION_MISSING,
    REFUSAL_ENVIRONMENT_MISMATCH,
    REFUSAL_EVIDENCE_ABSENT,
    REFUSAL_EVIDENCE_STALE,
    REFUSAL_PARAMETER_NOT_COVERED,
    REFUSAL_PIN_NOT_MATCHED,
    REFUSAL_PROVIDER_NOT_AUTHORIZED,
    REFUSAL_UNKNOWN_CAPABILITY,
    AuthorizationExceeded,
    AuthorizationMissing,
    CapabilityContractError,
    CapabilityIdInvalid,
    CapabilityUnknown,
    DeclarationConflict,
    EvidenceInvalid,
    RequirementConflict,
)
from .ids import CAPABILITY_ID_PATTERN, require_capability_id
from .match import (
    CONDITION_FAILED,
    CONDITION_UNKNOWN,
    CONDITION_VERIFIED,
    REGISTRY,
    MatchOutcome,
    MatchRule,
    MatchedItem,
    Refusal,
    match_requirements,
)
from .requirements import sidecar_grants, sidecar_requirements
from .selection import (
    REASON_INCUMBENT_NOT_MATCHED,
    REASON_SUPERSEDED,
    SelectionRecord,
    select_declaration,
)
from .slots import COMPONENT_SLOT_CAPABILITIES, slot_of_capability

__all__ = [
    "CAPABILITY_ID_PATTERN",
    "COMPONENT_SLOT_CAPABILITIES",
    "CONDITION_FAILED",
    "CONDITION_UNKNOWN",
    "CONDITION_VERIFIED",
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
    "REASON_INCUMBENT_NOT_MATCHED",
    "REASON_SUPERSEDED",
    "REGISTRY",
    "AuthorizationExceeded",
    "AuthorizationMissing",
    "CapabilityContractError",
    "CapabilityIdInvalid",
    "CapabilityUnknown",
    "Condition",
    "DeclarationConflict",
    "EnvironmentFact",
    "EvidenceInvalid",
    "EvidenceRef",
    "GrantProvenance",
    "MatchContext",
    "MatchOutcome",
    "MatchRule",
    "MatchedItem",
    "Refusal",
    "RequirementConflict",
    "RequirementParameterSet",
    "SandboxDeclaration",
    "SandboxDeclarationDocument",
    "SandboxGrant",
    "SandboxRequirement",
    "SelectionRecord",
    "SupportState",
    "canonical_json",
    "match_requirements",
    "require_capability_id",
    "requirement_set_digest",
    "select_declaration",
    "sidecar_grants",
    "sidecar_requirements",
    "slot_of_capability",
]
