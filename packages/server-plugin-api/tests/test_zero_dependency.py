"""C2 zero-runtime-dependency proof: the package imports with no product code.

Two real subprocess interpreters check it: one audits `sys.modules` and
installs a meta-path sentinel that fires if any forbidden top-level
module even reaches the import system; the other plants stub packages
named `pacthold`, `ordessa_server` and `ordessa_harness` first on
`sys.path` — each stub records its own import to a marker file — and
asserts no marker appears after importing `server_plugin_api`. The
second test also proves the recording mechanism itself works, so a
future accidental import cannot pass by the stubs being unreachable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

FORBIDDEN_ROOTS = ("pacthold", "ordessa_server", "ordessa_harness")


def test_importing_the_package_pulls_in_no_product_modules():
    code = textwrap.dedent("""
        import json, sys

        violations = []

        class _ImportSentinel:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in %r:
                    violations.append(name)
                    raise AssertionError("forbidden import reached the finder: " + name)
                return None

        sys.meta_path.insert(0, _ImportSentinel())

        import server_plugin_api
        import server_plugin_api.contributions

        forbidden_loaded = sorted(
            root for root in %r if any(
                name == root or name.startswith(root + ".") for name in sys.modules))
        print(json.dumps({"forbidden_loaded": forbidden_loaded,
                          "violations": violations,
                          "api_version": server_plugin_api.SERVER_PLUGIN_API_VERSION}))
    """ % (FORBIDDEN_ROOTS, FORBIDDEN_ROOTS))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["forbidden_loaded"] == []
    assert report["violations"] == []
    assert report["api_version"] == 1


def test_planted_product_stubs_are_never_reached_by_the_import(tmp_path):
    stub_root = tmp_path / "stubs"
    stub_root.mkdir()
    markers = tmp_path / "markers"
    markers.mkdir()
    recorded = []
    for name in FORBIDDEN_ROOTS:
        package = stub_root / name
        package.mkdir()
        marker = markers / name
        (package / "__init__.py").write_text(
            f"open({str(marker)!r}, 'w').write('imported')\n")
        recorded.append(str(marker))

    env = {**os.environ, "PYTHONPATH": str(stub_root) + os.pathsep
           + env_pth()}
    code = textwrap.dedent(f"""
        import json, os, sys
        import server_plugin_api
        import server_plugin_api.contributions
        print(json.dumps({{path: os.path.exists(path) for path in {recorded!r}}}))
    """)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, timeout=60, env=env)
    assert result.returncode == 0, result.stderr
    touched = json.loads(result.stdout.strip().splitlines()[-1])
    assert set(touched) == set(recorded)
    assert not any(touched.values()), (
        f"the package imported planted product stubs: {touched}")


def test_the_planted_stub_mechanism_records_a_real_import(tmp_path):
    """Counterexample control for the test above: importing a planted stub
    from the same mechanism does write its marker, so an absence proof is
    not an artefact of an unreachable path entry."""
    stub_root = tmp_path / "stubs"
    package = stub_root / "pacthold"
    package.mkdir(parents=True)
    marker = tmp_path / "pacthold-marker"
    (package / "__init__.py").write_text(
        f"open({str(marker)!r}, 'w').write('imported')\n")
    code = (f"import sys; sys.path.insert(0, {str(stub_root)!r}); "
            "import pacthold")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert marker.exists(), "the stub recording mechanism itself is broken"


def env_pth() -> str:
    """Keep the interpreter's own package resolution intact when a test
    overrides PYTHONPATH: inherit whatever the current process already
    resolves against (venv site-packages included)."""
    return os.environ.get("PYTHONPATH", "")
