"""Independent provider wheels remain installable without a root aggregate."""

import configparser
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[5]
BRAND_WHEELS = (
    ("plugins/harness/claude-code", "ordessa-harness-claude-code", "ordessa_harness_claude_code"),
    ("plugins/harness/codex", "ordessa-harness-codex", "ordessa_harness_codex"),
    ("plugins/harness/copilot", "ordessa-harness-copilot", "ordessa_harness_copilot"),
    ("plugins/harness/dsh", "ordessa-harness-dsh", "ordessa_harness_dsh"),
    ("plugins/harness/gemini_cli", "ordessa-harness-gemini-cli", "ordessa_harness_gemini_cli"),
    ("plugins/harness/goose", "ordessa-harness-goose", "ordessa_harness_goose"),
    ("plugins/harness/grok-build", "ordessa-harness-grok-build", "ordessa_harness_grok_build"),
    ("plugins/harness/hermes", "ordessa-harness-hermes", "ordessa_harness_hermes"),
    ("plugins/harness/kilo", "ordessa-harness-kilo", "ordessa_harness_kilo"),
    ("plugins/harness/kimi", "ordessa-harness-kimi", "ordessa_harness_kimi"),
    ("plugins/harness/opencode", "ordessa-harness-opencode", "ordessa_harness_opencode"),
    ("plugins/harness/pi", "ordessa-harness-pi", "ordessa_harness_pi"),
    ("plugins/harness/qoder", "ordessa-harness-qoder", "ordessa_harness_qoder"),
    ("plugins/harness/qwen", "ordessa-harness-qwen", "ordessa_harness_qwen"),
    ("plugins/harness/vibe", "ordessa-harness-vibe", "ordessa_harness_vibe"),
)
RETIRED_FAMILIES = {"codex", "claude", "claude-code", "pi"}
RETIRED_FACTORIES = {"create_codex", "create_claude", "create_pi", "create_plugin"}
RETIRED_MODULES = (
    "ordessa_harness",
    "pacthold.harness_kit.adapters",
    "pacthold.harness_kit.entrypoints",
)


def retired_discovery_is_absent(metadata: str) -> bool:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(metadata)
    for section in parser.sections():
        if section.casefold() == "agent_box.plugins":
            return False
        for name, value in parser.items(section):
            if name.casefold() in RETIRED_FAMILIES:
                return False
            target, separator, factory = value.split("[", 1)[0].strip().partition(":")
            if factory in RETIRED_FACTORIES:
                return False
            if any(target == prefix or target.startswith(prefix + ".")
                   for prefix in RETIRED_MODULES):
                return False
    return True


def test_registration_guard_detects_old_group_and_factory_alias_bypasses():
    assert retired_discovery_is_absent("[ordessa.plugins]\nhealthy = ordessa_harness_codex.server_plugin:CodexServerPlugin\n")
    assert not retired_discovery_is_absent(
        "[agent_box.plugins]\nopencode = pacthold.harness_kit.entrypoints:create_opencode\n"
    )
    for factory in ("create_codex", "create_claude", "create_pi", "create_plugin"):
        assert not retired_discovery_is_absent(
            "[alternate.discovery]\nrenamed = pacthold.harness_kit.entrypoints:" + factory + "\n"
        )
    assert not retired_discovery_is_absent(
        "[alternate.discovery]\nlegacy = ordessa_harness.codex:register\n"
    )
    assert not retired_discovery_is_absent(
        "[alternate.discovery]\nlegacy = pacthold.harness_kit.adapters.pi:create_pi\n"
    )
    assert not retired_discovery_is_absent(
        "[alternate.discovery]\ncodex = renamed.module:other_factory\n"
    )


def test_actual_independent_brand_wheels_preserve_families_without_aggregate(tmp_path):
    projects = (*BRAND_WHEELS, ("packages/execution/kernel", "pacthold", "pacthold"))
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    home = tmp_path / "isolated-home"
    home.mkdir()
    environment = {key: value for key, value in os.environ.items()
                    if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}
    environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
        PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")

    wheel_by_distribution = {}
    for index, (relative, distribution, package) in enumerate(projects):
        source = ROOT / relative
        staged = tmp_path / f"source-{index}"
        staged.mkdir()
        shutil.copyfile(source / "pyproject.toml", staged / "pyproject.toml")
        if (source / "README.md").is_file():
            shutil.copyfile(source / "README.md", staged / "README.md")
        shutil.copytree(source / "src", staged / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
        built = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-index", "--no-build-isolation",
             "--no-deps", "--wheel-dir", str(wheels), str(staged)],
            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90,
        )
        assert built.returncode == 0, built.stdout + built.stderr
        matching = list(wheels.glob(distribution.replace("-", "_") + "-*.whl"))
        assert len(matching) == 1, (distribution, matching)
        wheel = matching[0]
        wheel_by_distribution[distribution] = wheel
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            assert any(name.startswith(package + "/") and name.endswith(".py") for name in names), package
            metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
            assert len(metadata_files) == 1
            metadata = archive.read(metadata_files[0]).decode("utf-8")
            assert f"Name: {distribution}" in metadata.splitlines(), metadata_files[0]
            entry_files = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
            for entry_file in entry_files:
                assert retired_discovery_is_absent(archive.read(entry_file).decode("utf-8")), entry_file
            assert not any(name.startswith("ordessa_harness/") for name in names)
            assert not any(name.startswith("pacthold/harness_kit/adapters/") for name in names)

    assert set(wheel_by_distribution) == {distribution for _, distribution, _ in projects}
    created = subprocess.run(
        [sys.executable, "-m", "venv", str(tmp_path / "venv")],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    python = tmp_path / "venv/bin/python"
    installed = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps",
         *[str(wheel_by_distribution[distribution]) for _, distribution, _ in projects]],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=90,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    provider_modules = tuple(package for _, _, package in BRAND_WHEELS)
    inspection = f"""
import importlib.util
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
import sysconfig

for retired_distribution in ("ordessa-harness", "ordessa-harness-api"):
    try:
        distribution(retired_distribution)
    except PackageNotFoundError:
        pass
    else:
        raise AssertionError("retired root aggregate distribution is installed: "
                             + retired_distribution)
assert importlib.util.find_spec("ordessa_harness") is None
for retired in {RETIRED_MODULES!r}:
    try:
        spec = importlib.util.find_spec(retired)
    except ModuleNotFoundError:
        spec = None
    assert spec is None, (retired, spec)
purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
for module in {provider_modules!r}:
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin, "independent family is missing: " + module
    assert Path(spec.origin).resolve().is_relative_to(purelib), (module, spec.origin)
"""
    inspected = subprocess.run(
        [str(python), "-I", "-c", inspection], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=90,
    )
    assert inspected.returncode == 0, inspected.stdout + inspected.stderr
