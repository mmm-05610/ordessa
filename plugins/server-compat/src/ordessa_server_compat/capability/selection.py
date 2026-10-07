"""选择层：在候选声明文档中按 pin > incumbent > 稳定 (provider, revision) 字典序挑选。

选择是防抢占的（A-R2-003）：incumbent（既有选择/显式默认）通过匹配+授权即必选，
后加入候选无论排序如何不得改变选择；incumbent 失配（含其文档不在候选中）→ 整体
拒绝，替换必须显式 pin。pin 只定位尝试对象，不豁免匹配与授权；pin 的 provider 不在
候选中或全部失配 → ``REFUSAL_PIN_NOT_MATCHED``。无 pin 无 incumbent 的初始选择按
稳定 ``(provider, revision)`` 字典序取首个满足者——这是唯一使用排序的挑选点，输入
顺序无关。

整批拒绝的三种情形：重复 providerId → ``REFUSAL_DECLARATION_CONFLICT``；
授权集合外的候选一律 ``REFUSAL_PROVIDER_NOT_AUTHORIZED``（该专属原因在任何结局下
都保留在 rejected 中）；pin / incumbent 失配按上文原因码整批拒绝。

``rejected`` 按 ``(provider, revision)`` 升序记录每个未选中候选及其原因：候选自身
有失败时记其首个拒绝码，仅因优先级落选（被 pin/incumbent/更高排序候选取代）记
:data:`REASON_SUPERSEDED`。
"""
from __future__ import annotations

from dataclasses import dataclass

from .documents import (
    EnvironmentFact,
    MatchContext,
    SandboxDeclarationDocument,
    SandboxGrant,
    SandboxRequirement,
    requirement_set_digest,
)
from .errors import (
    REFUSAL_DECLARATION_CONFLICT,
    REFUSAL_PIN_NOT_MATCHED,
    REFUSAL_PROVIDER_NOT_AUTHORIZED,
)
from .match import MatchOutcome, match_requirements

#: 候选自身无失败、仅因 pin/incumbent/更高排序候选取得选择而落选的原因记录。
REASON_SUPERSEDED = "SUPERSEDED"

#: incumbent 在场但失配或缺席候选时整批拒绝的原因记录（替换必须显式 pin）。
REASON_INCUMBENT_NOT_MATCHED = "INCUMBENT_NOT_MATCHED"


@dataclass(frozen=True)
class SelectionRecord:
    """一次选择的中立记录：需求摘要、绑定、选中文档（可空）、匹配结论（可空）、落选者。"""

    requirements_digest: str
    binding: str
    selected: SandboxDeclarationDocument | None
    outcome: MatchOutcome | None
    rejected: tuple[tuple[str, int, str], ...]  # (provider, revision, reason)


def select_declaration(
    requirements: tuple[SandboxRequirement, ...],
    grants: tuple[SandboxGrant, ...],
    facts: tuple[EnvironmentFact, ...],
    candidates: tuple[SandboxDeclarationDocument, ...],
    *,
    context: MatchContext,
    binding: str,
    incumbent_provider: str | None = None,
    pinned_provider: str | None = None,
    authorized_providers: tuple[str, ...] | None = None,
) -> SelectionRecord:
    """从候选声明文档中挑选一个满足需求且获授权的文档；永不抛异常，结局全在记录里。"""
    digest = requirement_set_digest(requirements)

    # 重复 providerId：整批类型化拒绝（同 provider 的多份声明文档是装配错误，无静默覆盖）。
    providers = [document.provider for document in candidates]
    if len(set(providers)) != len(providers):
        return SelectionRecord(
            requirements_digest=digest,
            binding=binding,
            selected=None,
            outcome=None,
            rejected=tuple(
                sorted(
                    (document.provider, document.revision, REFUSAL_DECLARATION_CONFLICT)
                    for document in candidates
                )
            ),
        )

    # 系统授权过滤：授权集合外的候选在任何结局下都保留其专属拒绝原因。
    reasons: dict[str, str] = {}
    if authorized_providers is None:
        eligible = list(candidates)
    else:
        allowed = frozenset(authorized_providers)
        eligible = []
        for document in candidates:
            if document.provider in allowed:
                eligible.append(document)
            else:
                reasons[document.provider] = REFUSAL_PROVIDER_NOT_AUTHORIZED

    def finish(
        selected: SandboxDeclarationDocument | None, outcome: MatchOutcome | None
    ) -> SelectionRecord:
        rejected = tuple(
            sorted(
                (
                    document.provider,
                    document.revision,
                    reasons.get(document.provider, REASON_SUPERSEDED),
                )
                for document in candidates
                if document is not selected  # rejected 只记录未选中候选
            )
        )
        return SelectionRecord(digest, binding, selected, outcome, rejected)

    def batch_refusal(reason: str) -> SelectionRecord:
        for document in candidates:
            reasons.setdefault(document.provider, reason)
        return finish(None, None)

    stable = sorted(eligible, key=lambda document: (document.provider, document.revision))

    # pin > incumbent > 初始。pin 只定位尝试对象，不豁免匹配与授权。
    if pinned_provider is not None:
        for document in stable:
            if document.provider != pinned_provider:
                continue
            outcome = match_requirements(requirements, grants, document, facts, context=context)
            if outcome.satisfied:
                return finish(document, outcome)
        return batch_refusal(REFUSAL_PIN_NOT_MATCHED)

    if incumbent_provider is not None:
        for document in stable:
            if document.provider != incumbent_provider:
                continue
            outcome = match_requirements(requirements, grants, document, facts, context=context)
            if outcome.satisfied:
                return finish(document, outcome)
        return batch_refusal(REASON_INCUMBENT_NOT_MATCHED)

    # 初始选择：唯一排序挑选点。全员评估以记录每个落选者的具体原因。
    winner: SandboxDeclarationDocument | None = None
    win_outcome: MatchOutcome | None = None
    for document in stable:
        outcome = match_requirements(requirements, grants, document, facts, context=context)
        if outcome.satisfied:
            if winner is None:
                winner, win_outcome = document, outcome
        else:
            # 未满足 ⇒ refusals 非空（每条 demand 要么匹配要么拒绝）。
            reasons[document.provider] = outcome.refusals[0].reason
    return finish(winner, win_outcome)


__all__ = [
    "REASON_INCUMBENT_NOT_MATCHED",
    "REASON_SUPERSEDED",
    "SelectionRecord",
    "select_declaration",
]
