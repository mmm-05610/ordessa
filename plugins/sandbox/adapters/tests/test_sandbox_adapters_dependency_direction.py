"""T05b — dependency direction: this package installs and works WITHOUT Permissions.

The Sandbox adapters import the consumed Sandbox contracts, the public Server
plugin surface and — since the foundation checkpoint — the Harness C2
*descriptive* vocabulary (`ordessa_harness_api.contracts/.schema`), exactly the
closure the platform's own third-party contributor fixture declares
(`plugins/harness/tests/fixtures/external_adapter`). Harness package CODE
(`ordessa_harness`), the Server host, pacthold and Permissions stay forbidden
in src (verification.md extra-gate 2): `harnesses.toml` is located with
`importlib.util.find_spec`, which never executes harness code.
"""
from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[1] / "src" / "ordessa_sandbox_adapters"

FORBIDDEN_ROOTS = {
    "ordessa_server", "ordessa_server_compat", "ordessa_server_plugin_api",
    "ordessa_harness", "pacthold",
    "ordessa_permissions", "ordessa_permissions_api", "ordessa_permissions_backend",
    "ordessa_permissions_adapters",
}
ALLOWED_EXTERNAL = {"ordessa_sandbox_api", "ordessa_sandbox_backend",
                    "server_plugin_api", "ordessa_harness_api"}


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
                if node.level:
                    continue
                if node.module:
                    roots.add(node.module.split(".")[0])
    return roots


def test_source_imports_only_the_declared_contracts():
    roots = _imported_roots()
    external = {r for r in roots if "." not in r} - {"ordessa_sandbox_adapters"}
    unknown = {r for r in external - FORBIDDEN_ROOTS
               if r not in ALLOWED_EXTERNAL and r not in sys.stdlib_module_names}
    assert not unknown, f"undeclared external imports: {sorted(unknown)}"
    assert not (roots & FORBIDDEN_ROOTS), sorted(roots & FORBIDDEN_ROOTS)


def test_works_end_to_end_without_permissions_or_harness_code_importable():
    script = f"""
import sys, tomllib
from pathlib import Path

class _Blocker:
    BLOCK = {sorted(FORBIDDEN_ROOTS)!r}
    def find_spec(self, name, path=None, target=None):
        head = name.split(".")[0]
        # exact-root match: ordessa_harness_api is the allowed C2 edge,
        # ordessa_harness (harness CODE) and its submodules are not
        if any(head == b or head.startswith(b + ".") for b in self.BLOCK):
            raise ImportError("simulated absence: %s" % name)
        return None

sys.meta_path.insert(0, _Blocker())
from ordessa_sandbox_adapters import (
    ClaudeSandboxAdapter,
    CodexSandboxAdapter,
    PiSandboxAdapter,
    SANDBOX_CONFIGURATION_POINT_ID,
    SandboxAdaptersServerPlugin,
    build_configuration_batch,
    build_configuration_descriptor,
)
from server_plugin_api import ServerPluginContext

# harnesses.toml read WITHOUT harness code: the caller supplies the measured
# pins (the file is located relative to this package checkout).
toml = Path({str(PKG_DIR.parents[4] / 'harness' / 'src' / 'ordessa_harness' / 'harnesses.toml')!r})
pins = {{h["identity"]["harness_type"]: h["identity"]["version"]
          for h in tomllib.loads(toml.read_text(encoding="utf-8"))["harness"]}}
adapters = (CodexSandboxAdapter(), ClaudeSandboxAdapter(), PiSandboxAdapter())
for adapter in adapters:
    descriptor = build_configuration_descriptor(adapter, pins=pins)
    assert descriptor.harness_id in pins
batch = build_configuration_batch(adapters, pins=pins)
assert len(batch.contributions) == 3
plugin = SandboxAdaptersServerPlugin(pins=pins)
registration = plugin.build(ServerPluginContext(plugin_id="x", data_root=object()))
assert {{c.point_id for c in registration.contributions.contributions}} == {{SANDBOX_CONFIGURATION_POINT_ID}}
blocked = [m for m in sys.modules if m.split(".")[0] in {sorted(FORBIDDEN_ROOTS)!r}]
print("CLEAN", blocked)
"""
    proc = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "CLEAN []" in proc.stdout


def test_pyproject_declares_exactly_the_consumed_dependencies():
    import re
    data = tomllib.loads(
        (PKG_DIR.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    names = {re.split(r"[<>=!~;\[ ]", item, maxsplit=1)[0].strip()
             for item in data["project"]["dependencies"]}
    assert names == {
        "ordessa-sandbox-api", "ordessa-sandbox-backend",
        "ordessa-server-plugin-api", "ordessa-harness-api"}
