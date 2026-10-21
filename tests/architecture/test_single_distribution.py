"""One distribution, one importable package: `ordessa-execution-agents` / `ordessa_agents.harness`.

History: the old repository consolidated several distributions behind
import-only alias packages (`agent_box_harnesses`, `agent_box_harness_dsh`,
`_qwen`, `_kilo`). The monorepo baseline retires those alias packages with the
old layout, so what is pinned now is the property they existed to guarantee:
no second registry, no second copy of any class, and no silently created
modules — with the canonical names being the only names.
"""
import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

BRAND_MODULES = {"dsh": "ordessa_harness_dsh", "kilo": "ordessa_harness_kilo"}


def test_every_module_is_canonical_no_alias_machinery_is_present():
    """Importing every module of the package twice (fresh processes) is stable,
    and the retired alias names must NOT resolve to anything."""
    script = '''
import importlib
from pathlib import Path
import ordessa_agents.harness
root = Path(ordessa_agents.harness.__file__).parent
names = []
sources = sorted(root.rglob("*.py"))
assert sources, "actual Agents source must be nonempty"
for source in sources:
    relative = source.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or parts[0].startswith("_"):
        continue
    names.append(".".join(parts))
for suffix in sorted(names):
    module = importlib.import_module("ordessa_agents.harness." + suffix)
    assert module.__spec__.name == "ordessa_agents.harness." + suffix, (suffix, module.__spec__)
import sys
for legacy in ("pacthold.harness_kit", "agent_box_harnesses", "agent_box_harness", "agent_box_harness_dsh",
               "agent_box_harness_qwen", "agent_box_harness_kilo"):
    assert legacy not in sys.modules, legacy
    try:
        importlib.import_module(legacy)
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError("retired alias package is importable again: " + legacy)
print("all modules canonical; retired aliases absent")
'''
    result = subprocess.run([sys.executable, "-c", script], env=os.environ.copy(),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_unknown_module_is_not_silently_created():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ordessa_agents.harness.not_a_real_module")


def test_shared_adapter_exports_are_preserved():
    from ordessa_server_product.harness_adapters.adapters import HarnessAdapter, GenericCliAdapter
    from ordessa_server_product.harness_adapters.adapters.base import HarnessAdapter as protocol
    from ordessa_server_product.harness_adapters.adapters.generic_cli import GenericCliAdapter as defining
    # The package facade and the defining module must agree object-for-object.
    assert HarnessAdapter is protocol
    assert GenericCliAdapter is defining


def test_dsh_kilo_assets_use_the_single_plugin_root():
    root = Path(__file__).resolve().parents[2] / 'plugins' / 'harness'
    for brand in ("dsh", "kilo"):
        production = importlib.import_module(BRAND_MODULES[brand] + ".production")
        assert production.PLUGIN_ROOT == root
        assert (root / "deploy" / brand).is_dir()
