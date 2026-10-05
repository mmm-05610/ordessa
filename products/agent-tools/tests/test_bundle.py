"""Distribution integrity; no global installation or real model execution."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("agent_tools_bundle_builder", ROOT / "packaging/build_bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


@pytest.fixture(scope="module")
def built_bundle(tmp_path_factory):
    output = tmp_path_factory.mktemp("bundle") / "release"
    bundle.build(output)
    return output


def test_complete_bundle_and_hashes(built_bundle):
    bundle.verify_checksums(built_bundle)
    assert (built_bundle / "ACCEPTANCE.md").read_bytes() == (ROOT / "ACCEPTANCE.md").read_bytes()
    assert not (built_bundle / "deployment-source").exists()
    assert (built_bundle / ".gitignore").read_text() == "*\n"
    for name in bundle.SKILLS:
        assert (built_bundle / "skills" / name / "SKILL.md").read_bytes() == (ROOT / "skills" / name / "SKILL.md").read_bytes()
    wheel = next((built_bundle / "cli").glob("*.whl"))
    bundle.verify_wheel(wheel)
    with zipfile.ZipFile(wheel) as archive:
        assert json.loads(archive.read("ordessa_agent_tools/schema.json")) == json.loads((built_bundle / "schema.json").read_text())
        assert json.loads(archive.read("ordessa_agent_tools/harness_commands.json")) == json.loads((built_bundle / "harness_commands.json").read_text())


def test_checksum_detects_missing_changed_and_unlisted(tmp_path, built_bundle):
    output = tmp_path / "release"
    shutil.copytree(built_bundle, output)
    original = (output / "README.md").read_bytes()
    (output / "README.md").write_bytes(original + b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        bundle.verify_checksums(output)
    (output / "README.md").write_bytes(original)
    (output / "unlisted.txt").write_text("unexpected")
    with pytest.raises(ValueError, match="unlisted"):
        bundle.verify_checksums(output)
    (output / "unlisted.txt").unlink()
    (output / "skills/configure-agent-profile/SKILL.md").unlink()
    with pytest.raises(ValueError, match="missing"):
        bundle.verify_checksums(output)


def test_existing_bundle_never_overwritten(built_bundle):
    checksums = (built_bundle / "SHA256SUMS").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        bundle.build(built_bundle)
    assert (built_bundle / "SHA256SUMS").read_bytes() == checksums


def test_optional_deployment_source_separate(tmp_path):
    output = tmp_path / "release"
    bundle.build(output, include_deployment_source=True)
    assert (output / "deployment-source/composition.py").is_file()
    bundle.verify_checksums(output)
    with zipfile.ZipFile(next((output / "cli").glob("*.whl"))) as archive:
        assert all("deployment" not in name for name in archive.namelist())


def test_backend_import_rejected_in_wheel(tmp_path):
    wheel = tmp_path / "bad.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in ("schema.json", "schema-management.json", "provider-schema.json"):
            archive.writestr("ordessa_agent_tools/" + name, "{}")
        archive.writestr("ordessa_agent_tools/bad.py", "from ordessa_server.bootstrap import runtime\n")
    with pytest.raises(ValueError, match="dependency"):
        bundle.verify_wheel(wheel)


def test_source_core_schema_check():
    result = subprocess.run([sys.executable, str(ROOT / "packaging/generate_schema.py")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "verified" in result.stdout


def test_stdlib_native_client_rejected_in_wheel(tmp_path):
    wheel = tmp_path / "native.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in ("schema.json", "schema-management.json", "provider-schema.json"):
            archive.writestr("ordessa_agent_tools/" + name, "{}")
        archive.writestr("ordessa_agent_tools/native_clients/codex.py", "import json\n")
    with pytest.raises(ValueError, match="implementation"):
        bundle.verify_wheel(wheel)


@pytest.mark.parametrize('package', ['ordessa_harness_codex', 'ordessa_harness_pi', 'ordessa_harness_claude_code'])
def test_independent_provider_python_rejected_even_with_only_stdlib_imports(tmp_path, package):
    wheel = tmp_path / 'provider.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        for name in ('schema.json', 'schema-management.json', 'provider-schema.json'):
            archive.writestr('ordessa_agent_tools/' + name, '{}')
        archive.writestr(package + '/client.py', 'import json\n')
    with pytest.raises(ValueError, match='implementation'):
        bundle.verify_wheel(wheel)
