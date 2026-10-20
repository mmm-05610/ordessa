"""The Agent kernel stays independent from the neutral Decision distribution."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SRC = ROOT / 'packages/execution/decision/src'
PACTHOLD_ROOT = ROOT / 'packages/execution/kernel'


def test_default_and_agents_imports_load_no_decision_framework():
    script = (
        "import sys\n"
        "import pacthold, pacthold.public, ordessa_execution_agents.public\n"
        "assert 'decision_runtime' not in sys.modules\n"
        "assert 'pacthold.decision' not in sys.modules\n"
        "assert 'pydantic_graph' not in sys.modules\n"
        "assert 'typesafe_sdk' not in sys.modules\n"
        "print('isolated')\n"
    )
    result = subprocess.run([sys.executable, '-I', '-c', script],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'isolated' in result.stdout


def test_neutral_runtime_import_does_not_pull_pacthold_or_jev_sdk():
    script = (
        f"import sys; sys.path.insert(0, {str(RUNTIME_SRC)!r})\n"
        "import decision_runtime\n"
        "assert not any(name == 'pacthold' or name.startswith('pacthold.') for name in sys.modules)\n"
        "assert 'typesafe_sdk' not in sys.modules\n"
        "print('neutral-runtime-without-host-or-jev')\n"
    )
    result = subprocess.run([sys.executable, '-I', '-c', script],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'neutral-runtime-without-host-or-jev' in result.stdout


def test_jev_provider_import_is_exclusive_to_the_optional_dependency():
    # The neutral runtime has no optional-provider namespace. Importing that
    # retired path must fail precisely, regardless of whether Jev is installed.
    probe = (
        f"import importlib, sys; sys.path.insert(0, {str(RUNTIME_SRC)!r})\n"
        "import decision_runtime\n"
        "assert 'typesafe_sdk' not in sys.modules\n"
        "for name in ('decision_runtime.providers', 'decision_runtime.providers.jev'):\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except ModuleNotFoundError as error:\n"
        "        assert error.name in (name, 'decision_runtime.providers'), (name, error.name)\n"
        "    else:\n"
        "        raise AssertionError('retired provider path imported: ' + name)\n"
        "print('retired-provider-paths-unavailable')\n"
    )
    result = subprocess.run([sys.executable, '-I', '-c', probe],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'retired-provider-paths-unavailable' in result.stdout


def test_no_neutral_forwarding_modules_remain_in_pacthold():
    script = (
        f"import importlib.util, sys; sys.path.insert(0, {str(PACTHOLD_ROOT / 'src')!r})\n"
        "import pacthold.decision\n"
        "for name in ('pacthold.decision.public','pacthold.decision.contracts',"
        "'pacthold.decision.runtime','pacthold.decision.evidence','pacthold.decision.providers'):\n"
        "    if importlib.util.find_spec(name) is not None: raise AssertionError('retired neutral path remains: '+name)\n"
    )
    result = subprocess.run([sys.executable, '-I', '-c', script],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
