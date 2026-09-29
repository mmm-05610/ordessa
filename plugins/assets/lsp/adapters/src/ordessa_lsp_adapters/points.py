"""facet ``assets.lsp`` 与真实 C2 点的绑定（016 LSP-1）。

形制完全仿 sandbox adapters 的 ``points.py``（T05b 实测过的绑定法）：

* 点是平台自己的 ``harness.configuration-adapters``（v1），本包不自设第二
  注册机构；``harnesses.toml`` 定位与 sandbox 同法：先仓内 file-relative
  （测试与运行同源、换树不串），退回 ``importlib.util.find_spec``，都不在则
  ``HarnessRegistryUnavailable``——pin 永不编造。
* 本批三家品牌**零 native-field claims**（没有任何品牌拥有可写的原生 LSP
  配置字段，见 ``evidence.py``），payload schema 一律是闭合空对象：
  ``{"anything": …}`` 会被平台的 ``ValueSchema`` 以 ``unknown property`` 拒绝，
  在 compile 之前就拦下，不存在"配置先写上再说"的形状。
* callable payload 的三答（assess/compile/verify）把 LSP-3 的诚实逐格落成
  平台词汇：unsupported 带证据指针、compile ``CAPABILITY_UNSUPPORTED``、
  verify ``VerificationUnknown``——没有原生面就没有原生 readback，不冒充。

与 sandbox 的刻意差异：sandbox 的 callable 在缺授权事实时答 ``unknown``
（fail-closed 等事实）；LSP 的 unsupported 是**终态事实**（官方文档证据在
案），不是等待授权——两者不可混用，否则"无原生面"会被读成"还没轮到"。
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from ordessa_harness_api.contracts import (
    AdapterContext, AdapterRefusal, Assessment, ConfigurationAdapterDescriptor,
    VerificationUnknown,
)
from ordessa_harness_api.errors import ContractError, ErrorCode
from ordessa_harness_api.schema import ValueSchema
from server_plugin_api import Contribution, ContributionBatch

from .evidence import BRAND_EVIDENCE

__all__ = [
    "LSP_CONFIGURATION_POINT_ID",
    "LSP_POINT_API_VERSION",
    "LSP_FACET_ID",
    "LSP_FACET_SCHEMA_VERSION",
    "HarnessLspConfigurationAdapter",
    "HarnessRegistryUnavailable",
    "build_configuration_descriptor",
    "build_configuration_batch",
    "pinned_harness_versions",
]

LSP_CONFIGURATION_POINT_ID = "harness.configuration-adapters"
LSP_POINT_API_VERSION = "v1"

#: 任务 LSP-1 钦定的 facet 名（`assets.lsp`）。
LSP_FACET_ID = "assets.lsp"
LSP_FACET_SCHEMA_VERSION = "1"

#: 本发行物自己的 release fact（adapters/pyproject.toml version = 0.1.0），
#: 精确两界，不放大。
_ADAPTER_VERSION_RANGE = ((0, 1, 0), (0, 1, 0))


class HarnessRegistryUnavailable(RuntimeError):
    """`harnesses.toml` 不可定位；pin 必须来自真实 registry 或显式传入。"""


def _semver_tuple(text: str) -> tuple[int, int, int]:
    core = text.split("-", 1)[0].split("+", 1)[0].strip()
    parts = [int(segment) for segment in core.split(".") if segment != ""]
    if not parts:
        raise ValueError(f"unparseable native version: {text!r}")
    parts += [0] * (3 - len(parts))
    return tuple(parts[:3])


def _repo_harnesses_toml() -> Path | None:
    # points.py: plugins/assets/lsp/adapters/src/ordessa_lsp_adapters/
    #   -> parents[5] = plugins/ -> + harness/src/ordessa_harness/
    candidate = (Path(__file__).resolve().parents[5]
                 / "harness/src/ordessa_harness/harnesses.toml")
    return candidate if candidate.is_file() else None


def pinned_harness_versions() -> dict[str, str]:
    """按 harness_type 实测版本，来源优先仓内 ``harnesses.toml``。"""
    toml_path = _repo_harnesses_toml()
    if toml_path is None:
        try:
            spec = importlib.util.find_spec("ordessa_harness")
        except (ImportError, ValueError):
            spec = None
        if spec is None or not spec.submodule_search_locations:
            raise HarnessRegistryUnavailable(
                "cannot locate harnesses.toml (repo-relative and installed "
                "dist both absent); pass pins= explicitly — no pin is "
                "invented here")
        toml_path = (Path(next(iter(spec.submodule_search_locations)))
                     / "harnesses.toml")
        if not toml_path.is_file():
            raise HarnessRegistryUnavailable(
                f"ordessa_harness found at {toml_path.parent} but "
                "harnesses.toml is missing")
    import tomllib
    document = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    return {entry["identity"]["harness_type"]: entry["identity"]["version"]
            for entry in document["harness"]}


#: 三家品牌本批共同的事实：无原生 LSP 配置字段 → 闭合空 schema、零 claims。
_EMPTY_CLOSED_PAYLOAD = ValueSchema("object")


@dataclass(frozen=True)
class HarnessLspConfigurationAdapter:
    """callable C2 payload：unsupported 是带证据的终态，不是待授权的未知。"""

    descriptor: ConfigurationAdapterDescriptor

    def _evidence(self) -> dict[str, str]:
        return BRAND_EVIDENCE[self.descriptor.harness_id]

    # ------------------------------------------------------------------ assess
    def assess(self, context: AdapterContext, request: object) -> Assessment:
        if not isinstance(context, AdapterContext):
            return Assessment("unknown", reason="Harness adapter context is unavailable")
        if context.installation.harness_id != self.descriptor.harness_id:
            return Assessment(
                "unsupported",
                reason=f"Harness brand does not match this {LSP_FACET_ID} facet")
        if self.descriptor.native_versions.contains(
                context.installation.native_version) is not True:
            return Assessment(
                "unknown", reason="Observed native version is outside the measured pin")
        try:
            self.descriptor.payload_schema.validate(request)
        except ContractError:
            return Assessment(
                "unsupported",
                reason=(f"{LSP_FACET_ID} payload is invalid for "
                        f"{self.descriptor.harness_id}: the facet admits no "
                        "native LSP configuration keys"))
        record = self._evidence()
        return Assessment("unsupported", evidence_ref=record["evidence_ref"],
                          reason=record["reason"])

    # ----------------------------------------------------------------- compile
    def compile(self, context: AdapterContext, before: object,
                desired: object) -> AdapterRefusal:
        try:
            self.descriptor.payload_schema.validate(desired)
        except ContractError:
            return AdapterRefusal(
                ErrorCode.INVALID_FRAGMENT,
                f"{LSP_FACET_ID} payload is invalid: the facet admits no "
                "native LSP configuration keys")
        record = self._evidence()
        return AdapterRefusal(
            ErrorCode.CAPABILITY_UNSUPPORTED,
            f"{record['reason']} [evidence: {record['evidence_ref']}]")

    # ------------------------------------------------------------------ verify
    def verify(self, context: AdapterContext,
               observed: object) -> VerificationUnknown:
        return VerificationUnknown(
            f"no native LSP configuration surface exists for "
            f"{self.descriptor.harness_id}, so no native readback can exist "
            "to verify against")


def build_configuration_descriptor(
        adapter_id: str, harness_id: str, *,
        pins: Mapping[str, str] | None = None
) -> ConfigurationAdapterDescriptor:
    """一个品牌的 descriptor：零 entries/claims + 闭合空 payload schema。"""
    resolved = dict(pins) if pins is not None else pinned_harness_versions()
    if harness_id not in resolved:
        raise HarnessRegistryUnavailable(
            f"harnesses.toml records no harness {harness_id!r}; the "
            "descriptor stays unbuildable rather than inventing a pin")
    pin = _semver_tuple(resolved[harness_id])
    from ordessa_harness_api.contracts import VersionRange
    # entries 非空是平台合同（contracts.py 校验）；本域每品牌公开的能力面
    # 只有一个：该品牌的诚实投影决策面——由 HarnessLspConfigurationAdapter
    # 的 assess/compile/verify 与 project.project_selection 实现（决策记录
    # + 证据指针），entry 即该实现的名字。不是 native field claim——
    # claims 仍为零。
    entries = (f"lsp.decision.{harness_id}",)
    return ConfigurationAdapterDescriptor(
        adapter_id=adapter_id,
        api_version=LSP_POINT_API_VERSION,
        facet_id=LSP_FACET_ID,
        facet_schema_version=LSP_FACET_SCHEMA_VERSION,
        harness_id=harness_id,
        native_versions=VersionRange(pin, pin),
        adapter_versions=VersionRange(*_ADAPTER_VERSION_RANGE),
        entries=entries,
        payload_schema=_EMPTY_CLOSED_PAYLOAD,
        claims=(),
    )


def build_configuration_batch(
        brands: Iterable[tuple[str, str]] | None = None, *,
        pins: Mapping[str, str] | None = None) -> ContributionBatch:
    """真实点上的品牌贡献批；默认三家（pi/codex/claude-code）。"""
    if brands is None:
        from .registry import DEFAULT_LSP_BRANDS
        brands = DEFAULT_LSP_BRANDS
    items = tuple(
        Contribution(LSP_CONFIGURATION_POINT_ID, LSP_POINT_API_VERSION,
                     HarnessLspConfigurationAdapter(
                         build_configuration_descriptor(adapter_id, harness_id,
                                                        pins=pins)),
                     required=False)
        for adapter_id, harness_id in brands)
    return ContributionBatch(items, open_points=frozenset(
        {LSP_CONFIGURATION_POINT_ID}))
