"""The removed aggregate resource route cannot produce an OpenCode install seat."""
import json
from pathlib import Path
import subprocess
import sys


def test_legacy_install_set_refuses_opencode_before_build_or_deployment(tmp_path):
    root = Path(__file__).resolve().parents[4]
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, str(root / "plugins/harness/packaging/builders/harness-install-set.py"),
         "--output", str(output), "--artifact", "opencode=" + str(tmp_path / "not-a-binary")],
        capture_output=True, text=True, timeout=10, cwd=root)
    assert result.returncode == 1
    failure = json.loads(result.stderr.strip().splitlines()[-1])
    assert failure["code"] == "HARNESS_INSTALL_SET_ARTIFACT_ARG_INVALID"
    assert not (output / "deployment.json").exists()
    assert not (output / "install-set.json").exists()
