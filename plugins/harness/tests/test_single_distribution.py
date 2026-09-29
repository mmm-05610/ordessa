"""One distribution, one importable package: `ordessa-harness` / `ordessa_harness`.

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


def test_every_module_is_canonical_no_alias_machinery_is_present():
    """Importing every module of the package twice (fresh processes) is stable,
    and the retired alias names must NOT resolve to anything."""
    script = '''
import importlib
from pathlib import Path
import ordessa_harness
root = Path(ordessa_harness.__file__).parent
names = []
for source in root.rglob("*.py"):
    relative = source.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or parts[0].startswith("_"):
        continue
    names.append(".".join(parts))
for suffix in sorted(names):
    module = importlib.import_module("ordessa_harness." + suffix)
    assert module.__spec__.name == "ordessa_harness." + suffix, (suffix, module.__spec__)
import sys
for legacy in ("agent_box_harnesses", "agent_box_harness", "agent_box_harness_dsh",
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
        importlib.import_module("ordessa_harness.not_a_real_module")


def test_shared_adapter_exports_are_preserved():
    from ordessa_harness.adapters import HarnessAdapter, GenericCliAdapter
    from ordessa_harness.adapters.base import HarnessAdapter as protocol
    from ordessa_harness.adapters.generic_cli import GenericCliAdapter as defining
    # The package facade and the defining module must agree object-for-object.
    assert HarnessAdapter is protocol
    assert GenericCliAdapter is defining


def test_dsh_kilo_assets_use_the_single_plugin_root():
    root = Path(__file__).resolve().parents[1]
    for brand in ("dsh", "kilo"):
        production = importlib.import_module("ordessa_harness." + brand + ".production")
        assert production.PLUGIN_ROOT == root
        assert (root / "deploy" / brand).is_dir()
