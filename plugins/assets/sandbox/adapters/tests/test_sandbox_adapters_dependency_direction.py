"""T05b — dependency direction: this package installs and works WITHOUT Permissions.

The Sandbox adapters import the consumed Sandbox contracts, the public Server
plugin surface and — since the foundation checkpoint — the Harness C2
*descriptive* vocabulary (`pacthold.harness_contracts.contracts/.schema`), exactly the
closure the platform's own third-party contributor fixture declares
(`plugins/harness/tests/fixtures/external_adapter`). Harness package CODE
(`pacthold.harness_kit`), the Server host, pacthold and Permissions stay forbidden
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
    "pacthold.harness_kit", "pacthold",
    "ordessa_permissions", "ordessa_permissions_api", "ordessa_permissions_backend",
    "ordessa_permissions_adapters",
}
ALLOWED_EXTERNAL = {"ordessa_sandbox_api", "ordessa_sandbox_backend",
                    "server_plugin_api", "pacthold.harness_contracts"}


KERNEL_GRANTS = {"pacthold.harness_contracts"}


def _imported_roots() -> set[str]:
    """Top-level roots plus the exact dotted modules under a forbidden root."""
    roots: set[str] = set()
    files = sorted(PKG_DIR.rglob("*.py"))
    assert files, f"no source files under {PKG_DIR}"
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                if node.module:
                    roots.add(node.module)
    return roots


def _licensed(module: str) -> bool:
    return any(module == g or module.startswith(g + ".") for g in KERNEL_GRANTS)


def test_source_imports_only_the_declared_contracts():
    modules = _imported_roots()
    tops = {m.split(".")[0] for m in modules}
    external = {r for r in tops if r != "ordessa_sandbox_adapters"}
    unknown = {r for r in external - FORBIDDEN_ROOTS
               if r not in ALLOWED_EXTERNAL and r not in sys.stdlib_module_names}
    assert not unknown, f"undeclared external imports: {sorted(unknown)}"
    forbidden_tops = tops & FORBIDDEN_ROOTS
    # a forbidden root is tolerated only when every concrete import under it
    # carries an exact dotted grant (the kernel contract edge)
    if forbidden_tops:
        unlicensed = [m for m in modules
                      if m.split(".")[0] in forbidden_tops and not _licensed(m)]
        assert not unlicensed, f"imports under a forbidden root without a grant: {unlicensed}"


def test_works_end_to_end_without_permissions_or_harness_code_importable():
    script = f"""
import sys, tomllib
from pathlib import Path

class _Blocker:
    BLOCK = {sorted(FORBIDDEN_ROOTS)!r}
    GRANTS = {sorted(KERNEL_GRANTS)!r}
    def find_spec(self, name, path=None, target=None):
        head = name.split(".")[0]
        # exact-root match: the dotted kernel contract grant stays importable,
        # pacthold.harness_kit (harness CODE), permissions and the rest are not
        # a grant licenses its own dotted path and the parent chain needed to
        # import it; everything else under the blocked root stays blocked
        if any(name == g or name.startswith(g + ".") or g.startswith(name + ".")
               for g in self.GRANTS):
            return None
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
toml = Path({str(PKG_DIR.parents[5] / 'packages' / 'backend' / 'pacthold' / 'src' / 'pacthold' / 'harness_kit' / 'harnesses.toml')!r})
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
granted = {tuple(sorted(KERNEL_GRANTS))!r}
blocked = [m for m in sys.modules
           if m.split(".")[0] in {sorted(FORBIDDEN_ROOTS)!r}
           and not any(m == g or m.startswith(g + ".") or g.startswith(m + ".")
                       for g in granted)]
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
