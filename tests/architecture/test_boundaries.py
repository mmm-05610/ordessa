from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_SRC = Path(__file__).resolve().parents[2] / 'packages/execution/agents' / "src" / "ordessa_agents" / "harness"
FORBIDDEN = (
    "pacthold." + "launch",
    "pacthold.work_core." + "providers.resources",
    "pacthold." + "resources",
    "pacthold." + "application",
    "pacthold." + "server",
    "agent_box_" + "web",
)


def test_harness_source_has_no_legacy_or_web_imports():
    sources = sorted(HARNESS_SRC.rglob("*.py"))
    assert HARNESS_SRC.is_dir() and sources, "actual Agents Harness source must exist"
    violations = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN:
            if forbidden in text:
                violations.append(f"{path}: {forbidden}")
    assert violations == []


def test_codex_launch_spec_is_harness_owned():
    launch = (REPO_ROOT / "plugins/harness/codex/src/ordessa_harness_codex/launch.py").read_text(encoding="utf-8")
    assert "class CodexLaunchSpec" in launch
    assert "LaunchPlan" not in launch
