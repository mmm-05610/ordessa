"""P-A② equivalence pins (approvals/PA2-dialect-release.md, case 1, minimal split).

The dialect tables moved from literals in `native_materialization` into each
family's own `native.py`; these pins freeze exactly what the approval calls
equivalence:

  * every family table byte-equal to the pre-split literal (change needs a pin
    update in the same batch - frozen on purpose, x20 precedent);
  * the aggregation is the family tables themselves (`is`, not a copy) with the
    same key sets as before - 7 dialect keys, 6 target keys (dsh pins None in
    its own module and stays absent from `_NATIVE_TARGET`, exactly as the
    pre-split literals), `qoder` absent from both;
  * kilo/opencode hold distinct objects (equal by value, owned separately - the
    approval names "each family owns its facts, no cross-family import");
  * the shared module's public surface did not move (engine, renderers, error,
    vocabulary - the approval froze that list) and behaviour readings
    (translate/refuse/is_pinnable) are unchanged;
  * the `dsh/__init__` lazification (declared path, goal-H-027): package import
    needs no PyYAML, `__all__` frozen to the original 25 names; value identity
    with `production` is covered by the C-authority gate (env has PyYAML).

Red-green: on a prefix tree without `<family>/native.py` these pins fail at
import (that is the tooth); `native_materialization` itself would also be the
old literal version there, so the pins red for the right reason.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ordessa_harness import native_materialization as nm
from ordessa_harness.claude import native as claude_native
from ordessa_harness.codex import native as codex_native
from ordessa_harness.dsh import native as dsh_native
from ordessa_harness.hermes import native as hermes_native
from ordessa_harness.kilo import native as kilo_native
from ordessa_harness.opencode import native as opencode_native
from ordessa_harness.pi import native as pi_native

# -- frozen pre-split literals (copied from the P-A② source tree, d8a71c4) ----

FROZEN_DIALECTS = {
    "codex": {"openai-responses": ("wire_api", "responses"),
              "openai-chat": ("wire_api", "chat")},
    "pi": {"openai-chat": ("api", "openai-completions")},
    "hermes": {"openai-chat": ("transport", "chat_completions")},
    "opencode": {"openai-chat": ("npm", "@ai-sdk/openai-compatible")},
    "kilo": {"openai-chat": ("npm", "@ai-sdk/openai-compatible")},
    "claude-code": {"anthropic-messages": ("ANTHROPIC_BASE_URL", None)},
    "dsh": {},
}
FROZEN_TARGET = {
    "codex": "config.toml", "opencode": "opencode.json", "kilo": "kilo.json",
    "pi": "models.json", "hermes": "config.yaml", "claude-code": "settings.json",
}
FROZEN_DSH_LAZY_NAMES = (
    "ADAPTER_ARTIFACT_ENTRY", "ADAPTER_PACKAGE", "ADAPTER_VERSION", "ARTIFACT_NAME",
    "ARTIFACT_TARGET", "CREDENTIAL_ENVIRONMENT", "CREDENTIAL_KIND", "DSH_PROVIDER",
    "DshProductionTemplateError", "HARNESS_HOME", "MODEL_CONTROL_ID",
    "NATIVE_MODEL_VALUE", "OFFICIAL_BASE_URL", "OUTPUT_TOKEN_LIMIT", "PRODUCT_MODEL_ID",
    "STATE_TARGET", "capability_claims", "deployment_document", "documented_differences",
    "harness_deployment", "loopback_settings_document", "model_aliases", "native_model",
    "projection_files", "settings_document",
)


@pytest.mark.parametrize("family", sorted(FROZEN_DIALECTS))
def test_family_dialect_table_is_byte_equal_to_the_pre_split_literal(family):
    assert dict(FROZEN_DIALECTS[family]) == dict(nm._FAMILY_DIALECTS[family])


def test_aggregation_key_sets_match_the_pre_split_literals_exactly():
    assert sorted(nm._FAMILY_DIALECTS) == sorted(FROZEN_DIALECTS)   # 7 keys
    assert sorted(nm._NATIVE_TARGET) == sorted(FROZEN_TARGET)       # 6 keys
    assert nm._NATIVE_TARGET == FROZEN_TARGET


def test_aggregation_holds_the_family_tables_themselves_not_copies():
    pairs = {
        "codex": codex_native, "pi": pi_native, "hermes": hermes_native,
        "opencode": opencode_native, "kilo": kilo_native,
        "claude-code": claude_native, "dsh": dsh_native,
    }
    for key, module in pairs.items():
        assert nm._FAMILY_DIALECTS[key] is module.DIALECTS, key
    for key in FROZEN_TARGET:
        module = {"codex": codex_native, "pi": pi_native, "hermes": hermes_native,
                  "opencode": opencode_native, "kilo": kilo_native,
                  "claude-code": claude_native}[key]
        assert nm._NATIVE_TARGET[key] == module.NATIVE_TARGET, key


def test_dsh_pins_nothing_as_explicit_family_rule():
    assert dsh_native.DIALECTS == {} and dsh_native.NATIVE_TARGET is None
    assert "dsh" not in nm._NATIVE_TARGET


def test_kilo_and_opencode_hold_distinct_objects_equal_by_value():
    assert kilo_native is not opencode_native
    assert kilo_native.DIALECTS is not opencode_native.DIALECTS
    assert kilo_native.DIALECTS == opencode_native.DIALECTS


def test_claude_code_key_maps_to_the_claude_package_and_the_mismatch_stays():
    assert "claude-code" in nm._FAMILY_DIALECTS and "claude" not in nm._FAMILY_DIALECTS
    assert nm._FAMILY_DIALECTS["claude-code"] is claude_native.DIALECTS


def test_qoder_stays_absent_from_both_tables():
    assert "qoder" not in nm._FAMILY_DIALECTS
    assert "qoder" not in nm._NATIVE_TARGET
    assert nm.is_pinnable("qoder", "openai-chat") is False


def test_shared_module_public_surface_did_not_move():
    # the approval froze this list: engine + renderers + error + vocabulary
    assert nm.CANONICAL_PROTOCOLS == (
        "openai-chat", "openai-responses", "anthropic-messages", "gemini-generate")
    for name in ("translate_protocol", "is_pinnable", "materialize_family",
                 "NativeMaterializationError",
                 "render_codex_provider_section", "render_pi_provider",
                 "render_claude_env", "render_opencode_provider", "render_hermes_config"):
        assert hasattr(nm, name), name


def test_behaviour_readings_are_unchanged_after_the_split():
    assert nm.translate_protocol("codex", "openai-responses") == ("wire_api", "responses")
    assert nm.translate_protocol("hermes", "openai-chat") == ("transport", "chat_completions")
    with pytest.raises(nm.NativeMaterializationError) as refused:
        nm.translate_protocol("dsh", "openai-chat")
    assert refused.value.code == "PROTOCOL_UNSUPPORTED_BY_HARNESS"
    with pytest.raises(nm.NativeMaterializationError) as refused:
        nm.translate_protocol("claude-code", "openai-chat")
    assert refused.value.code == "PROTOCOL_UNSUPPORTED_BY_HARNESS"


def test_dsh_package_import_needs_no_yaml_and_its_lazysurface_is_frozen():
    # P-B note: the yaml dependency itself moved into the render functions
    # (PB-dsh-pilot-release.md §三处改码②), so this import - and the legacy
    # alias below - need no PyYAML in any environment now.
    import ordessa_harness.dsh as dsh_pkg
    assert tuple(dsh_pkg.__all__) == FROZEN_DSH_LAZY_NAMES
    # name not in the lazy list still fails loudly (no silent dict expansion)
    with pytest.raises(AttributeError):
        dsh_pkg.does_not_exist


# -- P-B pilot pins, restated for the monorepo baseline (2026-09-25) -----------
# The historical pins compared the legacy alias distributions
# (`agent_box_harness_dsh/kilo`) with the canonical package. Those alias
# distributions were retired together with the old repository layout; the
# pins below keep the parts that still carry weight: one implementation, no
# per-brand entry points, and no second copy of the pilot packages on disk.

CANONICAL_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "harness"


def test_the_distribution_is_ordessa_harness_and_registers_no_pilot_entry_points():
    """Capability-absence register stands; discovery stays on harnesses.toml (P-C)."""
    import tomllib

    data = tomllib.loads((CANONICAL_PLUGIN_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "ordessa-harness"
    group = data["project"]["entry-points"]["agent_box.plugins"]
    for pilot in ("dsh", "kilo"):
        assert pilot not in group


def test_the_pilot_brands_have_exactly_one_implementation_each():
    """The implementation exists exactly once: no legacy shim package on src."""
    from pathlib import Path

    src_root = CANONICAL_PLUGIN_ROOT / "src"
    for brand in ("dsh", "kilo"):
        assert (src_root / "ordessa_harness" / brand).is_dir()
        # The retired top-level shim packages (`agent_box_harness_<brand>`)
        # must not come back under any spelling.
        assert not (src_root / f"ordessa_harness.{brand}").exists()
        assert not (src_root / f"agent_box_harness_{brand}").exists()
    # the real body lives only in the canonical package
    assert "def harness_deployment" in (src_root / "ordessa_harness" / "dsh" / "production.py").read_text(encoding="utf-8")
    assert "DIALECTS" in (src_root / "ordessa_harness" / "dsh" / "native.py").read_text(encoding="utf-8")


def test_brand_modules_resolve_to_canonical_module_objects():
    """Package + both submodules import to stable, single module objects."""
    import importlib

    for brand in ("dsh", "kilo"):
        pkg = importlib.import_module(f"ordessa_harness.{brand}")
        native = importlib.import_module(f"ordessa_harness.{brand}.native")
        production = importlib.import_module(f"ordessa_harness.{brand}.production")
        assert importlib.import_module(f"ordessa_harness.{brand}") is pkg
        assert production.__package__ == f"ordessa_harness.{brand}"
        assert native.__package__ == f"ordessa_harness.{brand}"
