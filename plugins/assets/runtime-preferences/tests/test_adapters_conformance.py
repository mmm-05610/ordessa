"""P-A conformance gates for the runtime-preferences brand adapters.

Gate shapes follow the pinned form of
``plugins/assets/model-provider/adapters/tests/test_adapters_conformance.py``
(lines 80-103 there: real-C2-registry overlap refusal and disjoint-range
acceptance), re-driven against the production registry
(``ordessa_harness.contributions``) — refusal semantics are the production
ones (adapter_id / facet-entry-range / claim conflicts at stage time, never
order-resolved).

RA-1: the facet registers into C2, does not collide with the existing facet
vocabulary, and the overlap gates are green.
RA-2: the eight brand skeletons carry assess/compile/verify +
``registration_manifest()``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ordessa_harness_api import ConfigurationAdapterDescriptor, VersionRange
from ordessa_harness.contributions import HarnessContributionError, HarnessContributionRegistry
from server_plugin_api import Contribution, ContributionBatch, stage_contributions

from ordessa_runtime_preferences import bridge, common, keys
from ordessa_runtime_preferences.plugin import CONFIGURATION_POINT, PLUGIN_ID, RuntimePreferencesAdaptersPlugin
from ordessa_runtime_preferences.types import (
    AdapterContext, PreferenceRequest, Refusal, TargetHandle,
)

OWNER = PLUGIN_ID
SECOND_CLIENT = "second.client.probe"
SUPPORTED_PIN = "1.0.0"  # document-level window accepts a well-formed version


def _ctx(brand: str, version: str | None = SUPPORTED_PIN,
         scope: str = "instance", identity: str | None = None) -> AdapterContext:
    target = keys.BRAND_TARGETS[brand][0] or f"{brand}.fixture.json"
    return AdapterContext(
        target_handle=TargetHandle(brand, scope, identity or target),
        harness_version=version,
        capabilities={"native_session_id": "nat-7"},
        generation="gen-1",
    )


def _request(group: str = "compaction", **params) -> PreferenceRequest:
    return PreferenceRequest(group, dict(params))


# -- RA-1: real C2 registration -------------------------------------------------

def test_manifests_are_real_harness_api_descriptors_with_frozen_facet():
    for brand in keys.BRANDS:
        descriptor = bridge.descriptor_for(brand)
        assert isinstance(descriptor, ConfigurationAdapterDescriptor)
        assert descriptor.adapter_id == f"assets.runtime-preferences.{brand}"
        assert descriptor.harness_id == brand
        assert descriptor.facet_id == "assets.runtime-preferences"
        assert descriptor.facet_schema_version == "1"
        assert descriptor.api_version == "v1"
        assert descriptor.entries == ("acp",)
        assert descriptor.payload_schema.kind == "object"


def test_descriptor_claims_cover_compiled_keys_only():
    """RA-4 structural half: admin-only and recorded-but-uncompiled keys are
    never claimable — the claims mirror exactly the compiled keys. A brand
    with a pinnable target but nothing compilable yet (hermes at document
    level) legitimately claims nothing."""
    for brand in keys.BRANDS:
        claims = bridge.descriptor_for(brand).claims
        compiled_paths = {path for group in keys.GROUPS
                          for path in keys.compiled_keys(brand, group).values()}
        if keys.BRAND_TARGETS[brand][0] is None or not compiled_paths:
            assert claims == (), brand
            continue
        assert claims, brand
        for group in keys.GROUPS:
            for path in keys.compiled_keys(brand, group).values():
                assert any(path[:len(claim.field_path)] == claim.field_path
                           for claim in claims), (brand, path)
        for group in keys.GROUPS:
            for key in keys.admin_only_keys(brand, group):
                if key.path:
                    assert not any(tuple(key.path) == claim.field_path
                                   for claim in claims), (brand, key.path)


def test_facet_does_not_collide_with_the_existing_facet_vocabulary():
    """RA-1 '不与既有 facet 撞': the harnesses.toml slots vocabulary
    (provider/permission/instruction/mcp/skill/hooks) does not contain the
    four groups — this facet rides C2 typed parameters, not a new slot; the
    facet id is distinct from the model-provider facet id."""
    slots = {"provider", "permission", "instruction", "mcp", "skill", "hooks"}
    assert not set(keys.GROUPS) & slots
    assert common.FACET_ID != "assets.model-provider"


def _plugin_batch():
    plugin = RuntimePreferencesAdaptersPlugin()
    return plugin.build(None).contributions


def test_eight_brands_register_into_the_real_c2_registry():
    registry = HarnessContributionRegistry()
    staged = stage_contributions(registry.configuration_handler, OWNER, _plugin_batch())
    staged.commit()
    assert sorted(d.adapter_id for d in registry.configuration_descriptors()) == sorted(
        f"assets.runtime-preferences.{brand}" for brand in keys.BRANDS)


def test_identical_registration_overlap_is_refused_by_real_registry():
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER, _plugin_batch()).commit()
    second = ContributionBatch((
        Contribution(CONFIGURATION_POINT, "v1", bridge.BridgeConfigurationAdapter("pi")),
    ))
    with pytest.raises(HarnessContributionError, match="adapter_id already registered"):
        stage_contributions(registry.configuration_handler, SECOND_CLIENT, second)


def test_same_harness_overlapping_range_same_facet_refused_by_real_registry():
    """A second client may claim the same facet only outside the first
    owner's native version range; an overlapping range with a shared entry is
    a stage-time refusal (the pinned gate shape)."""
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER, _plugin_batch()).commit()

    overlap = bridge.descriptor_for("opencode")
    object.__setattr__(overlap, "adapter_id", "assets.runtime-preferences.opencode-alt")
    intruder = bridge.BridgeConfigurationAdapter("opencode")
    intruder.descriptor = overlap
    second = ContributionBatch((Contribution(CONFIGURATION_POINT, "v1", intruder),))
    with pytest.raises(HarnessContributionError):
        stage_contributions(registry.configuration_handler, SECOND_CLIENT, second)


def test_disjoint_native_range_accepted_by_real_registry():
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER, _plugin_batch()).commit()

    next_range = bridge.descriptor_for("opencode")
    object.__setattr__(next_range, "adapter_id", "assets.runtime-preferences.opencode-next")
    object.__setattr__(next_range, "native_versions", VersionRange((2, 0, 1), (3, 0, 0)))
    successor = bridge.BridgeConfigurationAdapter("opencode")
    successor.descriptor = next_range
    second = ContributionBatch((Contribution(CONFIGURATION_POINT, "v1", successor),))
    stage_contributions(registry.configuration_handler, SECOND_CLIENT, second).commit()
    assert {d.adapter_id for d in registry.configuration_descriptors()} >= {
        "assets.runtime-preferences.opencode", "assets.runtime-preferences.opencode-next"}


# -- RA-2/RA-6: version gates ---------------------------------------------------

@pytest.mark.parametrize("brand", keys.BRANDS)
def test_well_formed_version_assesses_supported(brand):
    from ordessa_runtime_preferences import engine
    assert engine.assess(brand, _ctx(brand), _request()).verdict == "supported"


@pytest.mark.parametrize("brand", keys.BRANDS)
def test_unrecognized_version_is_unknown_never_guessed(brand):
    from ordessa_runtime_preferences import engine
    assessment = engine.assess(brand, _ctx(brand, version="not-a-version"), _request())
    assert assessment.verdict == "unknown"
    assert "version" in assessment.reason.lower()


@pytest.mark.parametrize("brand", keys.BRANDS)
def test_missing_version_is_unknown_never_guessed(brand):
    from ordessa_runtime_preferences import engine
    assessment = engine.assess(brand, _ctx(brand, version=None), _request())
    assert assessment.verdict == "unknown"


# -- RA-3: the 32-cell catalog is complete and disciplined ----------------------

def test_catalog_covers_every_brand_group_exactly_once():
    assert set(keys.CELLS) == {(brand, group) for brand in keys.BRANDS
                               for group in keys.GROUPS}


@pytest.mark.parametrize("brand", keys.BRANDS)
@pytest.mark.parametrize("group", keys.GROUPS)
def test_every_cell_carries_evidence_and_a_conclusion(brand, group):
    cell = keys.cell(brand, group)
    assert cell.status in (keys.STATUS_AVAILABLE, keys.STATUS_UNSUPPORTED, keys.STATUS_UNKNOWN)
    assert cell.conclusion.strip()
    assert cell.keys, "every cell records at least the evidence rows behind its verdict"
    for key in cell.keys:
        assert key.evidence.strip(), (brand, group)


def test_compiled_keys_exist_only_in_available_cells():
    for (brand, group), cell in keys.CELLS.items():
        if cell.status != keys.STATUS_AVAILABLE:
            assert keys.compiled_keys(brand, group) == {}, (brand, group)


def test_apply_mode_vocabulary_is_closed():
    for cell in keys.CELLS.values():
        for key in cell.keys:
            assert key.apply_mode in (keys.APPLY_RELOAD, keys.APPLY_RESTART,
                                      keys.APPLY_NEXT_SESSION, keys.APPLY_UNKNOWN)


def test_kilo_compiled_keys_carry_the_documented_restart_mode():
    """INV §8: kilo's official CLI docs require a restart after config file
    changes — the rare documented apply mode; it must not silently regress
    to unknown (and nothing else may silently claim restart)."""
    for group in ("compaction", "shell"):
        for path in keys.compiled_keys("kilo", group).values():
            for key in keys.cell("kilo", group).keys:
                if key.path == path:
                    assert key.apply_mode == keys.APPLY_RESTART, (group, path)


def test_unverified_dominates_and_never_claims_hot_reload():
    from ordessa_runtime_preferences import common
    # kilo compaction: fully documented restart → restart-resume
    assert common.item_reconfiguration("kilo", "compaction") == "restart-resume"
    # opencode compaction: documented keys, no documented apply mode → unverified
    assert common.item_reconfiguration("opencode", "compaction") == "unverified"
    # every brand/group with unknown modes stays unverified
    for (brand, group), cell in keys.CELLS.items():
        modes = [k.apply_mode for k in cell.keys if k.canonical and not k.admin_only]
        if modes and keys.APPLY_UNKNOWN in modes:
            assert common.item_reconfiguration(brand, group) == "unverified"


# -- model-provider boundary (spec §4 ruling 3) ---------------------------------

def _harness_ctx(brand: str, version: str = SUPPORTED_PIN):
    """A harness-shaped adapter context (Installation + file targets), as C4
    hands the bridge."""
    from ordessa_harness_api import AdapterContext as HarnessAdapterContext
    from ordessa_harness_api import Installation, TargetDescriptor, TargetHandle

    handle = keys.BRAND_TARGETS[brand][0] or f"{brand}.fixture.json"
    targets = (TargetDescriptor(TargetHandle(handle, 7), "file", "json", "instance"),)
    installation = Installation(brand, tuple(int(p) for p in version.split(".")),
                                (1, 0, 0), "test:installed")
    return HarnessAdapterContext(targets, installation, "acp", "instance",
                                 "test:capability")


def test_codex_request_level_retry_family_is_refused_at_the_boundary():
    adapter = bridge.BridgeConfigurationAdapter("codex")
    refusal = adapter.compile(_harness_ctx("codex"), {}, {"retry": {"maxRetries": 3}})
    from ordessa_harness_api import AdapterRefusal
    assert isinstance(refusal, AdapterRefusal)
    assert refusal.code.name == "CAPABILITY_UNSUPPORTED"
    assert "model-provider" in refusal.reason


def test_provider_subtree_keys_never_enter_codex_claims():
    claims = bridge.descriptor_for("codex").claims
    assert not any(claim.field_path[:1] == ("model_providers",) for claim in claims)


# -- purity boundary -------------------------------------------------------------

#: Library-shaped references only: bare words like "requests" appear in
#: prose/docstrings, so match import/attribute usage.
_FORBIDDEN = re.compile(
    r"expanduser|environ\[|getenv\b|import socket|import urllib|http\.client|"
    r"import requests|requests\.(get|post|put|delete|head|Session)|"
    r"import subprocess|Popen|os\.system|path\.write\(|open\(.*'w'|import shutil",
)

_BRAND_ALLOWED_ROOTS = {"__future__", "typing", "dataclasses",
                        "ordessa_runtime_preferences"}


def _module_source(module: str) -> str:
    import importlib.util
    origin = importlib.util.find_spec(f"ordessa_runtime_preferences.{module}").origin
    return Path(origin).read_text()


def _import_roots(source: str):
    for module_line in source.splitlines():
        stripped = module_line.strip()
        if not stripped.startswith(("import ", "from ")):
            continue
        token = stripped.split()[1]
        if token.startswith("."):  # package-relative import, inside by construction
            continue
        yield token.split(".")[0], module_line


@pytest.mark.parametrize("module", [b.replace("-", "_") for b in
                                    ("pi", "codex", "claude", "hermes", "opencode",
                                     "dsh", "qwen", "kilo")])
def test_brand_modules_never_touch_home_network_or_spawn(module):
    match = _FORBIDDEN.search(_module_source(module))
    assert match is None, f"{module} references {match.group(0)!r}"


@pytest.mark.parametrize("module", [b.replace("-", "_") for b in
                                    ("pi", "codex", "claude", "hermes", "opencode",
                                     "dsh", "qwen", "kilo")])
def test_brand_modules_do_not_import_the_bridge_or_harness(module):
    for root, line in _import_roots(_module_source(module)):
        assert root in _BRAND_ALLOWED_ROOTS, line


@pytest.mark.parametrize("module", ["engine", "common", "keys", "bridge", "plugin",
                                    "facet", "session", "types"])
def test_core_modules_stay_pure(module):
    match = _FORBIDDEN.search(_module_source(module))
    assert match is None, f"{module} references {match.group(0)!r}"
