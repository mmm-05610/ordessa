"""T04b — dependency direction: this package installs and works WITHOUT Permissions.

verification.md extra-gate 2: installing Sandbox must not require installing
Permissions. Proven two ways: statically (the source imports nothing outside
the allowed set) and at runtime (importing and driving the package inside a
subprocess whose meta-path blocks `ordessa_permissions*`, `ordessa_server*`,
`ordessa_harness*`, `pacthold` succeeds).
"""
from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from _sandbox_backend_helpers import HARNESSES_TOML

PKG_DIR = Path(__file__).resolve().parents[1] / "src" / "ordessa_sandbox_backend"

FORBIDDEN_ROOTS = {
    "ordessa_server", "ordessa_server_compat",
    "ordessa_harness", "pacthold",
    "ordessa_permissions", "ordessa_permissions_api",
}
ALLOWED_EXTERNAL = {"ordessa_sandbox_api", "server_plugin_api"}


def _imported_roots() -> set[str]:
    roots: set[str] = set()
    files = sorted(PKG_DIR.rglob("*.py"))
    assert files, f"no source files under {PKG_DIR}"
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import stays inside the package
                    continue
                if node.module:
                    roots.add(node.module.split(".")[0])
    return roots


def test_source_imports_only_the_declared_contracts():
    roots = _imported_roots()
    external = {root for root in roots if "." not in root} - {"ordessa_sandbox_backend"}
    stdlib_or_allowed = external - FORBIDDEN_ROOTS
    unknown = {r for r in stdlib_or_allowed
               if r not in ALLOWED_EXTERNAL and r not in sys.stdlib_module_names}
    assert not unknown, f"undeclared external imports: {sorted(unknown)}"
    assert not (roots & FORBIDDEN_ROOTS), sorted(roots & FORBIDDEN_ROOTS)


def test_works_end_to_end_without_permissions_importable():
    """Subprocess: block forbidden modules from importing, then use the package."""
    script = f"""
import sys

class _Blocker:
    BLOCK = {sorted(FORBIDDEN_ROOTS)!r}
    def find_spec(self, name, path=None, target=None):
        head = name.split(".")[0]
        if any(head == b or head.startswith(b) for b in self.BLOCK):
            raise ImportError("simulated absence: %s is not installed" % name)
        return None

sys.path.insert(0, {str(PKG_DIR)!r})
sys.path.insert(0, {str(PKG_DIR.parent)!r})
sys.meta_path.insert(0, _Blocker())

from ordessa_sandbox_backend import (
    SandboxOptionCatalogue, SandboxNativeService, NativeSandboxRepository,
    SandboxVerifier, build_sandbox_plugin,
)
from server_plugin_api import ServerPluginContext

catalogue = SandboxOptionCatalogue.from_repo(harnesses_toml=__import__("pathlib").Path({str(HARNESSES_TOML)!r}))
service = SandboxNativeService(catalogue=catalogue)
result = service.describe("codex", "2.0", platform_os="linux")
assert result.region_visible is True
plugin = build_sandbox_plugin(service)
registration = plugin.build(ServerPluginContext(plugin_id="ordessa.sandbox",
                                                data_root=object()))
assert set(registration.provided_ports) == {{
    "sandbox.native-configuration@1", "sandbox.describe@1"}}
blocked = [m for m in sys.modules if m.split(".")[0] in {sorted(FORBIDDEN_ROOTS)!r}]
print("CLEAN", blocked)
"""
    proc = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "CLEAN []" in proc.stdout


def test_no_pacthold_sandboxv1_names_in_the_package():
    # FR-05: this domain is explicitly NOT the neutral Pacthold execution
    # resource; its identifiers must not leak in as implementations.
    offenders = []
    for path in sorted(PKG_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "SandboxV1" in text or "runtime_composition" in text:
            offenders.append(path.name)
    assert offenders == []


def test_pyproject_declares_exactly_the_two_consumed_dependencies():
    data = tomllib.loads(
        (PKG_DIR.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dependencies"] == [
        "ordessa-sandbox-api", "ordessa-server-plugin-api"]
