"""Distribution-level checks for the optional Jev provider boundary."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
JEV_SOURCE = ROOT / "plugins/decision/jev/src/ordessa_decision_jev"
RUNTIME_SOURCE = ROOT / "packages/execution/decision/src/decision_runtime"


def _run_isolated(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_provider_import_matches_explicit_install_mode_without_host_imports():
    script = f"""
import importlib
import json
import os
from pathlib import Path
import sys
import sysconfig

assert "ordessa_decision_jev" not in sys.modules
assert "decision_runtime" not in sys.modules

class HostImportBlocked(ImportError):
    pass

class HostImportBlocker:
    blocked = {{"pacthold", "ordessa_server", "ordessa_harness", "apps", "products",
                "ordessa_units", "ordessa_execution_agents", "ordessa_environments"}}
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.partition(".")[0]
        if root in self.blocked:
            raise HostImportBlocked("blocked host import: " + fullname)
        return None

sys.meta_path.insert(0, HostImportBlocker())
provider = importlib.import_module("ordessa_decision_jev.provider")
runtime = importlib.import_module("decision_runtime")
mode = os.environ.get("DECISION_PROVIDER_INSTALL_MODE", "editable")
if mode == "editable":
    expected_provider = Path({str(JEV_SOURCE / 'provider.py')!r}).resolve()
    expected_runtime = Path({str(RUNTIME_SOURCE / '__init__.py')!r}).resolve()
elif mode == "wheel":
    from importlib.metadata import distribution
    jev_distribution = distribution("ordessa-decision-jev")
    runtime_distribution = distribution("decision-runtime")
    expected_provider = Path(jev_distribution.locate_file(
        "ordessa_decision_jev/provider.py"
    )).resolve()
    expected_runtime = Path(runtime_distribution.locate_file(
        "decision_runtime/__init__.py"
    )).resolve()
    assert expected_provider.is_file(), expected_provider
    assert expected_runtime.is_file(), expected_runtime
    purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
    assert expected_provider.is_relative_to(purelib), expected_provider
    assert expected_runtime.is_relative_to(purelib), expected_runtime
    assert "site-packages" in expected_provider.parts, expected_provider
    assert "site-packages" in expected_runtime.parts, expected_runtime
    for installed_distribution in (jev_distribution, runtime_distribution):
        direct_url = installed_distribution.read_text("direct_url.json")
        details = json.loads(direct_url) if direct_url else {{}}
        assert not details.get("dir_info", {{}}).get("editable", False), installed_distribution.name
else:
    raise AssertionError("unknown DECISION_PROVIDER_INSTALL_MODE: " + mode)
assert Path(provider.__file__).resolve() == expected_provider
assert Path(runtime.__file__).resolve() == expected_runtime
assert not any(name == "pacthold" or name.startswith("pacthold.") for name in sys.modules)
assert not any(name == "ordessa_server" or name.startswith("ordessa_server.") for name in sys.modules)
assert not any(name == "apps" or name.startswith("apps.") for name in sys.modules)
assert not any(name == "products" or name.startswith("products.") for name in sys.modules)
assert not any(name.partition('.')[0] in {{'ordessa_units', 'ordessa_execution_agents',
                                       'ordessa_environments'}} for name in sys.modules)
assert "ordessa_decision_jev.provider" in sys.modules
print("installed-jev-provider-isolated")
"""
    result = _run_isolated(script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "installed-jev-provider-isolated" in result.stdout


def test_host_import_blocker_rejects_a_planted_import():
    # This inline tripwire proves the same meta_path guard used by the real
    # distribution check actually turns a forbidden import into a failure.
    script = """
import importlib
import sys

class HostImportBlocked(ImportError):
    pass

class HostImportBlocker:
    blocked = {"pacthold", "ordessa_server", "ordessa_harness", "apps", "products",
               "ordessa_units", "ordessa_execution_agents", "ordessa_environments"}
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in self.blocked:
            raise HostImportBlocked(fullname)
        return None

sys.meta_path.insert(0, HostImportBlocker())
for root in ('pacthold', 'ordessa_units', 'ordessa_execution_agents', 'ordessa_environments'):
    try:
        importlib.import_module(root + '.public')
    except HostImportBlocked as error:
        assert error.args == (root,)
    else:
        raise AssertionError("the host-import blocker did not reject " + root)
print("planted-host-import-blocked")
"""
    result = _run_isolated(script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "planted-host-import-blocked" in result.stdout
