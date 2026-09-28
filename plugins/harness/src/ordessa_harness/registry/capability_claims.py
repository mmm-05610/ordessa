"""生产部署声明与静态能力声明之间的**唯一**派生点。

生产模板（`{codex,pi,hermes,opencode}/production.py`）的 `capabilityClaims` 不允许再写
第二份手抄字典：它们必须从这里派生，而这里唯一的输入是注册表（`harnesses.toml`），
词汇表则来自 canonical 合同（`pacthold.resource_contracts.harness_capabilities`）。
测试对每一家逐项断言 `capabilityClaims` 的 **true 项**恰好等于 TOML 的 `capabilities`，
所以模板与注册表不可能各说一套。
"""
from __future__ import annotations

from pacthold_runtime_compat.resource_contracts.harness_capabilities import CANONICAL_CAPABILITY_IDS


def capability_claims(harness_type: str) -> dict[str, bool]:
    """该 harness 的 canonical 能力声明，**八个 id 全部**给出真 bool。

    * 声明了就是 `True`，没声明就是 `False`（不是缺省、不是 `"supported"`、
      不是 `1`）。显式 `False` 比"键不在"更有信息量：消费方不用把"没写"解释成
      "不支持"，而"写了 False"就是一个可断言的声明。
    * 值只由 `definition.capabilities` 决定，顺序恒为 `CANONICAL_CAPABILITY_IDS`
      的锁定顺序，因此同一份声明在每次调用里都是逐字节相同的形状。
    * 每次返回一个新的 dict，调用方改它不会污染其他模板或注册表。

    未知 `harness_type` 直接抛 `KeyError`（来自注册表），不返回空声明——把拼错的
    harness 名字静默降级成"什么都不支持"正是最危险的那种失败。
    """
    from .definitions import REGISTRY  # 惰性：避免 import 期的循环依赖

    declared = set(REGISTRY.get(harness_type).capabilities)
    return {capability_id: capability_id in declared for capability_id in CANONICAL_CAPABILITY_IDS}
