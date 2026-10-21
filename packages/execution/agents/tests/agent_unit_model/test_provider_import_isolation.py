"""Fresh installed-interpreter imports, not evidence of native readiness."""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
FAMILIES = {
    "ordessa_harness_pi": "pi",
    "ordessa_harness_codex": "codex",
    "ordessa_harness_claude_code": "claude-code",
}
LEGACY_PREFIXES = (
    "ordessa_harness",
    "pacthold.harness_kit.adapters",
    "pacthold.harness_kit.entrypoints",
)
UNIT_RECORDS = ROOT / "packages/execution/agents/src/ordessa_agents/units/records/unit_records.py"


def probe(family: str, *, extra: str | None = None) -> subprocess.CompletedProcess[str]:
    brand = FAMILIES[family]
    selected_source = ROOT / "plugins/harness" / brand / "src" / family / "__init__.py"
    script = f"""
import importlib
import sys
from pathlib import Path

assert "{family}" not in sys.modules
assert "ordessa_units.records.unit_records" not in sys.modules
selected = importlib.import_module({family!r})
records = importlib.import_module("ordessa_units.records.unit_records")
assert Path(selected.__file__).resolve() == Path({str(selected_source)!r}).resolve()
assert Path(records.__file__).resolve() == Path({str(UNIT_RECORDS)!r}).resolve()
extra = {extra!r}
if extra:
    importlib.import_module(extra)
assert {family!r} in sys.modules, "selected provider package was not imported"
for name in {tuple(FAMILIES)!r}:
    if name != {family!r}:
        assert not any(module == name or module.startswith(name + ".")
                       for module in sys.modules), "forbidden family imported: " + name
assert not any(module == "ordessa_cli.native_clients"
               or module.startswith("ordessa_cli.native_clients.")
               for module in sys.modules), "product native client imported"
for prefix in {LEGACY_PREFIXES!r}:
    assert not any(module == prefix or module.startswith(prefix + ".")
                   for module in sys.modules), "legacy aggregate/module imported: " + prefix
"""
    return subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("family", tuple(FAMILIES))
def test_only_selected_family_imported_with_existing_unit_journal(family):
    result = probe(family)
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_guard_really_rejects_another_family():
    selected, other = tuple(FAMILIES)[:2]
    result = probe(selected, extra=other)
    assert result.returncode == 1 and "forbidden family imported" in result.stderr
