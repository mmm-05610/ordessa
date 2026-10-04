"""Build an explicit local bundle; never install Skills or start a service."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("configure-agent-profile", "use-external-agent", "manage-external-agent")


def verify_checksums(directory):
    directory = Path(directory)
    required = {"schema.json", "README.md", "SHA256SUMS"} | {"skills/" + name + "/SKILL.md" for name in SKILLS}
    if any(not (directory / name).is_file() for name in required) or len(list((directory / "cli").glob("ordessa_agent_tools-*.whl"))) != 1:
        raise ValueError("Bundle required asset is missing")
    lines = (directory / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    listed = set()
    for line in lines:
        expected, relative = line.split("  ", 1)
        candidate = directory / relative
        if not candidate.resolve().is_relative_to(directory.resolve()) or not candidate.is_file() or candidate.is_symlink():
            raise ValueError("Bundle file is missing or escapes its directory")
        if relative in listed or hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
            raise ValueError("Bundle checksum mismatch")
        listed.add(relative)
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file() and path.name != "SHA256SUMS"}
    if listed != actual:
        raise ValueError("Bundle contains missing or unlisted files")


def verify_wheel(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if "ordessa_agent_tools/schema.json" not in names:
            raise ValueError("Wheel is missing its core schema")
        for name in names:
            if name.startswith(("pacthold/", "ordessa_server/", "ordessa_harness/", "deployment/", "ordessa_agent/")):
                raise ValueError("Wheel includes service implementation")
            if name.endswith(".py"):
                for node in ast.walk(ast.parse(archive.read(name))):
                    modules = []
                    if isinstance(node, ast.Import):
                        modules = [item.name.split(".")[0] for item in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        modules = [(node.module or "").split(".")[0]]
                    if any(module not in sys.stdlib_module_names and module != "ordessa_agent_tools" for module in modules):
                        raise ValueError("Wheel has a non-client runtime dependency")


def build(output, *, include_deployment_source=False):
    output = Path(output).absolute()
    if output.exists():
        raise ValueError("Output directory already exists; choose a new destination")
    output.parent.mkdir(parents=True, exist_ok=True)
    checked = subprocess.run([sys.executable, str(ROOT / "packaging/generate_schema.py")], capture_output=True, text=True)
    if checked.returncode != 0:
        raise ValueError("Core public schema is unavailable or differs from the client mirror")
    checked_catalog = subprocess.run([sys.executable, str(ROOT / "packaging/generate_harness_catalog.py")], capture_output=True, text=True)
    if checked_catalog.returncode != 0:
        raise ValueError("Harness public command catalog is unavailable or differs from the client mirror")
    schema = json.loads((ROOT / "src/ordessa_agent_tools/schema.json").read_text())
    encoded = json.dumps(schema["schema"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if schema["schemaDigest"] != "sha256:" + hashlib.sha256(encoded.encode()).hexdigest():
        raise ValueError("Client schema digest mismatch")
    for name in SKILLS:
        if not (ROOT / "skills" / name / "SKILL.md").is_file():
            raise ValueError("Required Skill source is missing")
    with tempfile.TemporaryDirectory(prefix="agent-tools-bundle-") as workspace:
        stage = Path(workspace) / "bundle"
        stage.mkdir()
        wheel_dir = stage / "cli"
        wheel_dir.mkdir()
        result = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps",
                                 "--wheel-dir", str(wheel_dir), str(ROOT)], capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError("Wheel build failed; ensure setuptools and wheel are installed in the build environment")
        wheels = list(wheel_dir.glob("ordessa_agent_tools-*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected exactly one CLI wheel")
        verify_wheel(wheels[0])
        with zipfile.ZipFile(wheels[0]) as archive:
            if json.loads(archive.read("ordessa_agent_tools/schema.json")) != schema:
                raise ValueError("Wheel schema differs from bundled schema")
        for name in SKILLS:
            shutil.copytree(ROOT / "skills" / name, stage / "skills" / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "src/ordessa_agent_tools/schema.json", stage / "schema.json")
        shutil.copy2(ROOT / "src/ordessa_agent_tools/harness_commands.json", stage / "harness_commands.json")
        shutil.copy2(ROOT / "README.md", stage / "README.md")
        shutil.copy2(ROOT / "ACCEPTANCE.md", stage / "ACCEPTANCE.md")
        (stage / ".gitignore").write_text("*\n", encoding="ascii")
        if include_deployment_source:
            # Opt-in local composition source only, not copied Server/core/runtime.
            shutil.copytree(ROOT / "deployment", stage / "deployment-source", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        payload = sorted(path for path in stage.rglob("*") if path.is_file())
        checksums = "".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.relative_to(stage).as_posix() + "\n" for path in payload)
        (stage / "SHA256SUMS").write_text(checksums, encoding="ascii")
        verify_checksums(stage)
        shutil.copytree(stage, output)
    verify_checksums(output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a local CLI and Skill bundle without installing or publishing")
    parser.add_argument("--output", required=True, help="New output directory explicitly selected by the caller")
    parser.add_argument("--include-deployment-source", action="store_true", help="Include optional composition source separately; does not start services")
    options = parser.parse_args(argv)
    try:
        output = build(options.output, include_deployment_source=options.include_deployment_source)
    except (ValueError, OSError, json.JSONDecodeError):
        print("Bundle build failed; check source assets, build dependencies, and the new output destination", file=sys.stderr)
        return 2
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
