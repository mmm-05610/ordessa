"""Native configuration ownership and explicit brand registration gates."""
import ast
import subprocess
import sys
from pathlib import Path

import pytest
from _brand_c2 import BRAND_MODULES, registration_adapters_for

@pytest.mark.parametrize("brand,harness_id", [
    ("pi", "pi"), ("codex", "codex"), ("claude-code", "claude-code"),
])
def test_each_brand_registers_fresh_configuration_implementations(brand, harness_id):
    first = registration_adapters_for(brand)
    second = registration_adapters_for(brand)
    assert len(first) == len(second) == 1
    assert first[0] is not second[0]
    assert first[0].descriptor.harness_id == harness_id
    assert first[0].descriptor.facet_id == "assets.model-provider"


def test_native_implementations_do_not_depend_on_resource_business_packages():
    root = Path(__file__).resolve().parents[4]
    sources = []
    for brand, module in BRAND_MODULES.items():
        brand_path = "claude-code" if brand == "claude-code" else brand
        brand_src = root / "plugins" / "harness" / brand_path / "src" / module
        for module_name in ("c2.py", "live_model.py"):
            candidate = brand_src / "configuration" / module_name
            if candidate.is_file():
                sources.append(candidate)
        if (brand_src / "registration.py").is_file():
            sources.append(brand_src / "registration.py")
    assert sources
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            assert not any(name.startswith((
                "ordessa_model_provider", "ordessa_skills", "ordessa_profile",
                "ordessa_server", "ordessa_server_product",
            )) for name in names), (source, names)


def test_retired_brand_adapter_distribution_has_no_source_entry():
    """032: the retired root harness shell and the retired model-provider
    adapters shim must both stay absent."""
    root = Path(__file__).resolve().parents[4]
    assert not (root / "plugins" / "harness" / "pyproject.toml").exists()
    assert not (root / "plugins/harness/src/ordessa_harness").exists()
    assert not (root / "plugins/agents/resources/model-provider/adapters/pyproject.toml").exists()
    # Ignored egg-info/bytecode may remain locally; no importable source shim.
    retired = root / "plugins/agents/resources/model-provider/adapters/src"
    assert not list(retired.rglob("*.py"))


def test_retired_brand_adapter_import_is_absent_in_a_fresh_source_interpreter():
    result = subprocess.run(
        [sys.executable, "-S", "-c",
         "import importlib.util; "
         "assert importlib.util.find_spec('ordessa_model_provider_adapters') is None"],
        check=False, capture_output=True, text=True,
    )
    # -S excludes historical editable metadata; active source PYTHONPATH stays.
    assert result.returncode == 0, result.stderr
