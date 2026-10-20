"""Static migration guards (source-level; not a substitute for runtime tests)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT.parents[2] / "plugins/decision"


def _sources(path):
    return [p for p in Path(path).rglob("*.py") if "__pycache__" not in p.parts]


def test_no_retired_contracts_imports_remain_in_owned_sources():
    offenders = []
    for path in _sources(ROOT / "src") + _sources(PLUGINS):
        text = path.read_text()
        if "decision_runtime.contracts" in text:
            offenders.append(str(path))
    assert offenders == []


def test_new_runner_lives_under_the_frozen_import_root():
    assert (ROOT / "src" / "decision_runtime" / "runner.py").is_file()
    assert not (ROOT / "src" / "ordessa_decision").exists()


def test_capability_imports_only_the_independent_contracts_package():
    text = (ROOT / "src" / "decision_runtime" / "capability.py").read_text()
    assert "ordessa_interfaces_contracts" in text
    assert "from ordessa_interfaces " not in text
    assert "import ordessa_interfaces\n" not in text


def test_jev_provider_uses_the_final_definitions_and_ports():
    text = (PLUGINS / "jev/src/ordessa_decision_jev/provider.py").read_text()
    assert "decision_runtime.definitions.models" in text
    assert "decision_runtime.ports" in text
    assert "decision_runtime.definitions.values" in text
