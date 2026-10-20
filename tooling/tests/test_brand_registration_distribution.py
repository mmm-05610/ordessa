"""Verify each resource-bearing Harness brand wheel in an isolated interpreter.

The caller builds wheels into ORDESSA_BRAND_WHEELHOUSE first. This test never
builds from a source checkout and installs with --no-index, so a missing wheel
or runtime dependency fails explicitly instead of being fetched implicitly.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
import venv
import zipfile

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BRANDS = (
    ("claude-code", "ordessa-harness-claude-code", "0.1.0a1", "ordessa_harness_claude_code"),
    ("codex", "ordessa-harness-codex", "0.1.0a1", "ordessa_harness_codex"),
    ("dsh", "ordessa-harness-dsh", "0.1.0a1", "ordessa_harness_dsh"),
    ("grok-build", "ordessa-harness-grok-build", "0.1.0a1", "ordessa_harness_grok_build"),
    ("hermes", "ordessa-harness-hermes", "0.1.0a1", "ordessa_harness_hermes"),
    ("kilo", "ordessa-harness-kilo", "0.1.0a1", "ordessa_harness_kilo"),
    ("opencode", "ordessa-harness-opencode", "0.1.0a1", "ordessa_harness_opencode"),
    ("pi", "ordessa-harness-pi", "0.1.0a1", "ordessa_harness_pi"),
)


def _wheel_metadata(wheel: Path) -> tuple[str, str, list[str]]:
    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        assert len(metadata_paths) == 1, f"{wheel.name}: expected one METADATA"
        metadata = archive.read(metadata_paths[0]).decode("utf-8")
    name = next((line.partition(":")[2].strip() for line in metadata.splitlines() if line.startswith("Name:")), None)
    version = next((line.partition(":")[2].strip() for line in metadata.splitlines() if line.startswith("Version:")), None)
    requires = [line.partition(":")[2].strip() for line in metadata.splitlines() if line.startswith("Requires-Dist:")]
    assert name and version, f"{wheel.name}: METADATA has no Name or Version"
    return name.casefold().replace("_", "-"), version, requires


def _brand_wheel(wheelhouse: Path, distribution: str) -> Path:
    matches = []
    for wheel in sorted(wheelhouse.glob("*.whl")):
        name, _, _ = _wheel_metadata(wheel)
        if name == distribution:
            matches.append(wheel)
    assert len(matches) == 1, (
        f"expected exactly one {distribution} wheel in {wheelhouse}, found "
        f"{[wheel.name for wheel in matches]}"
    )
    return matches[0]


def _source_fragments(leaf: str, package: str) -> tuple[bytes, bytes]:
    resource_dir = REPOSITORY_ROOT / "plugins" / "harness" / leaf / "src" / package / "_registration_declarations"
    registry_path = resource_dir / "harness.toml"
    launch_path = resource_dir / "launch.json"
    assert registry_path.is_file(), f"missing source registration TOML: {registry_path}"
    assert launch_path.is_file(), f"missing source launch JSON: {launch_path}"
    registry = registry_path.read_bytes()
    launch = launch_path.read_bytes()
    tomllib.loads(registry.decode("utf-8"))
    json.loads(launch.decode("utf-8"))
    return registry, launch


_ISOLATED_CHECK = r'''
import builtins
import importlib.resources as resources
import io
import json
import os
from pathlib import Path
import sys

module_name, expected_registry, expected_launch = sys.argv[1:]
package_name = module_name.split(".", 1)[0]
resource_reads = []
resource_files_calls = []
original_files = resources.files

def tracked_files(package):
    if package == package_name:
        resource_files_calls.append(package)
    return original_files(package)

resources.files = tracked_files

def watched_open(opener):
    def open_and_track(file, *args, **kwargs):
        try:
            path = os.fspath(file)
        except TypeError:
            path = str(file)
        if package_name in str(path) and "_registration_declarations" in str(path):
            resource_reads.append(str(path))
        return opener(file, *args, **kwargs)
    return open_and_track

builtins.open = watched_open(builtins.open)
io.open = watched_open(io.open)
Path.open = watched_open(Path.open)

port = __import__(module_name, fromlist=["registration_declarations"])
assert callable(port.registration_declarations), "public registration port is absent"
assert resource_files_calls == [], f"resource lookup happened during import: {resource_files_calls}"
assert resource_reads == [], f"registration resource read during import: {resource_reads}"

fragments = port.registration_declarations()
assert type(fragments).__name__ == "RegistrationDeclarations"
assert isinstance(fragments.registry_toml, bytes)
assert isinstance(fragments.launch_json, bytes)
actual_registry = __import__("hashlib").sha256(fragments.registry_toml).hexdigest()
actual_launch = __import__("hashlib").sha256(fragments.launch_json).hexdigest()
assert actual_registry == expected_registry, (actual_registry, expected_registry)
assert actual_launch == expected_launch, (actual_launch, expected_launch)
assert resource_files_calls == [package_name], f"unexpected resource lookup count: {resource_files_calls}"
read_names = {Path(path).name for path in resource_reads}
assert read_names == {"harness.toml", "launch.json"} and len(set(resource_reads)) == 2, (
    f"expected exactly both declaration fragments to be read: {resource_reads}"
)
print(f"{package_name} registry_sha256={actual_registry} launch_sha256={actual_launch}")

for loaded in tuple(sys.modules):
    top = loaded.split(".", 1)[0]
    assert top not in {"apps", "products"}, f"forbidden host/product import: {loaded}"
    if top.startswith(("ordessa_server", "ordessa_product")):
        raise AssertionError(f"forbidden server import: {loaded}")
    if top.startswith("ordessa_harness") and top != package_name:
        raise AssertionError(f"forbidden other-brand import: {loaded}")
'''


@pytest.mark.parametrize("leaf,distribution,version,package", BRANDS, ids=[brand[0] for brand in BRANDS])
def test_registration_declarations_are_in_each_independent_wheel(
    leaf: str, distribution: str, version: str, package: str, tmp_path: Path
) -> None:
    wheelhouse_value = os.environ.get("ORDESSA_BRAND_WHEELHOUSE")
    assert wheelhouse_value, "set ORDESSA_BRAND_WHEELHOUSE to a directory of the built brand and dependency wheels"
    wheelhouse = Path(wheelhouse_value).resolve()
    assert wheelhouse.is_dir(), f"wheelhouse does not exist: {wheelhouse}"
    wheel = _brand_wheel(wheelhouse, distribution)

    source_registry, source_launch = _source_fragments(leaf, package)
    registry_member = f"{package}/_registration_declarations/harness.toml"
    launch_member = f"{package}/_registration_declarations/launch.json"
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert registry_member in names, f"{wheel.name} omits {registry_member}"
        assert launch_member in names, f"{wheel.name} omits {launch_member}"
        wheel_registry = archive.read(registry_member)
        wheel_launch = archive.read(launch_member)
    assert wheel_registry == source_registry, f"TOML bytes differ in {wheel.name}"
    assert wheel_launch == source_launch, f"JSON bytes differ in {wheel.name}"
    tomllib.loads(wheel_registry.decode("utf-8"))
    json.loads(wheel_launch.decode("utf-8"))

    wheel_name, wheel_version, requirements = _wheel_metadata(wheel)
    assert wheel_name == distribution
    assert wheel_version == version, f"unexpected wheel version for {distribution}: {wheel_version}"
    forbidden_metadata = {"ordessa-server", "ordessa-server-product", "ordessa-product"}
    for requirement in requirements:
        dependency = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
        assert dependency, f"unparseable Requires-Dist in {distribution}: {requirement}"
        dependency_name = dependency.group(1).casefold().replace("_", "-")
        is_other_brand = dependency_name.startswith("ordessa-harness-") and dependency_name != distribution
        assert dependency_name not in forbidden_metadata and not is_other_brand, (
            f"{distribution} declares a host, product, or other-brand runtime dependency: {requirement}"
        )

    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    install = subprocess.run(
        [
            str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check",
            "--no-index", "--find-links", str(wheelhouse), str(wheel),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert install.returncode == 0, f"isolated offline install failed for {distribution}:\n{install.stdout}\n{install.stderr}"

    expected_registry_hash = hashlib.sha256(source_registry).hexdigest()
    expected_launch_hash = hashlib.sha256(source_launch).hexdigest()
    invocation = subprocess.run(
        [
            str(python), "-I", "-c", _ISOLATED_CHECK,
            f"{package}.registration_declarations", expected_registry_hash, expected_launch_hash,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert invocation.returncode == 0, (
        f"isolated public-port check failed for {distribution}:\n{invocation.stdout}\n{invocation.stderr}"
    )
    assert invocation.stdout.strip() == (
        f"{package} registry_sha256={expected_registry_hash} launch_sha256={expected_launch_hash}"
    ), f"{distribution} did not report the expected declaration fragment hashes: {invocation.stdout!r}"
