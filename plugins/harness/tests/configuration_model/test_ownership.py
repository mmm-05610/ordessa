"""Native configuration ownership and explicit brand registration gates."""
import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("brand,harness_id", [
    ("pi", "pi"), ("codex", "codex"), ("claude", "claude-code"),
])
def test_each_brand_registers_fresh_configuration_implementations(brand, harness_id):
    registration = importlib.import_module(f"ordessa_harness.{brand}.registration")
    first = registration.configuration_adapters()
    second = registration.configuration_adapters()
    assert len(first) == len(second) == 1
    assert first[0] is not second[0]
    assert first[0].descriptor.harness_id == harness_id
    assert first[0].descriptor.facet_id == "assets.model-provider"


def test_native_implementations_do_not_depend_on_resource_business_packages():
    harness = Path(importlib.import_module("ordessa_harness").__file__).parent
    sources = list((harness / "configuration" / "model").glob("*.py"))
    for brand in ("pi", "codex", "claude"):
        sources.extend((harness / brand / "configuration").glob("*.py"))
        sources.append(harness / brand / "registration.py")
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
                "ordessa_server",
            )) for name in names), (source, names)


def test_retired_brand_adapter_distribution_has_no_source_entry():
    harness = Path(importlib.import_module("ordessa_harness").__file__).parent
    root = harness.parents[3]
    assert (root / "plugins" / "harness" / "pyproject.toml").is_file()
    assert not (root / "plugins/model-provider/adapters/pyproject.toml").exists()
    # Ignored egg-info/bytecode may remain locally; no importable source shim.
    retired = root / "plugins/model-provider/adapters/src"
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
