"""specs/010 T009 bare-core scan: every kernel module imports without the assembly.

FR-011 / SC-001 (A面): a kernel-only installation must import *all* of
``pacthold.*`` with no business distribution present.  The scan runs in a
fresh interpreter with an import blocker installed for ``pacthold_runtime_compat``
and its submodules, then walks every module via ``pkgutil``.  A core module
that hard-depends on the assembly (transitively included) turns the run red;
the tripwire test plants exactly such a module to prove the scan is real.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROBE_MODULE = PACKAGE_ROOT / "src" / "pacthold" / "_t009_import_tripwire.py"

_SCAN_SCRIPT = r"""
import importlib, json, pkgutil, sys

class CompatBlocker:
    # Meta-path hook: any attempt to import the assembly is a failure.
    def find_spec(self, name, path=None, target=None):
        if name == "pacthold_runtime_compat" or name.startswith("pacthold_runtime_compat."):
            raise ImportError(f"bare-core scan: reverse dependency blocked: {name}")
        return None

sys.meta_path.insert(0, CompatBlocker())

import pacthold

modules = [pacthold.__name__]
for info in pkgutil.walk_packages(pacthold.__path__, prefix="pacthold."):
    modules.append(info.name)

failures = []
for name in sorted(set(modules)):
    try:
        importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - the scan reports, never hides
        failures.append({"module": name, "error": f"{type(exc).__name__}: {exc}"})

loaded_compat = sorted(k for k in sys.modules if k == "pacthold_runtime_compat" or k.startswith("pacthold_runtime_compat."))
print(json.dumps({"count": len(set(modules)), "failures": failures, "compat_loaded": loaded_compat}))
sys.exit(1 if failures or loaded_compat else 0)
"""


def _run_scan() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _SCAN_SCRIPT],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _scan_result(proc: subprocess.CompletedProcess) -> dict:
    assert proc.returncode in (0, 1), f"scan interpreter crashed: {proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_bare_core_import_scan_passes_with_compat_blocked():
    proc = _run_scan()
    assert proc.returncode == 0, (
        f"bare-core import scan failed:\n{proc.stdout}\n{proc.stderr}"
    )
    result = _scan_result(proc)
    assert result["failures"] == []
    assert result["compat_loaded"] == []
    # The kernel has ~40 modules after T009; refuse a scan that walked nothing.
    assert result["count"] >= 35, f"unexpectedly small module walk: {result}"


def test_tripwire_planted_compat_dependency_turns_the_scan_red():
    """Counterexample self-test: a core module importing the assembly must
    make the bare-core scan fail — and go green again once removed."""
    PROBE_MODULE.write_text(
        "import pacthold_runtime_compat  # planted tripwire, never persist\n",
        encoding="utf-8",
    )
    try:
        proc = _run_scan()
        assert proc.returncode == 1, (
            "the bare-core scan did not detect a planted reverse dependency — "
            "it would be vacuously green"
        )
        result = _scan_result(proc)
        assert any("t009_import_tripwire" in f["module"] for f in result["failures"]), result
    finally:
        PROBE_MODULE.unlink(missing_ok=True)
    proc = _run_scan()
    assert proc.returncode == 0, "scan must go green again after the probe is removed"


def test_kernel_public_facade_imports_standalone():
    """``pacthold.public`` (C1) is the product entry; it must import without
    pulling the assembly chain (same guard as T004's facade test, re-pinned
    here for the T009 module map)."""
    proc = subprocess.run(
        [sys.executable, "-c", "import pacthold.public; import pacthold.extensions; "
         "import pacthold.storage; print('ok')"],
        capture_output=True,
        text=True,
        env=None,
    )
    assert proc.returncode == 0 and proc.stdout.strip() == "ok", proc.stderr
