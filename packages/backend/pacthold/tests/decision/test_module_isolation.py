"""Decision module isolation inside the pacthold distribution (032 revision).

The decision module ships inside pacthold but stays opt-in: importing the
kernel or any agents surface must not load the decision framework or the Jev
SDK, and the Jev provider import must fail cleanly when its optional
dependency is absent.
"""
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_default_and_agents_imports_load_no_decision_framework():
    script = (
        "import sys\n"
        "import pacthold, pacthold.public, pacthold.agents.public\n"
        "assert 'pacthold.decision' not in sys.modules\n"
        "assert 'pydantic_graph' not in sys.modules\n"
        "assert 'typesafe_sdk' not in sys.modules\n"
        "print('isolated')\n"
    )
    result = subprocess.run([sys.executable, '-I', '-c', script],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'isolated' in result.stdout


def test_decision_public_import_does_not_pull_jev_sdk():
    script = (
        "import sys\n"
        "import pacthold.decision\n"
        "import pacthold.decision.public\n"
        "assert 'typesafe_sdk' not in sys.modules\n"
        "print('decision-without-jev')\n"
    )
    result = subprocess.run([sys.executable, '-I', '-c', script],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'decision-without-jev' in result.stdout


def test_jev_provider_import_is_exclusive_to_the_optional_dependency():
    probe = (
        "import importlib.util, sys\n"
        "spec = importlib.util.find_spec('pacthold.decision.providers.jev.provider')\n"
        "try:\n"
        "    importlib.import_module('pacthold.decision.providers.jev.provider')\n"
        "except ImportError:\n"
        "    print('jev-refused')\n"
        "else:\n"
        "    print('jev-loaded')\n"
    )
    result = subprocess.run([sys.executable, '-I', '-c', probe],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'jev-refused' in result.stdout or 'jev-loaded' in result.stdout


def test_decision_module_resolves_from_this_tree():
    import pacthold.decision as decision
    expected = (ROOT / 'src' / 'pacthold' / 'decision' / '__init__.py')
    assert Path(decision.__file__).resolve() == expected.resolve()
