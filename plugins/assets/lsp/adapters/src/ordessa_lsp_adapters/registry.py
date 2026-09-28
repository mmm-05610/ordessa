"""品牌 roster 与 Server plugin 载体（016 LSP-1/3）。

形制仿 sandbox ``registry.py``：组合权威在平台（``stage_contributions`` 背后的
``HarnessContributionRegistry``），本包只交批次、不做第二准入。

品牌面按 spec.md 品牌优先级裁定收窄：本批只贡献 **pi / codex / claude-code**
三家 descriptor（且三家都是"无原生 LSP 面"的诚实 unsupported 格）；
hermes/opencode/dsh/kilo 转阶段二设计，qwen 已除名——它们不出现在贡献批里，
投影入口（``project``）对它们给类型化拒绝。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from server_plugin_api import (
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from .evidence import BRAND_EVIDENCE
from .points import build_configuration_batch

__all__ = [
    "ADAPTER_PLUGIN_ID",
    "DEFAULT_LSP_BRANDS",
    "LspBrandAdapter",
    "LspAdaptersServerPlugin",
    "default_lsp_adapters",
]

ADAPTER_PLUGIN_ID = "ordessa.lsp-adapters"

#: (adapter_id, harness_id)。harness_id 与 harnesses.toml 的 harness_type 严格
#: 同名（descriptor pin 按它实测）；adapter_id 以任务钦定的 facet 前缀起头。
DEFAULT_LSP_BRANDS: tuple[tuple[str, str], ...] = (
    ("assets.lsp.pi", "pi"),
    ("assets.lsp.codex", "codex"),
    ("assets.lsp.claude-code", "claude-code"),
)


@dataclass(frozen=True)
class LspBrandAdapter:
    """一个品牌的 LSP 域 adapter：本批统一为"无原生面"的诚实格。"""

    adapter_id: str
    harness_id: str

    @property
    def brand(self) -> str:
        return self.harness_id

    @property
    def evidence(self) -> Mapping[str, str]:
        return BRAND_EVIDENCE[self.harness_id]

    def native_field_claims(self) -> tuple[str, ...]:
        # 三家都没有原生 LSP 配置字段：零 claims 是证据结论，不是省略。
        return ()


def default_lsp_adapters() -> tuple[LspBrandAdapter, ...]:
    return tuple(LspBrandAdapter(adapter_id=adapter_id, harness_id=harness_id)
                 for adapter_id, harness_id in DEFAULT_LSP_BRANDS)


class LspAdaptersServerPlugin:
    """把三家 descriptor 经真实点交平台；无 provided_ports/owner/generation。"""

    def __init__(self, *, pins: Mapping[str, str] | None = None) -> None:
        self._pins = None if pins is None else dict(pins)

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=ADAPTER_PLUGIN_ID,
            display_name="Ordessa LSP asset domain adapters (assets.lsp)",
            version="0.1.0",
            requires=())

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        return ServerPluginRegistration(
            contributions=build_configuration_batch(pins=self._pins))
