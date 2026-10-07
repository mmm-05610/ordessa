"""匹配层：需求（demand）× 授权（grant）× 声明（declaration）× 环境事实的纯函数判定。

无 I/O、无状态：相同输入永远得到相同 :class:`MatchOutcome`。规则注册表只显式登记
本切片的四个能力 id；未知 id 的需求一律类型化拒绝，绝不默认满足。每条 demand 独立
判定，检查顺序固定为：注册表 → fail-closed 授权 → 声明 → 条件 → 参数覆盖。

证据闭合按合同枚举执行：凡被采用参与成功判定的输入——适用 grant.source、被匹配
声明的 evidence、condition.evidence、参与求值的 EnvironmentFact.evidence——连同
文档级 environment_binding 一律校验时效与环境；demand 自身的 source 是 launcher
计划的出处记录，不在匹配期校验。facts 永不改写 demand 参数、永不放宽 grant；
无 demand 的 id 不产生匹配项。
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from .documents import (
    Condition,
    EnvironmentFact,
    EvidenceRef,
    MatchContext,
    RequirementParameterSet,
    SandboxDeclaration,
    SandboxDeclarationDocument,
    SandboxGrant,
    SandboxRequirement,
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
    REFUSAL_UNKNOWN_CAPABILITY,
)

#: 条件求值的三种非拒绝结论。
CONDITION_VERIFIED = "verified"
CONDITION_FAILED = "failed"
CONDITION_UNKNOWN = "unknown"

_CONDITION_VERDICTS = (CONDITION_VERIFIED, CONDITION_FAILED, CONDITION_UNKNOWN)

#: 冻结的声明支持状态（运行时 Literal 只在静态检查生效，这里 fail-closed 拒绝未知值）。
_FROZEN_SUPPORT_STATES = ("supported", "conditional", "unavailable")

#: 唯一可授权的 provenance（冻结合同：普通 Profile 默认值不建模为 grant）。
_LOCKED_POLICY = "locked-policy"


def _targets_superset(demand: RequirementParameterSet, declared: RequirementParameterSet) -> bool:
    """readonly/writable 的覆盖语义：声明 targets ⊇ demand targets（canonical 串比较）。

    当前参数形状只有 targets 一维（env.bounded 已移出切片）；未来参数集若引入其它
    强制维度（如上界 bound），通用比较在本函数内扩展，注册表形状不变。
    """
    return set(demand.targets).issubset(declared.targets)


def _targets_equal(demand: RequirementParameterSet, declared: RequirementParameterSet) -> bool:
    """network 的覆盖语义：枚举等值，无并集/交集。"""
    return demand.targets == declared.targets


@dataclass(frozen=True)
class MatchRule:
    """单个能力 id 的匹配规则：声明参数如何覆盖需求参数。"""

    capability_id: str
    rule: str  # 记入 MatchedItem.rule 的稳定规则名
    covers: Callable[[RequirementParameterSet, RequirementParameterSet], bool]


#: 仅显式注册本切片四个 id：readonly / writable / network.none / network.inherit。
REGISTRY: Mapping[str, MatchRule] = MappingProxyType(
    {
        rule.capability_id: rule
        for rule in (
            MatchRule("filesystem.readonly@1", "targets-superset", _targets_superset),
            MatchRule("filesystem.writable@1", "targets-superset", _targets_superset),
            MatchRule("network.none@1", "targets-equal", _targets_equal),
            MatchRule("network.inherit@1", "targets-equal", _targets_equal),
        )
    }
)


@dataclass(frozen=True)
class MatchedItem:
    """一条被满足的 demand 及其命中的规则。"""

    capability_id: str
    rule: str


@dataclass(frozen=True)
class Refusal:
    """一条类型化拒绝；文档级拒绝不带 capability_id。"""

    capability_id: str | None
    reason: str  # REFUSAL_* 原因码（中立内部记录，wire 不可见）
    detail: str


@dataclass(frozen=True)
class MatchOutcome:
    """匹配结论：satisfied 当且仅当无拒绝且每条 demand 都有 MatchedItem。"""

    satisfied: bool
    matches: tuple[MatchedItem, ...]
    refusals: tuple[Refusal, ...]


def match_requirements(
    requirements: tuple[SandboxRequirement, ...],
    grants: tuple[SandboxGrant, ...],
    document: SandboxDeclarationDocument,
    facts: tuple[EnvironmentFact, ...] = (),
    *,
    context: MatchContext,
) -> MatchOutcome:
    """对每条 demand 依次判定：注册表 → 授权 → 声明 → 条件 → 参数覆盖。

    文档级 environment_binding 与执行上下文不符时整文档拒绝。只处理 demand 侧：
    grants/declarations 中无 demand 的 id 不产生任何匹配项或拒绝。
    """
    if document.environment_binding != context.environment_binding:
        return MatchOutcome(
            satisfied=False,
            matches=(),
            refusals=(
                Refusal(
                    capability_id=None,
                    reason=REFUSAL_ENVIRONMENT_MISMATCH,
                    detail=(
                        f"document binding {document.environment_binding!r} != "
                        f"context binding {context.environment_binding!r}"
                    ),
                ),
            ),
        )
    facts_by_key: dict[str, EnvironmentFact] = {fact.key: fact for fact in facts}
    matches: list[MatchedItem] = []
    refusals: list[Refusal] = []
    for demand in requirements:
        verdict = _match_demand(demand, grants, document, facts_by_key, context)
        if isinstance(verdict, Refusal):
            refusals.append(verdict)
        else:
            matches.append(verdict)
    satisfied = not refusals and len(matches) == len(requirements)
    return MatchOutcome(satisfied=satisfied, matches=tuple(matches), refusals=tuple(refusals))


def _match_demand(
    demand: SandboxRequirement,
    grants: tuple[SandboxGrant, ...],
    document: SandboxDeclarationDocument,
    facts_by_key: Mapping[str, EnvironmentFact],
    context: MatchContext,
) -> MatchedItem | Refusal:
    rule = REGISTRY.get(demand.capability_id)
    if rule is None:
        return Refusal(
            demand.capability_id,
            REFUSAL_UNKNOWN_CAPABILITY,
            f"capability id {demand.capability_id!r} is not registered",
        )
    unauthorized = _authorization_refusal(demand, grants, rule, context)
    if unauthorized is not None:
        return unauthorized
    found = _find_declaration(demand, document)
    if isinstance(found, Refusal):
        return found
    declaration = found
    shape = _declaration_shape_refusal(demand.capability_id, declaration)
    if shape is not None:
        return shape
    if declaration.support_state == "conditional":
        verdict = _evaluate_condition(declaration.condition, facts_by_key, context)
        if verdict not in _CONDITION_VERDICTS:
            return Refusal(demand.capability_id, verdict, "condition evidence failed closure")
        if verdict != CONDITION_VERIFIED:
            return Refusal(demand.capability_id, REFUSAL_CONDITION_UNSATISFIED, verdict)
    if not declaration.evidence:
        return Refusal(
            demand.capability_id,
            REFUSAL_EVIDENCE_ABSENT,
            "matched declaration carries no evidence",
        )
    invalid = _evidence_code(declaration.evidence, context)
    if invalid is not None:
        return Refusal(
            demand.capability_id, invalid, "matched declaration evidence failed closure"
        )
    if not rule.covers(demand.parameters, declaration.parameters):
        return Refusal(
            demand.capability_id,
            REFUSAL_PARAMETER_NOT_COVERED,
            "declared parameters do not cover the demand",
        )
    return MatchedItem(capability_id=demand.capability_id, rule=rule.rule)


def _authorization_refusal(
    demand: SandboxRequirement,
    grants: tuple[SandboxGrant, ...],
    rule: MatchRule,
    context: MatchContext,
) -> Refusal | None:
    """fail-closed 授权：同 id、provenance 合法且按领域规则覆盖 demand 的 grant 至少一条证据有效。

    无同 id grant（或全部 provenance 非法）→ MISSING；有但无一按 ``rule.covers``
    覆盖 demand → EXCEEDED；覆盖者证据全部无效 → 证据闭合拒绝码（任一有效即授权
    成立，结论与 grant 输入顺序无关）。覆盖比较委托给该能力 id 的注册规则，
    不在此硬编码集合包含。
    """
    same_id = [
        grant
        for grant in grants
        if grant.capability_id == demand.capability_id and grant.provenance == _LOCKED_POLICY
    ]
    if not same_id:
        return Refusal(
            demand.capability_id,
            REFUSAL_AUTHORIZATION_MISSING,
            f"no grant for {demand.capability_id}",
        )
    first_evidence_code: str | None = None
    for grant in same_id:
        if not rule.covers(demand.parameters, grant.parameters):
            continue
        code = _evidence_code((grant.source,), context)
        if code is None:
            return None  # 一条适用且证据有效的 grant 即授权成立
        if first_evidence_code is None:
            first_evidence_code = code
    if first_evidence_code is not None:
        return Refusal(
            demand.capability_id, first_evidence_code, "applicable grant source failed closure"
        )
    return Refusal(
        demand.capability_id,
        REFUSAL_AUTHORIZATION_EXCEEDED,
        f"demand targets {demand.parameters.targets} exceed every same-id grant",
    )


def _find_declaration(
    demand: SandboxRequirement, document: SandboxDeclarationDocument
) -> SandboxDeclaration | Refusal:
    """同 id 声明查找：缺失/unavailable → DECLARATION_MISSING；重复 → 冲突防御性拒绝。"""
    same_id = [
        declaration
        for declaration in document.declarations
        if declaration.capability_id == demand.capability_id
    ]
    if not same_id:
        return Refusal(
            demand.capability_id,
            REFUSAL_DECLARATION_MISSING,
            f"document has no declaration for {demand.capability_id}",
        )
    if len(same_id) > 1:
        return Refusal(
            demand.capability_id,
            REFUSAL_DECLARATION_CONFLICT,
            f"{len(same_id)} declarations share {demand.capability_id}",
        )
    declaration = same_id[0]
    if declaration.support_state not in _FROZEN_SUPPORT_STATES:
        return Refusal(
            demand.capability_id,
            REFUSAL_DECLARATION_MISSING,
            f"declaration for {demand.capability_id} has unknown support_state "
            f"{declaration.support_state!r}",
        )
    if declaration.support_state == "unavailable":
        return Refusal(
            demand.capability_id,
            REFUSAL_DECLARATION_MISSING,
            f"declaration for {demand.capability_id} is 'unavailable'",
        )
    return declaration


def _declaration_shape_refusal(
    capability_id: str, declaration: SandboxDeclaration
) -> Refusal | None:
    """冻结字段不变式（fail-closed）：非法组合按缺失声明拒绝，绝不静默改形。

    * supported：condition 必须为 None，parameters 必须是非 None 参数对象；
    * conditional：condition 与 parameters 都不得为 None（条件不可验证即为缺失声明）；
    * unavailable：允许无参数面（它不参与成功判定）。
    """
    if declaration.support_state == "supported" and (
        declaration.condition is not None or declaration.parameters is None
    ):
        return Refusal(
            capability_id, REFUSAL_DECLARATION_MISSING,
            "supported declaration must carry parameters and no condition",
        )
    if declaration.support_state == "conditional" and (
        declaration.condition is None or declaration.parameters is None
    ):
        return Refusal(
            capability_id, REFUSAL_DECLARATION_MISSING,
            "conditional declaration must carry a condition and parameters",
        )
    return None


def _evaluate_condition(
    condition: Condition | None,
    facts_by_key: Mapping[str, EnvironmentFact],
    context: MatchContext,
) -> str:
    """以权威 facts 求值声明侧条件。

    返回 verified / failed / unknown；条件证据或参与求值的事实证据无效时返回对应
    拒绝码（证据闭合优先于取值结论）。expected_facts 全命中 → verified；任一键值
    不符 → failed；键缺失或 fact.value is None（未知 ≠ false）→ unknown。
    """
    if condition is None or not condition.expected_facts:
        return CONDITION_UNKNOWN  # 防御：无条件或无事实可验 → 不可 verified
    if not condition.evidence:
        return REFUSAL_EVIDENCE_ABSENT  # 条件无证据即不得判 verified
    invalid = _evidence_code(condition.evidence, context)
    if invalid is not None:
        return invalid
    for key, _expected in condition.expected_facts:
        fact = facts_by_key.get(key)
        if fact is None:
            continue
        if not fact.evidence:
            return REFUSAL_EVIDENCE_ABSENT  # 参与求值的事实无证据
        invalid = _evidence_code(fact.evidence, context)
        if invalid is not None:
            return invalid
    mismatched = False
    unknown = False
    for key, expected in condition.expected_facts:
        fact = facts_by_key.get(key)
        if fact is None or fact.value is None:
            unknown = True
        elif fact.value != expected:
            mismatched = True
    if mismatched:
        return CONDITION_FAILED
    if unknown:
        return CONDITION_UNKNOWN
    return CONDITION_VERIFIED


def _evidence_code(refs: Iterable[EvidenceRef], context: MatchContext) -> str | None:
    """证据闭合校验：过期 → REFUSAL_EVIDENCE_STALE；环境不符 → REFUSAL_ENVIRONMENT_MISMATCH。

    ``expires_at`` 为 None 表示不过期；``expires_at == now`` 仍在有效窗口内
    （只有严格早于判定时间才过期）。``environment_binding`` 为 None 表示环境无关。
    """
    for ref in refs:
        if ref.expires_at is not None and ref.expires_at < context.now:
            return REFUSAL_EVIDENCE_STALE
        if (
            ref.environment_binding is not None
            and ref.environment_binding != context.environment_binding
        ):
            return REFUSAL_ENVIRONMENT_MISMATCH
    return None


__all__ = [
    "CONDITION_FAILED",
    "CONDITION_UNKNOWN",
    "CONDITION_VERIFIED",
    "MatchOutcome",
    "MatchRule",
    "MatchedItem",
    "REGISTRY",
    "Refusal",
    "match_requirements",
]
