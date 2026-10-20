"""Controlled context tests: actual declarations, no build/model/service execution."""
from pathlib import Path
from functools import partial
import importlib
import importlib.util
import pytest
from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
from ordessa_server.composition.native_channels.selected_installation_ports import captured_installation_recipes
from ordessa_execution_agents.harness.providers.declarations.capability_claims import capability_claims
from ordessa_execution_agents.harness.providers.declarations.installation_recipe import BuildRecipeFiles

ROOT = Path(__file__).resolve().parents[2]
BRANDS = ("codex", "claude-code", "opencode", "hermes", "dsh", "kilo", "pi")

def context(owner_id, *, requires_npm):
    own = ROOT / "plugins/harness" / owner_id / "tooling"
    return BuildRecipeFiles(owner_id, own / "build-runtime-artifact.mjs", own / "npm" if requires_npm else None)

def test_actual_selected_recipes_keep_same_capture_order_and_callable_facts():
    captured = capture_selected_harness_catalog()
    recipes = captured_installation_recipes(captured, build_files_for=context)
    assert tuple(recipe.owner_id for recipe in recipes) == BRANDS
    for recipe in recipes:
        assert recipe.builder.is_file()
        assert callable(recipe.deployment_document)
        assert recipe.deployment_document.keywords["capabilities_for"].args[0] is captured.registry
        assert recipe.npm_root is None if recipe.owner_id == "hermes" else recipe.npm_root.is_dir()

@pytest.mark.parametrize("brand", BRANDS)
def test_installed_public_port_requires_context_not_its_module_location(brand, tmp_path):
    port = importlib.import_module("ordessa_harness_" + brand.replace("-", "_") + ".installation_declarations")
    captured = capture_selected_harness_catalog()
    callback = partial(capability_claims, captured.registry)
    with pytest.raises(TypeError):
        port.installation_declaration(capabilities_for=callback)
    with pytest.raises(TypeError, match="explicit BuildRecipeFiles"):
        port.installation_declaration(capabilities_for=callback, build_files=None)
    with pytest.raises(ValueError, match="INSTALLATION_BUILD_OWNER_MISMATCH"):
        port.installation_declaration(capabilities_for=callback, build_files=BuildRecipeFiles("foreign", tmp_path / "missing", None))
    with pytest.raises(ValueError, match="INSTALLATION_BUILDER_MISSING"):
        port.installation_declaration(capabilities_for=callback, build_files=BuildRecipeFiles(brand, tmp_path / "missing", None))
    with pytest.raises(ValueError, match="INSTALLATION_BUILD_PATH_INVALID"):
        port.installation_declaration(capabilities_for=callback, build_files=BuildRecipeFiles(brand, Path("relative"), None))
    # Simulate an installed provider location: supplied actual source context,
    # not __file__, determines the recipe paths.
    original = port.__file__
    try:
        port.__file__ = str(tmp_path / "site-packages" / "provider.py")
        recipe = port.installation_declaration(capabilities_for=callback, build_files=context(brand, requires_npm=port.installation_requires_npm()))
        assert recipe.builder == context(brand, requires_npm=port.installation_requires_npm()).builder
    finally:
        port.__file__ = original

def test_context_missing_npm_inputs_fail_closed(tmp_path):
    builder = tmp_path / "builder.mjs"
    builder.write_text("// controlled path fixture only; never executed")
    missing = tmp_path / "npm"
    files = BuildRecipeFiles("owner", builder, missing)
    with pytest.raises(ValueError, match="INSTALLATION_NPM_ROOT_MISSING"):
        files.require(owner_id="owner", requires_npm=True)
    missing.mkdir()
    with pytest.raises(ValueError, match="INSTALLATION_NPM_INPUT_MISSING"):
        files.require(owner_id="owner", requires_npm=True)
    with pytest.raises(ValueError, match="INSTALLATION_UNEXPECTED_NPM_ROOT"):
        files.require(owner_id="owner", requires_npm=False)

def test_host_selection_requires_explicit_context_callback():
    with pytest.raises(TypeError):
        captured_installation_recipes(capture_selected_harness_catalog())
    with pytest.raises(TypeError, match="explicit build-files callback"):
        captured_installation_recipes(capture_selected_harness_catalog(), build_files_for=None)
