"""016 LSP-1/3 — facet 形制、品牌门与 callable payload 的诚实三答。"""
from __future__ import annotations

import pytest
from ordessa_harness_api.contracts import AdapterContext, Assessment, \
    Installation
from ordessa_harness_api.errors import ContractError, ErrorCode

from ordessa_lsp_adapters import (
    BRAND_EVIDENCE,
    LSP_CONFIGURATION_POINT_ID,
    LSP_FACET_ID,
    PHASE2_BRANDS,
    REMOVED_BRANDS,
    HarnessLspConfigurationAdapter,
    HarnessRegistryUnavailable,
    build_configuration_batch,
    build_configuration_descriptor,
    default_lsp_adapters,
)
from ordessa_lsp_adapters.project import ProjectionRefusal, _resolve_brand
from _lsp_helpers import toml_pin


def _context(harness_id: str, native_version):
    return AdapterContext(
        targets=(),
        installation=Installation(harness_id=harness_id,
                                  native_version=native_version,
                                  adapter_version=(0, 1, 0),
                                  evidence_ref="test-fixture"),
        entry="test", scope="instance",
        capability_evidence_ref="test-fixture")


class TestFacetShape:
    def test_real_point_and_task_facet(self) -> None:
        assert LSP_CONFIGURATION_POINT_ID == "harness.configuration-adapters"
        assert LSP_FACET_ID == "assets.lsp"

    def test_batch_three_brands_on_real_point(self, repo_pins) -> None:
        batch = build_configuration_batch(pins=repo_pins)
        assert len(batch.contributions) == 3
        assert all(c.point_id == LSP_CONFIGURATION_POINT_ID
                   for c in batch.contributions)
        assert batch.open_points == frozenset({LSP_CONFIGURATION_POINT_ID})
        adapter_ids = {c.payload.descriptor.adapter_id
                       for c in batch.contributions}
        assert adapter_ids == {"assets.lsp.pi", "assets.lsp.codex",
                               "assets.lsp.claude-code"}

    def test_pins_measured_from_repo_toml(self, repo_pins) -> None:
        assert repo_pins["pi"] == toml_pin("pi")
        assert repo_pins["codex"] == toml_pin("codex")
        assert repo_pins["claude-code"] == toml_pin("claude-code")
        assert repo_pins["qwen"] == toml_pin("qwen")  # toml 事实仍在；格已除名

    def test_descriptors_zero_claims_closed_schema(self, repo_pins) -> None:
        for adapter in default_lsp_adapters():
            descriptor = build_configuration_descriptor(
                adapter.adapter_id, adapter.harness_id, pins=repo_pins)
            assert descriptor.facet_id == LSP_FACET_ID
            assert descriptor.api_version == "v1"
            # entries 只有该品牌的诚实决策面；claims 为零（无原生字段可写）
            assert descriptor.entries == (f"lsp.decision.{adapter.harness_id}",)
            assert descriptor.claims == ()
            pin = toml_pin(adapter.harness_id)
            parts = [int(x) for x in pin.split(".")]
            parts += [0] * (3 - len(parts))
            expected = tuple(parts[:3])
            assert descriptor.native_versions.minimum == expected
            assert descriptor.native_versions.maximum == expected
            assert descriptor.adapter_versions.minimum == (0, 1, 0)
            assert descriptor.adapter_versions.maximum == (0, 1, 0)
            with pytest.raises(ContractError):
                descriptor.payload_schema.validate({"lspServers": {}})

    def test_unknown_pin_refused_not_invented(self, repo_pins) -> None:
        with pytest.raises(HarnessRegistryUnavailable):
            build_configuration_descriptor("assets.lsp.pi", "not-a-brand",
                                           pins=repo_pins)


class TestCallablePayload:
    def _payload(self, harness_id: str, repo_pins) -> HarnessLspConfigurationAdapter:
        return HarnessLspConfigurationAdapter(build_configuration_descriptor(
            f"assets.lsp.{harness_id}", harness_id, pins=repo_pins))

    def test_assess_unsupported_with_evidence(self, repo_pins) -> None:
        payload = self._payload("pi", repo_pins)
        assessment = payload.assess(_context("pi", (2, 0, 0)), {})
        assert isinstance(assessment, Assessment)
        assert assessment.status == "unsupported"
        assert assessment.evidence_ref is not None
        assert "2b0a123de983" in assessment.reason
        assert "无原生 LSP 配置面" in assessment.reason

    def test_assess_brand_mismatch(self, repo_pins) -> None:
        payload = self._payload("pi", repo_pins)
        assert payload.assess(_context("codex", (2, 0, 0)), {}).status == \
            "unsupported"

    def test_assess_version_outside_pin_is_unknown(self, repo_pins) -> None:
        payload = self._payload("pi", repo_pins)
        assert payload.assess(_context("pi", (9, 9, 9)), {}).status == "unknown"

    def test_compile_refuses_capability(self, repo_pins) -> None:
        payload = self._payload("codex", repo_pins)
        refusal = payload.compile(_context("codex", (2, 0, 0)), None, {})
        assert refusal.code == ErrorCode.CAPABILITY_UNSUPPORTED
        assert "config-reference" in refusal.reason

    def test_compile_rejects_malformed_payload_first(self, repo_pins) -> None:
        payload = self._payload("codex", repo_pins)
        refusal = payload.compile(_context("codex", (2, 0, 0)), None,
                                  {"sandbox_mode": "x"})
        assert refusal.code == ErrorCode.INVALID_FRAGMENT

    def test_verify_unknown_no_native_readback(self, repo_pins) -> None:
        from ordessa_harness_api.contracts import VerificationUnknown
        payload = self._payload("claude-code", repo_pins)
        verdict = payload.verify(_context("claude-code", (0, 81, 2)), {})
        assert isinstance(verdict, VerificationUnknown)

    def test_every_brand_carries_evidence_record(self, repo_pins) -> None:
        for adapter in default_lsp_adapters():
            record = BRAND_EVIDENCE[adapter.harness_id]
            assert record["status"] == "unsupported"
            assert record["reason"] and record["evidence_ref"]


class TestBrandGate:
    """阶段二四家与除名品牌在投影入口的类型化拒绝（不出半截决策）。"""

    def test_phase2_brands_deferred(self) -> None:
        assert PHASE2_BRANDS == ("hermes", "opencode", "dsh", "kilo")
        for brand in PHASE2_BRANDS:
            with pytest.raises(ProjectionRefusal) as excinfo:
                _resolve_brand(brand)
            assert excinfo.value.code == "PHASE2_DEFERRED"

    def test_dsh_refusal_names_the_f6_correction(self) -> None:
        with pytest.raises(ProjectionRefusal) as excinfo:
            _resolve_brand("dsh")
        assert "lsp-stdio" in excinfo.value.reason

    def test_qwen_removed(self) -> None:
        assert REMOVED_BRANDS == ("qwen",)
        with pytest.raises(ProjectionRefusal) as excinfo:
            _resolve_brand("qwen")
        assert excinfo.value.code == "BRAND_REMOVED"
        assert "已除名" in excinfo.value.reason

    def test_unknown_brand(self) -> None:
        with pytest.raises(ProjectionRefusal) as excinfo:
            _resolve_brand("zcode-tui")
        assert excinfo.value.code == "UNKNOWN_BRAND"
