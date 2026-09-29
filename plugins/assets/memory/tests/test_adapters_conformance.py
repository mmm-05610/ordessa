"""C2 conformance gates for the assets.memory brand adapters (MB-1), in the
model-provider/015-A gate form (real registry, production refusal
semantics): every gate here was red before the bridge existed — none was
back-fitted to green.

The pinned honest semantics (bridge.py header): registration + overlap
discipline are real; compile refuses while the AR-4 injection mount is
absent, and that refusal is the registered seam — a green compile here
would be the dishonest result."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from ordessa_harness_api import VersionRange
from ordessa_harness.contributions import HarnessContributionError, HarnessContributionRegistry
from server_plugin_api import Contribution, ContributionBatch, stage_contributions

from ordessa_memory import bridge, common, facet
from ordessa_memory.bridge import BridgeMemoryAdapter

OWNER = "ordessa.assets.memory"
SECOND_CLIENT = "second.client.probe"


def _batch():
    return ContributionBatch(tuple(
        Contribution("harness.configuration-adapters", "v1", BridgeMemoryAdapter(brand),
                     required=True)
        for brand in common.BRANDS
    ), open_points=frozenset({"harness.configuration-adapters"}))


class _Ctx:
    """Minimal harness-context double: versions + capability facts."""

    def __init__(self, version="1.2.3", capabilities=None):
        from types import SimpleNamespace
        self.installation = SimpleNamespace(harness_id="pi", native_version=(1, 2, 3))
        self.targets = []
        self.capabilities = capabilities or {}
        self.generation = "gen-1"


BINDING = {
    "memory": {"enabled": True, "budgetTokens": 2000, "extractionModelRef": None,
               "boundBrands": ["pi", "dsh", "qwen", "kilo"]},
}
BINDING_WITH_NATIVE = {
    "memory": {"enabled": True, "budgetTokens": 2000, "extractionModelRef": "ref://m",
               "boundBrands": ["pi", "codex"]},
}


# -- registration + conflict discipline (the real registry) -----------------------

def test_manifests_are_real_descriptors_with_the_memory_facet():
    for brand in common.BRANDS:
        descriptor = bridge.descriptor_for(brand)
        assert descriptor.adapter_id == f"assets.memory.{brand}"
        assert descriptor.harness_id == brand
        assert descriptor.facet_id == "assets.memory"
        assert descriptor.facet_schema_version == "1"
        assert descriptor.api_version == "v1"
        assert descriptor.entries == ("acp",)
        assert descriptor.payload_schema.kind == "object"


def test_facet_does_not_collide_with_model_provider_or_runtime_preferences():
    registered = {bridge.descriptor_for(b).adapter_id for b in common.BRANDS}
    assert "assets.model-provider.pi" not in registered
    assert "assets.runtime-preferences.pi" not in registered
    assert all(a.startswith("assets.memory.") for a in registered)


def test_eight_brands_register_into_the_real_c2_registry():
    registry = HarnessContributionRegistry()
    staged = stage_contributions(registry.configuration_handler, OWNER, _batch())
    staged.commit()
    assert sorted(d.adapter_id for d in registry.configuration_descriptors()) == sorted(
        f"assets.memory.{b}" for b in common.BRANDS)


def test_identical_registration_overlap_is_refused_by_real_registry():
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER, _batch()).commit()
    second = ContributionBatch((
        Contribution("harness.configuration-adapters", "v1", BridgeMemoryAdapter("pi")),
    ))
    with pytest.raises(HarnessContributionError, match="adapter_id already registered"):
        stage_contributions(registry.configuration_handler, SECOND_CLIENT, second)


def test_same_harness_overlapping_native_range_refused_by_real_registry():
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER, _batch()).commit()
    overlap = bridge.descriptor_for("pi")
    object.__setattr__(overlap, "adapter_id", "assets.memory.pi-alt")
    intruder = BridgeMemoryAdapter("pi")
    intruder.descriptor = overlap
    second = ContributionBatch((
        Contribution("harness.configuration-adapters", "v1", intruder),
    ))
    with pytest.raises(HarnessContributionError):
        stage_contributions(registry.configuration_handler, SECOND_CLIENT, second)


def test_disjoint_native_range_accepted_by_real_registry():
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER, _batch()).commit()
    successor_descriptor = bridge.descriptor_for("pi")
    object.__setattr__(successor_descriptor, "adapter_id", "assets.memory.pi-next")
    object.__setattr__(successor_descriptor, "native_versions", VersionRange((3, 0, 0)))
    successor = BridgeMemoryAdapter("pi")
    successor.descriptor = successor_descriptor
    second = ContributionBatch((
        Contribution("harness.configuration-adapters", "v1", successor),
    ))
    stage_contributions(registry.configuration_handler, SECOND_CLIENT, second).commit()
    assert {d.adapter_id for d in registry.configuration_descriptors()} >= {
        "assets.memory.pi", "assets.memory.pi-next"}


# -- honest semantics: mount absent on this baseline ------------------------------

def test_empty_probe_is_unknown_never_supported():
    adapter = BridgeMemoryAdapter("pi")
    verdict = adapter.assess(_Ctx(), {})
    assert verdict.status == "unknown"


def test_mount_absent_is_unsupported_with_the_registered_reason():
    adapter = BridgeMemoryAdapter("pi")
    verdict = adapter.assess(_Ctx(), BINDING)
    assert verdict.status == "unsupported"
    assert "AR-4" in verdict.reason


def test_mount_present_and_brand_bound_is_supported_with_evidence():
    adapter = BridgeMemoryAdapter("pi")
    verdict = adapter.assess(
        _Ctx(capabilities={"instruction_slot_facet": "ordessa.memory"}), BINDING)
    assert verdict.status == "supported"
    assert verdict.evidence_ref == "assets.memory:pi:spec-matrix"


def test_mount_present_but_brand_not_bound_is_unsupported():
    adapter = BridgeMemoryAdapter("opencode")
    verdict = adapter.assess(
        _Ctx(capabilities={"instruction_slot_facet": "ordessa.memory"}), BINDING)
    assert verdict.status == "unsupported"
    assert "boundBrands" in verdict.reason


def test_native_memory_brand_carries_the_coexistence_note():
    adapter = BridgeMemoryAdapter("codex")
    verdict = adapter.assess(
        _Ctx(capabilities={"instruction_slot_facet": "ordessa.memory"}), BINDING_WITH_NATIVE)
    assert verdict.status == "supported"
    assert "重复" in verdict.reason


def test_default_mounted_set_is_the_four_brands_without_native_memory():
    assert set(common.DEFAULT_MOUNTED) == {"pi", "dsh", "qwen", "kilo"}
    assert set(common.NATIVE_MEMORY_BRANDS) == {"codex", "claude-code", "hermes", "opencode"}
    assert set(common.DEFAULT_MOUNTED).isdisjoint(common.NATIVE_MEMORY_BRANDS)


# -- compile refuses honestly; verify compares projections --------------------------

def test_compile_refuses_with_the_registered_seam_reason():
    adapter = BridgeMemoryAdapter("pi")
    refusal = adapter.compile(_Ctx(), {}, BINDING)
    assert refusal.code == "capability-unsupported"
    assert "AR-4" in refusal.reason
    assert "memory.binding.set" in refusal.reason


def test_compile_rejects_malformed_bindings_before_anything_else():
    adapter = BridgeMemoryAdapter("pi")
    refusal = adapter.compile(_Ctx(), {}, {"memory": {"enabled": True}})
    assert refusal.code == "invalid-fragment"


def test_verify_compares_desired_to_projected():
    adapter = BridgeMemoryAdapter("pi")
    match = adapter.verify(_Ctx(), {"desired": BINDING, "projected": BINDING})
    assert match.kind == "match"
    mismatch = adapter.verify(_Ctx(), {"desired": BINDING, "projected": {
        "memory": {**BINDING["memory"], "enabled": False}}})
    assert mismatch.kind == "mismatch"
    unknown = adapter.verify(_Ctx(), {"desired": BINDING})
    assert unknown.kind == "unknown"


# -- purity boundaries ---------------------------------------------------------------

#: the modules that must stay pure: no HOME reads, no network, no spawn, no
#: writes. ``provisioning`` (docker/git/files) and ``mem0_client`` (urllib)
#: ARE the package's IO edges; ``plugin``/``store`` own the data-root.
_PURE_MODULES = ("common", "facet", "bridge", "llm_wiring", "capture",
                 "injection", "events")
_FORBIDDEN = re.compile(
    r"expanduser|environ\[|getenv|socket|urllib|http\.client|requests\.|"
    r"subprocess|Popen|os\.system|shutil|open\(")


def _source(module: str) -> str:
    spec = importlib.util.find_spec(f"ordessa_memory.{module}")
    return Path(spec.origin).read_text()


@pytest.mark.parametrize("module", _PURE_MODULES)
def test_pure_modules_never_touch_home_network_or_spawn(module):
    match = _FORBIDDEN.search(_source(module))
    assert match is None, f"ordessa_memory.{module} references {match.group(0)!r}"


@pytest.mark.parametrize("module", _PURE_MODULES)
def test_pure_modules_never_import_sibling_plugins_or_host(module):
    for line in _source(module).splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            root = stripped.split()[1].split(".")[0]
            assert root not in {
                "ordessa_model_provider", "ordessa_server", "ordessa_server_compat",
                "ordessa_prompts", "ordessa_harness", "pacthold"}, line


def test_package_never_imports_the_model_provider_modules():
    for module in ("plugin", "provisioning", "mem0_client", "store"):
        for line in _source(module).splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                root = stripped.split()[1].split(".")[0]
                assert root != "ordessa_model_provider", line


def test_facet_keys_mirror_the_ar5_contract():
    """AR-5: the shared keys mirror P-A's memory item exactly (documented
    copy of the contract — cross-package imports are forbidden)."""
    assert common.VALUE_KEYS == ("enabled", "budgetTokens", "extractionModelRef", "boundBrands")
    assert facet.facet_descriptor()["items"][0]["valueKeys"] == list(common.VALUE_KEYS)
