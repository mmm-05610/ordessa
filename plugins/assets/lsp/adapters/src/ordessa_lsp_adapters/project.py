"""投影流水线：定义选择 → 探测 → 品牌评估 → 决策记录（016 LSP-3/4/5）。

一次投影返回**决策记录**而不是配置：本批没有任何品牌存在原生 LSP 配置面，
所以流水线的诚实产出是"逐定义的决策与理由"，经 ``ordessa_lsp_api`` 的规范
转录变成字节稳定 golden 的对象。三条硬规则：

* 品牌门先于一切：阶段二四家（hermes/opencode/dsh/kilo）与已除名的 qwen
  在入口就拿到类型化 ``ProjectionRefusal``——不产出半截决策。
* 探测先于评估（LSP-4 "投影前探测"）：可执行缺席的定义直接落
  ``absent-executable``，不再问品牌；在场而品牌无原生面落
  ``unsupported-native``，理由与证据指针取自 ``evidence.py``。
* 决策记录是不可变 frozen 数据；``SessionProjectionStore`` 按会话键保存，
  写入只替换本会话的元组——两会话隔离靠不可变结构成立，不靠纪律。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from ordessa_lsp_api import FormatterDefinition, LspSelection, \
    LspServerDefinition, canonical_json_bytes

from .evidence import PHASE2_BRANDS, REMOVED_BRANDS, BRAND_EVIDENCE
from .probe import ExecutablePresence, PathLookup, resolve_executable
from .registry import DEFAULT_LSP_BRANDS, LspBrandAdapter

__all__ = [
    "STATUS_ABSENT_EXECUTABLE",
    "STATUS_UNSUPPORTED_NATIVE",
    "ProjectionDecision",
    "ProjectionRefusal",
    "SessionProjectionStore",
    "project_selection",
]

STATUS_ABSENT_EXECUTABLE = "absent-executable"
STATUS_UNSUPPORTED_NATIVE = "unsupported-native"

_BRAND_ADAPTERS: dict[str, LspBrandAdapter] = {
    harness_id: LspBrandAdapter(adapter_id=adapter_id, harness_id=harness_id)
    for adapter_id, harness_id in DEFAULT_LSP_BRANDS
}

_PHASE2_POINTER = ("specs/016-overnight-batch/reports/LSP-report.md 的阶段二"
                   "设计包（reports/phase2-design-lsp.md）")


class ProjectionRefusal(Exception):
    """入口级拒绝：阶段二缓做 / 品牌除名 / 未知品牌。code 是稳定字面量。"""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


def _resolve_brand(brand: str) -> LspBrandAdapter:
    adapter = _BRAND_ADAPTERS.get(brand)
    if adapter is not None:
        return adapter
    if brand in PHASE2_BRANDS:
        record = BRAND_EVIDENCE[brand]
        raise ProjectionRefusal(
            "PHASE2_DEFERRED",
            f"{brand}: 本批不实施（{record['reason']}）→ {_PHASE2_POINTER}")
    if brand in REMOVED_BRANDS:
        raise ProjectionRefusal(
            "BRAND_REMOVED",
            f"qwen 已除名（用户裁定 2026-09-28）：{BRAND_EVIDENCE[brand]['reason']}")
    raise ProjectionRefusal(
        "UNKNOWN_BRAND",
        f"{brand!r} 不是本域品牌；本批实施面只有 pi/codex/claude-code，"
        f"阶段二四家 {PHASE2_BRANDS}，除名 {REMOVED_BRANDS}")


@dataclass(frozen=True)
class ProjectionDecision:
    """一台定义在一个品牌格上的最终决策（不可变、可转录）。"""

    brand: str
    scope: str
    definition: Mapping[str, object]
    executable: Mapping[str, object]
    status: str
    reason: str
    evidence_ref: str

    def to_jsonable(self) -> dict:
        return {
            "brand": self.brand,
            "definition": dict(self.definition),
            "evidence_ref": self.evidence_ref,
            "executable": dict(self.executable),
            "reason": self.reason,
            "scope": self.scope,
            "status": self.status,
        }


def _decide(adapter: LspBrandAdapter, scope: str,
            definition: LspServerDefinition | FormatterDefinition,
            lookup: PathLookup | None) -> ProjectionDecision:
    presence: ExecutablePresence = resolve_executable(definition.command,
                                                      lookup=lookup)
    evidence = BRAND_EVIDENCE[adapter.harness_id]
    if not presence.present:
        return ProjectionDecision(
            brand=adapter.harness_id, scope=scope,
            definition=definition.to_jsonable(),
            executable=presence.to_jsonable(),
            status=STATUS_ABSENT_EXECUTABLE,
            reason=presence.reason,
            evidence_ref="tasks.md LSP-4 可用性诚实检查",
        )
    return ProjectionDecision(
        brand=adapter.harness_id, scope=scope,
        definition=definition.to_jsonable(),
        executable=presence.to_jsonable(),
        status=STATUS_UNSUPPORTED_NATIVE,
        reason=evidence["reason"],
        evidence_ref=evidence["evidence_ref"],
    )


def project_selection(brand: str, selection: LspSelection, *,
                      lookup: PathLookup | None = None
                      ) -> tuple[ProjectionDecision, ...]:
    """对一个品牌格投影一次选择，返回逐定义决策（可能为空元组）。"""
    adapter = _resolve_brand(brand)
    decisions: list[ProjectionDecision] = []
    definitions: Iterable[LspServerDefinition | FormatterDefinition] = \
        selection.definitions()
    for definition in definitions:
        decisions.append(_decide(adapter, selection.scope, definition, lookup))
    return tuple(decisions)


def decisions_to_jsonable(
        decisions: Iterable[ProjectionDecision]) -> dict:
    """决策集的规范可转录形态（键排序交给 canonical_json_bytes）。"""
    return {"decisions": [d.to_jsonable() for d in decisions]}


def canonical_decision_bytes(decisions: Iterable[ProjectionDecision]) -> bytes:
    """字节稳定的决策转录（LSP-5 golden 的对象）。"""
    return canonical_json_bytes(decisions_to_jsonable(decisions))


@dataclass
class SessionProjectionStore:
    """按会话键保存决策集；写入只替换本会话，跨会话零共享可变状态。"""

    _sessions: dict[str, tuple[ProjectionDecision, ...]]

    def __init__(self) -> None:
        self._sessions = {}

    def project(self, session_id: str, brand: str, selection: LspSelection, *,
                lookup: PathLookup | None = None) -> tuple[ProjectionDecision, ...]:
        decisions = project_selection(brand, selection, lookup=lookup)
        self._sessions[session_id] = decisions
        return decisions

    def snapshot(self, session_id: str) -> tuple[ProjectionDecision, ...]:
        return self._sessions.get(session_id, ())
